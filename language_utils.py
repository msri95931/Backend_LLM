from textblob import TextBlob

# ---------------- AUTOCORRECT ----------------
def autocorrect_text(text: str):
    try:
        return str(TextBlob(text).correct())
    except:
        return text


# ---------------- TAMIL SCRIPT DETECTOR ----------------
def is_tamil(text: str):
    for ch in text:
        if '\u0B80' <= ch <= '\u0BFF':
            return True
    return False


# ---------------- HINDI SCRIPT DETECTOR ----------------
def is_hindi(text: str):
    for ch in text:
        if '\u0900' <= ch <= '\u097F':
            return True
    return False


# ---------------- TANGLISH DETECTOR ----------------
def is_tanglish(text: str):
    tanglish_words = [
        "enaku","venum","venam","iruku","irukku","pannanum",
        "nalla","unga","ennoda","kudunga","sollu",
        "mobile venum","laptop venum","phone venum",
        "suggest pannunga","cheap ah","budget ah",
        "under","price","best mobile","best phone"
    ]

    text = text.lower()
    return any(word in text for word in tanglish_words)


# ---------------- FINAL LANGUAGE DETECTOR ----------------
def detect_user_language(text: str):

    if is_tamil(text):
        return "Tamil"

    if is_hindi(text):
        return "Hindi"

    if is_tanglish(text):
        return "Tanglish"

    # default fallback
    return "English"