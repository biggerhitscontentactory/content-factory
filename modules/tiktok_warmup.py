"""
Content Factory — TikTok Daily Warmup Engine
=============================================
Simulates human engagement on TikTok to keep the account healthy
and avoid shadowbans or content suppression. Mirrors the IG warmup pattern.

Daily routine (configurable):
  - Browse 10–20 videos from niche hashtag/keyword feeds
  - Like 8–15 videos
  - Follow 2–3 accounts posting similar content
  - Optional: unfollow accounts followed 4+ days ago

Uses TikTok-Api (unofficial Python wrapper for TikTok's internal API).
Install: pip install TikTokApi playwright && python -m playwright install chromium

Required env vars:
  TIKTOK_SESSION_ID  — TikTok sessionid cookie (from browser DevTools)
                       Log into TikTok in Chrome → DevTools → Application →
                       Cookies → copy the value of "sessionid"

Safety limits:
  - Max 15 likes per session
  - Max 3 follows per session
  - 10–30 second random delays between actions
  - Stops on any rate-limit or ban signal
  - Daily state tracked in data/tiktok_warmup_state.json
"""

import os
import sys
import json
import time
import random
import logging
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from config import DATA_DIR, LOG_DIR

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────
WARMUP_STATE_FILE  = os.path.join(DATA_DIR, "tiktok_warmup_state.json")
WARMUP_LOG_FILE    = os.path.join(LOG_DIR,  "tiktok_warmup.jsonl")
FOLLOW_TRACK_FILE  = os.path.join(DATA_DIR, "tiktok_follow_track.json")

NICHE_KEYWORDS = [
    # Patriotic / USA
    "patriotic gifts", "made in usa", "american pride", "usa flag hat",
    "patriotic apparel", "american made products", "support local usa",
    # Gifts / ecommerce
    "unique gifts", "gift ideas for him", "gift ideas for her", "shop small business",
    "small business owner", "online shopping haul", "holiday gift ideas",
    # Apparel / hats
    "custom hats", "trucker hat", "embroidered hat", "hat collection",
    "streetwear outfit", "casual outfit ideas", "american apparel",
    # Home decor
    "home decor ideas", "american home decor", "rustic decor", "wall art decor",
    "home inspo", "farmhouse decor", "modern home decor",
]

DAILY_LIKE_LIMIT    = 15
DAILY_FOLLOW_LIMIT  = 3
DAILY_VIEW_LIMIT    = 20
UNFOLLOW_AFTER_DAYS = 4

MIN_DELAY = 10
MAX_DELAY = 30


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
        "platform": "tiktok",
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
    time.sleep(random.uniform(lo, hi))


def _pick_keywords(n=3) -> list:
    seed = int(date.today().isoformat().replace("-", "")) % len(NICHE_KEYWORDS)
    pool = NICHE_KEYWORDS[seed:] + NICHE_KEYWORDS[:seed]
    return random.sample(pool, min(n, len(pool)))


# ─── TikTok Client ────────────────────────────────────────────────────────────

async def _get_tiktok_api():
    """Get an authenticated TikTokApi instance using sessionid cookie."""
    try:
        from TikTokApi import TikTokApi
    except ImportError:
        raise ImportError(
            "TikTok warmup requires TikTokApi + Playwright (Chromium). "
            "These require system-level dependencies not available on Railway's standard builder. "
            "TikTok warmup is currently unavailable on this deployment."
        )
    session_id = os.environ.get("TIKTOK_SESSION_ID", "")
    if not session_id:
        raise ValueError(
            "TIKTOK_SESSION_ID not set. Log into TikTok in Chrome, open DevTools → "
            "Application → Cookies → copy the 'sessionid' value into Railway Variables."
        )
    api = TikTokApi()
    await api.create_sessions(
        ms_tokens=[None],
        num_sessions=1,
        sleep_after=3,
        cookies=[{"sessionid": session_id}],
        headless=True,
    )
    return api


# ─── Warmup Session ───────────────────────────────────────────────────────────

async def _run_live_session(state: dict, follow_track: dict) -> dict:
    """Async live session using TikTokApi."""
    likes_done    = 0
    follows_done  = 0
    views_done    = 0
    unfollows_done = 0
    errors        = 0

    keywords = _pick_keywords(3)
    print(f"[TikTok Warmup] Using keywords: {keywords}")

    api = await _get_tiktok_api()

    try:
        # --- Step 1: Browse keyword feeds and like videos ---
        for kw in keywords:
            if state["likes"] + likes_done >= DAILY_LIKE_LIMIT:
                break
            try:
                print(f"[TikTok Warmup] Browsing '{kw}'...")
                videos = []
                async for video in api.search.videos(kw, count=8):
                    videos.append(video)
                random.shuffle(videos)

                for video in videos:
                    if state["likes"] + likes_done >= DAILY_LIKE_LIMIT:
                        break
                    if state["views"] + views_done >= DAILY_VIEW_LIMIT:
                        break
                    views_done += 1
                    _human_delay(4, 12)  # shorter for views

                    if random.random() < 0.70:
                        try:
                            await video.like()
                            likes_done += 1
                            author = getattr(video, 'author', None)
                            uname = author.username if author else str(video.id)
                            print(f"[TikTok Warmup] ♥ Liked video by @{uname} ('{kw}')")
                            _log_action("like", uname, "success", kw)
                            _human_delay()
                        except Exception as e:
                            err_str = str(e).lower()
                            if any(x in err_str for x in ["ban", "block", "captcha", "risk"]):
                                print(f"[TikTok Warmup] ⚠️ Risk signal detected — stopping likes")
                                _log_action("like", "unknown", "risk_signal", str(e))
                                errors += 1
                                break
                            errors += 1
                            _log_action("like", str(getattr(video, 'id', '')), "error", str(e))
            except Exception as e:
                print(f"[TikTok Warmup] Error browsing '{kw}': {e}")
                errors += 1

        # --- Step 2: Follow 2–3 similar accounts ---
        follows_target = min(
            random.randint(2, DAILY_FOLLOW_LIMIT),
            DAILY_FOLLOW_LIMIT - state["follows"]
        )
        if follows_target > 0:
            try:
                kw = random.choice(keywords)
                candidates = []
                async for video in api.search.videos(kw, count=20):
                    author = getattr(video, 'author', None)
                    if author and author.username not in follow_track:
                        candidates.append(author)
                random.shuffle(candidates)
                for user in candidates[:follows_target]:
                    try:
                        await user.follow()
                        follows_done += 1
                        follow_track[user.username] = date.today().isoformat()
                        print(f"[TikTok Warmup] ➕ Followed @{user.username}")
                        _log_action("follow", user.username, "success", kw)
                        _human_delay()
                    except Exception as e:
                        err_str = str(e).lower()
                        if any(x in err_str for x in ["ban", "block", "captcha", "risk"]):
                            print(f"[TikTok Warmup] ⚠️ Risk signal on follow — stopping")
                            _log_action("follow", user.username, "risk_signal", str(e))
                            break
                        errors += 1
                        _log_action("follow", user.username, "error", str(e))
            except Exception as e:
                print(f"[TikTok Warmup] Error during follow phase: {e}")
                errors += 1

        # --- Step 3: Unfollow stale accounts ---
        stale = [
            uname for uname, followed_date in follow_track.items()
            if (date.today() - date.fromisoformat(followed_date)).days >= UNFOLLOW_AFTER_DAYS
        ]
        random.shuffle(stale)
        for uname in stale[:2]:
            try:
                user = api.user(username=uname)
                await user.unfollow()
                unfollows_done += 1
                del follow_track[uname]
                print(f"[TikTok Warmup] ➖ Unfollowed @{uname}")
                _log_action("unfollow", uname, "success", "stale follow cleanup")
                _human_delay()
            except Exception as e:
                errors += 1
                _log_action("unfollow", uname, "error", str(e))

    finally:
        await api.close_sessions()

    return {
        "total_likes":     likes_done,
        "total_follows":   follows_done,
        "total_views":     views_done,
        "total_unfollows": unfollows_done,
        "errors":          errors,
    }


def run_warmup_session(dry_run=False) -> dict:
    """
    Run a full TikTok warmup session.
    Wraps the async implementation for synchronous callers.
    """
    print(f"\n{'='*55}")
    print(f"TIKTOK WARMUP — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*55}\n")

    state = _load_state()
    follow_track = _load_follow_track()

    if state["likes"] >= DAILY_LIKE_LIMIT and state["follows"] >= DAILY_FOLLOW_LIMIT:
        msg = (f"Daily caps reached (likes: {state['likes']}/{DAILY_LIKE_LIMIT}, "
               f"follows: {state['follows']}/{DAILY_FOLLOW_LIMIT})")
        print(f"[TikTok Warmup] {msg}")
        return {"total_likes": state["likes"], "total_follows": state["follows"],
                "message": msg, "skipped": True}

    keywords = _pick_keywords(3)

    if dry_run:
        target_views   = random.randint(10, DAILY_VIEW_LIMIT)
        target_likes   = min(random.randint(8, DAILY_LIKE_LIMIT), DAILY_LIKE_LIMIT - state["likes"])
        target_follows = min(random.randint(2, DAILY_FOLLOW_LIMIT), DAILY_FOLLOW_LIMIT - state["follows"])
        print(f"[DRY RUN] Would view ~{target_views} videos")
        print(f"[DRY RUN] Would like ~{target_likes} videos")
        print(f"[DRY RUN] Would follow ~{target_follows} accounts")
        for kw in keywords:
            print(f"[DRY RUN] Would browse '{kw}'")
        _log_action("dry_run_session", str(keywords), "simulated",
                    f"views:{target_views} likes:{target_likes} follows:{target_follows}")
        return {
            "total_likes":   target_likes,
            "total_follows": target_follows,
            "total_views":   target_views,
            "total_unfollows": 0,
            "errors": 0,
            "message": f"DRY RUN: would like {target_likes}, follow {target_follows}, view {target_views}",
            "dry_run": True,
        }

    # Run async session
    import asyncio
    try:
        result = asyncio.run(_run_live_session(state, follow_track))
    except Exception as e:
        print(f"[TikTok Warmup] Session error: {e}")
        _log_action("session", "tiktok", "error", str(e))
        return {"error": str(e), "total_likes": 0, "total_follows": 0}

    state["likes"]     += result["total_likes"]
    state["follows"]   += result["total_follows"]
    state["views"]     += result["total_views"]
    state["unfollows"] += result["total_unfollows"]
    state["errors"]    += result["errors"]
    _save_state(state)
    _save_follow_track(follow_track)

    msg = (f"Liked {result['total_likes']} videos, followed {result['total_follows']} accounts, "
           f"viewed {result['total_views']} videos, unfollowed {result['total_unfollows']}")
    print(f"\n[TikTok Warmup] Session complete: {msg}")
    result["message"] = msg
    result["daily_likes"]   = state["likes"]
    result["daily_follows"] = state["follows"]
    return result


def get_warmup_log(limit=50) -> list:
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
