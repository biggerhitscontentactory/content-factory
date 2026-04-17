"""
Content Factory — HeyGen USA Store Video Generator
====================================================
Generates short (30-60 second) HeyGen avatar videos for USA Store products.
Uses the same HeyGen API as the AI Channel but with:
- Shorter scripts (product showcase format)
- USA Store avatar (configurable)
- Outputs to output/ecommerce/{handle}/heygen_video/

Env vars:
  HEYGEN_API_KEY              (required, same as AI Channel)
  HEYGEN_USA_STORE_ENABLED    (default: true)
  HEYGEN_USA_STORE_AVATAR_ID  (default: same as AI Channel avatar)
  HEYGEN_USA_STORE_VOICE_ID   (default: same as AI Channel voice)
"""
import os
import json
import time
import requests
from datetime import datetime

try:
    from config import (
        HEYGEN_API_KEY, HEYGEN_USA_STORE_ENABLED,
        HEYGEN_USA_STORE_AVATAR_ID, HEYGEN_USA_STORE_VOICE_ID,
        OUTPUT_DIR_ECOMMERCE, ECOMMERCE_STORE_URL
    )
except ImportError:
    HEYGEN_API_KEY = os.environ.get("HEYGEN_API_KEY", "")
    HEYGEN_USA_STORE_ENABLED = True
    HEYGEN_USA_STORE_AVATAR_ID = "01cd5898e6314ebbbc594840145dd829"
    HEYGEN_USA_STORE_VOICE_ID  = "cff38160a33643d7b8101d2ab989d5f1"
    OUTPUT_DIR_ECOMMERCE = os.path.join(os.path.dirname(__file__), "..", "output", "ecommerce")
    ECOMMERCE_STORE_URL = "https://www.officialusastore.com"

HEYGEN_API_BASE = "https://api.heygen.com"

def _headers():
    return {
        "X-Api-Key": os.environ.get("HEYGEN_API_KEY", HEYGEN_API_KEY),
        "Content-Type": "application/json",
    }

def build_product_video_script(product: dict, content_pack: dict) -> str:
    """
    Build a 30-60 second product showcase script from the content pack.
    Uses the video_script field if available, otherwise constructs one.
    """
    video_script = content_pack.get("video_script", {})
    if isinstance(video_script, dict) and video_script.get("hook"):
        hook = video_script.get("hook", "")
        body = video_script.get("body", "")
        cta  = video_script.get("cta", f"Shop now at {ECOMMERCE_STORE_URL}")
        script = f"{hook} {body} {cta}"
    else:
        title = product.get("title", "this product")
        price = product.get("price", "")
        price_str = f"just ${price:.2f}" if isinstance(price, (int, float)) else f"${price}"
        pins = content_pack.get("pinterest_pins", [])
        desc = pins[0].get("description", product.get("description", ""))[:200] if pins else product.get("description", "")[:200]
        script = (
            f"Hey everyone! I want to show you something amazing from the Official USA Store. "
            f"{title} — {desc} "
            f"And it's only {price_str}! "
            f"Perfect for celebrating America's 250th anniversary. "
            f"Shop now at {ECOMMERCE_STORE_URL} — link in bio!"
        )
    # Keep it under ~600 words for a 60-second video
    words = script.split()
    if len(words) > 120:
        script = " ".join(words[:120]) + "..."
    return script.strip()

def submit_heygen_video(script: str, title: str = "USA Store Product Video") -> dict:
    """
    Submit a video generation request to HeyGen API v2.
    Returns {"video_id": ..., "status": "pending"} or {"error": ...}
    """
    api_key = os.environ.get("HEYGEN_API_KEY", HEYGEN_API_KEY)
    if not api_key:
        return {"error": "HEYGEN_API_KEY not set"}

    avatar_id = os.environ.get("HEYGEN_USA_STORE_AVATAR_ID", HEYGEN_USA_STORE_AVATAR_ID)
    voice_id  = os.environ.get("HEYGEN_USA_STORE_VOICE_ID",  HEYGEN_USA_STORE_VOICE_ID)

    payload = {
        "video_inputs": [{
            "character": {
                "type": "avatar",
                "avatar_id": avatar_id,
                "avatar_style": "normal",
            },
            "voice": {
                "type": "text",
                "input_text": script,
                "voice_id": voice_id,
                "speed": 1.0,
            },
            "background": {
                "type": "color",
                "value": "#0B1A2E",
            }
        }],
        "dimension": {"width": 1080, "height": 1920},
        "title": title[:80],
        "test": False,
    }

    try:
        resp = requests.post(
            f"{HEYGEN_API_BASE}/v2/video/generate",
            headers=_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        video_id = data.get("video_id", "")
        print(f"[HeyGen USA Store] Submitted video: {video_id}")
        return {"video_id": video_id, "status": "pending", "title": title}
    except requests.exceptions.HTTPError as e:
        err = f"HeyGen API {e.response.status_code}: {e.response.text[:200]}"
        print(f"[HeyGen USA Store] Error: {err}")
        return {"error": err}
    except Exception as e:
        print(f"[HeyGen USA Store] Error: {e}")
        return {"error": str(e)}

def generate_usa_store_video(product: dict, content_pack: dict, dry_run: bool = False) -> dict:
    """
    Main entry point: generate a HeyGen product video for a USA Store product.
    Saves job info to output/ecommerce/{handle}/heygen_video/job.json
    Returns job dict.
    """
    enabled = os.environ.get("HEYGEN_USA_STORE_ENABLED", "true").lower() == "true"
    if not enabled:
        print("[HeyGen USA Store] Disabled via HEYGEN_USA_STORE_ENABLED env var")
        return {"skipped": "disabled"}

    api_key = os.environ.get("HEYGEN_API_KEY", HEYGEN_API_KEY)
    if not api_key:
        print("[HeyGen USA Store] HEYGEN_API_KEY not set — skipping")
        return {"skipped": "no api key"}

    handle = product.get("handle", product.get("id", "unknown"))
    title  = product.get("title", "USA Store Product")
    out_dir = os.path.join(OUTPUT_DIR_ECOMMERCE, handle, "heygen_video")
    os.makedirs(out_dir, exist_ok=True)

    script = build_product_video_script(product, content_pack)
    print(f"[HeyGen USA Store] Script ({len(script.split())} words): {script[:100]}...")

    if dry_run:
        job = {
            "video_id": f"dry_run_{handle}",
            "status": "dry_run",
            "title": title,
            "script": script,
            "product_handle": handle,
            "created_at": datetime.now().isoformat(),
        }
        print(f"[HeyGen USA Store] DRY RUN — would submit: {title}")
    else:
        result = submit_heygen_video(script, title=f"USA Store: {title[:60]}")
        if "error" in result:
            return result
        job = {
            **result,
            "script": script,
            "product_handle": handle,
            "product_title": title,
            "created_at": datetime.now().isoformat(),
        }

    # Save job info
    job_file = os.path.join(out_dir, "job.json")
    with open(job_file, "w") as f:
        json.dump(job, f, indent=2)
    print(f"[HeyGen USA Store] Job saved: {job_file}")
    return job

def check_video_status(video_id: str) -> dict:
    """Check the status of a HeyGen video."""
    api_key = os.environ.get("HEYGEN_API_KEY", HEYGEN_API_KEY)
    if not api_key:
        return {"error": "HEYGEN_API_KEY not set"}
    try:
        resp = requests.get(
            f"{HEYGEN_API_BASE}/v1/video_status.get",
            headers=_headers(),
            params={"video_id": video_id},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return {
            "video_id": video_id,
            "status": data.get("status", "unknown"),
            "video_url": data.get("video_url", ""),
            "thumbnail_url": data.get("thumbnail_url", ""),
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        vid = sys.argv[2] if len(sys.argv) > 2 else ""
        if vid:
            print(json.dumps(check_video_status(vid), indent=2))
    else:
        # Test with a dummy product
        test_product = {
            "title": "American Eagle Patriotic Hat",
            "price": 29.99,
            "handle": "american-eagle-hat",
            "url": "https://www.officialusastore.com/products/american-eagle-hat",
            "description": "Bold American Eagle design, perfect for July 4th and America 250th celebrations.",
        }
        test_pack = {
            "video_script": {
                "hook": "Looking for the perfect patriotic gift?",
                "body": "This American Eagle hat is bold, beautiful, and made for proud Americans celebrating 250 years of freedom.",
                "cta": "Shop now at officialusastore.com — link in bio!",
            }
        }
        result = generate_usa_store_video(test_product, test_pack, dry_run="--dry-run" in sys.argv)
        print(json.dumps(result, indent=2))
