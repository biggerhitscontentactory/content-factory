"""
Content Factory - Image Generator
====================================
Generates platform-ready images using DALL-E 3 (lifestyle scenes matching
OfficialUSAStore.com Pinterest style), then adds text overlays via PIL.

Platform specs:
  Pinterest  : 1000 x 1500 px (2:3 vertical)  -- 3 pins per product, DALL-E
  Instagram  : 1080 x 1080 px (1:1 square)    -- 1 image, DALL-E, minimal text
  Facebook   : 1200 x 630  px (landscape)     -- cropped from Instagram image
"""

import os
import io
import time
import base64
import requests
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# Brand Colors
COLOR_NAVY   = (15,  30,  70)
COLOR_RED    = (178, 34,  52)
COLOR_WHITE  = (255, 255, 255)
COLOR_GOLD   = (212, 175, 55)
COLOR_CREAM  = (255, 253, 240)

# Platform Specs
PLATFORM_SPECS = {
    "pinterest": {"size": (1000, 1500), "dalle_size": "1024x1792"},
    "instagram": {"size": (1080, 1080), "dalle_size": "1024x1024"},
    "facebook":  {"size": (1200, 630)},
}

# Pinterest Content Angles — used for DALL-E lifestyle scene generation
PIN_ANGLES = [
    "patriotic backyard party scene with American flags, gold stars, red white blue confetti on white wood table",
    "happy American family outdoors celebrating with patriotic decorations, warm golden sunset light",
    "elegant product flatlay on white rustic wood surface surrounded by mini American flags, gold stars, red white blue ribbon",
    "festive America 250th anniversary party setup with string lights, patriotic decor, 1776 neon sign",
    "close-up lifestyle shot with patriotic props: confetti, small flags, gold coins, celebration atmosphere",
]

# 9 unique Pinterest lifestyle scene angles for manual post generation
# Each angle creates a visually distinct pin for the same product
MANUAL_PIN_ANGLES = [
    # Angle 0 — Gift presentation / unboxing moment
    (
        "A beautifully wrapped patriotic gift box being opened on a white marble table. "
        "Red, white and blue tissue paper spilling out. Gold ribbon and bow. "
        "The product is prominently displayed next to the open box. "
        "Soft natural window light. Warm and celebratory mood."
    ),
    # Angle 1 — Outdoor lifestyle / Fourth of July celebration
    (
        "An outdoor Fourth of July backyard party scene. "
        "String lights overhead, American flags in the background, sparklers in the distance. "
        "The product is placed on a rustic wooden picnic table surrounded by patriotic decorations. "
        "Golden hour sunset light, warm and festive atmosphere."
    ),
    # Angle 2 — Flatlay / styled product shot
    (
        "A top-down flatlay on a clean white wood surface. "
        "The product is centered and surrounded by patriotic props: "
        "mini American flags, gold star confetti, red white blue ribbon, a small 1776 tag. "
        "Bright, clean, editorial Pinterest style. High contrast, crisp shadows."
    ),
    # Angle 3 — Lifestyle / person using/wearing the product
    (
        "A lifestyle photo of a proud American holding or wearing the product outdoors. "
        "Casual patriotic outfit, American flag visible in the background. "
        "Warm golden light, genuine smile, authentic and aspirational mood. "
        "Shallow depth of field, product is the clear focal point."
    ),
    # Angle 4 — America 250th anniversary themed
    (
        "An America 250th anniversary celebration scene. "
        "The product is displayed on a decorated table with a '1776-2026' banner, "
        "gold and navy balloons, confetti, and a small American flag centerpiece. "
        "Elegant, festive, commemorative mood. Warm indoor lighting."
    ),
    # Angle 5 — Rustic Americana / farmhouse style
    (
        "A rustic Americana farmhouse setting. "
        "The product is placed on a weathered barn wood surface with vintage American flag, "
        "mason jars with red white blue wildflowers, and a lantern. "
        "Warm, nostalgic, patriotic mood. Soft natural light."
    ),
    # Angle 6 — Military / veteran tribute
    (
        "A respectful military tribute scene. "
        "The product is displayed next to a neatly folded American flag, "
        "military dog tags, and a framed photo of a soldier. "
        "Dark navy background with dramatic lighting. "
        "Powerful, emotional, proud American mood."
    ),
    # Angle 7 — Summer / beach / outdoor adventure
    (
        "A bright summer outdoor scene at a beach or lake. "
        "The product is featured with patriotic beach accessories: "
        "red white blue beach towel, sunglasses, small American flag in the sand. "
        "Bright blue sky, warm sunlight, fun and energetic summer mood."
    ),
    # Angle 8 — Cozy home / living room display
    (
        "A cozy American home living room scene. "
        "The product is displayed on a mantle or shelf alongside patriotic home decor: "
        "framed 'God Bless America' sign, small eagle figurine, red white blue candles. "
        "Warm indoor lighting, homey and proud American atmosphere."
    ),
]

# Bundled Font Paths (relative to this file, committed to repo)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_FONTS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "static", "fonts")
_FONT_BOLD    = os.path.join(_FONTS_DIR, "LiberationSans-Bold.ttf")
_FONT_REGULAR = os.path.join(_FONTS_DIR, "LiberationSans-Regular.ttf")

# System font fallbacks
_SYSTEM_BOLD = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
]
_SYSTEM_REGULAR = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
]


def get_openai_client():
    """
    Returns an OpenAI client configured for IMAGE generation (DALL-E 3).
    Always uses the real OpenAI API endpoint, NOT any proxy.
    Priority for API key:
      1. DALLE_API_KEY env var (dedicated image key)
      2. OPENAI_API_KEY_DALLE env var
      3. OPENAI_API_KEY env var
    Base URL is always https://api.openai.com/v1 for image generation.
    """
    from openai import OpenAI
    api_key = (
        os.environ.get("DALLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY_DALLE")
        or os.environ.get("OPENAI_API_KEY", "")
    )
    # Always use the real OpenAI API for image generation — never a proxy
    return OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")


def _load_font(size: int, bold: bool = True):
    """
    Load a font at the given pixel size.
    Priority: bundled repo font -> system font -> PIL default (last resort).
    """
    primary = _FONT_BOLD if bold else _FONT_REGULAR
    fallbacks = _SYSTEM_BOLD if bold else _SYSTEM_REGULAR

    if os.path.exists(primary):
        try:
            font = ImageFont.truetype(primary, size)
            print(f"[Font] Loaded bundled {'bold' if bold else 'regular'} at {size}px from {primary}")
            return font
        except Exception as e:
            print(f"[Font] Bundled font failed: {e}")

    for path in fallbacks:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                print(f"[Font] Loaded system font {path} at {size}px")
                return font
            except Exception:
                continue

    print(f"[Font] WARNING: falling back to PIL default font -- text will be tiny!")
    return ImageFont.load_default()


def get_font(size: int):
    return _load_font(size, bold=True)


def get_font_regular(size: int):
    return _load_font(size, bold=False)


def wrap_text(text: str, font, max_width: int, draw) -> list:
    words = text.split()
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def smart_crop(img, target_w: int, target_h: int):
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_h = target_h
        new_w = int(src_w * (target_h / src_h))
    else:
        new_w = target_w
        new_h = int(src_h * (target_w / src_w))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def download_image(url: str):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        print(f"[ImageGen] Failed to download: {e}")
        return None


def _draw_patriotic_bg(bg: Image.Image):
    """Draw patriotic navy→red gradient with subtle stars on a PIL Image in place."""
    w, h = bg.size
    draw_bg = ImageDraw.Draw(bg)
    navy = (13, 43, 100)
    red  = (178, 34, 34)
    for y in range(h):
        t = y / h
        r = int(navy[0] + (red[0] - navy[0]) * t)
        g = int(navy[1] + (red[1] - navy[1]) * t)
        b = int(navy[2] + (red[2] - navy[2]) * t)
        draw_bg.line([(0, y), (w, y)], fill=(r, g, b))
    import random as _rnd
    _rnd.seed(42)
    for _ in range(60):
        sx = _rnd.randint(0, w)
        sy = _rnd.randint(0, int(h * 0.6))
        sr = _rnd.randint(1, 3)
        draw_bg.ellipse([sx-sr, sy-sr, sx+sr, sy+sr], fill=(255, 255, 255, 80))


def build_product_composite(product: dict, size: tuple, bg_style: str = "gradient") -> Image.Image:
    """
    Build a platform image using the actual product photo as the HERO on a patriotic background.

    Layout philosophy:
    - Portrait/Square (Pinterest, Instagram, TikTok):
        Top 12% = white text bar (added by overlay function later)
        Middle 80% = product photo, centered, fills as much space as possible
        Bottom 8% = URL bar (added by overlay function later)
    - Landscape (Facebook 1200x630, YouTube 1280x720):
        Left 45% = white text area (added by overlay function later)
        Right 55% = product photo, vertically centered, fills the right zone

    Returns a PIL Image with ONLY the background + product photo.
    Text/URL bars are added by the overlay functions.
    """
    w, h = size
    is_landscape = w > h

    # ── Background ────────────────────────────────────────────────────────────
    bg = Image.new("RGB", (w, h))
    _draw_patriotic_bg(bg)

    # ── Product image — HERO layout ───────────────────────────────────────────
    primary = (
        product.get("primary_image", "")
        or (product.get("images", [""])[0] if product.get("images") else "")
    )
    prod_img = None
    if primary:
        prod_img = download_image(primary)

    if prod_img:
        if is_landscape:
            # Landscape: product fills right 52% of canvas, full height minus small margins
            right_zone_x = int(w * 0.44)   # product starts here
            right_zone_w = w - right_zone_x - int(w * 0.02)
            margin_v = int(h * 0.06)
            max_w = right_zone_w
            max_h = h - margin_v * 2
            prod_copy = prod_img.copy()
            prod_copy.thumbnail((max_w, max_h), Image.LANCZOS)
            # Center vertically in right zone
            px = right_zone_x + (right_zone_w - prod_copy.width) // 2
            py = margin_v + (max_h - prod_copy.height) // 2
        else:
            # Portrait/Square: product fills center zone below text bar
            # Text bar will be ~12% of height at top, URL bar ~8% at bottom
            text_bar_h = int(h * 0.12)
            url_bar_h  = int(h * 0.08)
            margin_h   = int(w * 0.04)   # horizontal margin
            available_w = w - margin_h * 2
            available_h = h - text_bar_h - url_bar_h - int(h * 0.02)
            prod_copy = prod_img.copy()
            prod_copy.thumbnail((available_w, available_h), Image.LANCZOS)
            # Center horizontally, place below text bar zone
            px = (w - prod_copy.width) // 2
            py = text_bar_h + (available_h - prod_copy.height) // 2

        # White glow/halo behind product for clean separation from background
        glow_pad = max(int(min(w, h) * 0.012), 6)
        glow_rect = [
            px - glow_pad,
            py - glow_pad,
            px + prod_copy.width + glow_pad,
            py + prod_copy.height + glow_pad,
        ]
        draw_bg2 = ImageDraw.Draw(bg)
        draw_bg2.rounded_rectangle(glow_rect, radius=glow_pad * 2, fill=(255, 255, 255))

        # Paste product photo
        if prod_copy.mode == "RGBA":
            bg.paste(prod_copy, (px, py), prod_copy)
        else:
            bg.paste(prod_copy, (px, py))

    return bg


def generate_dalle_image(prompt: str, size: str = "1024x1792"):
    try:
        client = get_openai_client()
        print(f"[ImageGen] DALL-E 3 generating ({size})...")
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality="standard",
            n=1,
            response_format="b64_json"
        )
        img_data = base64.b64decode(response.data[0].b64_json)
        return Image.open(io.BytesIO(img_data)).convert("RGB")
    except Exception as e:
        print(f"[ImageGen] DALL-E error: {e}")
        return None


def build_pinterest_prompt(product: dict, pin_title: str, angle_idx: int) -> str:
    title = product.get("title", "patriotic product")
    angle = PIN_ANGLES[angle_idx % len(PIN_ANGLES)]
    prompt = (
        f"Vertical Pinterest pin image (2:3 ratio) for an American patriotic gift store. "
        f"Scene: {angle}. "
        f"The product featured is: {title}. "
        f"Style: bright, clean, professional lifestyle photography. "
        f"Color palette: red, white, navy blue, gold accents. "
        f"Props: mini American flags, gold stars, red-white-blue confetti or ribbon. "
        f"The top 12% of the image should be a clean white area for text overlay. "
        f"Bottom right corner should have a small subtle watermark area. "
        f"Photorealistic, high quality, warm inviting atmosphere. "
        f"NO text, NO words, NO labels in the image itself."
    )
    return prompt


def build_manual_pinterest_prompt(product: dict, angle_idx: int, content_pack_prompt: str = "") -> str:
    """
    Build a rich, unique DALL-E 3 prompt for a Manual Post Pinterest pin.
    Uses MANUAL_PIN_ANGLES for 9 distinct scene types.
    If the content_engine already generated an image_prompt, use that as the scene base.
    Always includes the product name and key details for maximum relevance.
    """
    title = product.get("title", "patriotic product")
    description = product.get("description", "")[:200]
    tags = ", ".join(product.get("tags", [])[:6])
    product_type = product.get("product_type", "")

    # Use content_engine's image_prompt if available, otherwise use MANUAL_PIN_ANGLES
    if content_pack_prompt and len(content_pack_prompt) > 30:
        scene = content_pack_prompt
    else:
        scene = MANUAL_PIN_ANGLES[angle_idx % len(MANUAL_PIN_ANGLES)]

    # Build a product description for DALL-E to understand what to show
    product_desc = f"{title}"
    if product_type:
        product_desc += f" ({product_type})"
    if description:
        product_desc += f". {description[:120]}"

    prompt = (
        f"Create a stunning vertical Pinterest pin image (2:3 portrait ratio) "
        f"for an American patriotic gift store called OfficialUSAStore.com. "
        f"\n\nSCENE: {scene}"
        f"\n\nPRODUCT TO FEATURE: {product_desc}"
        f"\n\nSTYLE REQUIREMENTS:"
        f"\n- Photorealistic lifestyle photography, NOT a plain product photo"
        f"\n- The product must be naturally integrated into the scene (on a table, being held, displayed, etc.)"
        f"\n- Color palette: red, white, navy blue, gold accents — patriotic and vibrant"
        f"\n- Bright, clean, high-contrast — optimized for Pinterest scroll-stopping appeal"
        f"\n- The top 12%% of the image should have a clean light/white area suitable for text overlay"
        f"\n- Emotional, aspirational, authentic American pride atmosphere"
        f"\n- High quality, sharp focus on the product"
        f"\n- America 250th anniversary (1776-2026) theme where appropriate"
        f"\n- NO text, NO words, NO labels, NO watermarks in the image"
        f"\n- NO plain white background — must be a scene/lifestyle setting"
    )
    return prompt


def build_instagram_prompt(product: dict, image_prompt: str = "") -> str:
    title = product.get("title", "patriotic product")
    base = image_prompt or f"patriotic lifestyle scene featuring {title}"
    prompt = (
        f"Square Instagram post image for an American patriotic gift store. "
        f"Scene: {base}. "
        f"Product: {title}. "
        f"Style: beautiful lifestyle photography, emotional and aspirational. "
        f"Color palette: red, white, navy blue, warm golden tones. "
        f"Atmosphere: celebratory, patriotic, family-friendly. "
        f"America 250th anniversary theme. "
        f"Clean composition, the product is naturally present in the scene. "
        f"Photorealistic, high quality. "
        f"NO text, NO words, NO labels in the image."
    )
    return prompt


def add_pinterest_overlay(img, headline: str, subtitle: str = "", price: str = ""):
    """
    Add Pinterest-style overlay — compact top bar so product photo is the HERO.
    Text bar is capped at 12% of canvas height.
    Font size is readable but not dominant — product photo must be the focus.
    """
    w, h = img.size
    draw = ImageDraw.Draw(img)

    scale = w / 1000.0

    # Compact font sizes — product photo is the hero
    HEADLINE_PX  = max(int(54  * scale), 44)
    SUBTITLE_PX  = max(int(30  * scale), 24)
    WATERMARK_PX = max(int(24  * scale), 20)
    PRICE_PX     = max(int(40  * scale), 34)

    pad    = max(int(20 * scale), 16)
    text_w = w - pad * 2

    headline_font = get_font(HEADLINE_PX)
    subtitle_font = get_font_regular(SUBTITLE_PX)

    headline_upper = headline.upper()
    h_lines = wrap_text(headline_upper, headline_font, text_w, draw)
    h_lines = h_lines[:2]  # max 2 lines

    h_line_h = int(HEADLINE_PX * 1.20)
    s_line_h = int(SUBTITLE_PX * 1.25)

    total_text_h = len(h_lines) * h_line_h

    s_lines = []
    if subtitle:
        s_lines = wrap_text(subtitle, subtitle_font, text_w, draw)[:1]
        total_text_h += int(SUBTITLE_PX * 0.5) + len(s_lines) * s_line_h

    bar_padding = max(int(16 * scale), 12)
    bar_h = total_text_h + bar_padding * 2
    # Cap bar at 12% of canvas height — product photo must dominate
    bar_h = min(bar_h, int(h * 0.12))
    bar_h = max(bar_h, int(h * 0.08))

    draw.rectangle([(0, 0), (w, bar_h)], fill=COLOR_WHITE)
    accent_h = max(int(5 * scale), 4)
    draw.rectangle([(0, bar_h - accent_h), (w, bar_h)], fill=COLOR_RED)

    y = (bar_h - total_text_h) // 2
    if y < bar_padding // 2:
        y = bar_padding // 2

    for line in h_lines:
        bbox = draw.textbbox((0, 0), line, font=headline_font)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        draw.text((x + 2, y + 2), line, font=headline_font, fill=(200, 200, 215))
        draw.text((x, y), line, font=headline_font, fill=COLOR_NAVY)
        y += h_line_h

    if s_lines:
        y += int(SUBTITLE_PX * 0.4)
        for sline in s_lines:
            bbox = draw.textbbox((0, 0), sline, font=subtitle_font)
            lw = bbox[2] - bbox[0]
            x = (w - lw) // 2
            draw.text((x, y), sline, font=subtitle_font, fill=(50, 50, 80))
            y += s_line_h

    if price:
        price_font = get_font(PRICE_PX)
        try:
            pt = f"${float(price):.2f}"
        except Exception:
            pt = f"${price}"
        pb = draw.textbbox((0, 0), pt, font=price_font)
        pw = pb[2] - pb[0] + int(36 * scale)
        ph = pb[3] - pb[1] + int(20 * scale)
        bx = pad
        by = h - int(60 * scale) - ph
        draw.rounded_rectangle([(bx + 3, by + 3), (bx + pw + 3, by + ph + 3)],
                                radius=12, fill=(100, 0, 0))
        draw.rounded_rectangle([(bx, by), (bx + pw, by + ph)], radius=12, fill=COLOR_RED)
        draw.text((bx + pw // 2, by + ph // 2), pt, font=price_font,
                  fill=COLOR_WHITE, anchor="mm")

    # Watermark bottom-right
    wm_font = get_font(WATERMARK_PX)
    wm_text = "OfficialUSAStore.com"
    wb = draw.textbbox((0, 0), wm_text, font=wm_font)
    wm_w = wb[2] - wb[0]
    wm_h = wb[3] - wb[1]
    wm_x = w - pad - wm_w
    wm_y = h - pad - wm_h
    bg_pad = int(8 * scale)
    draw.rounded_rectangle(
        [(wm_x - bg_pad, wm_y - bg_pad // 2),
         (wm_x + wm_w + bg_pad, wm_y + wm_h + bg_pad // 2)],
        radius=6, fill=(0, 0, 0, 180)
    )
    draw.text((wm_x, wm_y), wm_text, font=wm_font, fill=COLOR_WHITE)

    return img


def add_instagram_overlay(img, headline: str = "", price: str = ""):
    """
    Add Instagram/Facebook/YouTube overlay — product photo is the HERO.

    Portrait/Square (Instagram 1080x1080):
      - Compact white top bar (max 12% height) with title
      - Slim navy bottom bar with URL

    Landscape (Facebook 1200x630, YouTube 1280x720):
      - White left panel (44% width) with title text
      - Red accent divider line
      - Product photo fills right 52% (already placed by build_product_composite)
    """
    w, h = img.size
    draw = ImageDraw.Draw(img)
    is_landscape = w > h

    scale = w / 1080.0

    # Compact font sizes — product photo is the hero
    HEADLINE_PX  = max(int(50  * scale), 38)
    URL_PX       = max(int(28  * scale), 22)
    PRICE_PX     = max(int(40  * scale), 34)

    pad    = max(int(22 * scale), 16)

    if is_landscape:
        # ── Landscape layout: left text panel ─────────────────────────────────
        left_w = int(w * 0.44)
        text_w = left_w - pad * 2

        # White left panel
        draw.rectangle([(0, 0), (left_w, h)], fill=COLOR_WHITE)
        # Red accent divider
        draw.rectangle([(left_w, 0), (left_w + 5, h)], fill=COLOR_RED)
        # Navy bottom strip across full width
        bottom_bar_h = max(int(44 * scale), 36)
        draw.rectangle([(0, h - bottom_bar_h), (w, h)], fill=COLOR_NAVY)
        url_font = get_font(URL_PX)
        draw.text((w // 2, h - bottom_bar_h // 2), "OfficialUSAStore.com",
                  font=url_font, fill=COLOR_GOLD, anchor="mm")

        if headline:
            headline_font = get_font(HEADLINE_PX)
            h_lines = wrap_text(headline.upper(), headline_font, text_w, draw)
            h_lines = h_lines[:4]  # max 4 lines in left panel
            h_line_h = int(HEADLINE_PX * 1.20)
            total_h = len(h_lines) * h_line_h
            y = (h - bottom_bar_h - total_h) // 2
            if y < pad:
                y = pad
            for line in h_lines:
                bbox = draw.textbbox((0, 0), line, font=headline_font)
                lw = bbox[2] - bbox[0]
                x = (left_w - lw) // 2
                draw.text((x + 2, y + 2), line, font=headline_font, fill=(200, 200, 215))
                draw.text((x, y), line, font=headline_font, fill=COLOR_NAVY)
                y += h_line_h

    else:
        # ── Portrait/Square layout: compact top bar ────────────────────────────
        text_w = w - pad * 2
        top_bar_h = 0

        if headline:
            headline_font = get_font(HEADLINE_PX)
            h_lines = wrap_text(headline.upper(), headline_font, text_w, draw)
            h_lines = h_lines[:2]  # max 2 lines
            h_line_h = int(HEADLINE_PX * 1.20)

            bar_padding = max(int(16 * scale), 12)
            top_bar_h = len(h_lines) * h_line_h + bar_padding * 2
            # Cap at 12% of canvas height
            top_bar_h = min(top_bar_h, int(h * 0.12))
            top_bar_h = max(top_bar_h, int(h * 0.08))

            draw.rectangle([(0, 0), (w, top_bar_h)], fill=COLOR_WHITE)
            accent_h = max(int(5 * scale), 4)
            draw.rectangle([(0, top_bar_h - accent_h), (w, top_bar_h)], fill=COLOR_RED)

            y = (top_bar_h - len(h_lines) * h_line_h) // 2
            if y < bar_padding // 2:
                y = bar_padding // 2
            for line in h_lines:
                bbox = draw.textbbox((0, 0), line, font=headline_font)
                lw = bbox[2] - bbox[0]
                x = (w - lw) // 2
                draw.text((x + 2, y + 2), line, font=headline_font, fill=(200, 200, 215))
                draw.text((x, y), line, font=headline_font, fill=COLOR_NAVY)
                y += h_line_h

        # Slim navy bottom bar
        bottom_bar_h = max(int(44 * scale), 36)
        draw.rectangle([(0, h - bottom_bar_h), (w, h)], fill=COLOR_NAVY)
        url_font = get_font(URL_PX)
        draw.text((w // 2, h - bottom_bar_h // 2), "OfficialUSAStore.com",
                  font=url_font, fill=COLOR_GOLD, anchor="mm")

        if price:
            price_font = get_font(PRICE_PX)
            try:
                pt = f"${float(price):.2f}"
            except Exception:
                pt = f"${price}"
            pb = draw.textbbox((0, 0), pt, font=price_font)
            pw = pb[2] - pb[0] + int(32 * scale)
            ph = pb[3] - pb[1] + int(20 * scale)
            bx = w - pad - pw
            by = top_bar_h + pad
            draw.rounded_rectangle([(bx + 3, by + 3), (bx + pw + 3, by + ph + 3)], radius=10, fill=(100, 0, 0))
            draw.rounded_rectangle([(bx, by), (bx + pw, by + ph)], radius=10, fill=COLOR_RED)
            draw.text((bx + pw // 2, by + ph // 2), pt, font=price_font, fill=COLOR_WHITE, anchor="mm")

    return img


def add_tiktok_overlay(img, headline: str = "", price: str = ""):
    """Add TikTok vertical video cover overlay (1080x1920).
    Uses the same compact top-bar style as Pinterest overlay.
    """
    return add_pinterest_overlay(img, headline, subtitle="Shop the link in bio 👇", price=price)


def generate_product_images(product: dict, content_pack: dict, out_dir: str, dry_run: bool = False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    results = {}

    title = product.get("title", "Unknown Product")
    price = str(product.get("price", ""))
    pins  = content_pack.get("pinterest_pins", [])

    pin_images = []
    num_pins = min(3, len(pins)) if pins else 3

    for i in range(num_pins):
        pin = pins[i] if i < len(pins) else {}
        pin_title = pin.get("title", f"Shop {title}")
        dalle_prompt = pin.get("image_prompt") or build_pinterest_prompt(product, pin_title, i)

        print(f"[ImageGen] Generating Pinterest pin {i+1}/{num_pins}...")
        img = generate_dalle_image(dalle_prompt, size="1024x1792")

        if img is None:
            print(f"[ImageGen] DALL-E failed for pin {i+1}, trying product image fallback...")
            images = product.get("images", [])
            if images:
                url = images[0] if isinstance(images[0], str) else images[0].get("src", "")
                img = download_image(url)
            if img is None:
                print(f"[ImageGen] No fallback image available for pin {i+1}")
                continue

        img = smart_crop(img, *PLATFORM_SPECS["pinterest"]["size"])

        subtitle = pin.get("description", "")[:80] if pin else ""
        img = add_pinterest_overlay(img, pin_title, subtitle=subtitle, price="")

        path = os.path.join(out_dir, f"pinterest_{i+1}.jpg")
        img.save(path, "JPEG", quality=92)
        pin_images.append(path)
        print(f"[ImageGen] Pinterest pin {i+1} saved: {path}")

        if i < num_pins - 1:
            time.sleep(2)

    results["pinterest"] = pin_images

    print(f"[ImageGen] Generating Instagram image...")
    ig_data = content_pack.get("instagram_post", {})
    if isinstance(ig_data, dict):
        ig_prompt = ig_data.get("image_prompt", "")
    else:
        ig_prompt = ""

    ig_dalle_prompt = build_instagram_prompt(product, ig_prompt)
    ig_img = generate_dalle_image(ig_dalle_prompt, size="1024x1024")

    if ig_img is None:
        if pin_images:
            ig_img = Image.open(pin_images[0]).convert("RGB")
        else:
            images = product.get("images", [])
            if images:
                url = images[0] if isinstance(images[0], str) else images[0].get("src", "")
                ig_img = download_image(url)

    if ig_img:
        ig_img = smart_crop(ig_img, *PLATFORM_SPECS["instagram"]["size"])
        ig_headline = ig_data.get("headline", "") if isinstance(ig_data, dict) else ""
        if not ig_headline:
            ig_headline = title[:50]
        ig_img = add_instagram_overlay(ig_img, headline=ig_headline, price="")
        ig_path = os.path.join(out_dir, "instagram.jpg")
        ig_img.save(ig_path, "JPEG", quality=92)
        results["instagram"] = [ig_path]
        print(f"[ImageGen] Instagram saved: {ig_path}")

        fb_img = smart_crop(ig_img.copy(), *PLATFORM_SPECS["facebook"]["size"])
        fb_path = os.path.join(out_dir, "facebook.jpg")
        fb_img.save(fb_path, "JPEG", quality=92)
        results["facebook"] = [fb_path]
        print(f"[ImageGen] Facebook saved: {fb_path}")

    return results


def generate_ecommerce_images(content_pack: dict, product_handle: str,
                               output_dir: str = None, dry_run: bool = False) -> dict:
    try:
        from config import OUTPUT_DIR_ECOMMERCE
    except ImportError:
        OUTPUT_DIR_ECOMMERCE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "ecommerce")

    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR_ECOMMERCE, product_handle)
    product = content_pack.get("product", {})
    if not product:
        print("[ImageGen] No product data in content_pack")
        return {}
    return generate_product_images(product, content_pack, output_dir, dry_run=dry_run)


def generate_ai_channel_images(content_pack: dict, topic_slug: str, output_dir: str = None) -> dict:
    return {}


def generate_manual_post_images(product: dict, out_dir: str, content_pack: dict = None) -> dict:
    """
    Generate copy-paste-ready images for the Manual Post Generator.

    Pinterest pins (3): DALL-E 3 unique lifestyle scenes with product naturally in the scene.
      - Uses build_manual_pinterest_prompt() for 3 distinct angles.
      - Falls back to build_product_composite() if DALL-E fails.
      - Each pin uses a different MANUAL_PIN_ANGLES scene for visual variety.

    Instagram, Facebook, TikTok, YouTube: product photo composite (fast, no DALL-E cost).

    Args:
        product: normalized product dict from extract_product_data()
        out_dir: output directory for saved images
        content_pack: optional content pack from generate_ecommerce_content_pack(),
                      used to extract per-pin image_prompts if available
    """
    os.makedirs(out_dir, exist_ok=True)
    results = {}
    title = product.get("title", "Product")

    # Extract per-pin image_prompts from content_pack if available
    cp_pins = []
    if content_pack and isinstance(content_pack.get("pinterest_pins"), list):
        cp_pins = content_pack["pinterest_pins"]

    # ── Pinterest — 3 DALL-E lifestyle pins ───────────────────────────────────
    # Each pin uses a different angle from MANUAL_PIN_ANGLES for visual variety
    # Angle selection: 0=gift/unboxing, 1=outdoor July4, 2=flatlay
    # (rotates through all 9 angles if more pins are needed)
    pin_angle_indices = [0, 1, 2]  # gift, outdoor, flatlay — most Pinterest-friendly
    pin_paths = []

    for i in range(3):
        angle_idx = pin_angle_indices[i % len(pin_angle_indices)]
        # Get image_prompt from content_pack if available for this pin
        cp_prompt = ""
        if i < len(cp_pins) and isinstance(cp_pins[i], dict):
            cp_prompt = cp_pins[i].get("image_prompt", "")

        dalle_prompt = build_manual_pinterest_prompt(product, angle_idx, cp_prompt)
        print(f"[ImageGen] Manual Pinterest pin {i+1}/3 — DALL-E generating (angle {angle_idx})...")

        img = generate_dalle_image(dalle_prompt, size="1024x1792")

        if img is None:
            print(f"[ImageGen] DALL-E failed for pin {i+1}, falling back to product composite...")
            img = build_product_composite(product, PLATFORM_SPECS["pinterest"]["size"])
        else:
            # DALL-E returned a 1024x1792 image — crop to exact Pinterest size
            img = smart_crop(img, *PLATFORM_SPECS["pinterest"]["size"])

        if img:
            img = add_pinterest_overlay(img, title[:80], subtitle="", price="")
            path = os.path.join(out_dir, f"manual_pin_{i+1}.jpg")
            img.save(path, "JPEG", quality=92)
            pin_paths.append(path)
            print(f"[ImageGen] Manual Pinterest pin {i+1} saved: {path}")

        # Small delay between DALL-E calls to avoid rate limits
        if i < 2:
            time.sleep(3)

    results["pinterest"] = pin_paths

    # ── Instagram — square (1080x1080) — product composite ────────────────────
    ig_img = build_product_composite(product, PLATFORM_SPECS["instagram"]["size"])
    if ig_img:
        ig_img = add_instagram_overlay(ig_img, headline=title[:60], price="")
        ig_path = os.path.join(out_dir, "manual_instagram.jpg")
        ig_img.save(ig_path, "JPEG", quality=92)
        results["instagram"] = [ig_path]
        print(f"[ImageGen] Manual Instagram saved: {ig_path}")

    # ── Facebook — landscape (1200x630) — product composite ───────────────────
    fb_img = build_product_composite(product, PLATFORM_SPECS["facebook"]["size"])
    if fb_img:
        fb_img = add_instagram_overlay(fb_img, headline=title[:60], price="")
        fb_path = os.path.join(out_dir, "manual_facebook.jpg")
        fb_img.save(fb_path, "JPEG", quality=92)
        results["facebook"] = [fb_path]
        print(f"[ImageGen] Manual Facebook saved: {fb_path}")

    # ── TikTok — vertical (1080x1920) — product composite ────────────────────
    tk_img = build_product_composite(product, (1080, 1920))
    if tk_img:
        tk_img = add_tiktok_overlay(tk_img, headline=title[:80], price="")
        tk_path = os.path.join(out_dir, "manual_tiktok.jpg")
        tk_img.save(tk_path, "JPEG", quality=92)
        results["tiktok"] = [tk_path]
        print(f"[ImageGen] Manual TikTok saved: {tk_path}")

    # ── YouTube thumbnail — landscape (1280x720) — product composite ──────────
    yt_img = build_product_composite(product, (1280, 720))
    if yt_img:
        yt_img = add_instagram_overlay(yt_img, headline=title[:60], price="")
        yt_path = os.path.join(out_dir, "manual_youtube.jpg")
        yt_img.save(yt_path, "JPEG", quality=92)
        results["youtube"] = [yt_path]
        print(f"[ImageGen] Manual YouTube saved: {yt_path}")

    return results
