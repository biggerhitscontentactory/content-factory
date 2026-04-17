"""
Content Factory — Higgsfield AI UGC Video Generator
=====================================================
Generates UGC-style product videos for USA Store using Higgsfield AI API.
These are short (5-15 second) social-native videos using UGC presets like
"Outfit Check", "Static Posing", "Selfie", etc. — great for TikTok/Reels.

API: https://cloud.higgsfield.ai (requires HIGGSFIELD_API_KEY)
Endpoint: POST /v1/video/generate (image-to-video with UGC preset)

Env vars:
  HIGGSFIELD_API_KEY   (required — get from cloud.higgsfield.ai)

Usage:
  from higgsfield import generate_ugc_video
  result = generate_ugc_video(product, image_url, preset="outfit_check")
"""
import os
import json
import time
import requests
from datetime import datetime

try:
    from config import HIGGSFIELD_API_KEY, OUTPUT_DIR_ECOMMERCE
except ImportError:
    HIGGSFIELD_API_KEY = os.environ.get("HIGGSFIELD_API_KEY", "")
    OUTPUT_DIR_ECOMMERCE = os.path.join(os.path.dirname(__file__), "..", "output", "ecommerce")

HIGGSFIELD_API_BASE = "https://api.higgsfield.ai"

# UGC presets best suited for patriotic apparel/gifts
UGC_PRESETS_APPAREL = [
    "outfit_check", "selfie_outfit", "static_posing", "fix_and_pose",
    "selfie_posing", "happy", "peak_moment", "timelapse_glam",
]
UGC_PRESETS_GIFTS = [
    "static_posing", "selfie", "happy", "fix_and_pose",
    "group_photo", "morning_routine",
]
UGC_PRESETS_HATS = [
    "outfit_check", "selfie_outfit", "sunglasses", "fix_and_pose",
    "static_posing", "selfie_posing",
]

def _headers():
    key = os.environ.get("HIGGSFIELD_API_KEY", HIGGSFIELD_API_KEY)
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

def get_preset_for_product(product: dict) -> str:
    """Pick the best UGC preset based on product category."""
    import random
    category = (product.get("product_type") or "").lower()
    tags = [t.lower() for t in product.get("tags", [])]
    if any(x in category or x in " ".join(tags) for x in ["hat", "cap"]):
        return random.choice(UGC_PRESETS_HATS)
    if any(x in category or x in " ".join(tags) for x in ["shirt", "apparel", "hoodie", "tee", "clothing"]):
        return random.choice(UGC_PRESETS_APPAREL)
    return random.choice(UGC_PRESETS_GIFTS)

def generate_ugc_video(product: dict, image_url: str, preset: str = None,
                        dry_run: bool = False) -> dict:
    """
    Generate a UGC-style product video using Higgsfield AI.

    Args:
        product: product dict with title, handle, etc.
        image_url: URL of the product image to use as reference
        preset: UGC preset name (e.g. "outfit_check"). Auto-selected if None.
        dry_run: if True, simulate without calling API

    Returns:
        dict with video_id, status, preset used, and output path info
    """
    api_key = os.environ.get("HIGGSFIELD_API_KEY", HIGGSFIELD_API_KEY)
    if not api_key:
        return {"error": "HIGGSFIELD_API_KEY not set in Railway env vars"}

    if not image_url:
        return {"error": "No image_url provided"}

    if not preset:
        preset = get_preset_for_product(product)

    handle = product.get("handle", product.get("id", "unknown"))
    title  = product.get("title", "USA Store Product")
    out_dir = os.path.join(OUTPUT_DIR_ECOMMERCE, handle, "higgsfield_ugc")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[Higgsfield] Generating UGC video: preset={preset}, product={title[:50]}")

    if dry_run:
        result = {
            "video_id": f"dry_run_{handle}_{preset}",
            "status": "dry_run",
            "preset": preset,
            "product_handle": handle,
            "product_title": title,
            "image_url": image_url,
            "created_at": datetime.now().isoformat(),
        }
        print(f"[Higgsfield] DRY RUN — would generate {preset} video for {title}")
        with open(os.path.join(out_dir, "job.json"), "w") as f:
            json.dump(result, f, indent=2)
        return result

    # Higgsfield API: image-to-video with UGC preset
    # API endpoint: POST /v1/video/ugc
    payload = {
        "image_url": image_url,
        "preset": preset,
        "aspect_ratio": "9:16",   # vertical for TikTok/Reels
        "duration": 6,            # seconds (5-15 available)
    }

    try:
        resp = requests.post(
            f"{HIGGSFIELD_API_BASE}/v1/video/ugc",
            headers=_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        video_id = data.get("video_id") or data.get("id") or data.get("job_id", "")
        result = {
            "video_id": video_id,
            "status": data.get("status", "pending"),
            "preset": preset,
            "product_handle": handle,
            "product_title": title,
            "image_url": image_url,
            "created_at": datetime.now().isoformat(),
            "raw_response": data,
        }
        print(f"[Higgsfield] Video submitted: {video_id}")
        with open(os.path.join(out_dir, "job.json"), "w") as f:
            json.dump(result, f, indent=2)
        return result

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        body = e.response.text[:300]
        print(f"[Higgsfield] API error {status_code}: {body}")
        if status_code == 401:
            return {"error": "Invalid HIGGSFIELD_API_KEY — check your key at cloud.higgsfield.ai"}
        if status_code == 402:
            return {"error": "Higgsfield account out of credits — top up at higgsfield.ai/pricing"}
        return {"error": f"Higgsfield API {status_code}: {body}"}
    except Exception as e:
        print(f"[Higgsfield] Error: {e}")
        return {"error": str(e)}

def check_video_status(video_id: str) -> dict:
    """Poll Higgsfield for video completion status."""
    api_key = os.environ.get("HIGGSFIELD_API_KEY", HIGGSFIELD_API_KEY)
    if not api_key:
        return {"error": "HIGGSFIELD_API_KEY not set"}
    try:
        resp = requests.get(
            f"{HIGGSFIELD_API_BASE}/v1/video/{video_id}",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "video_id": video_id,
            "status": data.get("status", "unknown"),
            "video_url": data.get("video_url") or data.get("output_url", ""),
            "thumbnail_url": data.get("thumbnail_url", ""),
        }
    except Exception as e:
        return {"error": str(e)}

def generate_ugc_batch(products: list, dry_run: bool = False) -> list:
    """
    Generate UGC videos for a batch of products.
    Uses the first product image as the reference image.
    """
    results = []
    for product in products:
        images = product.get("images", [])
        if not images:
            results.append({"error": "no images", "product": product.get("handle", "")})
            continue
        image_url = images[0] if isinstance(images[0], str) else images[0].get("src", "")
        result = generate_ugc_video(product, image_url, dry_run=dry_run)
        results.append(result)
        if not dry_run:
            time.sleep(5)  # Rate limit: 5 seconds between requests
    return results

if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    test_product = {
        "title": "Patriotic American Eagle Hat",
        "handle": "patriotic-eagle-hat",
        "product_type": "Hats",
        "tags": ["hat", "patriotic", "eagle", "usa"],
        "images": ["https://cdn.shopify.com/s/files/1/0000/0000/products/eagle-hat.jpg"],
    }
    result = generate_ugc_video(
        test_product,
        "https://cdn.shopify.com/s/files/1/0000/0000/products/eagle-hat.jpg",
        dry_run=dry
    )
    print(json.dumps(result, indent=2))
