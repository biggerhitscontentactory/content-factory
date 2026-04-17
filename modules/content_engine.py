"""
Content Factory - AI Content Engine
=====================================
Generates platform-native content packs using OpenAI GPT.
Supports both ecommerce (USA Store) and AI channel (Laptops and Latitude) modes.
Built-in anti-repetition: rotates voice styles and avoids AI giveaway phrases.
"""

import json
import random
import time
from openai import OpenAI
from config import (
    OPENAI_API_KEY, OPENAI_MODEL,
    ECOMMERCE_STORE_NAME, ECOMMERCE_STORE_URL, ECOMMERCE_NICHE,
    AI_CHANNEL_NAME, AI_CHANNEL_WEBSITE
)

import os
from config import OPENAI_BASE_URL
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)

# ─── Voice Style Rotation (anti-repetition) ───────────────────────────────────
ECOMMERCE_VOICE_STYLES = [
    "patriotic_pride",
    "gift_angle",
    "historical_hook",
    "lifestyle_visual",
    "urgency_scarcity",
    "community_identity",
]

AI_CHANNEL_VOICE_STYLES = [
    "authority_expert",
    "results_driven",
    "contrarian_take",
    "build_in_public",
    "problem_solution",
    "case_study",
]

# ─── Voice Style Descriptions ─────────────────────────────────────────────────
VOICE_STYLE_PROMPTS = {
    # Ecommerce styles
    "patriotic_pride": "Write with deep American pride and emotional resonance. Celebrate freedom, heritage, and what it means to be American.",
    "gift_angle": "Write from a gift-giving perspective. Focus on who would love this, occasions to give it, and why it makes a perfect present.",
    "historical_hook": "Open with a fascinating historical fact about America, 1776, or the 250th anniversary. Connect it naturally to the product.",
    "lifestyle_visual": "Paint a vivid lifestyle picture. Describe the setting, the feeling, the moment — backyard BBQ, parade, family gathering. Product fits naturally into the scene.",
    "urgency_scarcity": "Create genuine urgency around the America 250th anniversary countdown. July 4, 2026 is a once-in-a-lifetime milestone. Limited time, limited edition feel.",
    "community_identity": "Speak to shared American identity and belonging. 'For everyone who...' framing. Tribal, inclusive, proud.",
    # AI channel styles
    "authority_expert": "Write as a seasoned AI developer who has built real systems for real clients. Specific, credible, no fluff.",
    "results_driven": "Lead with concrete results and numbers. 'I saved X hours,' 'Generated $Y,' 'Reduced costs by Z%.' Make it tangible.",
    "contrarian_take": "Challenge a common assumption or popular belief in the AI space. Provocative but backed by reasoning.",
    "build_in_public": "Share the process transparently. What you built, how you built it, what went wrong, what worked. Authentic and educational.",
    "problem_solution": "Start with a painful problem your target client faces. Agitate it briefly. Then present AI as the clear solution.",
    "case_study": "Walk through a real or realistic client scenario. Industry, problem, solution, result. Specific enough to be credible.",
}

# ─── Anti-AI-Detection Rules ──────────────────────────────────────────────────
ANTI_AI_SYSTEM_RULES = """
CRITICAL WRITING RULES — follow these exactly:
- NEVER use the words: delve, certainly, leverage, utilize, comprehensive, robust, seamlessly, game-changer, cutting-edge, revolutionize, transformative, unlock, empower
- NEVER start a sentence with "In today's..."
- NEVER use em-dashes (—) excessively — one maximum per post
- Vary sentence length: mix short punchy sentences with longer ones
- Include at least one specific concrete detail (a price, a date, a number, a place)
- Write like a real human who is passionate about this topic
- No emoji overload: maximum 2 emojis per post, zero on LinkedIn and Reddit
- Pinterest pins: include 7-10 relevant hashtags at end of description
- Instagram: include 15-20 hashtags (niche + broad + seasonal mix)
- Facebook: no hashtags (hurts reach on Facebook)
- LinkedIn: no hashtags
"""


def generate_ecommerce_content_pack(product, voice_style=None):
    """
    Generate a full content pack for a single ecommerce product.
    Returns dict with content for each platform.
    """
    if not voice_style:
        voice_style = random.choice(ECOMMERCE_VOICE_STYLES)

    style_instruction = VOICE_STYLE_PROMPTS.get(voice_style, "")

    # Build product context
    price_str = f"${product['price']:.2f}"
    if product.get("on_sale") and product.get("compare_price"):
        price_str = f"${product['price']:.2f} (was ${product['compare_price']:.2f})"

    product_context = f"""
PRODUCT DETAILS:
- Name: {product['title']}
- Price: {price_str}
- URL: {product['url']}
- Description: {product['description'][:300]}
- Category: {product.get('product_type', 'Patriotic merchandise')}
- Tags: {', '.join(product.get('tags', [])[:8])}
- Store: {ECOMMERCE_STORE_NAME} ({ECOMMERCE_STORE_URL})
- Niche: {ECOMMERCE_NICHE}
"""

    prompt = f"""You are a social media content expert for a patriotic USA merchandise store.
{ANTI_AI_SYSTEM_RULES}

VOICE STYLE FOR THIS BATCH: {style_instruction}

{product_context}

Generate a complete content pack. Return ONLY valid JSON with this exact structure:

{{
  "voice_style": "{voice_style}",
  "pinterest_pins": [
    {{
      "titles": [
        "Pin 1 title option 1 (max 100 chars, keyword-rich for Pinterest SEO)",
        "Pin 1 title option 2 — different angle",
        "Pin 1 title option 3 — benefit-focused",
        "Pin 1 title option 4 — curiosity/question style",
        "Pin 1 title option 5 — seasonal/occasion angle"
      ],
      "descriptions": [
        "Pin 1 description option 1 (150-250 chars, conversational)",
        "Pin 1 description option 2 — different emotional angle",
        "Pin 1 description option 3 — gift-giving angle",
        "Pin 1 description option 4 — lifestyle/identity angle"
      ],
      "hashtags": "#patriotic #america250 #usagifts #july4th #americanpride #giftideas #usastore",
      "link": "Use the product URL from PRODUCT DETAILS above",
      "image_prompt": "Detailed DALL-E prompt for a vertical 2:3 lifestyle image showing this product in a patriotic American setting"
    }},
    {{
      "titles": [
        "Pin 2 title option 1 — gift angle",
        "Pin 2 title option 2 — pride angle",
        "Pin 2 title option 3 — occasion angle",
        "Pin 2 title option 4 — value angle",
        "Pin 2 title option 5 — collector angle"
      ],
      "descriptions": [
        "Pin 2 description option 1",
        "Pin 2 description option 2",
        "Pin 2 description option 3",
        "Pin 2 description option 4"
      ],
      "hashtags": "#patrioticgifts #america #july4th #1776 #usapride #giftsforher #giftsforhim",
      "link": "Use the product URL from PRODUCT DETAILS above",
      "image_prompt": "Different scene DALL-E prompt — outdoor patriotic setting"
    }},
    {{
      "titles": [
        "Pin 3 title option 1 — America 250 angle",
        "Pin 3 title option 2 — heritage angle",
        "Pin 3 title option 3 — celebration angle",
        "Pin 3 title option 4 — shop/deal angle",
        "Pin 3 title option 5 — community/pride angle"
      ],
      "descriptions": [
        "Pin 3 description option 1",
        "Pin 3 description option 2",
        "Pin 3 description option 3",
        "Pin 3 description option 4"
      ],
      "hashtags": "#giftideas #patrioticgifts #americangifts #4thofjuly #america250 #usagifts #shopusa",
      "link": "Use the product URL from PRODUCT DETAILS above",
      "image_prompt": "Gift presentation DALL-E prompt"
    }}
  ],
  "instagram_post": {{
    "titles": [
      "IG caption option 1 (150-220 chars, conversational, max 2 emojis, ends with CTA)",
      "IG caption option 2 — different emotional hook",
      "IG caption option 3 — question/engagement style",
      "IG caption option 4 — story/narrative style",
      "IG caption option 5 — urgency/occasion style"
    ],
    "caption": "IG caption option 1 (same as titles[0] — primary pick)",
    "hashtags": "#america250 #patrioticgifts #usastore #giftideas #shopsmall #july4th #4thofjuly #independenceday #americanpride #usapride #patriotic #shopusa #americanmade #giftsforhim #giftsforher #patrioticfashion #usagifts #1776 #america #freedom",
    "link": "Use the product URL from PRODUCT DETAILS above",
    "image_prompt": "DALL-E prompt for a square lifestyle product image, bright and eye-catching"
  }},
  "facebook_post": {{
    "titles": [
      "Facebook post option 1 (100-180 chars, conversational, discussion CTA at end)",
      "Facebook post option 2 — different angle",
      "Facebook post option 3 — question to audience",
      "Facebook post option 4 — story angle",
      "Facebook post option 5 — value/deal angle"
    ],
    "text": "Facebook post option 1 (same as titles[0] — primary pick)",
    "link": "Use the product URL from PRODUCT DETAILS above",
    "image_prompt": "DALL-E prompt for a Facebook-optimized product lifestyle image"
  }},
  "tiktok_post": {{
    "titles": [
      "TikTok caption option 1 (short, punchy, 1-2 lines max)",
      "TikTok caption option 2 — trending hook style",
      "TikTok caption option 3 — question/challenge style",
      "TikTok caption option 4 — POV style",
      "TikTok caption option 5 — reaction/surprise style"
    ],
    "script": "TikTok caption option 1 (same as titles[0])",
    "hook": "First 3 seconds hook line (punchy, stops the scroll)",
    "hashtags": "#america250 #patriotic #usastore #july4th #fyp #foryou #patrioticvibes #usapride #giftideas #shopusa",
    "link": "Use the product URL from PRODUCT DETAILS above"
  }},
  "youtube_post": {{
    "titles": [
      "YouTube title option 1 (max 70 chars, SEO-optimized)",
      "YouTube title option 2 — curiosity angle",
      "YouTube title option 3 — benefit angle",
      "YouTube title option 4 — occasion angle",
      "YouTube title option 5 — review/showcase angle"
    ],
    "description": "YouTube description (150-250 chars, includes product link, subscribe CTA)",
    "link": "Use the product URL from PRODUCT DETAILS above",
    "image_prompt": "YouTube thumbnail prompt — high contrast, bold text overlay, eye-catching"
  }},
  "video_script": {{
    "hook": "First 3 seconds hook line (punchy, stops the scroll)",
    "body": "15-25 second body script (product showcase, key benefit, emotional appeal)",
    "cta": "Final 5 second CTA (clear action: visit link, comment, share)"
  }},
  "image_prompts": {{
    "thumbnail": "YouTube/TikTok thumbnail prompt — high contrast, bold text overlay suggestion, eye-catching",
    "product_lifestyle": "Main lifestyle image prompt — product in use in a patriotic American setting",
    "pinterest_vertical": "Vertical 2:3 Pinterest pin prompt with text overlay space at top and bottom"
  }}
}}"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=3500,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        content = json.loads(raw)
        content["product"] = product
        content["generated_at"] = time.strftime("%Y-%m-%d %Human:%M:%S")
        return content
    except json.JSONDecodeError as e:
        print(f"[ContentEngine] JSON parse error: {e}")
        print(f"[ContentEngine] Raw response: {raw[:200]}")
        return {"error": str(e), "product": product}
    except Exception as e:
        print(f"[ContentEngine] Error generating content: {e}")
        return {"error": str(e), "product": product}


def generate_ai_channel_content_pack(row, voice_style=None):
    """
    Generate a full content pack for the AI dev channel from a Google Sheet row.
    Returns dict with LinkedIn post, carousel outline, and Twitter thread.
    """
    if not voice_style:
        voice_style = random.choice(AI_CHANNEL_VOICE_STYLES)

    style_instruction = VOICE_STYLE_PROMPTS.get(voice_style, "")

    topic_context = f"""
CONTENT BRIEF:
- Topic: {row.get('topic', '')}
- Pillar: {row.get('pillar', 'AI for Business')}
- Target Client: {row.get('target_client', 'Business owners wanting AI automation')}
- Pain Point: {row.get('pain_point', '')}
- Proof Element: {row.get('proof_element', '')}
- CTA Goal: {row.get('cta', 'Book a discovery call')}
- Channel: {AI_CHANNEL_NAME} ({AI_CHANNEL_WEBSITE})
- Offer: AI development and automation services for businesses
"""

    prompt = f"""You are a LinkedIn content strategist for an AI developer who builds automation systems for businesses.
{ANTI_AI_SYSTEM_RULES}

VOICE STYLE: {style_instruction}

{topic_context}

Generate a complete content pack. Return ONLY valid JSON:

{{
  "voice_style": "{voice_style}",
  "linkedin_text_post": {{
    "hook": "Opening line (max 2 lines, must stop the scroll, no link)",
    "body": "Main content (150-250 words, insight-dense, paragraph format, no bullet overload)",
    "cta": "Closing CTA (soft: comment-based or question, no hard sell)",
    "full_post": "Complete post combining hook + body + cta, ready to copy-paste"
  }},
  "linkedin_carousel": {{
    "title": "Carousel title (bold, benefit-driven)",
    "slide_count": 8,
    "slides": [
      {{"slide": 1, "headline": "Cover slide headline", "subtext": "Cover subtext"}},
      {{"slide": 2, "headline": "Slide 2 headline", "subtext": "Key point or stat"}},
      {{"slide": 3, "headline": "Slide 3 headline", "subtext": "Key point"}},
      {{"slide": 4, "headline": "Slide 4 headline", "subtext": "Key point"}},
      {{"slide": 5, "headline": "Slide 5 headline", "subtext": "Key point"}},
      {{"slide": 6, "headline": "Slide 6 headline", "subtext": "Key point"}},
      {{"slide": 7, "headline": "Slide 7 headline", "subtext": "Key point"}},
      {{"slide": 8, "headline": "CTA slide headline", "subtext": "Clear next step for the reader"}}
    ],
    "cover_image_prompt": "DALL-E prompt for a professional LinkedIn carousel cover image"
  }},
  "twitter_thread": {{
    "tweet_count": 7,
    "tweets": [
      {{"n": 1, "text": "Hook tweet (max 240 chars, provocative or insight-driven)"}},
      {{"n": 2, "text": "Tweet 2 (max 240 chars)"}},
      {{"n": 3, "text": "Tweet 3 (max 240 chars)"}},
      {{"n": 4, "text": "Tweet 4 (max 240 chars)"}},
      {{"n": 5, "text": "Tweet 5 (max 240 chars)"}},
      {{"n": 6, "text": "Tweet 6 (max 240 chars)"}},
      {{"n": 7, "text": "Final tweet with CTA (max 240 chars)"}}
    ]
  }},
  "image_prompts": {{
    "linkedin_header": "Professional LinkedIn post header image prompt",
    "carousel_cover": "Eye-catching carousel cover slide image prompt"
  }}
}}"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=2500,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        content = json.loads(raw)
        content["row"] = row
        content["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return content
    except json.JSONDecodeError as e:
        print(f"[ContentEngine] JSON parse error: {e}")
        return {"error": str(e), "row": row}
    except Exception as e:
        print(f"[ContentEngine] Error generating AI channel content: {e}")
        return {"error": str(e), "row": row}


def generate_batch_ecommerce(products, max_items=5):
    """Generate content packs for a batch of products."""
    results = []
    styles = ECOMMERCE_VOICE_STYLES.copy()
    random.shuffle(styles)

    for i, product in enumerate(products[:max_items]):
        style = styles[i % len(styles)]
        print(f"[ContentEngine] Generating content for: {product['title'][:50]} (style: {style})")
        pack = generate_ecommerce_content_pack(product, voice_style=style)
        results.append(pack)
        time.sleep(1)  # rate limit buffer

    return results


if __name__ == "__main__":
    # Quick test with a mock product
    test_product = {
        "title": "United States of America 250th Anniversary Patriotic Baseball Hat",
        "price": 34.95,
        "compare_price": 0,
        "on_sale": False,
        "url": "https://www.officialusastore.com/products/usa-250th-anniversary-hat",
        "description": "Celebrate America's 250th birthday with this premium embroidered baseball hat. Features the iconic bald eagle and 1776-2026 dates.",
        "product_type": "Hats",
        "tags": ["america 250", "patriotic", "hat", "anniversary", "1776", "2026"],
        "primary_image": "",
        "tier": 1,
    }

    print("Testing ecommerce content generation...")
    pack = generate_ecommerce_content_pack(test_product)
    if "error" not in pack:
        print("\n✓ Content generated successfully!")
        print(f"Voice style: {pack.get('voice_style')}")
        if pack.get("pinterest_pins"):
            print(f"Pinterest pin 1: {pack['pinterest_pins'][0]['title']}")
        if pack.get("instagram_post"):
            print(f"Instagram: {pack['instagram_post']['caption'][:80]}...")
    else:
        print(f"✗ Error: {pack['error']}")
