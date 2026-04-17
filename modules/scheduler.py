"""
Content Factory - OneUp Scheduler
=====================================
Schedules generated content to social media via OneUp API.
Correct API: https://www.oneupapp.io/api/
  - Auth: ?apiKey=YOUR_KEY (query param, NOT Bearer header)
  - List accounts: GET /listsocialaccounts
  - List categories: GET /listcategory
  - Schedule image post: POST /scheduleimagepost
  - Schedule video post: POST /schedulevideo
  - Schedule text post: POST /schedulepost
  - social_network_id is the string ID from /listcategoryaccount
  - category_id is required for all post endpoints
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

ONEUP_BASE = "https://www.oneupapp.io/api"

# Platform Account IDs - read at call time (not import time) so Railway env vars work
def _get_platform_ids():
    return {
        "pinterest":  os.environ.get("ONEUP_PINTEREST_ID", ""),
        "instagram":  os.environ.get("ONEUP_INSTAGRAM_ID", ""),
        "facebook":   os.environ.get("ONEUP_FACEBOOK_ID", ""),
        "linkedin":   os.environ.get("ONEUP_LINKEDIN_ID", ""),
        "twitter":    os.environ.get("ONEUP_TWITTER_ID", ""),
        "tiktok":     os.environ.get("ONEUP_TIKTOK_ID", ""),
        "youtube":    os.environ.get("ONEUP_YOUTUBE_ID", ""),
    }

def _get_category_id():
    return os.environ.get("ONEUP_CATEGORY_ID", "")

def _get_api_key():
    return os.environ.get("ONEUP_API_KEY", "")

POSTING_WINDOWS = {
    "pinterest":  [(8, 11), (14, 16), (20, 22)],
    "instagram":  [(9, 11), (19, 21)],
    "facebook":   [(9, 11), (13, 15), (19, 21)],
    "linkedin":   [(8, 10), (12, 13), (17, 18)],
    "twitter":    [(8, 9), (12, 13), (17, 18), (20, 21)],
    "tiktok":     [(19, 21), (12, 13)],
    "youtube":    [(14, 16), (10, 12)],
}

_daily_counts = {}
_daily_counts_file = os.path.join(DATA_DIR, "daily_counts.json")

def load_daily_counts():
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
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_daily_counts_file, "w") as f:
        json.dump({"date": today, "counts": _daily_counts}, f)

def can_post_today(platform):
    load_daily_counts()
    return _daily_counts.get(platform, 0) < DAILY_LIMITS.get(platform, 1)

def increment_post_count(platform):
    load_daily_counts()
    _daily_counts[platform] = _daily_counts.get(platform, 0) + 1
    save_daily_counts()

def get_next_post_time(platform, base_time=None):
    if base_time is None:
        base_time = datetime.now()
    min_gap = MIN_GAP_MINUTES.get(platform, 60)
    earliest = base_time + timedelta(minutes=min_gap + random.randint(0, 15))
    windows = POSTING_WINDOWS.get(platform, [(9, 21)])
    candidate = earliest
    for _ in range(96):
        hour = candidate.hour
        for start_h, end_h in windows:
            if start_h <= hour <= end_h:
                return candidate.replace(minute=random.randint(0, 20), second=0, microsecond=0)
        candidate += timedelta(minutes=30)
    return earliest

def get_oneup_accounts():
    """Fetch all connected social accounts. Correct endpoint: /listsocialaccounts?apiKey=KEY"""
    api_key = _get_api_key()
    if not api_key:
        print("[Scheduler] ONEUP_API_KEY not set")
        return []
    try:
        resp = requests.get(
            f"{ONEUP_BASE}/listsocialaccounts",
            params={"apiKey": api_key},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        accounts = data.get("data", [])
        print(f"[Scheduler] Found {len(accounts)} connected OneUp accounts")
        return accounts
    except Exception as e:
        print(f"[Scheduler] Error fetching OneUp accounts: {e}")
        return []

def get_oneup_categories():
    api_key = _get_api_key()
    if not api_key:
        return []
    try:
        resp = requests.get(f"{ONEUP_BASE}/listcategory", params={"apiKey": api_key}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        print(f"[Scheduler] Error fetching categories: {e}")
        return []

def get_category_accounts(category_id):
    api_key = _get_api_key()
    if not api_key or not category_id:
        return []
    try:
        resp = requests.get(
            f"{ONEUP_BASE}/listcategoryaccount",
            params={"apiKey": api_key, "category_id": category_id},
            timeout=15
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        print(f"[Scheduler] Error fetching category accounts: {e}")
        return []

def upload_image_to_hosting(image_path):
    """Convert local image path to public URL via Railway app."""
    if not image_path or not os.path.exists(image_path):
        return None
    # Try multiple env vars Railway may set
    railway_url = (
        os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
        or os.environ.get("APP_URL", "")
        or os.environ.get("RAILWAY_STATIC_URL", "")
    )
    # Strip protocol prefix if present
    if railway_url.startswith("https://"):
        railway_url = railway_url[8:]
    elif railway_url.startswith("http://"):
        railway_url = railway_url[7:]
    if not railway_url:
        print(f"[Scheduler] WARNING: No APP_URL/RAILWAY_PUBLIC_DOMAIN set — cannot build image URL for OneUp")
        print(f"[Scheduler] Set APP_URL=web-production-128b8.up.railway.app in Railway Variables")
        return None
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output")
    static_dir = os.path.join(base_dir, "static")
    if image_path.startswith(output_dir):
        rel = os.path.relpath(image_path, output_dir).replace(os.sep, "/")
        return f"https://{railway_url}/output/{rel}"
    if image_path.startswith(static_dir):
        rel = os.path.relpath(image_path, static_dir).replace(os.sep, "/")
        return f"https://{railway_url}/static/{rel}"
    return None

def schedule_post_oneup(social_network_id, text, image_paths=None, scheduled_at=None,
                         link=None, category_id=None, dry_run=False):
    """
    Schedule a post via OneUp API.
    social_network_id: string ID from /listcategoryaccount (e.g. "pin_username", "113024478527731")
    category_id: the OneUp category_id that contains this account
    """
    api_key = _get_api_key()
    if not api_key:
        print("[Scheduler] ONEUP_API_KEY not set")
        return None
    if not social_network_id:
        print("[Scheduler] No social_network_id")
        return None
    if not category_id:
        category_id = _get_category_id()
    if not category_id:
        print("[Scheduler] ONEUP_CATEGORY_ID not set")
        return None
    if scheduled_at is None:
        scheduled_at = datetime.now() + timedelta(hours=1)
    scheduled_str = scheduled_at.strftime("%Y-%m-%d %H:%M")
    if dry_run:
        print(f"[DRY RUN] Would post to {social_network_id} at {scheduled_str}: {text[:60]}...")
        return {"mock": True, "social_network_id": social_network_id, "scheduled_at": scheduled_str}
    if link and link not in text:
        text = f"{text}\n\n{link}"
    image_urls = []
    if image_paths:
        for p in image_paths:
            if p and os.path.exists(p):
                url = upload_image_to_hosting(p)
                if url:
                    image_urls.append(url)
                else:
                    print(f"[Scheduler] Could not build public URL for image: {p}")
                    print(f"[Scheduler] Post will be sent as text-only (no image)")
            elif p:
                print(f"[Scheduler] Image path does not exist: {p}")
    try:
        if image_urls:
            payload = {
                "apiKey": api_key,
                "category_id": str(category_id),
                "social_network_id": json.dumps([social_network_id]),
                "scheduled_date_time": scheduled_str,
                "content": text,
                "image_url": "~~".join(image_urls),
            }
            resp = requests.post(f"{ONEUP_BASE}/scheduleimagepost", data=payload, timeout=30)
        else:
            payload = {
                "apiKey": api_key,
                "category_id": str(category_id),
                "social_network_id": json.dumps([social_network_id]),
                "scheduled_date_time": scheduled_str,
                "content": text,
            }
            resp = requests.post(f"{ONEUP_BASE}/schedulepost", data=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            print(f"[Scheduler] OneUp error: {result.get('message', 'unknown')}")
            return None
        print(f"[Scheduler] Scheduled post to {social_network_id} at {scheduled_str}")
        return result
    except Exception as e:
        print(f"[Scheduler] Error scheduling post: {e}")
        return None

def schedule_video_post_oneup(social_network_id, text, video_url, scheduled_at=None,
                               category_id=None, dry_run=False):
    api_key = _get_api_key()
    if not api_key or not social_network_id:
        return None
    if not category_id:
        category_id = _get_category_id()
    if not category_id:
        return None
    if scheduled_at is None:
        scheduled_at = datetime.now() + timedelta(hours=1)
    scheduled_str = scheduled_at.strftime("%Y-%m-%d %H:%M")
    if dry_run:
        print(f"[DRY RUN] Would schedule video to {social_network_id} at {scheduled_str}")
        return {"mock": True}
    try:
        payload = {
            "apiKey": api_key,
            "category_id": str(category_id),
            "social_network_id": json.dumps([social_network_id]),
            "scheduled_date_time": scheduled_str,
            "content": text,
            "video_url": video_url,
        }
        resp = requests.post(f"{ONEUP_BASE}/schedulevideo", data=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            print(f"[Scheduler] OneUp video error: {result.get('message')}")
            return None
        print(f"[Scheduler] Scheduled video to {social_network_id} at {scheduled_str}")
        return result
    except Exception as e:
        print(f"[Scheduler] Error scheduling video: {e}")
        return None

def schedule_ecommerce_content_pack(content_pack, images, account_ids, base_time=None, dry_run=False):
    if base_time is None:
        base_time = datetime.now()
    category_id = _get_category_id()
    product = content_pack.get("product", {})
    product_url = product.get("url", "")
    pins = content_pack.get("pinterest_pins", [])
    ig = content_pack.get("instagram_post", {})
    fb = content_pack.get("facebook_post", {})
    tiktok_post = content_pack.get("tiktok_post", {})
    yt_post = content_pack.get("youtube_post", {})
    scheduled = {}
    current_time = base_time
    # Day 1: Pinterest pin 1 + Facebook
    if account_ids.get("pinterest") and pins:
        post_time = get_next_post_time("pinterest", current_time)
        pin = pins[0]
        text = f"{pin.get('title', '')}\n\n{pin.get('description', '')}\n\n{product_url}"
        img = [images.get("pinterest_1")] if images.get("pinterest_1") else []
        result = schedule_post_oneup(account_ids["pinterest"], text, img, post_time, category_id=category_id, dry_run=dry_run)
        if result:
            increment_post_count("pinterest")
            scheduled["pinterest_1"] = {"scheduled_at": str(post_time)}
    if account_ids.get("facebook") and fb:
        post_time = get_next_post_time("facebook", current_time)
        fb_hashtags = fb.get("hashtags", "")
        text = fb.get("text", "")
        if fb_hashtags:
            text = f"{text}\n\n{fb_hashtags}"
        if product_url:
            text = f"{text}\n\n{product_url}"
        img = [images.get("facebook")] if images.get("facebook") else []
        result = schedule_post_oneup(account_ids["facebook"], text, img, post_time, category_id=category_id, dry_run=dry_run)
        if result:
            increment_post_count("facebook")
            scheduled["facebook"] = {"scheduled_at": str(post_time)}
    # Day 2: Instagram
    day2 = current_time + timedelta(days=1)
    if account_ids.get("instagram") and ig:
        post_time = get_next_post_time("instagram", day2)
        caption = ig.get("caption", "") + "\n" + ig.get("hashtags", "")
        img = [images.get("instagram")] if images.get("instagram") else []
        result = schedule_post_oneup(account_ids["instagram"], caption, img, post_time, category_id=category_id, dry_run=dry_run)
        if result:
            scheduled["instagram"] = {"scheduled_at": str(post_time)}
    # Day 3: Pinterest pin 2 + TikTok
    day3 = current_time + timedelta(days=2)
    if account_ids.get("pinterest") and len(pins) > 1:
        post_time = get_next_post_time("pinterest", day3)
        pin = pins[1]
        text = f"{pin.get('title', '')}\n\n{pin.get('description', '')}\n\n{product_url}"
        img = [images.get("pinterest_2")] if images.get("pinterest_2") else []
        result = schedule_post_oneup(account_ids["pinterest"], text, img, post_time, category_id=category_id, dry_run=dry_run)
        if result:
            increment_post_count("pinterest")
            scheduled["pinterest_2"] = {"scheduled_at": str(post_time)}
    if account_ids.get("tiktok") and tiktok_post:
        post_time = get_next_post_time("tiktok", day3)
        script = tiktok_post.get("script", tiktok_post.get("hook", ""))
        tt_hashtags = tiktok_post.get("hashtags", "")
        text = script
        if tt_hashtags:
            text = f"{text}\n\n{tt_hashtags}"
        if product_url:
            text = f"{text}\n\n{product_url}"
        img = [images.get("tiktok")] if images.get("tiktok") else []
        result = schedule_post_oneup(account_ids["tiktok"], text, img, post_time, category_id=category_id, dry_run=dry_run)
        if result:
            increment_post_count("tiktok")
            scheduled["tiktok"] = {"scheduled_at": str(post_time)}
    # Day 4: YouTube
    day4 = current_time + timedelta(days=3)
    if account_ids.get("youtube") and yt_post:
        post_time = get_next_post_time("youtube", day4)
        text = yt_post.get("description", yt_post.get("title", ""))
        if product_url:
            text += f"\n\nShop here: {product_url}"
        img = [images.get("youtube")] if images.get("youtube") else []
        result = schedule_post_oneup(account_ids["youtube"], text, img, post_time, category_id=category_id, dry_run=dry_run)
        if result:
            increment_post_count("youtube")
            scheduled["youtube"] = {"scheduled_at": str(post_time)}
    # Day 5: Pinterest pin 3
    day5 = current_time + timedelta(days=4)
    if account_ids.get("pinterest") and len(pins) > 2:
        post_time = get_next_post_time("pinterest", day5)
        pin = pins[2]
        text = f"{pin.get('title', '')}\n\n{pin.get('description', '')}\n\n{product_url}"
        result = schedule_post_oneup(account_ids["pinterest"], text, [], post_time, category_id=category_id, dry_run=dry_run)
        if result:
            increment_post_count("pinterest")
            scheduled["pinterest_3"] = {"scheduled_at": str(post_time)}
    return scheduled

def schedule_ai_channel_content_pack(content_pack, images, account_ids, carousel_pdf=None, base_time=None, dry_run=False):
    if base_time is None:
        base_time = datetime.now()
    category_id = _get_category_id()
    li_post = content_pack.get("linkedin_text_post", {})
    thread = content_pack.get("twitter_thread", {})
    scheduled = {}
    if account_ids.get("linkedin") and li_post:
        post_time = get_next_post_time("linkedin", base_time)
        img = [images.get("linkedin_header")] if images.get("linkedin_header") else []
        result = schedule_post_oneup(account_ids["linkedin"], li_post.get("full_post", ""), img, post_time, category_id=category_id, dry_run=dry_run)
        if result:
            scheduled["linkedin_post"] = {"scheduled_at": str(post_time)}
    day2 = base_time + timedelta(days=1)
    if account_ids.get("linkedin") and carousel_pdf and os.path.exists(carousel_pdf):
        post_time = get_next_post_time("linkedin", day2)
        caption = content_pack.get("linkedin_carousel", {}).get("title", "New carousel") + " — swipe through"
        result = schedule_post_oneup(account_ids["linkedin"], caption, [carousel_pdf], post_time, category_id=category_id, dry_run=dry_run)
        if result:
            scheduled["linkedin_carousel"] = {"scheduled_at": str(post_time)}
    if account_ids.get("twitter") and thread:
        tweets = thread.get("tweets", [])
        if tweets:
            post_time = get_next_post_time("twitter", base_time)
            first_tweet = tweets[0].get("text", "")
            if len(tweets) > 1:
                first_tweet += "\n\nThread below:"
            result = schedule_post_oneup(account_ids["twitter"], first_tweet, [], post_time, category_id=category_id, dry_run=dry_run)
            if result:
                scheduled["twitter_thread"] = {"scheduled_at": str(post_time)}
    return scheduled

def log_scheduled_posts(scheduled, product_or_topic, project="ecommerce"):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"scheduled_{project}.jsonl")
    entry = {"timestamp": datetime.now().isoformat(), "subject": str(product_or_topic)[:100], "posts": scheduled}
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

def get_daily_summary():
    load_daily_counts()
    return " | ".join(f"{p}: {_daily_counts.get(p,0)}/{l}" for p, l in DAILY_LIMITS.items())
