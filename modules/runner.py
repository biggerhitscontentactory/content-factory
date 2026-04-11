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
from image_generator import generate_ecommerce_images
from carousel_generator import generate_carousel_pdf
from scheduler import (
    schedule_ecommerce_content_pack, schedule_ai_channel_content_pack,
    log_scheduled_posts, get_daily_summary, load_daily_counts, get_oneup_accounts
)
from queue_manager import get_next_product, mark_product_posted, get_queue_stats
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
        "twitter":   os.environ.get("ONEUP_TWITTER_ID",   ""),
    },
    "ai_channel": {
        "linkedin":  os.environ.get("ONEUP_LINKEDIN_ID",  ""),
        "twitter":   os.environ.get("ONEUP_TWITTER_ID",   ""),
    }
}


# ─── Ecommerce Batch ──────────────────────────────────────────────────────────
def run_ecommerce_batch(count=5, dry_run=False, product_url=None):
    load_daily_counts()

    print(f"\n{'='*60}")
    print(f"ECOMMERCE CONTENT FACTORY — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'} | Batch size: {count}")
    print(f"Daily post status: {get_daily_summary()}")
    print(f"{'='*60}\n")

    processed = 0
    errors = 0

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

            # Generate images (skip in dry run)
            images = {}
            if not dry_run:
                print("[Runner] Generating images...")
                handle = product.get("handle", f"product_{i}")
                out_dir = os.path.join(OUTPUT_DIR_ECOMMERCE, handle)
                os.makedirs(out_dir, exist_ok=True)
                images = generate_ecommerce_images(content_pack, handle, out_dir)
                print(f"[Runner] Generated {len([v for v in images.values() if v])} images")

            # Schedule posts
            scheduled = {}
            if not dry_run:
                print("[Runner] Scheduling posts via OneUp...")
                scheduled = schedule_ecommerce_content_pack(
                    content_pack, images, ACCOUNT_IDS["ecommerce"]
                )
                log_scheduled_posts(scheduled, title, "ecommerce")
                print(f"[Runner] Scheduled {len(scheduled)} posts")
                mark_product_posted(product.get("id", ""), len(scheduled))
            else:
                pins = content_pack.get("pinterest_pins", [])
                ig   = content_pack.get("instagram_caption", "")
                fb   = content_pack.get("facebook_post", "")
                print(f"\n[Runner] DRY RUN PREVIEW:")
                print(f"[Runner] Would post: {len(pins)} Pinterest pins, 1 Instagram, 1 Facebook")
                for j, pin in enumerate(pins[:2], 1):
                    print(f"\n  Pinterest Pin {j}: {pin.get('title', '')}")
                    print(f"  Description: {pin.get('description', '')[:120]}...")
                if ig:
                    print(f"\n  Instagram Caption:\n  {ig[:200]}...")
                if fb:
                    print(f"\n  Facebook Post:\n  {fb[:200]}...")

            # Save content pack
            out_dir = os.path.join(OUTPUT_DIR_ECOMMERCE, product.get("handle", f"product_{i}"))
            os.makedirs(out_dir, exist_ok=True)
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
                pdf_path = generate_carousel_pdf(content_pack, topic_slug, out_dir)
                print(f"[Runner] Carousel saved: {pdf_path}")

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
    accounts = get_oneup_accounts()
    if not accounts:
        print("[Runner] No OneUp accounts found.")
        print("[Runner] Make sure ONEUP_API_KEY is set and accounts are connected in OneUp.")
        return
    print(f"\n[Runner] Found {len(accounts)} OneUp accounts:\n")
    for acc in accounts:
        platform = acc.get("service", acc.get("type", "unknown")).lower()
        name = acc.get("name", "")
        acc_id = acc.get("id", "")
        print(f"  Platform : {platform.upper()}")
        print(f"  Name     : {name}")
        print(f"  ID       : {acc_id}")
        print(f"  Env Var  : ONEUP_{platform.upper()}_ID={acc_id}")
        print()


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Content Factory Runner")
    parser.add_argument("--mode", choices=["ecommerce", "ai_channel", "get_accounts"],
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
