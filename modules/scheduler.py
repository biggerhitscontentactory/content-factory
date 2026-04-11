"""
Content Factory - OneUp Scheduler
=====================================
Schedules generated content to social media via OneUp API.
Built-in anti-ban rate limiting, daily volume caps, and smart time spreading.
Supports: Pinterest, Instagram, Facebook, LinkedIn, Twitter/X
"""

import os
import json
import time
import random
import requests
from datetime import datetime, timedelta
from config import (
    ONEUP_API_KEY, DAILY_LIMITS, MIN_GAP_MINUTES,
    LOG_DIR, DATA_DIR
)

ONEUP_BASE_URL = "https://www.oneupapp.io/api"

# ─── Platform IDs (filled after OneUp account setup) ─────────────────────────
# These are fetched from OneUp API once accounts are connected
PLATFORM_ACCOUNT_IDS = {
    "pinterest":  os.environ.get("ONEUP_PINTEREST_ID", ""),
    "instagram":  os.environ.get("ONEUP_INSTAGRAM_ID", ""),
    "facebook":   os.environ.get("ONEUP_FACEBOOK_ID", ""),
    "linkedin":   os.environ.get("ONEUP_LINKEDIN_ID", ""),
    "twitter":    os.environ.get("ONEUP_TWITTER_ID", ""),
}

# ─── Optimal posting windows per platform (hour ranges, local time) ──────────
POSTING_WINDOWS = {
    "pinterest":  [(8, 11), (14, 16), (20, 22)],   # morning, afternoon, evening
    "instagram":  [(9, 11), (19, 21)],
    "facebook":   [(9, 11), (13, 15), (19, 21)],
    "linkedin":   [(8, 10), (12, 13), (17, 18)],   # business hours
    "twitter":    [(8, 9), (12, 13), (17, 18), (20, 21)],
    "tiktok":     [(19, 21), (12, 13)],
}

# ─── Daily post tracking (in-memory + file-backed) ───────────────────────────
_daily_counts = {}
_daily_counts_file = os.path.join(DATA_DIR, "daily_counts.json")


def load_daily_counts():
    """Load today's post counts from file."""
    global _daily_counts
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(_daily_counts_file):
        try:
            with open(_daily_counts_file) as f:
                data = json.load(f)
            if data.get("date") == today:
                _daily_counts = data.get("counts", {})
                return
        except Exception:
            pass
    _daily_counts = {p: 0 for p in DAILY_LIMITS}


def save_daily_counts():
    """Persist today's post counts to file."""
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_daily_counts_file, "w") as f:
        json.dump({"date": today, "counts": _daily_counts}, f)


def can_post_today(platform):
    """Check if we're under the daily limit for a platform."""
    load_daily_counts()
    current = _daily_counts.get(platform, 0)
    limit = DAILY_LIMITS.get(platform, 1)
    return current < limit


def increment_post_count(platform):
    """Increment and save the post count for a platform."""
    load_daily_counts()
    _daily_counts[platform] = _daily_counts.get(platform, 0) + 1
    save_daily_counts()


def get_next_post_time(platform, base_time=None):
    """
    Calculate the next safe posting time for a platform.
    Respects minimum gaps and optimal posting windows.
    Returns a datetime object.
    """
    if base_time is None:
        base_time = datetime.now()

    # Add minimum gap from now
    min_gap = MIN_GAP_MINUTES.get(platform, 60)
    earliest = base_time + timedelta(minutes=min_gap + random.randint(0, 15))

    # Find the next optimal window
    windows = POSTING_WINDOWS.get(platform, [(9, 21)])
    candidate = earliest

    # Try to find a slot in the next 48 hours
    for _ in range(96):  # check every 30 minutes for 48 hours
        hour = candidate.hour
        for start_h, end_h in windows:
            if start_h <= hour <= end_h:
                # Add some randomness within the window
                jitter = random.randint(0, 20)
                return candidate.replace(minute=jitter, second=0, microsecond=0)
        candidate += timedelta(minutes=30)

    # Fallback: just use earliest time
    return earliest


def get_oneup_accounts():
    """Fetch connected social accounts from OneUp API."""
    if not ONEUP_API_KEY:
        print("[Scheduler] OneUp API key not configured")
        return []
    try:
        resp = requests.get(
            f"{ONEUP_BASE_URL}/accounts",
            headers={"Authorization": f"Bearer {ONEUP_API_KEY}"},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json().get("accounts", [])
    except Exception as e:
        print(f"[Scheduler] Error fetching OneUp accounts: {e}")
        return []


def schedule_post_oneup(account_id, text, image_paths=None, scheduled_at=None, link=None):
    """
    Schedule a single post via OneUp API.
    Returns post ID if successful, None otherwise.
    """
    if not ONEUP_API_KEY:
        print("[Scheduler] OneUp API key not set — skipping actual scheduling")
        return f"mock_{int(time.time())}"

    if scheduled_at is None:
        scheduled_at = datetime.now() + timedelta(hours=1)

    payload = {
        "account_ids": [account_id],
        "text": text,
        "scheduled_at": scheduled_at.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if link:
        payload["link"] = link

    # Handle image uploads
    if image_paths:
        media_ids = []
        for img_path in image_paths:
            if img_path and os.path.exists(img_path):
                media_id = upload_media_oneup(img_path)
                if media_id:
                    media_ids.append(media_id)
        if media_ids:
            payload["media_ids"] = media_ids

    try:
        resp = requests.post(
            f"{ONEUP_BASE_URL}/posts",
            headers={
                "Authorization": f"Bearer {ONEUP_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        post_id = resp.json().get("post", {}).get("id")
        print(f"[Scheduler] Scheduled post {post_id} for {scheduled_at.strftime('%Y-%m-%d %H:%M')}")
        return post_id
    except Exception as e:
        print(f"[Scheduler] Error scheduling post: {e}")
        return None


def upload_media_oneup(image_path):
    """Upload an image to OneUp and return the media ID."""
    if not ONEUP_API_KEY:
        return None
    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{ONEUP_BASE_URL}/media",
                headers={"Authorization": f"Bearer {ONEUP_API_KEY}"},
                files={"file": f},
                timeout=60
            )
        resp.raise_for_status()
        return resp.json().get("media", {}).get("id")
    except Exception as e:
        print(f"[Scheduler] Error uploading media {image_path}: {e}")
        return None


def schedule_ecommerce_content_pack(content_pack, images, account_ids, base_time=None):
    """
    Schedule all platform posts for an ecommerce content pack.
    Spreads posts across the optimal 5-day window.
    Returns dict of platform -> scheduled post info.
    """
    if base_time is None:
        base_time = datetime.now()

    product = content_pack.get("product", {})
    product_url = product.get("url", "")
    pins = content_pack.get("pinterest_pins", [])
    ig = content_pack.get("instagram_post", {})
    fb = content_pack.get("facebook_post", {})

    scheduled = {}
    current_time = base_time

    # Day 1: Pinterest pin 1 + Facebook
    if "pinterest" in account_ids and can_post_today("pinterest") and pins:
        post_time = get_next_post_time("pinterest", current_time)
        pin = pins[0]
        text = f"{pin.get('title', '')}\n\n{pin.get('description', '')}"
        img = [images.get("pinterest_1")] if images.get("pinterest_1") else []
        post_id = schedule_post_oneup(
            account_ids["pinterest"], text, img, post_time, product_url
        )
        if post_id:
            increment_post_count("pinterest")
            scheduled["pinterest_1"] = {"post_id": post_id, "scheduled_at": str(post_time)}

    if "facebook" in account_ids and can_post_today("facebook") and fb:
        post_time = get_next_post_time("facebook", current_time)
        img = [images.get("facebook")] if images.get("facebook") else []
        post_id = schedule_post_oneup(
            account_ids["facebook"], fb.get("text", ""), img, post_time, product_url
        )
        if post_id:
            increment_post_count("facebook")
            scheduled["facebook"] = {"post_id": post_id, "scheduled_at": str(post_time)}

    # Day 2: Instagram
    day2 = current_time + timedelta(days=1)
    if "instagram" in account_ids and ig:
        post_time = get_next_post_time("instagram", day2)
        caption = ig.get("caption", "") + "\n" + ig.get("hashtags", "")
        img = [images.get("instagram")] if images.get("instagram") else []
        post_id = schedule_post_oneup(
            account_ids["instagram"], caption, img, post_time
        )
        if post_id:
            scheduled["instagram"] = {"post_id": post_id, "scheduled_at": str(post_time)}

    # Day 3: Pinterest pin 2
    day3 = current_time + timedelta(days=2)
    if "pinterest" in account_ids and len(pins) > 1:
        post_time = get_next_post_time("pinterest", day3)
        pin = pins[1]
        text = f"{pin.get('title', '')}\n\n{pin.get('description', '')}"
        img = [images.get("pinterest_2")] if images.get("pinterest_2") else []
        post_id = schedule_post_oneup(
            account_ids["pinterest"], text, img, post_time, product_url
        )
        if post_id:
            increment_post_count("pinterest")
            scheduled["pinterest_2"] = {"post_id": post_id, "scheduled_at": str(post_time)}

    # Day 5: Pinterest pin 3 (gift angle)
    day5 = current_time + timedelta(days=4)
    if "pinterest" in account_ids and len(pins) > 2:
        post_time = get_next_post_time("pinterest", day5)
        pin = pins[2]
        text = f"{pin.get('title', '')}\n\n{pin.get('description', '')}"
        post_id = schedule_post_oneup(
            account_ids["pinterest"], text, [], post_time, product_url
        )
        if post_id:
            increment_post_count("pinterest")
            scheduled["pinterest_3"] = {"post_id": post_id, "scheduled_at": str(post_time)}

    return scheduled


def schedule_ai_channel_content_pack(content_pack, images, account_ids, carousel_pdf=None, base_time=None):
    """
    Schedule LinkedIn and Twitter posts for an AI channel content pack.
    """
    if base_time is None:
        base_time = datetime.now()

    li_post = content_pack.get("linkedin_text_post", {})
    thread = content_pack.get("twitter_thread", {})
    scheduled = {}

    # Day 1: LinkedIn text post
    if "linkedin" in account_ids and li_post:
        post_time = get_next_post_time("linkedin", base_time)
        img = [images.get("linkedin_header")] if images.get("linkedin_header") else []
        post_id = schedule_post_oneup(
            account_ids["linkedin"],
            li_post.get("full_post", ""),
            img,
            post_time
        )
        if post_id:
            scheduled["linkedin_post"] = {"post_id": post_id, "scheduled_at": str(post_time)}

    # Day 2: LinkedIn carousel (PDF)
    day2 = base_time + timedelta(days=1)
    if "linkedin" in account_ids and carousel_pdf and os.path.exists(carousel_pdf):
        post_time = get_next_post_time("linkedin", day2)
        carousel_data = content_pack.get("linkedin_carousel", {})
        caption = f"{carousel_data.get('title', 'New carousel')} — swipe through 👉"
        post_id = schedule_post_oneup(
            account_ids["linkedin"],
            caption,
            [carousel_pdf],
            post_time
        )
        if post_id:
            scheduled["linkedin_carousel"] = {"post_id": post_id, "scheduled_at": str(post_time)}

    # Day 1: Twitter thread (first tweet only — rest as replies not supported by OneUp)
    if "twitter" in account_ids and thread:
        tweets = thread.get("tweets", [])
        if tweets:
            post_time = get_next_post_time("twitter", base_time)
            first_tweet = tweets[0].get("text", "")
            # Append thread indicator
            if len(tweets) > 1:
                first_tweet += "\n\n🧵 Thread below:"
            post_id = schedule_post_oneup(
                account_ids["twitter"], first_tweet, [], post_time
            )
            if post_id:
                scheduled["twitter_thread"] = {"post_id": post_id, "scheduled_at": str(post_time)}

    return scheduled


def log_scheduled_posts(scheduled, product_or_topic, project="ecommerce"):
    """Log scheduled post info to file for tracking."""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"scheduled_{project}.jsonl")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "subject": str(product_or_topic)[:100],
        "posts": scheduled
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_daily_summary():
    """Return a summary of today's scheduled post counts."""
    load_daily_counts()
    summary = []
    for platform, limit in DAILY_LIMITS.items():
        count = _daily_counts.get(platform, 0)
        summary.append(f"{platform}: {count}/{limit}")
    return " | ".join(summary)


if __name__ == "__main__":
    print("Scheduler module loaded")
    print(f"Daily limits: {DAILY_LIMITS}")
    print(f"\nNext post times from now:")
    for platform in ["pinterest", "instagram", "facebook", "linkedin", "twitter"]:
        next_time = get_next_post_time(platform)
        print(f"  {platform}: {next_time.strftime('%Y-%m-%d %H:%M')}")

    if not ONEUP_API_KEY:
        print("\n⚠ OneUp API key not configured yet.")
        print("Add it to config.py after signing up at oneupapp.io")
    else:
        print("\nFetching OneUp accounts...")
        accounts = get_oneup_accounts()
        print(f"Connected accounts: {len(accounts)}")
        for acc in accounts:
            print(f"  - {acc.get('name')} ({acc.get('type')}): {acc.get('id')}")
