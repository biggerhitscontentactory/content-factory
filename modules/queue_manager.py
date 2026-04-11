"""
Content Factory - Queue Manager
=====================================
Manages the product queue for the ecommerce content factory.
Handles:
  - Tier-based prioritization (Tier 1 > Tier 2 > Tier 3)
  - Recycle cooldown tracking (don't re-post same product too soon)
  - America 250 sprint mode (accelerated cycling before July 4, 2026)
  - New product detection and priority insertion
"""

import os
import json
import time
from datetime import datetime, timedelta
from config import (
    RECYCLE_COOLDOWN, AMERICA_250_END_DATE, SPRINT_RECYCLE_DAYS,
    DATA_DIR, LOG_DIR
)

QUEUE_FILE    = os.path.join(DATA_DIR, "queue.json")
HISTORY_FILE  = os.path.join(DATA_DIR, "post_history.json")


def load_queue():
    """Load the current product queue from file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE) as f:
            return json.load(f)
    return {"products": [], "last_updated": None}


def save_queue(queue):
    """Save the product queue to file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    queue["last_updated"] = datetime.now().isoformat()
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def load_history():
    """Load post history (product_id -> last_posted_date)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {}


def save_history(history):
    """Save post history to file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def is_sprint_mode():
    """Check if we're in America 250 sprint mode (before July 5, 2026)."""
    end_date = datetime.strptime(AMERICA_250_END_DATE, "%Y-%m-%d")
    return datetime.now() < end_date


def get_cooldown_days(tier):
    """Get the recycle cooldown in days for a given tier."""
    if is_sprint_mode() and tier == 1:
        return SPRINT_RECYCLE_DAYS
    return RECYCLE_COOLDOWN.get(tier, 90)


def is_product_ready(product_id, tier, history):
    """
    Check if a product is ready to be posted again.
    Returns True if cooldown has passed or product has never been posted.
    """
    if product_id not in history:
        return True
    last_posted_str = history[product_id].get("last_posted")
    if not last_posted_str:
        return True
    last_posted = datetime.fromisoformat(last_posted_str)
    cooldown = get_cooldown_days(tier)
    return datetime.now() >= last_posted + timedelta(days=cooldown)


def build_queue_from_products(products):
    """
    Build a prioritized queue from the full product catalog.
    Tier 1 products go first, then Tier 2, then Tier 3.
    Within each tier, shuffle for variety.
    """
    import random

    tier1 = [p for p in products if p.get("tier") == 1]
    tier2 = [p for p in products if p.get("tier") == 2]
    tier3 = [p for p in products if p.get("tier") == 3]

    random.shuffle(tier1)
    random.shuffle(tier2)
    random.shuffle(tier3)

    queue_products = tier1 + tier2 + tier3
    queue = {
        "products": queue_products,
        "position": 0,
        "total": len(queue_products),
        "last_updated": datetime.now().isoformat(),
        "sprint_mode": is_sprint_mode(),
    }
    save_queue(queue)
    print(f"[Queue] Built queue: {len(tier1)} Tier 1 | {len(tier2)} Tier 2 | {len(tier3)} Tier 3")
    print(f"[Queue] Sprint mode: {'ON' if is_sprint_mode() else 'OFF'}")
    return queue


def get_next_product(max_skip=50):
    """
    Get the next product ready to be posted.
    Skips products still in cooldown.
    Automatically cycles back to start when queue is exhausted.
    Returns product dict or None.
    """
    queue = load_queue()
    history = load_history()

    if not queue.get("products"):
        print("[Queue] Queue is empty — run build_queue_from_products() first")
        return None

    products = queue["products"]
    position = queue.get("position", 0)
    total = len(products)
    skipped = 0

    while skipped < max_skip:
        if position >= total:
            position = 0  # cycle back to start
            print("[Queue] Cycled back to start of queue")

        product = products[position]
        product_id = str(product.get("id", ""))
        tier = product.get("tier", 3)

        if is_product_ready(product_id, tier, history):
            queue["position"] = position + 1
            save_queue(queue)
            return product

        position += 1
        skipped += 1

    print(f"[Queue] All products in cooldown — checked {skipped} products")
    return None


def mark_product_posted(product_id, platform_count=0):
    """Record that a product was posted and update cooldown timer."""
    history = load_history()
    history[str(product_id)] = {
        "last_posted": datetime.now().isoformat(),
        "post_count": history.get(str(product_id), {}).get("post_count", 0) + 1,
        "platforms_last_run": platform_count,
    }
    save_history(history)


def insert_priority_product(product):
    """
    Insert a new or priority product at the front of the queue.
    Used when a new product is added to the store.
    """
    queue = load_queue()
    # Check if already in queue
    existing_ids = {str(p.get("id")) for p in queue.get("products", [])}
    if str(product.get("id")) not in existing_ids:
        queue["products"].insert(0, product)
        queue["position"] = 0  # restart from this product
        queue["total"] = len(queue["products"])
        save_queue(queue)
        print(f"[Queue] Inserted priority product: {product.get('title', '')[:50]}")
    else:
        print(f"[Queue] Product already in queue: {product.get('title', '')[:50]}")


def get_queue_stats():
    """Return a summary of queue status."""
    queue = load_queue()
    history = load_history()
    products = queue.get("products", [])
    position = queue.get("position", 0)
    total = len(products)

    posted_count = len(history)
    in_cooldown = sum(
        1 for p in products
        if not is_product_ready(str(p.get("id")), p.get("tier", 3), history)
    )
    ready_count = total - in_cooldown

    return {
        "total_products": total,
        "queue_position": position,
        "products_posted_ever": posted_count,
        "ready_to_post": ready_count,
        "in_cooldown": in_cooldown,
        "sprint_mode": is_sprint_mode(),
        "last_updated": queue.get("last_updated", "never"),
    }


if __name__ == "__main__":
    from shopify_connector import fetch_and_cache_all_products

    print("Building product queue from store catalog...")
    products = fetch_and_cache_all_products(force_refresh=False)

    if products:
        queue = build_queue_from_products(products)
        stats = get_queue_stats()
        print(f"\nQueue Stats:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

        print("\nNext 5 products to post:")
        for i in range(5):
            p = get_next_product()
            if p:
                print(f"  {i+1}. [{p['tier']}] {p['title'][:50]} (${p['price']})")
            else:
                print("  No more products ready")
                break
    else:
        print("No products found in store")
