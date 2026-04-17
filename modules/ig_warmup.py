"""
Content Factory — Instagram Daily Warmup Engine
=================================================
Simulates human engagement on Instagram to keep the account healthy
and avoid bans/shadowbans. Mirrors the Pinterest repinner pattern.

Daily routine (configurable):
  - View 10–20 posts/reels from hashtag feeds related to your niche
  - Like 8–15 posts from those feeds
  - Follow 2–3 accounts that post similar content
  - Optional: unfollow accounts followed 3+ days ago (keeps ratio clean)

Uses instagrapi (unofficial Instagram private API wrapper).
Install: pip install instagrapi

Required env vars:
  IG_USERNAME       — Instagram username (no @)
  IG_PASSWORD       — Instagram password
  IG_SESSION_FILE   — (optional) path to persist session JSON, default: data/ig_session.json

Safety limits (conservative to avoid action blocks):
  - Max 15 likes per session
  - Max 3 follows per session
  - 8–25 second random delay between each action
  - Stops immediately if action block detected
  - Daily state tracked in data/ig_warmup_state.json
"""

import os
import sys
import json
import time
import random
import logging
from datetime import datetime, date

# ─── Path Setup ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from config import DATA_DIR, LOG_DIR

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────
WARMUP_STATE_FILE  = os.path.join(DATA_DIR, "ig_warmup_state.json")
WARMUP_LOG_FILE    = os.path.join(LOG_DIR,  "ig_warmup.jsonl")
FOLLOW_TRACK_FILE  = os.path.join(DATA_DIR, "ig_follow_track.json")

# Niche hashtags — rotated daily to look natural
NICHE_HASHTAGS = [
    # Patriotic / USA
    "patrioticgifts", "madeinusa", "americanpride", "usaflag",
    "patrioticapparel", "americanmade", "supportlocal", "usaveteran",
    # Gifts / ecommerce
    "uniquegifts", "giftsforhim", "giftsforher", "shopsmall",
    "smallbusiness", "onlineshopping", "giftsideas", "holidaygifts",
    # Apparel / hats
    "customhats", "snapback", "truckerhat", "embroideredhats",
    "hatcollection", "streetwear", "casualwear", "americanapparel",
    # Home decor
    "homedecor", "americandecor", "rusticdecor", "walldecor",
    "homeinspo", "interiordesign", "farmhousedecor", "modernhome",
]

DAILY_LIKE_LIMIT   = 15   # max likes per day
DAILY_FOLLOW_LIMIT = 3    # max follows per day
DAILY_VIEW_LIMIT   = 20   # max posts to "view" (scroll past) per day
UNFOLLOW_AFTER_DAYS = 4   # unfollow accounts followed N days ago

MIN_DELAY = 8    # seconds between actions
MAX_DELAY = 25   # seconds between actions


# ─── State Management ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    today = date.today().isoformat()
    if os.path.exists(WARMUP_STATE_FILE):
        try:
            with open(WARMUP_STATE_FILE) as f:
                s = json.load(f)
            if s.get("date") == today:
                return s
        except Exception:
            pass
    return {"date": today, "likes": 0, "follows": 0, "views": 0, "unfollows": 0, "errors": 0}


def _save_state(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WARMUP_STATE_FILE, "w") as f:
        json.dump(state, f)


def _load_follow_track() -> dict:
    if os.path.exists(FOLLOW_TRACK_FILE):
        try:
            with open(FOLLOW_TRACK_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_follow_track(track: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(FOLLOW_TRACK_FILE, "w") as f:
        json.dump(track, f)


def _log_action(action: str, target: str, status: str, detail: str = ""):
    os.makedirs(LOG_DIR, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(),
        "platform": "instagram",
        "action": action,
        "target": target,
        "status": status,
        "detail": detail,
    }
    with open(WARMUP_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _human_delay(min_s=None, max_s=None):
    lo = min_s or MIN_DELAY
    hi = max_s or MAX_DELAY
    t = random.uniform(lo, hi)
    time.sleep(t)


# ─── Instagram Client ─────────────────────────────────────────────────────────

def _get_client():
    """Get an authenticated instagrapi Client, reusing session if available."""
    try:
        from instagrapi import Client
        from instagrapi.exceptions import LoginRequired, BadPassword, ChallengeRequired
    except ImportError:
        raise ImportError("instagrapi not installed. Run: pip install instagrapi")

    username = os.environ.get("IG_USERNAME", "")
    password = os.environ.get("IG_PASSWORD", "")
    if not username or not password:
        raise ValueError("IG_USERNAME and IG_PASSWORD must be set in Railway Variables")

    session_file = os.environ.get(
        "IG_SESSION_FILE",
        os.path.join(DATA_DIR, "ig_session.json")
    )
    os.makedirs(DATA_DIR, exist_ok=True)

    cl = Client()
    # Use a consistent device fingerprint to avoid suspicion
    cl.set_device({
        "app_version": "269.0.0.18.75",
        "android_version": 26,
        "android_release": "8.0.0",
        "dpi": "480dpi",
        "resolution": "1080x1920",
        "manufacturer": "OnePlus",
        "device": "OnePlus5",
        "model": "ONEPLUS A5000",
        "cpu": "qcom",
        "version_code": "314665256",
    })
    cl.delay_range = [MIN_DELAY, MAX_DELAY]

    # Try to load existing session
    if os.path.exists(session_file):
        try:
            cl.load_settings(session_file)
            cl.login(username, password)
            cl.dump_settings(session_file)
            print(f"[IG Warmup] Logged in via saved session as @{username}")
            return cl
        except Exception as e:
            print(f"[IG Warmup] Session reload failed ({e}), re-logging in...")

    # Fresh login
    try:
        cl.login(username, password)
        cl.dump_settings(session_file)
        print(f"[IG Warmup] Fresh login successful as @{username}")
        return cl
    except Exception as e:
        raise RuntimeError(f"Instagram login failed: {e}")


# ─── Warmup Actions ───────────────────────────────────────────────────────────

def _pick_hashtags(n=3) -> list:
    """Pick N random hashtags from the niche pool, rotating daily."""
    seed = int(date.today().isoformat().replace("-", "")) % len(NICHE_HASHTAGS)
    pool = NICHE_HASHTAGS[seed:] + NICHE_HASHTAGS[:seed]
    return random.sample(pool, min(n, len(pool)))


def run_warmup_session(dry_run=False) -> dict:
    """
    Run a full Instagram warmup session.
    Returns a result dict with counts and status.
    """
    print(f"\n{'='*55}")
    print(f"INSTAGRAM WARMUP — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*55}\n")

    state = _load_state()
    follow_track = _load_follow_track()

    # Check daily caps
    if state["likes"] >= DAILY_LIKE_LIMIT and state["follows"] >= DAILY_FOLLOW_LIMIT:
        msg = f"Daily caps reached (likes: {state['likes']}/{DAILY_LIKE_LIMIT}, follows: {state['follows']}/{DAILY_FOLLOW_LIMIT})"
        print(f"[IG Warmup] {msg}")
        return {"total_likes": state["likes"], "total_follows": state["follows"],
                "message": msg, "skipped": True}

    likes_done    = 0
    follows_done  = 0
    views_done    = 0
    unfollows_done = 0
    errors        = 0

    hashtags = _pick_hashtags(3)
    print(f"[IG Warmup] Using hashtags: {hashtags}")

    if dry_run:
        # Simulate the session without making any API calls
        target_views  = random.randint(10, DAILY_VIEW_LIMIT)
        target_likes  = min(random.randint(8, DAILY_LIKE_LIMIT), DAILY_LIKE_LIMIT - state["likes"])
        target_follows = min(random.randint(2, DAILY_FOLLOW_LIMIT), DAILY_FOLLOW_LIMIT - state["follows"])
        print(f"[DRY RUN] Would view ~{target_views} posts")
        print(f"[DRY RUN] Would like ~{target_likes} posts")
        print(f"[DRY RUN] Would follow ~{target_follows} accounts")
        for tag in hashtags:
            print(f"[DRY RUN] Would browse #{tag}")
        _log_action("dry_run_session", str(hashtags), "simulated",
                    f"views:{target_views} likes:{target_likes} follows:{target_follows}")
        return {
            "total_likes": target_likes,
            "total_follows": target_follows,
            "total_views": target_views,
            "total_unfollows": 0,
            "errors": 0,
            "message": f"DRY RUN: would like {target_likes}, follow {target_follows}, view {target_views}",
            "dry_run": True,
        }

    # Live session
    try:
        cl = _get_client()
    except Exception as e:
        print(f"[IG Warmup] Login error: {e}")
        _log_action("login", "instagram", "error", str(e))
        return {"error": str(e), "total_likes": 0, "total_follows": 0}

    # --- Step 1: Browse hashtag feeds and like posts ---
    for tag in hashtags:
        if state["likes"] + likes_done >= DAILY_LIKE_LIMIT:
            break
        try:
            print(f"[IG Warmup] Browsing #{tag}...")
            medias = cl.hashtag_medias_recent(tag, amount=8)
            random.shuffle(medias)
            for media in medias:
                if state["likes"] + likes_done >= DAILY_LIKE_LIMIT:
                    break
                if state["views"] + views_done >= DAILY_VIEW_LIMIT:
                    break
                # "View" the post (just count it)
                views_done += 1
                _human_delay(3, 8)  # shorter delay for views
                # Like with ~70% probability (not every post)
                if random.random() < 0.70:
                    try:
                        cl.media_like(media.id)
                        likes_done += 1
                        owner = getattr(media, 'user', None)
                        owner_name = owner.username if owner else str(media.id)
                        print(f"[IG Warmup] ♥ Liked post by @{owner_name} (#{tag})")
                        _log_action("like", owner_name, "success", f"#{tag}")
                        _human_delay()
                    except Exception as e:
                        err_str = str(e).lower()
                        if "feedback_required" in err_str or "action_blocked" in err_str:
                            print(f"[IG Warmup] ⚠️ Action block detected — stopping likes")
                            _log_action("like", "unknown", "action_block", str(e))
                            errors += 1
                            break
                        errors += 1
                        _log_action("like", str(media.id), "error", str(e))
        except Exception as e:
            print(f"[IG Warmup] Error browsing #{tag}: {e}")
            errors += 1

    # --- Step 2: Follow 2–3 similar accounts ---
    follows_target = min(
        random.randint(2, DAILY_FOLLOW_LIMIT),
        DAILY_FOLLOW_LIMIT - state["follows"]
    )
    if follows_target > 0:
        try:
            tag = random.choice(hashtags)
            medias = cl.hashtag_medias_recent(tag, amount=20)
            candidates = []
            for m in medias:
                owner = getattr(m, 'user', None)
                if owner and owner.username not in follow_track:
                    candidates.append(owner)
            random.shuffle(candidates)
            for user in candidates[:follows_target]:
                try:
                    cl.user_follow(user.pk)
                    follows_done += 1
                    follow_track[user.username] = date.today().isoformat()
                    print(f"[IG Warmup] ➕ Followed @{user.username}")
                    _log_action("follow", user.username, "success", f"#{tag}")
                    _human_delay()
                except Exception as e:
                    err_str = str(e).lower()
                    if "feedback_required" in err_str or "action_blocked" in err_str:
                        print(f"[IG Warmup] ⚠️ Action block on follow — stopping")
                        _log_action("follow", user.username, "action_block", str(e))
                        break
                    errors += 1
                    _log_action("follow", user.username, "error", str(e))
        except Exception as e:
            print(f"[IG Warmup] Error during follow phase: {e}")
            errors += 1

    # --- Step 3: Unfollow stale accounts (followed 4+ days ago) ---
    today_str = date.today().isoformat()
    stale = [
        uname for uname, followed_date in follow_track.items()
        if (date.today() - date.fromisoformat(followed_date)).days >= UNFOLLOW_AFTER_DAYS
    ]
    random.shuffle(stale)
    for uname in stale[:2]:  # max 2 unfollows per session
        try:
            user_id = cl.user_id_from_username(uname)
            cl.user_unfollow(user_id)
            unfollows_done += 1
            del follow_track[uname]
            print(f"[IG Warmup] ➖ Unfollowed @{uname} (followed {UNFOLLOW_AFTER_DAYS}+ days ago)")
            _log_action("unfollow", uname, "success", "stale follow cleanup")
            _human_delay()
        except Exception as e:
            errors += 1
            _log_action("unfollow", uname, "error", str(e))

    # Update state
    state["likes"]     += likes_done
    state["follows"]   += follows_done
    state["views"]     += views_done
    state["unfollows"] += unfollows_done
    state["errors"]    += errors
    _save_state(state)
    _save_follow_track(follow_track)

    msg = (f"Liked {likes_done} posts, followed {follows_done} accounts, "
           f"viewed {views_done} posts, unfollowed {unfollows_done}")
    print(f"\n[IG Warmup] Session complete: {msg}")
    print(f"[IG Warmup] Daily totals: likes {state['likes']}/{DAILY_LIKE_LIMIT}, "
          f"follows {state['follows']}/{DAILY_FOLLOW_LIMIT}")

    return {
        "total_likes":     likes_done,
        "total_follows":   follows_done,
        "total_views":     views_done,
        "total_unfollows": unfollows_done,
        "errors":          errors,
        "daily_likes":     state["likes"],
        "daily_follows":   state["follows"],
        "message":         msg,
    }


def get_warmup_log(limit=50) -> list:
    """Return recent warmup log entries."""
    if not os.path.exists(WARMUP_LOG_FILE):
        return []
    entries = []
    with open(WARMUP_LOG_FILE) as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                pass
    return entries[-limit:]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run_warmup_session(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
