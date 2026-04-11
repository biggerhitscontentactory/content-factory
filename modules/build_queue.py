"""Build product queue from a limited fetch to avoid hanging."""
import sys
import os

# Ensure paths work from any directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import requests
import json
import random
from datetime import datetime

DATA_DIR = os.path.join(BASE_DIR, "data")
QUEUE_FILE = os.path.join(DATA_DIR, "queue.json")

os.makedirs(DATA_DIR, exist_ok=True)

print("Fetching products from store (limited to 250)...")
url = "https://officialusastore.myshopify.com/products.json?limit=250"
resp = requests.get(url, timeout=20)
raw_products = resp.json().get("products", [])
print(f"Fetched {len(raw_products)} products")

TIER1_KW = ["250", "anniversary", "1776", "2026", "america 250", "birthday", "independence"]
TIER2_KW = ["patriotic", "eagle", "flag", "freedom", "usa", "american"]

def assign_tier(p):
    tags = p.get('tags', '')
    if isinstance(tags, list):
        tags_str = ' '.join(tags)
    else:
        tags_str = tags
    combined = f"{p.get('title','').lower()} {tags_str.lower()}"
    for kw in TIER1_KW:
        if kw in combined:
            return 1
    for kw in TIER2_KW:
        if kw in combined:
            return 2
    return 3

products = []
for p in raw_products:
    variants = p.get("variants", [])
    price = float(variants[0].get("price", 0)) if variants else 0
    images = p.get("images", [])
    tier = assign_tier(p)
    import re
    raw_body = p.get('body_html', '') or ''
    clean_desc = re.sub(r'<[^>]+>', ' ', raw_body).strip()
    clean_desc = re.sub(r'\s+', ' ', clean_desc)[:500]
    tags_raw = p.get('tags', '')
    tags_list = tags_raw if isinstance(tags_raw, list) else [t.strip() for t in tags_raw.split(',') if t.strip()]
    products.append({
        "id": p.get("id"),
        "title": p.get("title"),
        "handle": p.get("handle"),
        "url": f"https://www.officialusastore.com/products/{p.get('handle','')}",
        "price": price,
        "tier": tier,
        "primary_image": images[0].get("src","") if images else "",
        "tags": tags_list,
        "description": clean_desc,
        "product_type": p.get("product_type", ""),
        "on_sale": False,
        "compare_price": 0,
        "variant_count": len(variants),
    })

tier1 = [p for p in products if p["tier"] == 1]
tier2 = [p for p in products if p["tier"] == 2]
tier3 = [p for p in products if p["tier"] == 3]
random.shuffle(tier1); random.shuffle(tier2); random.shuffle(tier3)
ordered = tier1 + tier2 + tier3

queue = {
    "products": ordered,
    "position": 0,
    "total": len(ordered),
    "last_updated": datetime.now().isoformat(),
    "sprint_mode": True,
}
with open(QUEUE_FILE, "w") as f:
    json.dump(queue, f, indent=2)

print(f"\nQueue built: {len(tier1)} Tier1 | {len(tier2)} Tier2 | {len(tier3)} Tier3")
print(f"Total: {len(ordered)} products")
print(f"Saved to {QUEUE_FILE}")
print("\nFirst 5 products:")
for p in ordered[:5]:
    print(f"  [{p['tier']}] {p['title'][:55]} (${p['price']})")
