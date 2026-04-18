"""
Content Factory - Shopify Connector
=====================================
Fetches product data from OfficialUSAStore via Shopify's public JSON API
(no auth token required for public stores) or Admin API if token is available.
"""

import requests
import json
import time
import os
from datetime import datetime
from config import (
    SHOPIFY_STORE_URL, SHOPIFY_ADMIN_TOKEN, SHOPIFY_API_VERSION,
    TIER_1_KEYWORDS, TIER_1_MIN_PRICE, TIER_2_KEYWORDS,
    DATA_DIR, LOG_DIR
)


def get_products_public(limit=250, page_info=None):
    """
    Fetch products using Shopify's public storefront JSON endpoint.
    No authentication required. Works on any public Shopify store.
    Returns list of product dicts.
    """
    url = f"https://{SHOPIFY_STORE_URL}/products.json"
    params = {"limit": limit}
    if page_info:
        params["page_info"] = page_info

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("products", [])
    except requests.RequestException as e:
        print(f"[Shopify] Error fetching products: {e}")
        return []


def get_all_products_public():
    """
    Paginate through all products using the public API.
    Shopify public API returns max 250 per page.
    """
    all_products = []
    page = 1
    while True:
        print(f"[Shopify] Fetching page {page}...")
        products = get_products_public(limit=250)
        if not products:
            break
        all_products.extend(products)
        print(f"[Shopify] Got {len(products)} products (total: {len(all_products)})")
        if len(products) < 250:
            break
        page += 1
        time.sleep(0.5)  # be polite to the API
    return all_products


def get_product_by_url(product_url):
    """
    Fetch a single product by its Shopify URL.
    Handles:
      - URLs with query strings (?variant=xxx) or fragments (#)
      - /collections/xxx/products/yyy paths
      - HTML responses (password pages, 404 pages that return 200)
      - Redirects
    """
    from urllib.parse import urlparse, urlunparse

    # Strip query string and fragment before appending .json
    parsed = urlparse(product_url)
    clean_path = parsed.path.rstrip("/")

    # If URL contains /collections/.../products/handle, extract just /products/handle
    import re as _re
    m = _re.search(r'(/products/[^/?#]+)', clean_path)
    if m:
        clean_path = m.group(1)

    # Build the .json URL using the original scheme + host
    if not clean_path.endswith(".json"):
        clean_path = clean_path + ".json"

    json_url = urlunparse((parsed.scheme, parsed.netloc, clean_path, '', '', ''))
    print(f"[Shopify] Fetching product JSON: {json_url}")

    try:
        resp = requests.get(json_url, timeout=15, allow_redirects=True)

        # Check content type — if it's HTML, Shopify returned an error page
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type:
            print(f"[Shopify] Got HTML response (not JSON) for {json_url} — status {resp.status_code}")
            return {}

        if resp.status_code == 404:
            print(f"[Shopify] 404 for {json_url}")
            return {}

        resp.raise_for_status()

        # Guard against HTML slipping through without Content-Type header
        text = resp.text.strip()
        if text.startswith("<"):
            print(f"[Shopify] Response looks like HTML, not JSON: {text[:80]}")
            return {}

        data = resp.json()
        product = data.get("product", {})
        if not product:
            print(f"[Shopify] Empty product in JSON response for {json_url}")
        return product

    except ValueError as e:
        # json decode error
        print(f"[Shopify] JSON decode error for {json_url}: {e}")
        return {}
    except requests.RequestException as e:
        print(f"[Shopify] Request error fetching {json_url}: {e}")
        return {}


def extract_product_data(raw_product):
    """
    Normalize a raw Shopify product dict into a clean content-ready dict.
    """
    if not raw_product:
        return {}

    # Get first variant for price
    variants = raw_product.get("variants", [])
    price = float(variants[0].get("price", 0)) if variants else 0.0
    compare_price = float(variants[0].get("compare_at_price") or 0) if variants else 0.0

    # Get images
    images = raw_product.get("images", [])
    image_urls = [img.get("src", "") for img in images if img.get("src")]

    # Clean description (strip HTML tags simply)
    raw_body = raw_product.get("body_html", "") or ""
    import re
    clean_desc = re.sub(r"<[^>]+>", " ", raw_body).strip()
    clean_desc = re.sub(r"\s+", " ", clean_desc)[:500]  # cap at 500 chars

    # Build tags list
    tags_raw = raw_product.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

    product = {
        "id":           raw_product.get("id", ""),
        "title":        raw_product.get("title", ""),
        "handle":       raw_product.get("handle", ""),
        "url":          f"https://www.officialusastore.com/products/{raw_product.get('handle', '')}",
        "description":  clean_desc,
        "price":        price,
        "compare_price": compare_price,
        "on_sale":      compare_price > price > 0,
        "product_type": raw_product.get("product_type", ""),
        "vendor":       raw_product.get("vendor", ""),
        "tags":         tags,
        "images":       image_urls,
        "primary_image": image_urls[0] if image_urls else "",
        "variant_count": len(variants),
        "created_at":   raw_product.get("created_at", ""),
        "updated_at":   raw_product.get("updated_at", ""),
    }

    # Auto-assign tier
    product["tier"] = assign_tier(product)

    return product


def assign_tier(product):
    """
    Auto-assign content priority tier based on product data.
    Tier 1 = America 250 / high priority
    Tier 2 = General patriotic
    Tier 3 = Everything else
    """
    title_lower = product.get("title", "").lower()
    desc_lower  = product.get("description", "").lower()
    tags_lower  = " ".join(product.get("tags", [])).lower()
    combined    = f"{title_lower} {desc_lower} {tags_lower}"
    price       = product.get("price", 0)

    # Tier 1: America 250 keywords OR high-price items with patriotic keywords
    for kw in TIER_1_KEYWORDS:
        if kw.lower() in combined:
            return 1
    if price >= TIER_1_MIN_PRICE:
        for kw in TIER_2_KEYWORDS:
            if kw.lower() in combined:
                return 1

    # Tier 2: General patriotic keywords
    for kw in TIER_2_KEYWORDS:
        if kw.lower() in combined:
            return 2

    # Tier 3: Everything else
    return 3


def save_products_to_file(products, filename=None):
    """Save product list to JSON file for caching."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{DATA_DIR}/products_{timestamp}.json"
    with open(filename, "w") as f:
        json.dump(products, f, indent=2)
    print(f"[Shopify] Saved {len(products)} products to {filename}")
    return filename


def load_products_from_file(filename):
    """Load cached product list from JSON file."""
    with open(filename, "r") as f:
        return json.load(f)


def fetch_and_cache_all_products(force_refresh=False):
    """
    Main entry point: fetch all products, extract data, cache to file.
    Uses cached file if available and not forcing refresh.
    """
    cache_file = f"{DATA_DIR}/products_cache.json"

    if not force_refresh and os.path.exists(cache_file):
        # Check if cache is less than 6 hours old
        mtime = os.path.getmtime(cache_file)
        age_hours = (time.time() - mtime) / 3600
        if age_hours < 6:
            print(f"[Shopify] Using cached products (age: {age_hours:.1f}h)")
            return load_products_from_file(cache_file)

    print("[Shopify] Fetching fresh product catalog...")
    raw_products = get_all_products_public()
    products = [extract_product_data(p) for p in raw_products if p]
    products = [p for p in products if p.get("title")]  # filter empties

    # Sort by tier then price descending
    products.sort(key=lambda p: (p.get("tier", 3), -p.get("price", 0)))

    save_products_to_file(products, cache_file)
    print(f"[Shopify] Catalog ready: {len(products)} products")

    # Print tier summary
    t1 = sum(1 for p in products if p.get("tier") == 1)
    t2 = sum(1 for p in products if p.get("tier") == 2)
    t3 = sum(1 for p in products if p.get("tier") == 3)
    print(f"[Shopify] Tier 1: {t1} | Tier 2: {t2} | Tier 3: {t3}")

    return products


if __name__ == "__main__":
    products = fetch_and_cache_all_products(force_refresh=True)
    print(f"\nSample product:")
    if products:
        p = products[0]
        print(f"  Title: {p['title']}")
        print(f"  Price: ${p['price']}")
        print(f"  Tier:  {p['tier']}")
        print(f"  URL:   {p['url']}")
        print(f"  Image: {p['primary_image'][:60]}...")
