"""
Content Factory - Image Generator
=====================================
Generates platform-optimized images using DALL-E 3.
Supports Pinterest vertical, Instagram square, Facebook landscape, and LinkedIn formats.
Falls back to downloading the product's own Shopify image when generation fails.
"""

import os
import re
import time
import requests
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OUTPUT_DIR_ECOMMERCE, OUTPUT_DIR_AI_CHANNEL

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# ─── Image size specs per platform ────────────────────────────────────────────
IMAGE_SIZES = {
    "pinterest":   "1024x1792",   # vertical 2:3 (closest DALL-E supports)
    "instagram":   "1024x1024",   # square
    "facebook":    "1792x1024",   # landscape
    "linkedin":    "1792x1024",   # landscape
    "thumbnail":   "1792x1024",   # landscape for video thumbnails
    "square":      "1024x1024",
    "vertical":    "1024x1792",
    "landscape":   "1792x1024",
}

# ─── Safety wrapper for DALL-E prompts ────────────────────────────────────────
DALLE_SAFETY_PREFIX = (
    "Professional product photography style. "
    "Clean, vibrant, commercial quality. "
    "No text overlays. No people's faces. "
    "Patriotic American aesthetic. "
)

def sanitize_prompt(prompt):
    """Remove any potentially flagged terms from DALL-E prompts."""
    # Remove overly political terms that might trigger content filters
    safe = re.sub(r'\b(MAGA|Trump|Biden|political party|Democrat|Republican)\b', 
                  'American', prompt, flags=re.IGNORECASE)
    return safe[:900]  # DALL-E prompt limit


def generate_image(prompt, platform="instagram", output_dir=None, filename=None):
    """
    Generate a single image using DALL-E 3.
    Returns local file path of saved image, or None on failure.
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR_ECOMMERCE
    os.makedirs(output_dir, exist_ok=True)

    size = IMAGE_SIZES.get(platform, "1024x1024")
    full_prompt = DALLE_SAFETY_PREFIX + sanitize_prompt(prompt)

    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=full_prompt,
            size=size,
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url

        # Download the image
        img_data = requests.get(image_url, timeout=30).content
        if not filename:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{platform}_{timestamp}.png"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(img_data)
        print(f"[ImageGen] Saved {platform} image: {filepath}")
        return filepath

    except Exception as e:
        print(f"[ImageGen] DALL-E error for {platform}: {e}")
        return None


def download_product_image(image_url, output_dir, filename):
    """
    Download a product's existing Shopify image as fallback.
    """
    os.makedirs(output_dir, exist_ok=True)
    try:
        resp = requests.get(image_url, timeout=15)
        resp.raise_for_status()
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(resp.content)
        print(f"[ImageGen] Downloaded product image: {filepath}")
        return filepath
    except Exception as e:
        print(f"[ImageGen] Failed to download product image: {e}")
        return None


def generate_ecommerce_images(content_pack, product_handle, output_dir=None):
    """
    Generate all images for an ecommerce content pack.
    Returns dict of platform -> local file path.
    """
    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR_ECOMMERCE, product_handle)
    os.makedirs(output_dir, exist_ok=True)

    images = {}
    image_prompts = content_pack.get("image_prompts", {})
    pins = content_pack.get("pinterest_pins", [])
    ig = content_pack.get("instagram_post", {})
    fb = content_pack.get("facebook_post", {})

    # Pinterest pin 1 (vertical)
    if pins and pins[0].get("image_prompt"):
        path = generate_image(
            pins[0]["image_prompt"], platform="pinterest",
            output_dir=output_dir, filename="pinterest_pin1.png"
        )
        images["pinterest_1"] = path
        time.sleep(2)  # rate limit between DALL-E calls

    # Pinterest pin 2 (vertical) - use pin 2 prompt or lifestyle prompt
    if len(pins) > 1 and pins[1].get("image_prompt"):
        path = generate_image(
            pins[1]["image_prompt"], platform="pinterest",
            output_dir=output_dir, filename="pinterest_pin2.png"
        )
        images["pinterest_2"] = path
        time.sleep(2)

    # Instagram square
    if ig.get("image_prompt"):
        path = generate_image(
            ig["image_prompt"], platform="instagram",
            output_dir=output_dir, filename="instagram.png"
        )
        images["instagram"] = path
        time.sleep(2)

    # Facebook landscape
    if fb.get("image_prompt"):
        path = generate_image(
            fb["image_prompt"], platform="facebook",
            output_dir=output_dir, filename="facebook.png"
        )
        images["facebook"] = path
        time.sleep(2)

    # Fallback: use product's own image if any generation failed
    product = content_pack.get("product", {})
    primary_image = product.get("primary_image", "")
    if primary_image:
        for platform in ["pinterest_1", "instagram", "facebook"]:
            if not images.get(platform):
                path = download_product_image(
                    primary_image, output_dir, f"{platform}_fallback.jpg"
                )
                images[platform] = path

    return images


def generate_ai_channel_images(content_pack, topic_slug, output_dir=None):
    """
    Generate images for an AI channel content pack (LinkedIn + Twitter).
    """
    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR_AI_CHANNEL, topic_slug)
    os.makedirs(output_dir, exist_ok=True)

    images = {}
    image_prompts = content_pack.get("image_prompts", {})

    # LinkedIn header image
    if image_prompts.get("linkedin_header"):
        path = generate_image(
            image_prompts["linkedin_header"], platform="linkedin",
            output_dir=output_dir, filename="linkedin_header.png"
        )
        images["linkedin_header"] = path
        time.sleep(2)

    # Carousel cover
    if image_prompts.get("carousel_cover"):
        path = generate_image(
            image_prompts["carousel_cover"], platform="linkedin",
            output_dir=output_dir, filename="carousel_cover.png"
        )
        images["carousel_cover"] = path

    return images


if __name__ == "__main__":
    # Quick test
    print("Testing image generation...")
    path = generate_image(
        "A beautiful patriotic American garden flag waving in a sunny backyard, "
        "red white and blue colors, 4th of July decorations, warm summer light",
        platform="instagram",
        output_dir="/home/ubuntu/content-factory/output/ecommerce",
        filename="test_image.png"
    )
    if path:
        print(f"✓ Image saved to: {path}")
    else:
        print("✗ Image generation failed")
