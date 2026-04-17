"""
Content Factory - Runner
=========================
Entry point for running content generation batches.
Called by the web app via subprocess, or directly from command line.

Usage:
  python3 runner.py --mode ecommerce [--count 5] [--dry-run]
  python3 runner.py --mode ai_channel [--dry-run]
  python3 runner.py --mode get_accounts
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime

# ─── Path Setup ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_DIR  = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, MOD_DIR)

# Create required directories on startup
for _d in ["data", "logs", "output/ecommerce", "output/ai_channel"]:
    os.makedirs(os.path.join(BASE_DIR, _d), exist_ok=True)

# ─── Imports ──────────────────────────────────────────────────────────────────
from shopify_connector import get_product_by_url, extract_product_data
from content_engine import generate_ecommerce_content_pack, generate_ai_channel_content_pack
from image_generator import generate_product_images
try:
    from carousel_generator import generate_carousel_pdf
except ImportError:
    generate_carousel_pdf = None
from scheduler import (
    schedule_ecommerce_content_pack, schedule_ai_channel_content_pack,
    log_scheduled_posts, get_daily_summary, load_daily_counts, get_oneup_accounts
)
from queue_manager import get_next_product, mark_product_posted, get_queue_stats
try:
    from board_manager import get_board_for_product, get_repin_boards, get_all_boards
except ImportError:
    get_board_for_product = lambda p: ""
    get_repin_boards = lambda: []
    get_all_boards = lambda: []
try:
    from repinner import run_repin_session
except ImportError:
    run_repin_session = None
from config import (
    OUTPUT_DIR_ECOMMERCE, OUTPUT_DIR_AI_CHANNEL, LOG_DIR, DATA_DIR,
    AI_CHANNEL_SHEET_ID
)

# ─── Account IDs from Environment Variables ───────────────────────────────────
ACCOUNT_IDS = {
    "ecommerce": {
        "pinterest": os.environ.get("ONEUP_PINTEREST_ID", ""),
        "instagram": os.environ.get("ONEUP_INSTAGRAM_ID", ""),
        "facebook":  os.environ.get("ONEUP_FACEBOOK_ID",  ""),
        "tiktok":    os.environ.get("ONEUP_TIKTOK_ID",    ""),
        "youtube":   os.environ.get("ONEUP_YOUTUBE_ID",   ""),
        "twitter":   os.environ.get("ONEUP_TWITTER_ID",   ""),
    },
    "ai_channel": {
        "linkedin":  os.environ.get("ONEUP_LINKEDIN_ID",  ""),
        "twitter":   os.environ.get("ONEUP_TWITTER_ID",   ""),
    }
}


# ─── Ecommerce Batch ──────────────────────────────────────────────────────────
def _relative_output_path(abs_path: str) -> str:
    """Convert absolute output path to a web-accessible relative path."""
    if abs_path.startswith(BASE_DIR):
        rel = abs_path[len(BASE_DIR):].lstrip("/")
        return rel
    return abs_path


def run_ecommerce_batch(count=5, dry_run=False, product_url=None):
    load_daily_counts()

    print(f"\n{'='*60}")
    print(f"ECOMMERCE CONTENT FACTORY — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'} | Batch size: {count}")
    print(f"Daily post status: {get_daily_summary()}")
    print(f"{'='*60}\n")

    processed = 0
    errors = 0
    preview_items = []   # Structured output for dashboard rendering

    for i in range(count):
        # Get product
        if product_url:
            print(f"[Runner] Processing specific URL: {product_url}")
            raw = get_product_by_url(product_url)
            product = extract_product_data(raw) if raw else None
            if not product:
                print(f"[Runner] Could not fetch product from URL: {product_url}")
                break
        else:
            product = get_next_product()
            if not product:
                print("[Runner] Queue empty or all products in cooldown — run Rebuild Queue")
                break

        title = product.get("title", "Unknown")
        handle = product.get("handle", f"product_{i}")
        print(f"\n[{i+1}/{count}] Processing: {title[:60]}")
        print(f"         Tier: {product.get('tier', 3)} | Price: ${product.get('price', 0)}")

        try:
            # Generate content
            print("[Runner] Generating content pack...")
            content_pack = generate_ecommerce_content_pack(product)
            if "error" in content_pack:
                print(f"[Runner] Content error: {content_pack['error']}")
                errors += 1
                continue

            # Generate images — in BOTH dry run and live run
            print("[Runner] Generating images with DALL-E 3...")
            out_dir = os.path.join(OUTPUT_DIR_ECOMMERCE, handle)
            os.makedirs(out_dir, exist_ok=True)
            images = generate_product_images(product, content_pack, out_dir, dry_run=dry_run)
            total_imgs = sum(len(v) for v in images.values() if v)
            print(f"[Runner] Generated {total_imgs} images")

            # Resolve Pinterest board_id for this product
            board_id = get_board_for_product(product)
            if board_id:
                print(f"[Runner] Pinterest board: {board_id}")
            else:
                print("[Runner] No board mapped — pin will go to default board")

            # Schedule posts (live only)
            scheduled = {}
            if not dry_run:
                print("[Runner] Scheduling posts via OneUp...")
                scheduled = schedule_ecommerce_content_pack(
                    content_pack, images, ACCOUNT_IDS["ecommerce"],
                    dry_run=False
                )
                log_scheduled_posts(scheduled, title, "ecommerce")
                print(f"[Runner] Scheduled {len(scheduled)} posts")
                mark_product_posted(product.get("id", ""), len(scheduled))
                # HeyGen short product video (USA Store)
                try:
                    from heygen_usa_store import generate_usa_store_video
                    generate_usa_store_video(product, content_pack, dry_run=dry_run)
                except Exception as hg_err:
                    print(f"[Runner] HeyGen USA Store video skipped: {hg_err}")

            # Build preview item for dashboard
            pins = content_pack.get("pinterest_pins", [])
            ig_post = content_pack.get("instagram_post", {})
            fb_post = content_pack.get("facebook_post", {})
            ig_caption = ig_post.get("caption", "") if isinstance(ig_post, dict) else str(ig_post)
            ig_hashtags = ig_post.get("hashtags", "") if isinstance(ig_post, dict) else ""
            fb_text = fb_post.get("text", "") if isinstance(fb_post, dict) else str(fb_post)

            # Convert absolute image paths to relative web paths
            web_images = {}
            for platform, paths in images.items():
                web_images[platform] = [_relative_output_path(p) for p in paths]

            preview_item = {
                "title": title,
                "handle": handle,
                "tier": product.get("tier", 3),
                "price": product.get("price", 0),
                "board_id": board_id,
                "images": web_images,
                "pinterest_pins": [
                    {
                        "title": p.get("title", ""),
                        "description": p.get("description", "")[:200],
                    }
                    for p in pins[:3]
                ],
                "instagram": {
                    "caption": ig_caption[:300],
                    "hashtags": ig_hashtags[:200],
                },
                "facebook": {
                    "text": fb_text[:300],
                },
                "scheduled": len(scheduled),
                "dry_run": dry_run,
            }
            preview_items.append(preview_item)

            # Human-readable output for logs
            print(f"\n[Runner] {'DRY RUN' if dry_run else 'LIVE'} PREVIEW:")
            print(f"  Pinterest Pins: {len(pins)}")
            for j, pin in enumerate(pins[:2], 1):
                print(f"    Pin {j}: {pin.get('title', '')[:70]}")
            if ig_caption:
                print(f"  Instagram: {ig_caption[:120]}...")
            if fb_text:
                print(f"  Facebook: {fb_text[:120]}...")
            print(f"  Images generated: {total_imgs}")
            for plat, paths in web_images.items():
                for p in paths:
                    print(f"    [{plat}] {p}")

            # Save content pack
            with open(os.path.join(out_dir, "content_pack.json"), "w") as f:
                json.dump(content_pack, f, indent=2)

            processed += 1
            print(f"\n[Runner] ✓ Done: {title[:50]}")

            if i < count - 1 and not product_url:
                time.sleep(3 if dry_run else 6)

        except Exception as e:
            import traceback
            print(f"[Runner] ✗ Error: {e}")
            traceback.print_exc()
            errors += 1
            continue

        if product_url:
            break

    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE: {processed} processed, {errors} errors")
    print(f"Daily post status: {get_daily_summary()}")
    print(f"{'='*60}\n")

    # Emit structured JSON block for dashboard parsing
    if preview_items:
        print("__PREVIEW_JSON_START__")
        print(json.dumps(preview_items, indent=2))
        print("__PREVIEW_JSON_END__")

    return processed, errors


# ─── AI Channel Batch ─────────────────────────────────────────────────────────
def run_ai_channel_batch(dry_run=False):
    load_daily_counts()

    print(f"\n{'='*60}")
    print(f"AI CHANNEL CONTENT FACTORY — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    # Load topics from local file
    rows = []
    topic_file = os.path.join(DATA_DIR, "ai_topics.jsonl")
    if os.path.exists(topic_file):
        with open(topic_file) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("status") == "pending":
                        rows.append(entry)
                except Exception:
                    pass

    # Fall back to Google Sheets if configured
    if not rows and AI_CHANNEL_SHEET_ID:
        try:
            from sheets_connector import get_pending_ai_channel_rows
            rows = get_pending_ai_channel_rows(AI_CHANNEL_SHEET_ID)
        except Exception as e:
            print(f"[Runner] Google Sheets error: {e}")

    # Fall back to demo row
    if not rows:
        print("[Runner] No pending topics — using demo row for testing...")
        rows = [{
            "topic": "How I built a content factory that posts 25 times a day automatically",
            "pillar": "Marketing Automation",
            "target_client": "Ecommerce store owners and marketing agencies",
            "pain_point": "Spending hours manually creating and scheduling social media content",
            "proof_element": "Reduced content creation time from 4 hours/day to 15 minutes",
            "cta": "Comment 'FACTORY' and I'll send you the blueprint",
        }]

    processed = 0
    errors = 0

    for row in rows[:3]:
        topic = row.get("topic", "Unknown topic")
        print(f"\n[Runner] Processing: {topic[:60]}")

        try:
            print("[Runner] Generating AI channel content pack...")
            content_pack = generate_ai_channel_content_pack(row)
            if "error" in content_pack:
                print(f"[Runner] Content error: {content_pack['error']}")
                errors += 1
                continue

            # Preview
            li_post  = content_pack.get("linkedin_post", "")
            carousel = content_pack.get("carousel_slides", [])
            tw_thread = content_pack.get("twitter_thread", [])
            print(f"\n--- LINKEDIN POST ---")
            print(li_post[:400] + ("..." if len(li_post) > 400 else ""))
            print(f"\n--- CAROUSEL: {content_pack.get('carousel_title', '')[:60]} ---")
            for s in (carousel or [])[:3]:
                print(f"  Slide {s.get('slide', '')}: {s.get('headline', '')[:60]}")
            if len(carousel or []) > 3:
                print(f"  ... ({len(carousel)} slides total)")
            if tw_thread:
                print(f"\n--- TWITTER THREAD ({len(tw_thread)} tweets) ---")
                print(f"  {tw_thread[0][:100]}...")

            if not dry_run:
                print("\n[Runner] Generating carousel PDF...")
                topic_slug = "".join(c for c in topic[:30].lower().replace(" ", "_") if c.isalnum() or c == "_")
                out_dir = os.path.join(OUTPUT_DIR_AI_CHANNEL, topic_slug)
                os.makedirs(out_dir, exist_ok=True)
                if generate_carousel_pdf:
                    pdf_path = generate_carousel_pdf(content_pack, topic_slug, out_dir)
                    print(f"[Runner] Carousel saved: {pdf_path}")
                else:
                    pdf_path = ""
                    print("[Runner] Carousel generator not available")

                print("[Runner] Scheduling via OneUp...")
                scheduled = schedule_ai_channel_content_pack(
                    content_pack, {"carousel_pdf": pdf_path}, ACCOUNT_IDS["ai_channel"]
                )
                log_scheduled_posts(scheduled, topic, "ai_channel")
                print(f"[Runner] Scheduled {len(scheduled)} posts")

                # Mark topic done
                _mark_topic_done(topic_file, topic)

            processed += 1
            print(f"\n[Runner] ✓ Done: {topic[:50]}")
            time.sleep(3)

        except Exception as e:
            import traceback
            print(f"[Runner] ✗ Error: {e}")
            traceback.print_exc()
            errors += 1

    print(f"\nAI CHANNEL BATCH COMPLETE: {processed} processed, {errors} errors\n")
    return processed, errors


def _mark_topic_done(topic_file, topic_text):
    if not os.path.exists(topic_file):
        return
    lines = []
    with open(topic_file) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("topic") == topic_text and entry.get("status") == "pending":
                    entry["status"] = "done"
                lines.append(json.dumps(entry))
            except Exception:
                lines.append(line.strip())
    with open(topic_file, "w") as f:
        f.write("\n".join(lines) + "\n")


def get_oneup_account_ids():
    """
    Fetch and display all connected OneUp accounts with their social_network_id values.
    The real OneUp API returns: username, full_name, social_network_type
    social_network_id is retrieved from /listcategoryaccount and is what goes in env vars.
    """
    accounts = get_oneup_accounts()
    if not accounts:
        print("[Runner] No OneUp accounts found.")
        print("[Runner] Make sure ONEUP_API_KEY is set and accounts are connected in OneUp.")
        return
    # Also fetch categories to get social_network_id values
    from scheduler import get_oneup_categories, get_category_accounts
    categories = get_oneup_categories()
    # Build map of (network_type_lower, name) -> social_network_id
    sn_id_map = {}
    for cat in categories:
        cat_id = cat.get("category_id") or cat.get("id")
        if cat_id:
            cat_accounts = get_category_accounts(cat_id)
            for ca in cat_accounts:
                nt = ca.get("social_network_type", "").lower()
                nm = ca.get("social_network_name", "")
                sn_id_map[(nt, nm)] = ca.get("social_network_id", "")
    platform_map = {
        "pinterest": "PINTEREST", "instagram": "INSTAGRAM", "facebook": "FACEBOOK",
        "linkedin": "LINKEDIN", "twitter": "TWITTER", "x": "TWITTER",
        "tiktok": "TIKTOK", "youtube": "YOUTUBE",
    }
    print(f"\n[Runner] Found {len(accounts)} connected OneUp accounts:\n")
    for acc in accounts:
        network_type = acc.get("social_network_type", "unknown")
        username = acc.get("username", "")
        full_name = acc.get("full_name", "")
        is_expired = acc.get("is_expired", 0)
        nt_lower = network_type.lower()
        sn_id = sn_id_map.get((nt_lower, username), "") or sn_id_map.get((nt_lower, full_name), "")
        env_platform = platform_map.get(nt_lower, network_type.upper())
        status = "EXPIRED" if is_expired else "active"
        print(f"  Platform : {network_type}")
        print(f"  Username : {username} ({full_name})")
        print(f"  Status   : {status}")
        if sn_id:
            print(f"  ID       : {sn_id}")
            print(f"  Env Var  : ONEUP_{env_platform}_ID={sn_id}")
        else:
            print(f"  ID       : (add this account to a OneUp Category first)")
            print(f"  Env Var  : ONEUP_{env_platform}_ID=<from OneUp category accounts>")
        print()


# ─── Repin Batch ─────────────────────────────────────────────────────────────
def run_repin_batch(dry_run=False):
    """Run a Pinterest repinning session using configured boards."""
    print(f"\n{'='*60}")
    print(f"PINTEREST REPINNER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    if run_repin_session is None:
        print("[Repinner] repinner module not available")
        return 0, 1

    repin_ids = get_repin_boards()
    boards = get_all_boards()
    name_map = {b["id"]: b["name"] for b in boards}

    if not repin_ids:
        print("[Repinner] No repin boards configured.")
        print("[Repinner] Go to Setup → Board Selector → check boards for repinning.")
        return 0, 0

    print(f"[Repinner] Repin boards: {[name_map.get(bid, bid) for bid in repin_ids]}")
    result = run_repin_session(repin_ids, name_map, dry_run=dry_run)

    if "error" in result:
        print(f"[Repinner] Error: {result['error']}")
        return 0, 1

    print(f"\n{result['message']}")
    print(f"By board: {result.get('by_board', {})}")
    print(f"Skipped: {result.get('skipped', 0)} | Errors: {result.get('errors', 0)}")

    # Emit JSON block for dashboard
    print("__REPIN_JSON_START__")
    print(json.dumps(result, indent=2))
    print("__REPIN_JSON_END__")

    return result.get("total", 0), result.get("errors", 0)


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Content Factory Runner")
    parser.add_argument("--mode",
                        choices=["ecommerce", "ai_channel", "get_accounts", "repin",
                                 "ig_warmup", "tiktok_warmup"],
                        default="ecommerce")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--product-url", type=str, default="")
    args = parser.parse_args()

    if args.mode == "ecommerce":
        run_ecommerce_batch(count=args.count, dry_run=args.dry_run,
                            product_url=args.product_url or None)
    elif args.mode == "ai_channel":
        run_ai_channel_batch(dry_run=args.dry_run)
    elif args.mode == "get_accounts":
        get_oneup_account_ids()
    elif args.mode == "repin":
        run_repin_batch(dry_run=args.dry_run)
    elif args.mode == "ig_warmup":
        import importlib
        ig_warmup_mod = importlib.import_module("ig_warmup")
        result = ig_warmup_mod.run_warmup_session(dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
    elif args.mode == "tiktok_warmup":
        import importlib
        tiktok_warmup_mod = importlib.import_module("tiktok_warmup")
        result = tiktok_warmup_mod.run_warmup_session(dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
