"""
Content Factory - Google Sheets Connector
==========================================
Reads trigger rows from Google Sheets and writes back status/results.
Two sheets:
  - Ecommerce Sheet: product URL trigger → auto-generate content pack
  - AI Channel Sheet: topic brief → generate LinkedIn/Twitter content

SETUP REQUIRED:
  1. Create a Google Cloud project and enable Sheets API
  2. Create a Service Account and download JSON credentials
  3. Save credentials as 'google_credentials.json' in this directory
  4. Share both Google Sheets with the service account email
"""

import os
import json
import time
from datetime import datetime

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    print("[Sheets] gspread not installed. Run: pip install gspread google-auth")

from config import (
    GOOGLE_SHEETS_CREDENTIALS_FILE,
    ECOMMERCE_SHEET_ID,
    AI_CHANNEL_SHEET_ID
)

# ─── Google Sheets column definitions ─────────────────────────────────────────

# Ecommerce sheet columns
ECOMMERCE_COLUMNS = {
    "A": "product_url",
    "B": "product_title",       # auto-filled after scrape
    "C": "price",               # auto-filled
    "D": "tier",                # auto-filled (1/2/3)
    "E": "goal",                # manual: Traffic / Sales / Launch / Recycle
    "F": "tone",                # manual: Viral / Lifestyle / UGC / Educational
    "G": "offer",               # manual: e.g. "10% off with JULY4"
    "H": "status",              # auto: Pending / Processing / Done / Error
    "I": "pinterest_captions",  # auto-filled
    "J": "instagram_caption",   # auto-filled
    "K": "facebook_post",       # auto-filled
    "L": "video_hook",          # auto-filled
    "M": "video_script",        # auto-filled
    "N": "image_folder",        # auto-filled: path to generated images
    "O": "scheduled_at",        # auto-filled: when posts were scheduled
    "P": "notes",               # manual: any notes
    "Q": "last_updated",        # auto-filled timestamp
}

# AI Channel sheet columns
AI_CHANNEL_COLUMNS = {
    "A": "topic",               # manual: topic/idea
    "B": "pillar",              # manual: Marketing Automation / Ecommerce AI / etc.
    "C": "target_client",       # manual: who this is for
    "D": "pain_point",          # manual: the problem being addressed
    "E": "proof_element",       # manual: stat, case study, or result
    "F": "cta",                 # manual: desired action
    "G": "status",              # auto: Pending / Processing / Done / Error
    "H": "linkedin_post",       # auto-filled
    "I": "carousel_outline",    # auto-filled (JSON)
    "J": "twitter_thread",      # auto-filled
    "K": "image_folder",        # auto-filled
    "L": "scheduled_at",        # auto-filled
    "M": "notes",               # manual
    "N": "last_updated",        # auto-filled
}


def get_sheets_client():
    """Initialize and return authenticated gspread client."""
    if not GSPREAD_AVAILABLE:
        raise ImportError("gspread not installed")

    creds_file = GOOGLE_SHEETS_CREDENTIALS_FILE
    if not os.path.exists(creds_file):
        raise FileNotFoundError(
            f"Google credentials file not found: {creds_file}\n"
            "Please download your service account JSON from Google Cloud Console."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
    return gspread.authorize(creds)


def get_pending_ecommerce_rows(sheet_id=None):
    """
    Fetch all rows from ecommerce sheet where status is 'Pending' or empty.
    Returns list of dicts with row data + row number.
    """
    if not sheet_id:
        sheet_id = ECOMMERCE_SHEET_ID
    if not sheet_id:
        print("[Sheets] No ecommerce sheet ID configured")
        return []

    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(sheet_id).sheet1
        rows = sheet.get_all_records()
        pending = []
        for i, row in enumerate(rows, start=2):  # start=2 because row 1 is header
            status = str(row.get("status", "")).strip().lower()
            url = str(row.get("product_url", "")).strip()
            if url and status in ("", "pending"):
                row["_row_number"] = i
                pending.append(row)
        print(f"[Sheets] Found {len(pending)} pending ecommerce rows")
        return pending
    except Exception as e:
        print(f"[Sheets] Error reading ecommerce sheet: {e}")
        return []


def get_pending_ai_channel_rows(sheet_id=None):
    """
    Fetch all rows from AI channel sheet where status is 'Pending' or empty.
    """
    if not sheet_id:
        sheet_id = AI_CHANNEL_SHEET_ID
    if not sheet_id:
        print("[Sheets] No AI channel sheet ID configured")
        return []

    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(sheet_id).sheet1
        rows = sheet.get_all_records()
        pending = []
        for i, row in enumerate(rows, start=2):
            status = str(row.get("status", "")).strip().lower()
            topic = str(row.get("topic", "")).strip()
            if topic and status in ("", "pending"):
                row["_row_number"] = i
                pending.append(row)
        print(f"[Sheets] Found {len(pending)} pending AI channel rows")
        return pending
    except Exception as e:
        print(f"[Sheets] Error reading AI channel sheet: {e}")
        return []


def update_ecommerce_row(sheet_id, row_number, content_pack, image_folder="", scheduled_at=""):
    """Write generated content back to the ecommerce Google Sheet row."""
    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(sheet_id).sheet1

        product = content_pack.get("product", {})
        pins = content_pack.get("pinterest_pins", [])
        ig = content_pack.get("instagram_post", {})
        fb = content_pack.get("facebook_post", {})
        vs = content_pack.get("video_script", {})

        pin_captions = " | ".join([p.get("description", "") for p in pins[:3]])
        ig_caption = ig.get("caption", "") + " " + ig.get("hashtags", "")
        fb_text = fb.get("text", "")
        video_hook = vs.get("hook", "")
        video_script = f"{vs.get('hook','')} {vs.get('body','')} {vs.get('cta','')}".strip()

        updates = {
            "B": product.get("title", ""),
            "C": str(product.get("price", "")),
            "D": str(product.get("tier", "")),
            "H": "Done",
            "I": pin_captions[:500],
            "J": ig_caption[:300],
            "K": fb_text[:300],
            "L": video_hook[:200],
            "M": video_script[:500],
            "N": image_folder,
            "O": scheduled_at,
            "Q": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        for col, value in updates.items():
            col_index = ord(col) - ord("A") + 1
            sheet.update_cell(row_number, col_index, value)
            time.sleep(0.1)  # avoid Sheets API rate limits

        print(f"[Sheets] Updated ecommerce row {row_number}")
    except Exception as e:
        print(f"[Sheets] Error updating ecommerce row {row_number}: {e}")


def update_ai_channel_row(sheet_id, row_number, content_pack, image_folder="", scheduled_at=""):
    """Write generated content back to the AI channel Google Sheet row."""
    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(sheet_id).sheet1

        li_post = content_pack.get("linkedin_text_post", {})
        carousel = content_pack.get("linkedin_carousel", {})
        thread = content_pack.get("twitter_thread", {})

        carousel_json = json.dumps(carousel.get("slides", []))[:1000]
        thread_text = "\n".join([t.get("text", "") for t in thread.get("tweets", [])])[:1000]

        updates = {
            "G": "Done",
            "H": li_post.get("full_post", "")[:500],
            "I": carousel_json,
            "J": thread_text[:500],
            "K": image_folder,
            "L": scheduled_at,
            "N": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        for col, value in updates.items():
            col_index = ord(col) - ord("A") + 1
            sheet.update_cell(row_number, col_index, value)
            time.sleep(0.1)

        print(f"[Sheets] Updated AI channel row {row_number}")
    except Exception as e:
        print(f"[Sheets] Error updating AI channel row {row_number}: {e}")


def mark_row_error(sheet_id, row_number, error_msg, sheet_type="ecommerce"):
    """Mark a row as errored with the error message."""
    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(sheet_id).sheet1
        status_col = 8 if sheet_type == "ecommerce" else 7  # column H or G
        sheet.update_cell(row_number, status_col, f"Error: {error_msg[:100]}")
        notes_col = 16 if sheet_type == "ecommerce" else 13
        sheet.update_cell(row_number, notes_col, error_msg[:200])
    except Exception as e:
        print(f"[Sheets] Error marking row {row_number} as error: {e}")


def create_sheet_template(sheet_type="ecommerce"):
    """
    Print the header row template for copy-pasting into a new Google Sheet.
    """
    if sheet_type == "ecommerce":
        headers = list(ECOMMERCE_COLUMNS.values())
    else:
        headers = list(AI_CHANNEL_COLUMNS.values())

    print(f"\n{sheet_type.upper()} SHEET HEADERS (copy to row 1):")
    print("\t".join(headers))
    return headers


if __name__ == "__main__":
    print("Google Sheets Connector")
    print("=" * 40)
    print("\nEcommerce sheet headers:")
    create_sheet_template("ecommerce")
    print("\nAI Channel sheet headers:")
    create_sheet_template("ai_channel")

    if not os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE):
        print(f"\n⚠ Google credentials file not found: {GOOGLE_SHEETS_CREDENTIALS_FILE}")
        print("To set up Google Sheets integration:")
        print("1. Go to console.cloud.google.com")
        print("2. Create a project → Enable Google Sheets API")
        print("3. Create Service Account → Download JSON key")
        print(f"4. Save as '{GOOGLE_SHEETS_CREDENTIALS_FILE}' in this directory")
        print("5. Share your Google Sheets with the service account email")
    else:
        print(f"\n✓ Credentials file found: {GOOGLE_SHEETS_CREDENTIALS_FILE}")
