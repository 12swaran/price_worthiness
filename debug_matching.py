from rapidfuzz import fuzz
from app.utils.matching import normalize_title, extract_model_number, evaluate_matches

q = normalize_title("Sony WH1000 Wireless Headphones")
t1 = normalize_title("Sony WH1000XM4 Wireless Headphones")
t2 = normalize_title("Sony WH1000XM5 Wireless Headphones")
s1 = fuzz.token_set_ratio(q, t1)
s2 = fuzz.token_set_ratio(q, t2)
print(f"Query: {q}")
print(f"T1: {t1} score={s1}")
print(f"T2: {t2} score={s2}")
print(f"Model1: {extract_model_number('Sony WH1000XM4 Wireless Headphones')}")
print(f"Model2: {extract_model_number('Sony WH1000XM5 Wireless Headphones')}")

# Now test evaluate_matches directly
results = [
    {"site": "A", "title": "Sony WH1000XM4 Wireless Headphones", "price": 10000, "currency": "INR", "url": "", "availability": "In Stock", "rating": 4.0, "reviews_count": 100, "error": False},
    {"site": "B", "title": "Sony WH1000XM5 Wireless Headphones", "price": 20000, "currency": "INR", "url": "", "availability": "In Stock", "rating": 4.0, "reviews_count": 100, "error": False},
]
exact, similar, is_ambig = evaluate_matches("Sony WH1000 Wireless Headphones", "", results)
print(f"\nexact count: {len(exact)}")
print(f"similar count: {len(similar)}")
print(f"is_ambig: {is_ambig}")

# Try with more overlapping names
print("\n--- Test with iPhone ---")
results2 = [
    {"site": "A", "title": "Apple iPhone 14 128GB", "price": 50000, "currency": "INR", "url": "", "availability": "In Stock", "rating": 4.0, "reviews_count": 100, "error": False},
    {"site": "B", "title": "Apple iPhone 15 128GB", "price": 60000, "currency": "INR", "url": "", "availability": "In Stock", "rating": 4.0, "reviews_count": 100, "error": False},
]
exact2, similar2, is_ambig2 = evaluate_matches("Apple iPhone 128GB", "", results2)
print(f"exact count: {len(exact2)}")
print(f"similar count: {len(similar2)}")
print(f"is_ambig: {is_ambig2}")
for r in results2:
    q2 = normalize_title("Apple iPhone 128GB")
    t = normalize_title(r["title"])
    s = fuzz.token_set_ratio(q2, t)
    print(f"  {r['title']} → score={s}")
