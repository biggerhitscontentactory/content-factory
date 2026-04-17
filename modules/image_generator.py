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

# Pinterest Content Angles
PIN_ANGLES = [
    "patriotic backyard party scene with American flags, gold stars, red white blue confetti on white wood table",
    "happy American family outdoors celebrating with patriotic decorations, warm golden sunset light",
    "elegant product flatlay on white rustic wood surface surrounded by mini American flags, gold stars, red white blue ribbon",
    "festive America 250th anniversary party setup with string lights, patriotic decor, 1776 neon sign",
    "close-up lifestyle shot with patriotic props: confetti, small flags, gold coins, celebration atmosphere",
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
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def _load_font(size: int, bold: bool = True):
    """
    Load a font at the given pixel size.
    Priority: bundled repo font -> system font -> PIL default (last resort).
    Logs which path was used so Railway logs show what is happening.
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
        f"The top 20% of the image should be a clean white or very light area suitable for bold text overlay. "
        f"Bottom right corner should have a small subtle watermark area. "
        f"Photorealistic, high quality, warm inviting atmosphere. "
        f"NO text, NO words, NO labels in the image itself."
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
    Add Pinterest-style overlay.
    HARDCODED large pixel sizes (not fractions) -- always readable.
    Fonts loaded from bundled repo files so Railway always works.

    At 1000px width:
      Headline  = 96px bold
      Subtitle  = 52px regular
      Price     = 64px bold
      Watermark = 36px bold
    """
    w, h = img.size
    draw = ImageDraw.Draw(img)

    scale = w / 1000.0

    HEADLINE_PX  = max(int(96  * scale), 80)
    SUBTITLE_PX  = max(int(52  * scale), 44)
    PRICE_PX     = max(int(64  * scale), 56)
    WATERMARK_PX = max(int(36  * scale), 30)

    pad    = max(int(32 * scale), 24)
    text_w = w - pad * 2

    headline_font = get_font(HEADLINE_PX)
    subtitle_font = get_font_regular(SUBTITLE_PX)

    headline_upper = headline.upper()
    h_lines = wrap_text(headline_upper, headline_font, text_w, draw)

    h_line_h = int(HEADLINE_PX * 1.25)
    s_line_h = int(SUBTITLE_PX * 1.30)

    total_text_h = len(h_lines) * h_line_h

    s_lines = []
    if subtitle:
        s_lines = wrap_text(subtitle, subtitle_font, text_w, draw)[:2]
        total_text_h += int(SUBTITLE_PX * 0.6) + len(s_lines) * s_line_h

    bar_padding = max(int(40 * scale), 32)
    bar_h = total_text_h + bar_padding * 2
    bar_h = max(bar_h, int(h * 0.18))

    draw.rectangle([(0, 0), (w, bar_h)], fill=COLOR_WHITE)
    accent_h = max(int(8 * scale), 6)
    draw.rectangle([(0, bar_h - accent_h), (w, bar_h)], fill=COLOR_RED)

    y = (bar_h - total_text_h) // 2
    if y < bar_padding // 2:
        y = bar_padding // 2

    for line in h_lines:
        bbox = draw.textbbox((0, 0), line, font=headline_font)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        draw.text((x + 3, y + 3), line, font=headline_font, fill=(200, 200, 215))
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
        pw = pb[2] - pb[0] + int(48 * scale)
        ph = pb[3] - pb[1] + int(28 * scale)
        bx = pad
        by = h - int(80 * scale) - ph
        draw.rounded_rectangle([(bx + 4, by + 4), (bx + pw + 4, by + ph + 4)],
                                radius=14, fill=(100, 0, 0))
        draw.rounded_rectangle([(bx, by), (bx + pw, by + ph)], radius=14, fill=COLOR_RED)
        draw.text((bx + pw // 2, by + ph // 2), pt, font=price_font,
                  fill=COLOR_WHITE, anchor="mm")

    wm_font = get_font(WATERMARK_PX)
    wm_text = "OfficialUSAStore.com"
    wb = draw.textbbox((0, 0), wm_text, font=wm_font)
    wm_w = wb[2] - wb[0]
    wm_h = wb[3] - wb[1]
    wm_x = w - pad - wm_w
    wm_y = h - pad - wm_h
    bg_pad = int(12 * scale)
    draw.rounded_rectangle(
        [(wm_x - bg_pad, wm_y - bg_pad // 2),
         (wm_x + wm_w + bg_pad, wm_y + wm_h + bg_pad // 2)],
        radius=8, fill=(0, 0, 0, 180)
    )
    draw.text((wm_x, wm_y), wm_text, font=wm_font, fill=COLOR_WHITE)

    return img


def add_instagram_overlay(img, headline: str = "", price: str = ""):
    """
    Add Instagram overlay with large readable text.
    HARDCODED pixel sizes at 1080px width:
      Headline = 88px bold
      URL bar  = 40px bold
      Price    = 68px bold
    """
    w, h = img.size
    draw = ImageDraw.Draw(img)

    scale = w / 1080.0

    HEADLINE_PX  = max(int(88  * scale), 72)
    URL_PX       = max(int(40  * scale), 32)
    PRICE_PX     = max(int(68  * scale), 56)

    pad    = max(int(36 * scale), 28)
    text_w = w - pad * 2

    top_bar_h = 0
    if headline:
        headline_font = get_font(HEADLINE_PX)
        h_lines = wrap_text(headline.upper(), headline_font, text_w, draw)
        h_line_h = int(HEADLINE_PX * 1.25)

        bar_padding = max(int(40 * scale), 32)
        top_bar_h = len(h_lines) * h_line_h + bar_padding * 2
        top_bar_h = max(top_bar_h, int(h * 0.16))

        draw.rectangle([(0, 0), (w, top_bar_h)], fill=COLOR_WHITE)
        accent_h = max(int(7 * scale), 5)
        draw.rectangle([(0, top_bar_h - accent_h), (w, top_bar_h)], fill=COLOR_RED)

        y = (top_bar_h - len(h_lines) * h_line_h) // 2
        if y < bar_padding // 2:
            y = bar_padding // 2
        for line in h_lines:
            bbox = draw.textbbox((0, 0), line, font=headline_font)
            lw = bbox[2] - bbox[0]
            x = (w - lw) // 2
            draw.text((x + 3, y + 3), line, font=headline_font, fill=(200, 200, 215))
            draw.text((x, y), line, font=headline_font, fill=COLOR_NAVY)
            y += h_line_h

    bottom_bar_h = max(int(72 * scale), 60)
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
        pw = pb[2] - pb[0] + int(40 * scale)
        ph = pb[3] - pb[1] + int(24 * scale)
        bx = w - pad - pw
        by = top_bar_h + pad
        draw.rounded_rectangle([(bx + 4, by + 4), (bx + pw + 4, by + ph + 4)], radius=12, fill=(100, 0, 0))
        draw.rounded_rectangle([(bx, by), (bx + pw, by + ph)], radius=12, fill=COLOR_RED)
        draw.text((bx + pw // 2, by + ph // 2), pt, font=price_font, fill=COLOR_WHITE, anchor="mm")

    return img



def add_tiktok_overlay(img, headline: str = "", price: str = ""):
    """Add TikTok vertical video cover overlay (1080x1920)."""
    img = img.copy()
    w, h = img.size
    draw = ImageDraw.Draw(img)
    bold_font   = _load_font(bold=True,  size=88)
    price_font  = _load_font(bold=True,  size=72)
    small_font  = _load_font(bold=False, size=38)

    # Dark gradient at bottom 40%
    grad_h = int(h * 0.42)
    grad_start = h - grad_h
    for y in range(grad_h):
        alpha = int(200 * (y / grad_h))
        draw.rectangle([(0, grad_start + y), (w, grad_start + y + 1)],
                       fill=(0, 0, 0, alpha))

    # Price badge top-right
    if price:
        badge_text = f"${price}" if not str(price).startswith("$") else price
        bbox = draw.textbbox((0, 0), badge_text, font=price_font)
        bw = bbox[2] - bbox[0] + 32
        bh = bbox[3] - bbox[1] + 18
        bx = w - bw - 24
        by = 36
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=14, fill=(220, 38, 38))
        draw.text((bx + 16, by + 9), badge_text, font=price_font, fill=(255, 255, 255))

    # Headline text bottom area
    if headline:
        max_w = w - 60
        words = headline.upper().split()
        lines, line = [], []
        for word in words:
            test = " ".join(line + [word])
            if draw.textlength(test, font=bold_font) <= max_w:
                line.append(word)
            else:
                if line:
                    lines.append(" ".join(line))
                line = [word]
        if line:
            lines.append(" ".join(line))
        lines = lines[:3]
        line_h = bold_font.size + 12
        total_h = len(lines) * line_h
        y_start = h - total_h - 80
        for i, ln in enumerate(lines):
            y = y_start + i * line_h
            draw.text((30, y + 2), ln, font=bold_font, fill=(0, 0, 0, 120))
            draw.text((30, y), ln, font=bold_font, fill=(255, 255, 255))

    # TikTok-style "SHOP NOW" CTA bar at very bottom
    cta_h = 64
    draw.rectangle([(0, h - cta_h), (w, h)], fill=(220, 38, 38))
    cta_font = _load_font(bold=True, size=44)
    cta_text = "SHOP NOW  →"
    cta_bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    cta_x = (w - (cta_bbox[2] - cta_bbox[0])) // 2
    draw.text((cta_x, h - cta_h + 10), cta_text, font=cta_font, fill=(255, 255, 255))

    return img

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
        img = add_pinterest_overlay(img, pin_title, subtitle=subtitle, price=price)

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
        ig_img = add_instagram_overlay(ig_img, headline=ig_headline, price=price)
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
