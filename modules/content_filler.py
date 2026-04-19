"""
Content Factory - Content Filler Module
=========================================
Generates pure engagement/lifestyle content (NO product links) based on a
theme keyword entered by the user (e.g. "4th of July picnic", "Washington DC",
"Arches National Park").

Produces per-platform:
  - 5 title options (SEO + viral)
  - 4 description/caption options
  - Hashtag block
  - DALL-E 3 lifestyle image (no product, pure scene)

Platforms:
  Pinterest  (1000x1500 vertical)  — up to 3 unique pins
  Instagram  (1080x1080 square)    — 1 image
  Facebook   (1200x630 landscape)  — 1 image
  TikTok     (1080x1920 vertical)  — 1 image
  YouTube    (1280x720 landscape)  — 1 image
"""

import os
import json
import re
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# ── Platform image sizes ───────────────────────────────────────────────────────
FILLER_SPECS = {
    "pinterest": {"size": (1000, 1500), "dalle_size": "1024x1792"},
    "instagram": {"size": (1080, 1080), "dalle_size": "1024x1024"},
    "facebook":  {"size": (1200,  630), "dalle_size": "1792x1024"},
    "tiktok":    {"size": (1080, 1920), "dalle_size": "1024x1792"},
    "youtube":   {"size": (1280,  720), "dalle_size": "1792x1024"},
}

# ── Font helpers (reuse from image_generator) ─────────────────────────────────
_FONT_BOLD    = os.path.join(os.path.dirname(__file__), "..", "static", "fonts", "Oswald-Bold.ttf")
_FONT_REGULAR = os.path.join(os.path.dirname(__file__), "..", "static", "fonts", "Oswald-Regular.ttf")
_SYSTEM_BOLD    = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf"]
_SYSTEM_REGULAR = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                   "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf"]


def _load_font(size: int, bold: bool = True):
    primary = _FONT_BOLD if bold else _FONT_REGULAR
    fallbacks = _SYSTEM_BOLD if bold else _SYSTEM_REGULAR
    if os.path.exists(primary):
        try:
            return ImageFont.truetype(primary, size)
        except Exception:
            pass
    for fb in fallbacks:
        if os.path.exists(fb):
            try:
                return ImageFont.truetype(fb, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _get_openai_client():
    from openai import OpenAI
    api_key = (
        os.environ.get("DALLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY_DALLE")
        or os.environ.get("OPENAI_API_KEY", "")
    )
    return OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")


# ── GPT: Generate content pack for a theme ────────────────────────────────────

def generate_filler_content(theme: str, image_count: int = 3) -> dict:
    """
    Use GPT-4 to generate SEO/viral titles, descriptions, hashtags,
    and DALL-E image prompts for a given theme.
    Returns a dict with per-platform content.
    """
    from openai import OpenAI
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or ""
    )
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    client = OpenAI(api_key=api_key, base_url=base_url)

    system_prompt = """You are an expert American patriotic lifestyle social media content creator.
You create viral, SEO-optimized engagement content for OfficialUSAStore.com's social channels.
These posts have NO product links — they are pure lifestyle/engagement content to build audience.
Tone: Patriotic, celebratory, inspiring, emotionally resonant, shareable.
Always tie content back to American pride, freedom, heritage, or celebration where natural."""

    user_prompt = f"""Generate a complete social media content pack for the theme: "{theme}"

This is ENGAGEMENT CONTENT — no product links, no selling. Pure lifestyle/inspiration.

Return ONLY valid JSON in this exact structure:
{{
  "theme": "{theme}",
  "pinterest_pins": [
    {{
      "titles": ["title1", "title2", "title3", "title4", "title5"],
      "descriptions": ["desc1", "desc2", "desc3", "desc4"],
      "hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5 #tag6 #tag7 #tag8 #tag9 #tag10",
      "image_prompt": "Detailed DALL-E 3 prompt for a stunning vertical Pinterest lifestyle image about this theme. Photorealistic, vibrant, patriotic color palette where natural. NO text in image."
    }},
    {{
      "titles": ["title1", "title2", "title3", "title4", "title5"],
      "descriptions": ["desc1", "desc2", "desc3", "desc4"],
      "hashtags": "#tag1 #tag2 ...",
      "image_prompt": "Different scene/angle DALL-E 3 prompt for Pinterest pin 2."
    }},
    {{
      "titles": ["title1", "title2", "title3", "title4", "title5"],
      "descriptions": ["desc1", "desc2", "desc3", "desc4"],
      "hashtags": "#tag1 #tag2 ...",
      "image_prompt": "Different scene/angle DALL-E 3 prompt for Pinterest pin 3."
    }}
  ],
  "instagram_post": {{
    "titles": ["caption1", "caption2", "caption3", "caption4", "caption5"],
    "hashtags": "#tag1 #tag2 #tag3 ... (25-30 tags)",
    "image_prompt": "DALL-E 3 prompt for a square Instagram lifestyle image. Bold, bright, scroll-stopping. NO text in image."
  }},
  "facebook_post": {{
    "titles": ["post1", "post2", "post3", "post4", "post5"],
    "hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5",
    "image_prompt": "DALL-E 3 prompt for a wide Facebook landscape lifestyle image. Warm, shareable, community feel. NO text in image."
  }},
  "tiktok_post": {{
    "titles": ["hook1", "hook2", "hook3", "hook4", "hook5"],
    "hashtags": "#tag1 #tag2 ... #fyp #foryou (15-20 tags)",
    "image_prompt": "DALL-E 3 prompt for a tall TikTok cover image. Dynamic, youthful, eye-catching. NO text in image."
  }},
  "youtube_post": {{
    "titles": ["title1", "title2", "title3", "title4", "title5"],
    "descriptions": ["Full YouTube description option 1 (2-3 sentences, SEO rich)", "Full YouTube description option 2", "Full YouTube description option 3"],
    "hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5",
    "image_prompt": "DALL-E 3 prompt for a YouTube thumbnail. High contrast, dramatic, cinematic wide shot. NO text in image."
  }}
}}

Requirements for titles/captions:
- Each option must be DIFFERENT in angle/tone (curiosity, emotion, humor, nostalgia, inspiration)
- Max 5 words for Pinterest titles (SEO keyword-rich)
- Instagram captions: 1-3 sentences, conversational, end with a question or CTA
- Facebook posts: 2-4 sentences, storytelling, shareable
- TikTok hooks: punchy, 1 sentence, starts with action word or question
- YouTube titles: 8-12 words, curiosity gap, searchable

Requirements for image prompts:
- Photorealistic lifestyle photography style
- Vibrant, high-contrast, optimized for social media
- Patriotic color palette (red, white, blue, gold) where it fits naturally
- Each Pinterest pin must be a DIFFERENT scene/angle
- NO text, NO words, NO watermarks in the generated image"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,
            max_tokens=3000,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown code fences if present
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[Filler] JSON parse error: {e}\nRaw: {raw[:300]}")
        return {"error": f"Content generation JSON parse error: {e}"}
    except Exception as e:
        print(f"[Filler] Content generation error: {e}")
        return {"error": str(e)}


# ── DALL-E: Generate a filler lifestyle image ─────────────────────────────────

def _generate_dalle_image(prompt: str, dalle_size: str = "1024x1792") -> Image.Image | None:
    """Call DALL-E 3 and return a PIL Image, or None on failure."""
    try:
        client = _get_openai_client()
        print(f"[Filler] DALL-E 3 generating ({dalle_size})...")
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size=dalle_size,
            quality="standard",
        )
        img_url = resp.data[0].url
        r = requests.get(img_url, timeout=30)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"[Filler] DALL-E error: {e}")
        return None


# ── Fallback: Gradient placeholder image ──────────────────────────────────────

def _make_gradient_placeholder(theme: str, platform: str, size: tuple) -> Image.Image:
    """Create a patriotic gradient placeholder when DALL-E fails."""
    w, h = size
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    # Patriotic gradient: navy → red
    for y in range(h):
        t = y / h
        r = int(10 + t * (178 - 10))
        g = int(20 + t * (34 - 20))
        b = int(80 + t * (34 - 80))
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Stars overlay
    import random
    rng = random.Random(42)
    for _ in range(60):
        sx = rng.randint(0, w)
        sy = rng.randint(0, h // 2)
        draw.ellipse([sx-2, sy-2, sx+2, sy+2], fill=(255, 255, 255, 180))

    # Theme text centered
    font_size = max(28, w // 18)
    font = _load_font(font_size, bold=True)
    words = theme.upper().split()
    lines = []
    line = []
    for word in words:
        line.append(word)
        if len(" ".join(line)) > 20:
            lines.append(" ".join(line[:-1]))
            line = [word]
    if line:
        lines.append(" ".join(line))

    total_h = len(lines) * (font_size + 8)
    y_start = (h - total_h) // 2
    for i, ln in enumerate(lines):
        bbox = draw.textbbox((0, 0), ln, font=font)
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2
        y = y_start + i * (font_size + 8)
        draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 120))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255))

    return img


# ── Add watermark/branding to filler image ────────────────────────────────────

def _add_filler_branding(img: Image.Image, platform: str) -> Image.Image:
    """Add a slim OfficialUSAStore.com watermark bar at the bottom."""
    w, h = img.size
    draw = ImageDraw.Draw(img)

    bar_h = max(28, h // 35)
    draw.rectangle([(0, h - bar_h), (w, h)], fill=(10, 20, 60))

    font = _load_font(max(14, bar_h - 8), bold=False)
    label = "OfficialUSAStore.com"
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    tx = (w - tw) // 2
    ty = h - bar_h + (bar_h - (bbox[3] - bbox[1])) // 2
    draw.text((tx, ty), label, font=font, fill=(200, 200, 220))

    return img


# ── Main: Generate all filler images ─────────────────────────────────────────

def generate_filler_images(theme: str, content: dict, out_dir: str) -> dict:
    """
    Generate platform images for a filler content pack.
    Returns dict: { "pinterest": [path1, path2, path3], "instagram": [path], ... }
    """
    os.makedirs(out_dir, exist_ok=True)
    safe_theme = re.sub(r'[^a-z0-9]+', '_', theme.lower()).strip('_')[:40]
    result = {}

    # ── Pinterest: 3 unique pins ──────────────────────────────────────────────
    pin_paths = []
    pins = content.get("pinterest_pins", [])
    for i, pin in enumerate(pins[:3]):
        prompt = pin.get("image_prompt", f"Stunning patriotic lifestyle scene: {theme}. Vertical portrait, vibrant, photorealistic. No text.")
        # Enhance prompt for Pinterest
        full_prompt = (
            f"{prompt} "
            f"Vertical 2:3 portrait orientation. Photorealistic lifestyle photography. "
            f"Vibrant patriotic colors (red, white, navy blue, gold) where natural. "
            f"Bright, high-contrast, scroll-stopping Pinterest aesthetic. "
            f"NO text, NO words, NO watermarks in the image."
        )
        img = _generate_dalle_image(full_prompt, dalle_size="1024x1792")
        if img is None:
            print(f"[Filler] DALL-E failed for Pinterest pin {i+1}, using placeholder")
            img = _make_gradient_placeholder(theme, "pinterest", (1000, 1500))
        else:
            img = img.resize((1000, 1500), Image.LANCZOS)

        img = _add_filler_branding(img, "pinterest")
        path = os.path.join(out_dir, f"filler_{safe_theme}_pin{i+1}.jpg")
        img.save(path, "JPEG", quality=92)
        pin_paths.append(path)
        print(f"[Filler] Saved Pinterest pin {i+1}: {path}")

    if pin_paths:
        result["pinterest"] = pin_paths

    # ── Instagram ─────────────────────────────────────────────────────────────
    ig = content.get("instagram_post", {})
    ig_prompt = ig.get("image_prompt", f"Beautiful square lifestyle photo: {theme}. Bold, bright, Instagram-worthy. No text.")
    full_ig_prompt = (
        f"{ig_prompt} "
        f"Square 1:1 format. Photorealistic lifestyle photography. "
        f"Vibrant, high-contrast, Instagram scroll-stopping. "
        f"NO text, NO words, NO watermarks."
    )
    ig_img = _generate_dalle_image(full_ig_prompt, dalle_size="1024x1024")
    if ig_img is None:
        ig_img = _make_gradient_placeholder(theme, "instagram", (1080, 1080))
    else:
        ig_img = ig_img.resize((1080, 1080), Image.LANCZOS)
    ig_img = _add_filler_branding(ig_img, "instagram")
    ig_path = os.path.join(out_dir, f"filler_{safe_theme}_instagram.jpg")
    ig_img.save(ig_path, "JPEG", quality=92)
    result["instagram"] = [ig_path]
    print(f"[Filler] Saved Instagram: {ig_path}")

    # ── Facebook ──────────────────────────────────────────────────────────────
    fb = content.get("facebook_post", {})
    fb_prompt = fb.get("image_prompt", f"Wide landscape lifestyle photo: {theme}. Warm, shareable, community feel. No text.")
    full_fb_prompt = (
        f"{fb_prompt} "
        f"Wide 16:9 landscape format. Photorealistic lifestyle photography. "
        f"Warm, inviting, shareable Facebook aesthetic. "
        f"NO text, NO words, NO watermarks."
    )
    fb_img = _generate_dalle_image(full_fb_prompt, dalle_size="1792x1024")
    if fb_img is None:
        fb_img = _make_gradient_placeholder(theme, "facebook", (1200, 630))
    else:
        fb_img = fb_img.resize((1200, 630), Image.LANCZOS)
    fb_img = _add_filler_branding(fb_img, "facebook")
    fb_path = os.path.join(out_dir, f"filler_{safe_theme}_facebook.jpg")
    fb_img.save(fb_path, "JPEG", quality=92)
    result["facebook"] = [fb_path]
    print(f"[Filler] Saved Facebook: {fb_path}")

    # ── TikTok ────────────────────────────────────────────────────────────────
    tt = content.get("tiktok_post", {})
    tt_prompt = tt.get("image_prompt", f"Dynamic vertical lifestyle image: {theme}. Eye-catching, youthful. No text.")
    full_tt_prompt = (
        f"{tt_prompt} "
        f"Tall 9:16 vertical format. Dynamic, eye-catching TikTok cover aesthetic. "
        f"Vibrant colors, high energy. "
        f"NO text, NO words, NO watermarks."
    )
    tt_img = _generate_dalle_image(full_tt_prompt, dalle_size="1024x1792")
    if tt_img is None:
        tt_img = _make_gradient_placeholder(theme, "tiktok", (1080, 1920))
    else:
        tt_img = tt_img.resize((1080, 1920), Image.LANCZOS)
    tt_img = _add_filler_branding(tt_img, "tiktok")
    tt_path = os.path.join(out_dir, f"filler_{safe_theme}_tiktok.jpg")
    tt_img.save(tt_path, "JPEG", quality=92)
    result["tiktok"] = [tt_path]
    print(f"[Filler] Saved TikTok: {tt_path}")

    # ── YouTube ───────────────────────────────────────────────────────────────
    yt = content.get("youtube_post", {})
    yt_prompt = yt.get("image_prompt", f"Cinematic wide landscape: {theme}. Dramatic, high contrast. No text.")
    full_yt_prompt = (
        f"{yt_prompt} "
        f"Wide 16:9 YouTube thumbnail format. Cinematic, dramatic, high contrast. "
        f"Professional photography quality. "
        f"NO text, NO words, NO watermarks."
    )
    yt_img = _generate_dalle_image(full_yt_prompt, dalle_size="1792x1024")
    if yt_img is None:
        yt_img = _make_gradient_placeholder(theme, "youtube", (1280, 720))
    else:
        yt_img = yt_img.resize((1280, 720), Image.LANCZOS)
    yt_img = _add_filler_branding(yt_img, "youtube")
    yt_path = os.path.join(out_dir, f"filler_{safe_theme}_youtube.jpg")
    yt_img.save(yt_path, "JPEG", quality=92)
    result["youtube"] = [yt_path]
    print(f"[Filler] Saved YouTube: {yt_path}")

    return result
