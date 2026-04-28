"""
blog_writer.py
GPT-powered SEO blog article generator for Content Factory.
Takes a topic + list of Shopify products and produces full HTML article
with embedded product images, text links, and a shop section.
"""

import os
import json
import logging
import re
from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


def _gpt_client():
    return OpenAI(
        api_key=OPENAI_API_KEY,
        base_url="https://api.openai.com/v1",
    )


def generate_blog_article(topic: str, products: list, store_name: str = "Official USA Store") -> dict:
    """
    Generate a full SEO blog article.

    Args:
        topic: Blog topic/title hint, e.g. "Best Patriotic Gifts for July 4th 2026"
        products: List of dicts with keys: title, description, price, url, image_url
        store_name: Display name for the store

    Returns:
        dict with keys:
            title           - SEO blog post title
            seo_description - Meta description (155 chars)
            html_content    - Full HTML article body
            tags            - List of tag strings
            suggested_category - Suggested WordPress category name
    """
    if not products:
        return {"error": "No products provided"}

    # Build product context block for GPT
    product_lines = []
    for i, p in enumerate(products, 1):
        product_lines.append(
            f"Product {i}:\n"
            f"  Title: {p.get('title', 'Unknown')}\n"
            f"  Price: ${p.get('price', '0')}\n"
            f"  URL: {p.get('url', '')}\n"
            f"  Image URL: {p.get('image_url', '')}\n"
            f"  Description: {p.get('description', '')[:300]}"
        )
    products_block = "\n\n".join(product_lines)

    system_prompt = """You are an expert SEO content writer and American patriotic lifestyle blogger.
You write engaging, viral, high-converting blog articles for an American patriotic merchandise store.
Your writing style is enthusiastic, proud, and celebratory of American history and culture.
You naturally weave product recommendations into editorial content — never sounding like an ad.
You write in clean, valid HTML suitable for WordPress (no <html>, <head>, or <body> tags — just the article body content).
"""

    user_prompt = f"""Write a full SEO-optimized blog article for the following topic and products.

TOPIC: {topic}
STORE NAME: {store_name}
STORE URL: https://www.officialusastore.com

PRODUCTS TO FEATURE:
{products_block}

REQUIREMENTS:
1. Write 900–1,400 words of engaging, SEO-rich content
2. Use an H1 title at the top (make it viral and click-worthy)
3. Use H2 and H3 subheadings throughout
4. Naturally mention and link each product at least once using: <a href="PRODUCT_URL" target="_blank" rel="noopener">PRODUCT TITLE</a>
5. For each product, embed its image with a click-through link using this exact HTML pattern:
   <div class="cf-product-block">
     <a href="PRODUCT_URL" target="_blank" rel="noopener">
       <img src="IMAGE_URL" alt="PRODUCT_TITLE" style="max-width:100%;height:auto;border-radius:8px;margin:16px 0;" />
     </a>
     <p><strong><a href="PRODUCT_URL" target="_blank" rel="noopener">PRODUCT_TITLE</a></strong> — $PRICE</p>
   </div>
6. Place product blocks naturally within the article flow — not all at the end
7. End with a "Shop the Collection" section listing all products with links and prices
8. Include a patriotic call-to-action paragraph at the very end
9. Write compelling anchor text for all links — never "click here"
10. Target keywords naturally throughout (America 250, patriotic gifts, 4th of July, etc.)

OUTPUT FORMAT — Return ONLY valid JSON with these exact keys:
{{
  "title": "SEO blog post title (60-70 chars)",
  "seo_description": "Meta description 140-155 chars, includes main keyword",
  "suggested_category": "Best WordPress category name for this article",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8"],
  "html_content": "FULL HTML ARTICLE BODY — all the HTML for the article"
}}

The html_content must be complete, valid HTML ready to paste into WordPress. Include all product images and links.
"""

    try:
        client = _gpt_client()
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)

        # Validate required keys
        required = ["title", "seo_description", "html_content", "tags", "suggested_category"]
        for key in required:
            if key not in data:
                data[key] = "" if key != "tags" else []

        return data

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error in blog article: {e}")
        return {"error": f"JSON parse error: {e}"}
    except Exception as e:
        logger.error(f"blog article generation error: {e}")
        return {"error": str(e)}


def build_preview_html(article: dict, products: list) -> str:
    """
    Build a standalone HTML preview of the article for the dashboard.
    Wraps the article content in a styled preview container.
    """
    title = article.get("title", "Blog Post Preview")
    content = article.get("html_content", "")
    seo_desc = article.get("seo_description", "")
    category = article.get("suggested_category", "")
    tags = article.get("tags", [])

    tags_html = " ".join(f'<span style="background:#1a3a6b;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;margin:2px;">{t}</span>' for t in tags)

    return f"""
<div style="font-family:Georgia,serif;max-width:860px;margin:0 auto;padding:20px;color:#222;">
  <div style="background:#f0f4ff;border-left:4px solid #1a3a6b;padding:12px 16px;margin-bottom:20px;border-radius:4px;">
    <strong>📌 Category:</strong> {category}<br>
    <strong>🔍 Meta:</strong> {seo_desc}<br>
    <strong>🏷 Tags:</strong> {tags_html}
  </div>
  {content}
</div>
"""
