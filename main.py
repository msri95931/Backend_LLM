from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import mysql.connector
from mysql.connector import Error
import bcrypt
import jwt
import os, uuid, json, re, math
from datetime import datetime, timedelta
from dotenv import load_dotenv
from groq import Groq   # ← CHANGED: was "import anthropic"

load_dotenv()

app = FastAPI(title="ShopAI API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.getenv("FRONTEND_URL", "http://localhost:3000"),
        "https://*.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JWT_SECRET  = os.getenv("JWT_SECRET", "shopai-secret-change-in-prod")
JWT_ALGO    = "HS256"
JWT_EXP_HRS = 24 * 7
security    = HTTPBearer(auto_error=False)

# ── GROQ MODEL ────────────────────────────────────────────────────────────────
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# ── DATABASE ──────────────────────────────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE", "shopai"),
        autocommit=True,
        charset="utf8mb4",
    )
def init_db():
    try:
        conn = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", 3306)),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD"),
            autocommit=True,
        )
        cur = conn.cursor()
        db = os.getenv("MYSQL_DATABASE", "shopai")
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}`")
        cur.execute(f"USE `{db}`")

        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            id VARCHAR(36) PRIMARY KEY, name VARCHAR(100) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

        cur.execute("""CREATE TABLE IF NOT EXISTS conversations (
            id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36),
            title VARCHAR(255), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)""")

        cur.execute("""CREATE TABLE IF NOT EXISTS messages (
            id VARCHAR(36) PRIMARY KEY, conversation_id VARCHAR(36) NOT NULL,
            role ENUM('user','assistant') NOT NULL, content TEXT NOT NULL,
            feature_detected VARCHAR(100), product_ids TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE)""")

        cur.execute("""CREATE TABLE IF NOT EXISTS products (
            id VARCHAR(36) PRIMARY KEY, product_name VARCHAR(500) NOT NULL,
            brand VARCHAR(200), category VARCHAR(200), sub_category VARCHAR(200),
            discounted_price DECIMAL(10,2), actual_price DECIMAL(10,2),
            discount_percentage DECIMAL(5,2), product_rating DECIMAL(3,2),
            rating_count INT DEFAULT 0, about_product TEXT,
            img_link VARCHAR(1000), product_link VARCHAR(1000),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_category(category), INDEX idx_brand(brand),
            INDEX idx_price(discounted_price), INDEX idx_rating(product_rating),
            FULLTEXT INDEX ft_search(product_name, brand, about_product)
        ) CHARACTER SET utf8mb4""")

        cur.execute("""CREATE TABLE IF NOT EXISTS wishlists (
            id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL,
            product_id VARCHAR(36) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_up(user_id, product_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)""")

        cur.close(); conn.close()
        print("✅ DB initialised")
    except Error as e:
        print(f"⚠️  DB init: {e}")

# ── AUTH HELPERS ──────────────────────────────────────────────────────────────────
def hash_pw(pw): return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
def check_pw(pw, h): return bcrypt.checkpw(pw.encode(), h.encode())

def make_token(uid, email, name):
    return jwt.encode(
        {"sub": uid, "email": email, "name": name,
         "exp": datetime.utcnow() + timedelta(hours=JWT_EXP_HRS)},
        JWT_SECRET, algorithm=JWT_ALGO)

def parse_token(token):
    try: return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError: raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:    raise HTTPException(401, "Invalid token")

def current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    return parse_token(creds.credentials) if creds else None

def require_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds: raise HTTPException(401, "Login required")
    return parse_token(creds.credentials)

# ── SMART SEARCH ENGINE ───────────────────────────────────────────────────────────
def extract_price_filter(text: str):
    t = text.lower().replace(",", "")
    patterns = [
        (r"(?:under|below|less than|within|budget of?|max|upto?)\s*[₹rs\.]*\s*(\d+)\s*k", True),
        (r"(?:under|below|less than|within|upto?)\s*[₹rs\.]*\s*(\d+)", False),
        (r"[₹]\s*(\d+)\s*k", True),
        (r"[₹]\s*(\d+)", False),
    ]
    for pattern, is_k in patterns:
        m = re.search(pattern, t)
        if m:
            val = int(m.group(1))
            return val * 1000 if is_k else val
    return None

STOPWORDS = {"i","want","need","looking","for","a","the","good","best","find",
             "show","me","please","some","any","under","below","within","budget",
             "cheap","affordable","expensive","compare","vs","versus","with","and",
             "or","is","are","what","which","that","this","these","those","get",
             "give","have","has","can","could","would","should","will","tell"}

def extract_keywords(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]

def detect_feature(msg: str) -> str:
    m = msg.lower()
    if any(w in m for w in ["compare", " vs ", "versus", "difference between"]):
        return "comparison"
    if any(w in m for w in ["recommend", "suggest", "best for me", "personalized"]):
        return "recommendation"
    return "search"

def relevance_score(r: dict) -> float:
    rating = float(r.get("product_rating") or 0)
    count  = int(r.get("rating_count") or 0)
    ft_rel = float(r.get("relevance") or 0)
    return ft_rel * 2 + rating * math.log(count + 2)

def search_products(query: str, limit: int = 6) -> List[dict]:
    """3-stage search: FULLTEXT → keyword LIKE → category fallback, with price filter."""
    try:
        conn = get_db(); cur = conn.cursor(dictionary=True)
        price_max = extract_price_filter(query)
        keywords  = extract_keywords(query)
        results   = []
        price_sql = f"AND discounted_price <= {price_max}" if price_max else ""

        # Stage 1 — FULLTEXT
        try:
            cur.execute(f"""
                SELECT *, MATCH(product_name,brand,about_product)
                          AGAINST(%s IN NATURAL LANGUAGE MODE) AS relevance
                FROM products
                WHERE MATCH(product_name,brand,about_product) AGAINST(%s IN NATURAL LANGUAGE MODE)
                {price_sql}
                ORDER BY relevance DESC, product_rating DESC LIMIT %s
            """, (query, query, limit * 2))
            results = cur.fetchall()
        except Exception as e:
            print(f"FULLTEXT error: {e}")

        # Stage 2 — LIKE per keyword
        if len(results) < 3 and keywords:
            kw_list = keywords[:5]
            or_parts = " OR ".join(
                ["(product_name LIKE %s OR brand LIKE %s OR category LIKE %s OR about_product LIKE %s)"
                 for _ in kw_list])
            params = [v for kw in kw_list for v in [f"%{kw}%"]*4]
            cur.execute(f"""
                SELECT *, 0 AS relevance FROM products
                WHERE ({or_parts}) {price_sql}
                ORDER BY product_rating DESC, rating_count DESC LIMIT %s
            """, params + [limit * 2])
            extra = cur.fetchall()
            seen = {r["id"] for r in results}
            results += [r for r in extra if r["id"] not in seen]

        # Stage 3 — if still empty, try just first keyword in name
        if not results and keywords:
            cur.execute(f"""
                SELECT *, 0 AS relevance FROM products
                WHERE product_name LIKE %s {price_sql}
                ORDER BY product_rating DESC LIMIT %s
            """, (f"%{keywords[0]}%", limit))
            results = cur.fetchall()

        cur.close(); conn.close()

        # Deduplicate & rank
        seen, final = set(), []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                r["_score"] = relevance_score(r)
                final.append(r)

        final.sort(key=lambda x: x["_score"], reverse=True)
        final = final[:limit]

        for r in final:
            for k in ["discounted_price","actual_price","product_rating","discount_percentage"]:
                if r.get(k) is not None: r[k] = float(r[k])
            r.pop("_score", None); r.pop("relevance", None)

        return final
    except Exception as e:
        print(f"Search error: {e}"); return []

# ── AI  (Groq — replaces Anthropic) ──────────────────────────────────────────
def build_system(products: List[dict]) -> str:
    ctx = ""
    if products:
        ctx = "\n\n## Products from database:\n"
        for p in products:
            ctx += (f"• **{p.get('product_name','')}** | Brand: {p.get('brand','N/A')} "
                    f"| ₹{p.get('discounted_price','?')} "
                    f"| ⭐ {p.get('product_rating','?')} "
                    f"({p.get('rating_count',0)} reviews)\n")
    return f"""You are ShopAI, an expert AI shopping assistant for an Indian e-commerce platform.

Personality: knowledgeable, warm, concise — like a smart friend who knows every product.
- Always use ₹ for prices
- Reference specific products from the database list below when relevant
- Comparisons: give clear pros/cons per product
- Recommendations: give your top pick with a short reason + mention 1-2 alternatives
- Keep responses under 180 words unless doing detailed comparison
- Speak naturally; avoid bullet-point overload
- If products don't match the query, say so and suggest better search terms{ctx}"""


# ── CHANGED: get_ai_response now uses Groq ────────────────────────────────────
def get_ai_response(message: str, history: List[dict], products: List[dict]) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "AI service not configured. Please add GROQ_API_KEY to your .env file."
    try:
        client = Groq(api_key=api_key)
        messages = [{"role": "system", "content": build_system(products)}]
        messages += [{"role": h["role"], "content": h["content"]} for h in history[-10:]]
        messages.append({"role": "user", "content": message})

        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=700,
            temperature=0.7,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"AI error: {e}"


# ── CHANGED: ai_stream_generator now uses Groq streaming ─────────────────────
async def ai_stream_generator(message, history, products, conv_id, cur):
    """SSE generator: sends metadata first, then tokens, saves on done."""
    api_key = os.getenv("GROQ_API_KEY")

    # Send metadata immediately
    meta = json.dumps({"type": "meta", "conversation_id": conv_id, "products": products})
    yield f"data: {meta}\n\n"

    if not api_key:
        yield f"data: {json.dumps({'type':'token','text':'GROQ_API_KEY not set in .env'})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"
        return

    full = []
    try:
        client   = Groq(api_key=api_key)
        messages = [{"role": "system", "content": build_system(products)}]
        messages += [{"role": h["role"], "content": h["content"]} for h in history[-10:]]
        messages.append({"role": "user", "content": message})

        # Groq streaming — same SSE pattern as before
        stream = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=700,
            temperature=0.7,
            stream=True,   # ← enable streaming
        )
        for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                full.append(token)
                yield f"data: {json.dumps({'type':'token','text':token})}\n\n"

    except Exception as e:
        err = f"Stream error: {e}"
        full.append(err)
        yield f"data: {json.dumps({'type':'token','text':err})}\n\n"

    # Save to DB (same as before)
    reply_text = "".join(full)
    pid_json   = json.dumps([p.get("id","") for p in products])
    feature    = detect_feature(message)
    cur.execute("""INSERT INTO messages (id,conversation_id,role,content,feature_detected,product_ids)
                   VALUES(%s,%s,%s,%s,%s,%s)""",
                (str(uuid.uuid4()), conv_id, "assistant", reply_text, feature, pid_json))
    cur.close()

    yield f"data: {json.dumps({'type':'done'})}\n\n"


# ── SCHEMAS ───────────────────────────────────────────────────────────────────────
class SignUpReq(BaseModel):
    name: str; email: EmailStr; password: str

class SignInReq(BaseModel):
    email: EmailStr; password: str

class ChatReq(BaseModel):
    message: str
    conversation_id: Optional[str] = None

# ── ROUTES ────────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0", "ai": "Groq", "model": GROQ_MODEL}

# ── AUTH ──────────────────────────────────────────────────────────────────────────
@app.post("/api/auth/signup", status_code=201)
def signup(b: SignUpReq):
    if len(b.password) < 6: raise HTTPException(400, "Password must be ≥ 6 chars")
    conn = get_db(); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id FROM users WHERE email=%s", (b.email,))
    if cur.fetchone(): raise HTTPException(409, "Email already registered")
    uid = str(uuid.uuid4())
    cur.execute("INSERT INTO users (id,name,email,password_hash) VALUES(%s,%s,%s,%s)",
                (uid, b.name.strip(), b.email, hash_pw(b.password)))
    cur.close(); conn.close()
    return {"token": make_token(uid, b.email, b.name.strip()),
            "user":  {"id": uid, "name": b.name.strip(), "email": b.email}}

@app.post("/api/auth/signin")
def signin(b: SignInReq):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE email=%s", (b.email,))
    user = cur.fetchone(); cur.close(); conn.close()
    if not user or not check_pw(b.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    return {"token": make_token(user["id"], user["email"], user["name"]),
            "user":  {"id": user["id"], "name": user["name"], "email": user["email"]}}

@app.get("/api/auth/me")
def me(u=Depends(require_user)):
    return {"user": {"id": u["sub"], "name": u["name"], "email": u["email"]}}

# ── CHAT (streaming SSE) ──────────────────────────────────────────────────────────
@app.post("/api/chat/stream")
async def chat_stream(b: ChatReq, u=Depends(current_user)):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    user_id = u["sub"] if u else None
    conv_id = b.conversation_id

    if conv_id:
        cur.execute("SELECT id FROM conversations WHERE id=%s", (conv_id,))
        if not cur.fetchone(): conv_id = None

    if not conv_id:
        conv_id = str(uuid.uuid4())
        title = b.message[:60] + ("…" if len(b.message) > 60 else "")
        cur.execute("INSERT INTO conversations (id,user_id,title) VALUES(%s,%s,%s)",
                    (conv_id, user_id, title))

    cur.execute("SELECT role,content FROM messages WHERE conversation_id=%s ORDER BY created_at LIMIT 20",
                (conv_id,))
    history  = [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]
    products = search_products(b.message)

    cur.execute("INSERT INTO messages (id,conversation_id,role,content) VALUES(%s,%s,%s,%s)",
                (str(uuid.uuid4()), conv_id, "user", b.message))

    return StreamingResponse(
        ai_stream_generator(b.message, history, products, conv_id, cur),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── CHAT (non-streaming fallback) ─────────────────────────────────────────────────
@app.post("/api/chat")
def chat(b: ChatReq, u=Depends(current_user)):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    user_id = u["sub"] if u else None
    conv_id = b.conversation_id

    if conv_id:
        cur.execute("SELECT id FROM conversations WHERE id=%s", (conv_id,))
        if not cur.fetchone(): conv_id = None

    if not conv_id:
        conv_id = str(uuid.uuid4())
        title = b.message[:60] + ("…" if len(b.message) > 60 else "")
        cur.execute("INSERT INTO conversations (id,user_id,title) VALUES(%s,%s,%s)",
                    (conv_id, user_id, title))

    cur.execute("SELECT role,content FROM messages WHERE conversation_id=%s ORDER BY created_at LIMIT 20",
                (conv_id,))
    history  = [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]
    products = search_products(b.message)
    reply    = get_ai_response(b.message, history, products)
    feature  = detect_feature(b.message)

    cur.execute("INSERT INTO messages (id,conversation_id,role,content) VALUES(%s,%s,%s,%s)",
                (str(uuid.uuid4()), conv_id, "user", b.message))
    cur.execute("""INSERT INTO messages (id,conversation_id,role,content,feature_detected,product_ids)
                   VALUES(%s,%s,%s,%s,%s,%s)""",
                (str(uuid.uuid4()), conv_id, "assistant", reply, feature,
                 json.dumps([p.get("id","") for p in products])))
    cur.close(); conn.close()
    return {"response": reply, "conversation_id": conv_id,
            "feature_detected": feature, "results": products}

# ── CONVERSATIONS ─────────────────────────────────────────────────────────────────
@app.get("/api/conversations")
def get_convs(u=Depends(require_user)):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id,title,created_at FROM conversations WHERE user_id=%s ORDER BY created_at DESC LIMIT 30",
                (u["sub"],))
    rows = cur.fetchall(); cur.close(); conn.close()
    return {"conversations": rows}

@app.delete("/api/conversations/{cid}")
def delete_conv(cid: str, u=Depends(require_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM conversations WHERE id=%s AND user_id=%s", (cid, u["sub"]))
    cur.close(); conn.close()
    return {"deleted": True}

@app.get("/api/conversations/{cid}/messages")
def get_msgs(cid: str, u=Depends(require_user)):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT role,content,feature_detected,created_at FROM messages WHERE conversation_id=%s ORDER BY created_at",
                (cid,))
    msgs = cur.fetchall(); cur.close(); conn.close()
    return {"messages": msgs}

@app.get("/api/conversations/{cid}/export")
def export_conv(cid: str, u=Depends(require_user)):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    cur.execute("SELECT title FROM conversations WHERE id=%s AND user_id=%s", (cid, u["sub"]))
    conv = cur.fetchone()
    if not conv: raise HTTPException(404, "Not found")
    cur.execute("SELECT role,content,created_at FROM messages WHERE conversation_id=%s ORDER BY created_at",
                (cid,))
    msgs = cur.fetchall(); cur.close(); conn.close()
    lines = [f"ShopAI Conversation — {conv['title']}", "="*50, ""]
    for m in msgs:
        role = "You" if m["role"] == "user" else "ShopAI"
        ts   = str(m["created_at"])[:16]
        lines += [f"[{ts}] {role}:", m["content"], ""]
    return {"title": conv["title"], "text": "\n".join(lines)}

# ── PRODUCTS ──────────────────────────────────────────────────────────────────────
@app.get("/api/products/search")
def search(q: str = Query(..., min_length=1), limit: int = 8):
    results = search_products(q, limit)
    return {"results": results, "count": len(results)}

@app.get("/api/products/categories")
def categories():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category")
    cats = [r[0] for r in cur.fetchall()]; cur.close(); conn.close()
    return {"categories": cats}

# ── WISHLIST ──────────────────────────────────────────────────────────────────────
@app.get("/api/wishlist")
def get_wishlist(u=Depends(require_user)):
    conn = get_db(); cur = conn.cursor(dictionary=True)
    cur.execute("""SELECT p.* FROM products p JOIN wishlists w ON p.id=w.product_id
                   WHERE w.user_id=%s ORDER BY w.created_at DESC""", (u["sub"],))
    rows = cur.fetchall(); cur.close(); conn.close()
    for r in rows:
        for k in ["discounted_price","actual_price","product_rating"]:
            if r.get(k): r[k] = float(r[k])
    return {"wishlist": rows}

@app.post("/api/wishlist/{product_id}")
def add_wishlist(product_id: str, u=Depends(require_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT IGNORE INTO wishlists (id,user_id,product_id) VALUES(%s,%s,%s)",
                (str(uuid.uuid4()), u["sub"], product_id))
    cur.close(); conn.close()
    return {"added": True}

@app.delete("/api/wishlist/{product_id}")
def rm_wishlist(product_id: str, u=Depends(require_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM wishlists WHERE user_id=%s AND product_id=%s", (u["sub"], product_id))
    cur.close(); conn.close()
    return {"removed": True}

@app.on_event("startup")
def startup():
    init_db()
    print(f"🚀 ShopAI v2.0 started | AI: Groq ({GROQ_MODEL})")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)