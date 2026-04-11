"""
Content Factory — Pinterest Repinner
======================================
Automatically repins trending content from Pinterest to your boards.

Strategy:
- 25–45 repins per day, spread across all configured repin boards
- 5–10 repins per board per run
- Rotates through keyword lists per board category
- Anti-spam: random delays, daily caps, skip already-repinned pins
- Saves repin log to data/repin_log.json

Pinterest API v5 used:
  GET  /v5/pins/search          — search for trending pins by keyword
  POST /v5/pins                 — save/repin a pin to a board (parent_pin_id)

Requires: PINTEREST_ACCESS_TOKEN in Railway env vars
"""

import os
import json
import time
import random
import requests
from datetime import datetime, date
from config import DATA_DIR

PINTEREST_API_BASE = "https://api.pinterest.com/v5"
PINTEREST_TOKEN    = os.environ.get("PINTEREST_ACCESS_TOKEN", "")

REPIN_LOG_FILE     = os.path.join(DATA_DIR, "repin_log.json")
REPIN_STATE_FILE   = os.path.join(DATA_DIR, "repin_state.json")

# ─── Keyword pools per board theme ────────────────────────────────────────────
# These rotate so Pinterest doesn't flag repetitive search patterns.
# Add more keywords to expand reach.

KEYWORD_POOLS = {
    "patriotic": [
        "american flag decor", "patriotic home decor", "USA pride",
        "4th of July decorations", "american eagle art", "red white blue decor",
        "patriotic gifts", "american pride gifts", "stars and stripes",
        "independence day ideas", "july 4th party ideas", "american flag fashion",
        "patriotic wall art", "USA flag gifts", "american heritage",
    ],
    "america_250": [
        "america 250th anniversary", "semiquincentennial 2026",
        "america birthday 2026", "1776 2026 anniversary",
        "america 250 celebration", "USA 250 years",
        "america 250th birthday gifts", "bicentennial plus 50",
        "america anniversary decor", "250 years of freedom",
    ],
    "gifts": [
        "patriotic gift ideas", "american gifts for him",
        "american gifts for her", "USA themed gifts",
        "4th of July gifts", "military appreciation gifts",
        "american pride gifts", "unique american gifts",
        "patriotic home gifts", "USA souvenir gifts",
    ],
    "apparel": [
        "patriotic shirts", "american flag tshirt",
        "USA hoodie", "patriotic clothing",
        "american flag fashion", "4th of july outfit",
        "patriotic dress", "USA apparel",
        "american eagle clothing", "red white blue outfit",
    ],
    "hats": [
        "american flag hat", "patriotic baseball cap",
        "USA trucker hat", "patriotic dad hat",
        "american eagle hat", "4th of july hat",
        "stars and stripes hat", "USA cap",
        "patriotic snapback", "american pride hat",
    ],
    "home_decor": [
        "patriotic home decor", "american flag wall art",
        "USA living room decor", "patriotic kitchen decor",
        "american themed bedroom", "flag display ideas",
        "patriotic porch decor", "american farmhouse decor",
        "4th of july home decor", "red white blue home",
    ],
    "general": [
        "patriotic DIY", "american history facts",
        "USA travel destinations", "american landmarks",
        "patriotic recipes", "american flag crafts",
        "USA bucket list", "american culture",
        "patriotic quotes", "american pride",
    ],
}

# Default keyword pool to use when board theme is unknown
DEFAULT_KEYWORD_POOL = "patriotic"

# Daily repin limits
DAILY_REPIN_MIN = 25
DAILY_REPIN_MAX = 45
REPINS_PER_BOARD_MIN = 5
REPINS_PER_BOARD_MAX = 10

# Delay between repins (seconds) — looks more human
REPIN_DELAY_MIN = 8
REPIN_DELAY_MAX = 25


# ─── State / Log Helpers ──────────────────────────────────────────────────────

def load_repin_state():
    """Load today's repin state (count, used pin IDs, keyword cursor)."""
    today = date.today().isoformat()
    if os.path.exists(REPIN_STATE_FILE):
        try:
            with open(REPIN_STATE_FILE) as f:
                state = json.load(f)
            if state.get("date") == today:
                return state
        except Exception:
            pass
    return {
        "date": today,
        "total_repins": 0,
        "repinned_ids": [],       # pin IDs already repinned today
        "board_counts": {},       # board_id → count today
        "keyword_cursors": {},    # pool_name → next index
    }


def save_repin_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REPIN_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def log_repin(board_id, board_name, pin_id, keyword, dry_run=False):
    os.makedirs(DATA_DIR, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(),
        "board_id": board_id,
        "board_name": board_name,
        "pin_id": pin_id,
        "keyword": keyword,
        "dry_run": dry_run,
    }
    with open(REPIN_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ─── Pinterest API Helpers ────────────────────────────────────────────────────

def _headers():
    return {
        "Authorization": f"Bearer {PINTEREST_TOKEN}",
        "Content-Type": "application/json",
    }


def search_pins(keyword, count=20):
    """
    Search Pinterest for pins matching keyword.
    Returns list of pin dicts: [{id, title, description, link, image_url}]
    Note: Pinterest API search returns pins from the authenticated user's
    following network. For broader search, we use the /pins endpoint with
    ad_account_id scope or rely on the organic search endpoint.
    """
    if not PINTEREST_TOKEN:
        return []

    try:
        resp = requests.get(
            f"{PINTEREST_API_BASE}/search/pins",
            headers=_headers(),
            params={"query": keyword, "page_size": min(count, 25)},
            timeout=15,
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            pins = []
            for p in items:
                pins.append({
                    "id": p.get("id", ""),
                    "title": p.get("title", ""),
                    "description": p.get("description", ""),
                    "link": p.get("link", ""),
                    "image_url": (p.get("media", {}) or {}).get("images", {}).get("originals", {}).get("url", ""),
                })
            return pins
        else:
            print(f"[Repinner] Search returned {resp.status_code}: {resp.text[:100]}")
            return []
    except Exception as e:
        print(f"[Repinner] Search error: {e}")
        return []


def repin(board_id, source_pin_id):
    """
    Save/repin a pin to a board using Pinterest API v5.
    POST /v5/pins with parent_pin_id = source_pin_id
    Returns (success, new_pin_id or error)
    """
    if not PINTEREST_TOKEN:
        return False, "PINTEREST_ACCESS_TOKEN not set"

    payload = {
        "board_id": board_id,
        "media_source": {
            "source_type": "pin_url",
            "pin_id": source_pin_id,
        },
    }

    try:
        resp = requests.post(
            f"{PINTEREST_API_BASE}/pins",
            headers=_headers(),
            json=payload,
            timeout=20,
        )
        if resp.status_code in (200, 201):
            new_pin_id = resp.json().get("id", "")
            return True, new_pin_id
        else:
            return False, f"HTTP {resp.status_code}: {resp.text[:150]}"
    except Exception as e:
        return False, str(e)


# ─── Keyword Rotation ─────────────────────────────────────────────────────────

def get_next_keyword(pool_name, state):
    """Pick the next keyword from a pool, rotating through all of them."""
    pool = KEYWORD_POOLS.get(pool_name, KEYWORD_POOLS[DEFAULT_KEYWORD_POOL])
    cursors = state.setdefault("keyword_cursors", {})
    idx = cursors.get(pool_name, 0)
    keyword = pool[idx % len(pool)]
    cursors[pool_name] = (idx + 1) % len(pool)
    return keyword


def board_keyword_pool(board_name):
    """Map a board name to a keyword pool name."""
    name_lower = board_name.lower()
    if any(x in name_lower for x in ["hat", "cap"]):
        return "hats"
    if any(x in name_lower for x in ["shirt", "apparel", "cloth", "wear", "hoodie", "tee"]):
        return "apparel"
    if any(x in name_lower for x in ["home", "decor", "wall", "kitchen", "living"]):
        return "home_decor"
    if any(x in name_lower for x in ["gift"]):
        return "gifts"
    if any(x in name_lower for x in ["250", "anniversary", "semiquincentennial", "birthday"]):
        return "america_250"
    if any(x in name_lower for x in ["patriot", "america", "usa", "flag", "eagle"]):
        return "patriotic"
    return "general"


# ─── Main Repinning Run ───────────────────────────────────────────────────────

def run_repin_session(repin_board_ids, board_name_map=None, dry_run=False):
    """
    Execute a repinning session across the given boards.

    Args:
        repin_board_ids: list of Pinterest board IDs to repin into
        board_name_map: dict {board_id: board_name} for keyword pool selection
        dry_run: if True, simulate without actually posting

    Returns:
        dict with summary: {total, by_board, skipped, errors, log}
    """
    if not PINTEREST_TOKEN and not dry_run:
        return {"error": "PINTEREST_ACCESS_TOKEN not set. Add it in Railway env vars."}

    if not repin_board_ids:
        return {"error": "No repin boards configured. Set them in the Board Selector tab."}

    board_name_map = board_name_map or {}
    state = load_repin_state()

    # Determine today's target
    daily_target = random.randint(DAILY_REPIN_MIN, DAILY_REPIN_MAX)
    already_done = state.get("total_repins", 0)
    remaining_today = max(0, daily_target - already_done)

    if remaining_today == 0:
        return {
            "total": 0,
            "skipped": 0,
            "errors": 0,
            "message": f"Daily repin target ({daily_target}) already reached for today.",
            "log": [],
        }

    repinned_ids_set = set(state.get("repinned_ids", []))
    summary = {"total": 0, "by_board": {}, "skipped": 0, "errors": 0, "log": []}

    # Shuffle boards so rotation is varied each run
    boards_shuffled = list(repin_board_ids)
    random.shuffle(boards_shuffled)

    for board_id in boards_shuffled:
        if summary["total"] >= remaining_today:
            break

        board_name = board_name_map.get(board_id, board_id)
        pool_name  = board_keyword_pool(board_name)
        keyword    = get_next_keyword(pool_name, state)

        # How many to repin to this board this session
        per_board_target = random.randint(REPINS_PER_BOARD_MIN, REPINS_PER_BOARD_MAX)
        per_board_target = min(per_board_target, remaining_today - summary["total"])

        board_count = state.get("board_counts", {}).get(board_id, 0)
        if board_count >= REPINS_PER_BOARD_MAX * 2:
            print(f"[Repinner] Board {board_name} already hit daily cap, skipping")
            continue

        print(f"[Repinner] Board: {board_name} | Keyword: '{keyword}' | Target: {per_board_target}")

        # Search for pins
        candidates = search_pins(keyword, count=per_board_target + 5)
        if not candidates:
            print(f"[Repinner] No pins found for '{keyword}'")
            summary["skipped"] += 1
            continue

        board_repins = 0
        for pin in candidates:
            if board_repins >= per_board_target:
                break

            pin_id = pin.get("id", "")
            if not pin_id or pin_id in repinned_ids_set:
                summary["skipped"] += 1
                continue

            if dry_run:
                print(f"  [DRY RUN] Would repin {pin_id} ({pin.get('title', '')[:50]}) → {board_name}")
                success, result = True, f"dry_run_{pin_id}"
            else:
                success, result = repin(board_id, pin_id)
                # Human-like delay between repins
                time.sleep(random.uniform(REPIN_DELAY_MIN, REPIN_DELAY_MAX))

            if success:
                repinned_ids_set.add(pin_id)
                board_repins += 1
                summary["total"] += 1
                summary["by_board"][board_name] = summary["by_board"].get(board_name, 0) + 1
                state.setdefault("board_counts", {})[board_id] = board_count + board_repins
                log_entry = {
                    "board": board_name,
                    "pin_id": pin_id,
                    "title": pin.get("title", "")[:60],
                    "keyword": keyword,
                    "new_pin_id": result,
                }
                summary["log"].append(log_entry)
                log_repin(board_id, board_name, pin_id, keyword, dry_run=dry_run)
                print(f"  ✓ Repinned {pin_id} → {board_name}")
            else:
                summary["errors"] += 1
                print(f"  ✗ Failed to repin {pin_id}: {result}")

    # Update state
    state["total_repins"] = already_done + summary["total"]
    state["repinned_ids"] = list(repinned_ids_set)
    save_repin_state(state)

    summary["message"] = (
        f"Repinned {summary['total']} pins across {len(summary['by_board'])} boards "
        f"({'dry run' if dry_run else 'live'}). "
        f"Daily total: {state['total_repins']}/{daily_target}"
    )
    return summary


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from board_manager import get_repin_boards, get_all_boards

    dry = "--dry-run" in sys.argv

    boards = get_all_boards()
    repin_ids = get_repin_boards()
    name_map = {b["id"]: b["name"] for b in boards}

    if not repin_ids:
        print("No repin boards configured.")
        print("Go to the dashboard → Setup → Board Selector → select boards for repinning.")
        sys.exit(1)

    print(f"Starting repin session — {len(repin_ids)} boards — {'DRY RUN' if dry else 'LIVE'}")
    result = run_repin_session(repin_ids, name_map, dry_run=dry)

    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"\n{result['message']}")
    print(f"By board: {result['by_board']}")
    print(f"Skipped: {result['skipped']} | Errors: {result['errors']}")
