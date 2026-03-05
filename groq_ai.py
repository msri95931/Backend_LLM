from groq import Groq
import json
import os

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ---------------- INTENT DETECTION ----------------
def detect_intent_and_language(user_query: str):

    prompt = f"""
Detect the user shopping intent.

Return ONLY JSON like this:
{{
 "intent": "search/recommend/compare",
 "search_query": "keywords"
}}

User message:
{user_query}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    text = response.choices[0].message.content

    try:
        return json.loads(text)
    except:
        return {
            "intent": "search",
            "search_query": user_query
        }


# ---------------- FINAL AI REPLY ----------------
def generate_ai_reply(user_query, products, language):

    prompt = f"""
You are Flipkart Shopping Assistant.

Reply ONLY in this language: {language}

Language rules:
Tamil → Tamil script
Hindi → Hindi script
Tanglish → Tamil words using English letters
English → normal English

Keep answer short (max 4 lines).

User query:
{user_query}

Products:
{products}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": f"You MUST reply ONLY in {language}."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    return response.choices[0].message.content