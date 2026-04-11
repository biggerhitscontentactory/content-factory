"""
Content Factory - Image Generator
====================================
Generates platform-ready images using DALL-E 3 (lifestyle scenes matching
OfficialUSAStore.com Pinterest style), then adds text overlays via PIL.

Pinterest style:
  - Patriotic lifestyle scenes (backyard parties, product flatlays, family gatherings)
  - Bold headline text at top (dark navy on white bar) OR overlaid on image
  - OfficialUSAStore.com watermark bottom-right
  - Red/white/blue color palette, gold stars, mini flags as props

Platform specs:
  Pinterest  : 1000 x 1500 px (2:3 vertical)  — 3 pins per product, DALL-E
  Instagram  : 1080 x 1080 px (1:1 square)    — 1 image, DALL-E, minimal text
  Facebook   : 1200 x 630  px (landscape)     — cropped from Instagram image
"""

import os
import io
import time
import base64
import requests
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# ─── Brand Colors ─────────────────────────────────────────────────────────────
COLOR_NAVY   = (15,  30,  70)
COLOR_RED    = (178, 34,  52)
COLOR_WHITE  = (255, 255, 255)
COLOR_GOLD   = (212, 175, 55)
COLOR_CREAM  = (255, 253, 240)

# ─── Platform Specs ───────────────────────────────────────────────────────────
PLATFORM_SPECS = {
    "pinterest": {"size": (1000, 1500), "dalle_size": "1024x1792"},
    "instagram": {"size": (1080, 1080), "dalle_size": "1024x1024"},
    "facebook":  {"size": (1200, 630)},
}

# ─── Pinterest Content Angles (rotated per pin) ───────────────────────────────
PIN_ANGLES = [
    "patriotic backyard party scene with American flags, gold stars, red white blue confetti on white wood table",
    "happy American family outdoors celebrating with patriotic decorations, warm golden sunset light",
    "elegant product flatlay on white rustic wood surface surrounded by mini American flags, gold stars, red white blue ribbon",
    "festive America 250th anniversary party setup with string lights, patriotic decor, 1776 neon sign",
    "close-up lifestyle shot with patriotic props: confetti, small flags, gold coins, celebration atmosphere",
]


def get_openai_client():
    """Get OpenAI client using environment variables."""
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def get_font(size: int):
    """Try to load a system bold font, fall back to default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def get_font_regular(size: int):
    """Try to load a regular (non-bold) system font."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def wrap_text(text: str, font, max_width: int, draw) -> list:
    """Wrap text to fit within max_width pixels."""
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
    """Resize to fill target dimensions, then center-crop."""
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
    """Download image from URL and return as PIL Image."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        print(f"[ImageGen] Failed to download: {e}")
        return None


def generate_dalle_image(prompt: str, size: str = "1024x1792") -> Image.Image | None:
    """Generate an image using DALL-E 3 and return as PIL Image."""
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
    """Build a DALL-E prompt matching OfficialUSAStore Pinterest style."""
    title = product.get("title", "patriotic product")
    price = product.get("price", "")
    angle = PIN_ANGLES[angle_idx % len(PIN_ANGLES)]

    # Leave white space at top for text overlay (about 20% of image height)
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
    """Build a DALL-E prompt for Instagram square lifestyle image."""
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


def add_pinterest_overlay(img: Image.Image, headline: str, subtitle: str = "", price: str = "") -> Image.Image:
    """
    Add Pinterest-style overlay matching OfficialUSAStore style:
    - White bar at top with LARGE bold navy headline text
    - Subtitle in readable regular text below headline
    - OfficialUSAStore.com watermark bottom-right
    """
    w, h = img.size
    draw = ImageDraw.Draw(img)

    pad = int(w * 0.05)
    text_w = w - pad * 2

    # ── Font sizes: much larger for readability ──────────────────────────────
    # On a 1000px wide pin: headline=130px, subtitle=72px, price=90px, watermark=52px
    headline_size = int(w * 0.13)   # was 0.085 — now ~53% bigger
    subtitle_size = int(w * 0.072)  # was 0.042 — now ~71% bigger
    price_size    = int(w * 0.09)   # was 0.055 — now ~64% bigger
    wm_size       = int(w * 0.052)  # was 0.028 — now ~86% bigger

    headline_font = get_font(headline_size)
    subtitle_font = get_font_regular(subtitle_size)

    # ── Measure text to size the bar dynamically ─────────────────────────────
    headline_upper = headline.upper()
    h_lines = wrap_text(headline_upper, headline_font, text_w, draw)

    h_line_h = int(headline_size * 1.15)  # line height with spacing
    s_line_h = int(subtitle_size * 1.2)
    total_text_h = len(h_lines) * h_line_h + (s_line_h + 12 if subtitle else 0)

    # Pre-measure subtitle lines so bar height accounts for them
    s_lines_preview = []
    if subtitle:
        s_lines_preview = wrap_text(subtitle, subtitle_font, text_w, draw)[:2]
        total_text_h += len(s_lines_preview) * s_line_h + 12

    # Bar height: text block + generous top/bottom padding
    bar_h = total_text_h + int(h * 0.07)
    bar_h = max(bar_h, int(h * 0.22))  # minimum 22% of image height

    # Draw white bar
    draw.rectangle([(0, 0), (w, bar_h)], fill=COLOR_WHITE)
    # Add a thin red accent line at bottom of bar
    draw.rectangle([(0, bar_h - 6), (w, bar_h)], fill=COLOR_RED)

    # ── Draw headline centered in bar ────────────────────────────────────────
    y = (bar_h - total_text_h) // 2
    if y < 12:
        y = 12

    for line in h_lines:
        bbox = draw.textbbox((0, 0), line, font=headline_font)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        # Shadow for depth
        draw.text((x + 2, y + 2), line, font=headline_font, fill=(180, 180, 200))
        draw.text((x, y), line, font=headline_font, fill=COLOR_NAVY)
        y += h_line_h

    # ── Draw subtitle ────────────────────────────────────────────────────────
    if subtitle:
        # Truncate subtitle to fit on 2 lines max (already measured above)
        s_lines = s_lines_preview if s_lines_preview else wrap_text(subtitle, subtitle_font, text_w, draw)[:2]
        for sline in s_lines:
            bbox = draw.textbbox((0, 0), sline, font=subtitle_font)
            x = (w - (bbox[2] - bbox[0])) // 2
            draw.text((x, y + 6), sline, font=subtitle_font, fill=(60, 60, 90))
            y += s_line_h

    # ── Price badge (bottom-left, large and bold) ────────────────────────────
    if price:
        price_font = get_font(price_size)
        try:
            pt = f"${float(price):.2f}"
        except Exception:
            pt = f"${price}"
        pb = draw.textbbox((0, 0), pt, font=price_font)
        pw = pb[2] - pb[0] + 40
        ph = pb[3] - pb[1] + 24
        bx = pad
        by = h - int(h * 0.07) - ph
        # Shadow
        draw.rounded_rectangle([(bx + 3, by + 3), (bx + pw + 3, by + ph + 3)],
                                radius=12, fill=(100, 0, 0))
        draw.rounded_rectangle([(bx, by), (bx + pw, by + ph)], radius=12, fill=COLOR_RED)
        draw.text((bx + pw // 2, by + ph // 2), pt, font=price_font,
                  fill=COLOR_WHITE, anchor="mm")

    # ── Watermark bottom-right, large enough to read ─────────────────────────
    wm_font = get_font(wm_size)
    wm_text = "OfficialUSAStore.com"
    wb = draw.textbbox((0, 0), wm_text, font=wm_font)
    wm_w = wb[2] - wb[0]
    wm_h = wb[3] - wb[1]
    wm_x = w - pad - wm_w
    wm_y = h - pad - wm_h
    # Dark semi-transparent pill background
    bg_pad = 10
    draw.rounded_rectangle(
        [(wm_x - bg_pad, wm_y - bg_pad // 2),
         (wm_x + wm_w + bg_pad, wm_y + wm_h + bg_pad // 2)],
        radius=8, fill=(0, 0, 0, 160)
    )
    draw.text((wm_x, wm_y), wm_text, font=wm_font, fill=COLOR_WHITE)

    return img


def add_instagram_overlay(img: Image.Image, price: str = "") -> Image.Image:
    """
    Add minimal Instagram overlay:
    - Thin navy bar at bottom with OfficialUSAStore.com
    - Optional price badge
    """
    w, h = img.size
    draw = ImageDraw.Draw(img)

    # Bottom navy bar
    bar_h = int(h * 0.07)
    draw.rectangle([(0, h - bar_h), (w, h)], fill=COLOR_NAVY)

    url_font = get_font(int(w * 0.032))
    draw.text((w // 2, h - bar_h // 2), "OfficialUSAStore.com",
              font=url_font, fill=COLOR_GOLD, anchor="mm")

    # Price badge top-right
    if price:
        price_font = get_font(int(w * 0.055))
        pt = f"${price}"
        pb = draw.textbbox((0, 0), pt, font=price_font)
        pw = pb[2] - pb[0] + 24
        ph = pb[3] - pb[1] + 14
        pad = int(w * 0.04)
        bx = w - pad - pw
        by = pad
        draw.rounded_rectangle([(bx, by), (bx + pw, by + ph)], radius=10, fill=COLOR_RED)
        draw.text((bx + pw // 2, by + ph // 2), pt, font=price_font, fill=COLOR_WHITE, anchor="mm")

    return img


def generate_product_images(product: dict, content_pack: dict, out_dir: str, dry_run: bool = False) -> dict:
    """
    Main entry point: generate all platform images for a product using DALL-E 3.
    Returns dict of {platform: [image_path, ...]}
    """
    os.makedirs(out_dir, exist_ok=True)
    results = {}

    title = product.get("title", "Unknown Product")
    price = str(product.get("price", ""))
    pins  = content_pack.get("pinterest_pins", [])

    # ── Pinterest Pins (DALL-E 3, vertical) ──────────────────────────────────
    pin_images = []
    num_pins = min(3, len(pins)) if pins else 3

    for i in range(num_pins):
        pin = pins[i] if i < len(pins) else {}
        pin_title = pin.get("title", f"Shop {title}")
        # Use the image_prompt from content engine if available, else build one
        dalle_prompt = pin.get("image_prompt") or build_pinterest_prompt(product, pin_title, i)

        print(f"[ImageGen] Generating Pinterest pin {i+1}/{num_pins}...")
        img = generate_dalle_image(dalle_prompt, size="1024x1792")

        if img is None:
            # Fallback: use product image from Shopify
            print(f"[ImageGen] DALL-E failed for pin {i+1}, trying product image fallback...")
            images = product.get("images", [])
            if images:
                url = images[0] if isinstance(images[0], str) else images[0].get("src", "")
                img = download_image(url)
            if img is None:
                print(f"[ImageGen] No fallback image available for pin {i+1}")
                continue

        # Resize to Pinterest spec
        img = smart_crop(img, *PLATFORM_SPECS["pinterest"]["size"])

        # Add overlay
        subtitle = pin.get("description", "")[:60] if pin else ""
        img = add_pinterest_overlay(img, pin_title, subtitle=subtitle, price=price)

        path = os.path.join(out_dir, f"pinterest_{i+1}.jpg")
        img.save(path, "JPEG", quality=92)
        pin_images.append(path)
        print(f"[ImageGen] ✓ Pinterest pin {i+1} saved: {path}")

        # Small delay between DALL-E calls
        if i < num_pins - 1:
            time.sleep(2)

    results["pinterest"] = pin_images

    # ── Instagram (DALL-E 3, square) ─────────────────────────────────────────
    print(f"[ImageGen] Generating Instagram image...")
    ig_data = content_pack.get("instagram_post", {})
    if isinstance(ig_data, dict):
        ig_prompt = ig_data.get("image_prompt", "")
    else:
        ig_prompt = ""

    ig_dalle_prompt = build_instagram_prompt(product, ig_prompt)
    ig_img = generate_dalle_image(ig_dalle_prompt, size="1024x1024")

    if ig_img is None:
        # Fallback: use first Pinterest image cropped to square
        if pin_images:
            ig_img = Image.open(pin_images[0]).convert("RGB")
        else:
            images = product.get("images", [])
            if images:
                url = images[0] if isinstance(images[0], str) else images[0].get("src", "")
                ig_img = download_image(url)

    if ig_img:
        ig_img = smart_crop(ig_img, *PLATFORM_SPECS["instagram"]["size"])
        ig_img = add_instagram_overlay(ig_img, price=price)
        ig_path = os.path.join(out_dir, "instagram.jpg")
        ig_img.save(ig_path, "JPEG", quality=92)
        results["instagram"] = [ig_path]
        print(f"[ImageGen] ✓ Instagram saved: {ig_path}")

        # ── Facebook (crop from Instagram image) ─────────────────────────────
        fb_img = smart_crop(ig_img.copy(), *PLATFORM_SPECS["facebook"]["size"])
        fb_path = os.path.join(out_dir, "facebook.jpg")
        fb_img.save(fb_path, "JPEG", quality=92)
        results["facebook"] = [fb_path]
        print(f"[ImageGen] ✓ Facebook saved: {fb_path}")

    return results


# ─── Legacy wrappers ──────────────────────────────────────────────────────────
def generate_ecommerce_images(content_pack: dict, product_handle: str,
                               output_dir: str = None, dry_run: bool = False) -> dict:
    """Legacy wrapper — reads product from content_pack['product']."""
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
    """AI channel images — not needed for this product-based approach."""
    return {}
