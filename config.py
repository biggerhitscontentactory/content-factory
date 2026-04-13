"""
Content Factory — Configuration
================================
All settings read from environment variables (set in Railway dashboard).
Never hardcode API keys in this file.
"""

import os

# ─── OpenAI ───────────────────────────────────────────────────────────────────
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL  = "https://api.openai.com/v1"
OPENAI_MODEL     = "gpt-4o-mini"
OPENAI_IMAGE_MODEL = "dall-e-3"

# ─── Shopify ──────────────────────────────────────────────────────────────────
SHOPIFY_STORE_URL   = "officialusastore.myshopify.com"
SHOPIFY_ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "")
SHOPIFY_API_VERSION = "2024-01"

# ─── OneUp ────────────────────────────────────────────────────────────────────
ONEUP_API_KEY = os.environ.get("ONEUP_API_KEY", "")

# ─── HeyGen ───────────────────────────────────────────────────────────────────
HEYGEN_API_KEY       = os.environ.get("HEYGEN_API_KEY", "")
HEYGEN_AVATAR_ID     = "01cd5898e6314ebbbc594840145dd829"   # Brian Tines
HEYGEN_VOICE_ID      = "cff38160a33643d7b8101d2ab989d5f1"   # Brian Tines voice (Essential plan)
HEYGEN_SHEET_ID      = os.environ.get("HEYGEN_SHEET_ID", "1xPAwaOish_Nw6Fix4xGEqeR_EfQaFwL2XcsWkfxy3q0")
HEYGEN_VIDEO_MIN_MIN = 7    # minimum video length in minutes
HEYGEN_VIDEO_MAX_MIN = 13   # maximum video length in minutes
HEYGEN_DAILY_LIMIT   = int(os.environ.get("HEYGEN_DAILY_LIMIT", 3))

# ─── Google Sheets (optional) ─────────────────────────────────────────────────
GOOGLE_SHEETS_CREDENTIALS_FILE = "google_credentials.json"
ECOMMERCE_SHEET_ID  = os.environ.get("ECOMMERCE_SHEET_ID", "")
AI_CHANNEL_SHEET_ID = os.environ.get("AI_CHANNEL_SHEET_ID", "")

# ─── Project Settings ─────────────────────────────────────────────────────────
ECOMMERCE_STORE_NAME = "Official USA Store"
ECOMMERCE_STORE_URL  = "https://www.officialusastore.com"
ECOMMERCE_NICHE      = "patriotic USA merchandise, America 250th Anniversary gifts"

AI_CHANNEL_NAME    = "Laptops and Latitude"
AI_CHANNEL_URL     = "https://www.youtube.com/@LaptopsandLatitude"
AI_CHANNEL_WEBSITE = "https://laptopsandlatitude.com"

# ─── Daily Posting Limits (anti-ban) ─────────────────────────────────────────
DAILY_LIMITS = {
    "pinterest": int(os.environ.get("LIMIT_PINTEREST", 25)),
    "instagram": int(os.environ.get("LIMIT_INSTAGRAM", 1)),
    "facebook":  int(os.environ.get("LIMIT_FACEBOOK",  2)),
    "tiktok":    int(os.environ.get("LIMIT_TIKTOK",    1)),
    "youtube":   int(os.environ.get("LIMIT_YOUTUBE",   1)),
    "twitter":   int(os.environ.get("LIMIT_TWITTER",   4)),
    "linkedin":  int(os.environ.get("LIMIT_LINKEDIN",  2)),
}

MIN_GAP_MINUTES = {
    "pinterest": 45, "instagram": 60, "facebook": 90,
    "tiktok": 240,   "youtube": 120,  "twitter": 60, "linkedin": 90,
}

# ─── Tier Rules ───────────────────────────────────────────────────────────────
TIER_1_KEYWORDS = [
    "250", "anniversary", "1776", "2026", "america 250",
    "semiquincentennial", "birthday", "independence"
]
TIER_1_MIN_PRICE = 25.00
TIER_2_KEYWORDS  = ["patriotic", "eagle", "flag", "freedom", "usa", "american"]
TIER_3_FALLBACK  = True

RECYCLE_COOLDOWN = {1: 30, 2: 60, 3: 90}

# ─── Sprint Mode ──────────────────────────────────────────────────────────────
AMERICA_250_END_DATE = "2026-07-05"
SPRINT_RECYCLE_DAYS  = 21

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR               = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR_ECOMMERCE   = os.path.join(BASE_DIR, "output", "ecommerce")
OUTPUT_DIR_AI_CHANNEL  = os.path.join(BASE_DIR, "output", "ai_channel")
LOG_DIR                = os.path.join(BASE_DIR, "logs")
DATA_DIR               = os.path.join(BASE_DIR, "data")
