def detect_feature(query: str):
    q = query.lower()

    # Comparison intent
    compare_words = ["compare", "vs", "difference", "better than"]
    if any(word in q for word in compare_words):
        return "compare"

    # Recommendation intent
    recommend_words = ["recommend", "suggest", "best for", "for me"]
    if any(word in q for word in recommend_words):
        return "recommend"

    # Default → search
    return "search"