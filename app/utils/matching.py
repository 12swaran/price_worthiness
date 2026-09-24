import re
import string
from typing import List, Dict, Any
from rapidfuzz import fuzz


ACCESSORY_TERMS = {
    "case", "cover", "protector", "tempered", "charger", "charging",
    "cable", "adapter", "skin", "guard", "bumper", "holder", "stand",
}
IPHONE_VARIANTS = {"pro", "max", "plus", "mini", "air", "e"}

def normalize_title(title: str) -> str:
    """Lowercase, remove punctuation, expand abbreviations."""
    title = title.lower()
    # Remove punctuation
    title = title.translate(str.maketrans('', '', string.punctuation))
    # Expand some known abbreviations/normalize spacing
    # e.g., wh1000xm5 -> wh 1000 xm 5 or just keeping it simple
    # The regex below adds spaces around numbers if they are attached to letters,
    # but token_set_ratio is pretty robust. Let's just do a basic cleanup.
    title = re.sub(r'([a-z])(\d)', r'\1 \2', title)
    title = re.sub(r'(\d)([a-z])', r'\1 \2', title)
    # compress multiple spaces
    title = re.sub(r'\s+', ' ', title).strip()
    return title

def extract_model_number(text: str) -> str:
    r"""Extract potential model numbers [A-Z]{1,5}[-]?\d{1,4}"""
    match = re.search(r'([A-Z]{1,5}[-]?\d{1,4})', text.upper())
    return match.group(1) if match else ""

def evaluate_matches(
    query_product: str, 
    query_model: str, 
    results: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """
    Evaluates scraped results against the query.
    Returns: (exact_matches, similar_matches, is_ambiguous)
    """
    exact_matches = []
    similar_matches = []
    
    # Combine product and model for the match query
    query = normalize_title(f"{query_product} {query_model if query_model else ''}")
    query_model_terms = set(normalize_title(query_model).split()) if query_model else set()
    
    models_found = set()
    query_terms = set(query.split())
    required_terms = query_terms - {"the", "a", "an"}
    if "iphone" in query_terms:
        required_terms.discard("apple")
    requested_iphone = re.search(r'\biphone\s+(\d+)\b', query)

    for item in results:
        if item.get("error"):
            continue
        
        if not item.get("title") or not item.get("url", "").startswith(("https://", "http://")):
            continue
        if not isinstance(item.get("price"), (int, float)) or item["price"] <= 0:
            continue

        normalized_item_title = normalize_title(item["title"])
        score = fuzz.token_set_ratio(query, normalized_item_title)
        
        item_terms = set(normalized_item_title.split())
        if (item_terms & ACCESSORY_TERMS) - query_terms:
            continue

        has_model = True
        if query_model_terms:
            has_model = query_model_terms.issubset(item_terms)

        # Fuzzy token matching alone treats iPhone 16/17 and Pro/base models as exact.
        same_iphone_model = True
        same_iphone_variant = True
        if "iphone" in query_terms:
            item_iphone = re.search(r'\biphone\s+(\d+)\b', normalized_item_title)
            if requested_iphone:
                same_iphone_model = bool(item_iphone and item_iphone.group(1) == requested_iphone.group(1))
            same_iphone_variant = (item_terms & IPHONE_VARIANTS) == (query_terms & IPHONE_VARIANTS)
        
        if (score >= 85 and required_terms.issubset(item_terms) and has_model
                and same_iphone_model and same_iphone_variant):
            exact_matches.append(item)
            # Try to extract model to check ambiguity
            model = item_iphone.group(1) if "iphone" in query_terms and item_iphone else extract_model_number(item["title"])
            if model:
                models_found.add(model)
        elif score >= 70 and (not requested_iphone or "iphone" in item_terms):
            similar_matches.append(item)

    is_ambiguous = False
    if not query_model and len(models_found) > 1:
        # e.g., user searched iPhone, found iPhone 13 and iPhone 14
        is_ambiguous = True

    return exact_matches, similar_matches, is_ambiguous
