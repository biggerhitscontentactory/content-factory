"""
Content Factory — Pinterest Board Manager
==========================================
Fetches boards from Pinterest API v5, stores board-to-tier/category mapping,
and provides board_id lookup for the scheduler and repinner.

Pinterest API v5 docs: https://developers.pinterest.com/docs/api/v5/
OAuth token required: set PINTEREST_ACCESS_TOKEN in Railway env vars.

Board config is stored in data/board_config.json:
{
  "boards": [{"id": "...", "name": "...", "description": "..."}],
  "tier_map": {"1": "board_id", "2": "board_id", "3": "board_id"},
  "category_map": {"Hats": "board_id", "Apparel": "board_id", ...},
  "default_board_id": "board_id",
  "repin_boards": ["board_id1", "board_id2"],   # boards to repin INTO
  "last_fetched": "2026-04-11T..."
}
"""

import os
import json
import requests
from datetime import datetime
from config import DATA_DIR

PINTEREST_API_BASE = "https://api.pinterest.com/v5"
# PINTEREST_TOKEN is read at call time (see _pinterest_headers) to pick up Railway env vars
PINTEREST_TOKEN = ""  # not used directly

BOARD_CONFIG_FILE  = os.path.join(DATA_DIR, "board_config.json")


# ─── Load / Save Config ───────────────────────────────────────────────────────

def load_board_config():
    """Load board config from disk. Returns empty structure if not found."""
    if os.path.exists(BOARD_CONFIG_FILE):
        try:
            with open(BOARD_CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "boards": [],
        "tier_map": {},
        "category_map": {},
        "default_board_id": "",
        "repin_boards": [],
        "last_fetched": None,
    }


def save_board_config(config):
    """Persist board config to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(BOARD_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


# ─── Pinterest API Helpers ────────────────────────────────────────────────────

def _pinterest_headers():
    token = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def fetch_boards():
    """
    Fetch all boards for the authenticated Pinterest user.
    Returns list of dicts: [{id, name, description, pin_count, privacy}]
    """
    if not os.environ.get("PINTEREST_ACCESS_TOKEN", ""):
        return {"error": "PINTEREST_ACCESS_TOKEN not set in environment variables"}

    boards = []
    bookmark = None

    while True:
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark

        try:
            resp = requests.get(
                f"{PINTEREST_API_BASE}/boards",
                headers=_pinterest_headers(),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as e:
            return {"error": f"Pinterest API error: {e.response.status_code} — {e.response.text[:200]}"}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}

        items = data.get("items", [])
        for b in items:
            boards.append({
                "id": b.get("id", ""),
                "name": b.get("name", ""),
                "description": b.get("description", ""),
                "pin_count": b.get("pin_count", 0),
                "privacy": b.get("privacy", "PUBLIC"),
                "owner": b.get("owner", {}).get("username", ""),
            })

        bookmark = data.get("bookmark")
        if not bookmark or not items:
            break

    return {"boards": boards}


def refresh_boards():
    """
    Fetch boards from Pinterest API and update the config file.
    Preserves existing tier_map and category_map.
    Returns (success: bool, message: str, boards: list)
    """
    result = fetch_boards()
    if "error" in result:
        return False, result["error"], []

    boards = result["boards"]
    config = load_board_config()
    config["boards"] = boards
    config["last_fetched"] = datetime.now().isoformat()

    # Set default board if not already set
    if not config.get("default_board_id") and boards:
        config["default_board_id"] = boards[0]["id"]

    save_board_config(config)
    return True, f"Fetched {len(boards)} boards from Pinterest", boards


# ─── Board Lookup ─────────────────────────────────────────────────────────────

def get_board_for_product(product):
    """
    Return the best board_id for a given product dict.
    Priority: category_map → tier_map → default_board_id
    """
    config = load_board_config()

    # 1. Category match
    product_type = (product.get("product_type") or "").strip()
    if product_type and product_type in config.get("category_map", {}):
        return config["category_map"][product_type]

    # 2. Tier match
    tier = str(product.get("tier", 3))
    if tier in config.get("tier_map", {}):
        return config["tier_map"][tier]

    # 3. Default board
    return config.get("default_board_id", "")


def get_repin_boards():
    """Return list of board IDs configured for repinning."""
    config = load_board_config()
    return config.get("repin_boards", [])


def get_all_boards():
    """Return list of all known boards from config."""
    config = load_board_config()
    return config.get("boards", [])


def update_tier_map(tier_map):
    """Update tier → board_id mapping. tier_map = {"1": "id", "2": "id", "3": "id"}"""
    config = load_board_config()
    config["tier_map"] = tier_map
    save_board_config(config)


def update_category_map(category_map):
    """Update category → board_id mapping."""
    config = load_board_config()
    config["category_map"] = category_map
    save_board_config(config)


def update_repin_boards(board_ids):
    """Set which boards to repin into."""
    config = load_board_config()
    config["repin_boards"] = board_ids
    save_board_config(config)


def update_default_board(board_id):
    """Set the fallback default board."""
    config = load_board_config()
    config["default_board_id"] = board_id
    save_board_config(config)


# ─── Pinterest Direct Post (bypasses OneUp for board assignment) ──────────────

def post_pin_to_board(board_id, title, description, image_url, link=None):
    """
    Post a pin directly to Pinterest API v5 (bypasses OneUp).
    Use this when board_id assignment is needed.
    Returns (success, pin_id or error_message)
    """
    if not os.environ.get("PINTEREST_ACCESS_TOKEN", ""):
        return False, "PINTEREST_ACCESS_TOKEN not set"
    if not board_id:
        return False, "No board_id provided"

    payload = {
        "board_id": board_id,
        "title": title[:100],
        "description": description[:800],
        "media_source": {
            "source_type": "image_url",
            "url": image_url,
        },
    }
    if link:
        payload["link"] = link

    try:
        resp = requests.post(
            f"{PINTEREST_API_BASE}/pins",
            headers=_pinterest_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        pin_id = resp.json().get("id", "")
        return True, pin_id
    except requests.exceptions.HTTPError as e:
        return False, f"Pinterest API {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        return False, str(e)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "fetch":
        ok, msg, boards = refresh_boards()
        print(f"{'✓' if ok else '✗'} {msg}")
        for b in boards:
            print(f"  [{b['id']}] {b['name']} ({b['pin_count']} pins, {b['privacy']})")

    elif cmd == "list":
        boards = get_all_boards()
        if not boards:
            print("No boards cached. Run: python board_manager.py fetch")
        else:
            config = load_board_config()
            tier_map = config.get("tier_map", {})
            repin_boards = config.get("repin_boards", [])
            print(f"{'ID':<25} {'Name':<35} {'Tier':<6} {'Repin'}")
            print("-" * 80)
            for b in boards:
                tier_label = next((f"T{t}" for t, bid in tier_map.items() if bid == b["id"]), "—")
                repin_label = "✓" if b["id"] in repin_boards else ""
                print(f"{b['id']:<25} {b['name']:<35} {tier_label:<6} {repin_label}")

    elif cmd == "config":
        config = load_board_config()
        print(json.dumps(config, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python board_manager.py [fetch|list|config]")
