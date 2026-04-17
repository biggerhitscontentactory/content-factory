"""
Content Factory — Shopify Blog Generator
==========================================
Uses Shopify OAuth (Client ID + Client Secret) to authenticate.

First-time setup:
  1. User clicks "Connect Shopify" in the Blog tab
  2. They are redirected to Shopify's OAuth approval page
  3. After approving, Shopify redirects back to /shopify/callback
  4. The callback exchanges the code for a permanent access token
  5. Token is saved to data/shopify_token.json and reused forever

Requires env vars:
  SHOPIFY_CLIENT_ID      — OAuth Client ID (from Shopify Partners)
  SHOPIFY_CLIENT_SECRET  — OAuth Client Secret (shpss_...)
  SHOPIFY_STORE_DOMAIN   — e.g. officialusastore.myshopify.com
  APP_URL                — Railway public domain (no https://)
  OPENAI_API_KEY         — for GPT-4.1-mini + DALL-E 3
"""

import os
import re
import json
import base64
import hashlib
import hmac as _hmac
import requests
from datetime import datetime

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR   = os.path.join(BASE_DIR, "data")
TOKEN_FILE = os.path.join(DATA_DIR, "shopify_token.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ─── Config helpers ───────────────────────────────────────────────────────────

def _cfg():
    return {
        "client_id":     os.environ.get("SHOPIFY_CLIENT_ID",     os.environ.get("SHOPIFY_API_KEY", "")),
        "client_secret": os.environ.get("SHOPIFY_CLIENT_SECRET", os.environ.get("SHOPIFY_SECRET_KEY", "")),
        "store_domain":  os.environ.get("SHOPIFY_STORE_DOMAIN",  "officialusastore.myshopify.com").strip().strip("/"),
        "app_url":       os.environ.get("APP_URL", "web-production-128b8.up.railway.app").strip().strip("/"),
    }

def shopify_configured():
    c = _cfg()
    return bool(c["client_id"] and c["client_secret"])

# ─── Token persistence ────────────────────────────────────────────────────────

def get_access_token():
    try:
        with open(TOKEN_FILE) as f:
            return json.load(f).get("access_token", "")
    except Exception:
        return ""

def save_access_token(token, scope=""):
    with open(TOKEN_FILE, "w") as f:
        json.dump({"access_token": token, "scope": scope, "saved_at": datetime.now().isoformat()}, f)

def is_authorized():
    return bool(get_access_token())

# ─── OAuth helpers ────────────────────────────────────────────────────────────

def get_install_url():
    c = _cfg()
    scopes = "read_products,write_content,read_content"
    redirect_uri = f"https://{c['app_url']}/shopify/callback"
    return (
        f"https://{c['store_domain']}/admin/oauth/authorize"
        f"?client_id={c['client_id']}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
        f"&state=cf-blog-connect"
    )

def exchange_code_for_token(code):
    """Exchange OAuth code for a permanent access token. Saves and returns it."""
    c = _cfg()
    resp = requests.post(
        f"https://{c['store_domain']}/admin/oauth/access_token",
        json={"client_id": c["client_id"], "client_secret": c["client_secret"], "code": code},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "")
    scope = data.get("scope", "")
    if token:
        save_access_token(token, scope)
    return token

def verify_shopify_hmac(params: dict) -> bool:
    """Verify Shopify's HMAC on the OAuth callback."""
    c = _cfg()
    hmac_value = params.get("hmac", "")
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "hmac")
    digest = _hmac.new(c["client_secret"].encode(), message.encode(), hashlib.sha256).hexdigest()
    return _hmac.compare_digest(digest, hmac_value)

# ─── Shopify REST API client ──────────────────────────────────────────────────

def _headers():
    token = get_access_token()
    if not token:
        raise RuntimeError("Shopify not connected. Click 'Connect Shopify' in the Blog tab first.")
    return {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

def _base():
    domain = _cfg()["store_domain"]
    if not domain.startswith("http"):
        domain = "https://" + domain
    return f"{domain}/admin/api/2024-01"

def _get(path, params=None):
    r = requests.get(f"{_base()}/{path}", headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def _post(path, payload):
    r = requests.post(f"{_base()}/{path}", headers=_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def _put(path, payload):
    r = requests.put(f"{_base()}/{path}", headers=_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def _delete(path):
    r = requests.delete(f"{_base()}/{path}", headers=_headers(), timeout=10)
    return r.status_code

# ─── Product fetching ─────────────────────────────────────────────────────────

def fetch_products(keyword="patriotic", limit=10):
    data = _get("products.json", params={"limit": 50, "status": "active"})
    all_products = data.get("products", [])
    kw = keyword.lower()
    words = kw.split()

    scored = []
    for p in all_products:
        title = p.get("title", "").lower()
        tags  = p.get("tags", "").lower()
        body  = p.get("body_html", "").lower()
        score = 0
        if kw in title: score += 10
        for w in words:
            if w in title: score += 3
            if w in tags:  score += 2
            if w in body:  score += 1
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [p for _, p in scored[:limit]] if scored[0][0] > 0 else [p for _, p in scored[:limit]]

    domain = _cfg()["store_domain"]
    storefront = domain.replace(".myshopify.com", ".com") if ".myshopify.com" in domain else domain

    result = []
    for p in top:
        images   = p.get("images", [])
        variants = p.get("variants", [])
        handle   = p.get("handle", "")
        result.append({
            "id":          p.get("id"),
            "title":       p.get("title", ""),
            "handle":      handle,
            "price":       variants[0].get("price", "0.00") if variants else "0.00",
            "image_url":   images[0].get("src", "") if images else "",
            "product_url": f"https://{storefront}/products/{handle}",
            "tags":        p.get("tags", ""),
        })
    return result

# ─── Blog content generation ──────────────────────────────────────────────────

def generate_blog_content(topic, products):
    from openai import OpenAI
    client = OpenAI()

    product_list = "\n".join(
        f"{i}. {p['title']} — ${p['price']} — {p['product_url']} — image: {p['image_url']}"
        for i, p in enumerate(products[:8], 1)
    )

    prompt = f"""You are a professional content writer for OfficialUSAStore.com, a patriotic American merchandise store.

Write a complete, SEO-optimized blog post about: "{topic}"

Products to feature (embed 5-8 naturally throughout the article):
{product_list}

Requirements:
- Length: 900-1,200 words
- Tone: Enthusiastic, patriotic, conversational American lifestyle blogger
- Structure: Compelling H1 title → intro → 3-4 H2 sections → closing CTA
- For each product embed, use EXACTLY this HTML (fill in real values):
<div class="product-embed" style="background:#f9f9f9;border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin:24px 0;max-width:340px;display:inline-block;vertical-align:top;">
  <img src="PRODUCT_IMAGE_URL" alt="PRODUCT_TITLE" style="width:100%;border-radius:6px;margin-bottom:12px;">
  <h3 style="margin:0 0 6px;font-size:16px;"><a href="PRODUCT_URL" style="color:#1e3a5f;text-decoration:none;">PRODUCT_TITLE</a></h3>
  <p style="font-size:18px;font-weight:bold;color:#b91c1c;margin:4px 0 10px;">$PRODUCT_PRICE</p>
  <a href="PRODUCT_URL" style="display:inline-block;background:#b91c1c;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">Shop Now →</a>
</div>
- Use real product URLs, images, and prices from the list above
- Include the main topic keyword naturally 4-6 times
- Write real, publish-ready content — no placeholders

Return ONLY valid JSON (no markdown fences):
{{
  "title": "The H1 blog post title",
  "meta_description": "155-character SEO meta description",
  "body_html": "The complete HTML body (everything after the H1 title)",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=3500,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)

# ─── Hero image generation ────────────────────────────────────────────────────

def generate_hero_image(topic):
    """Generate a wide hero image. Returns base64 string or None."""
    from openai import OpenAI
    client = OpenAI()
    try:
        resp = client.images.generate(
            model="dall-e-3",
            prompt=(
                f"Wide-format lifestyle photography for a patriotic American blog post about '{topic}'. "
                "American flags, red white and blue colors, warm natural lighting, editorial photography style. "
                "No text, no watermarks, photorealistic."
            ),
            size="1792x1024",
            quality="standard",
            n=1,
            response_format="b64_json",
        )
        return resp.data[0].b64_json
    except Exception as e:
        print(f"[Blog] Hero image error: {e}")
        return None

# ─── Image upload to Shopify CDN ──────────────────────────────────────────────

def upload_hero_image(b64_data, topic):
    """Upload hero image via a temp draft product, return CDN URL."""
    filename = f"blog-hero-{topic.lower().replace(' ', '-')[:40]}.png"
    try:
        resp = _post("products.json", {
            "product": {
                "title": f"__blog_hero_{filename}",
                "status": "draft",
                "images": [{"attachment": b64_data, "filename": filename}],
            }
        })
        product = resp.get("product", {})
        product_id = product.get("id")
        images = product.get("images", [])
        image_url = images[0].get("src", "") if images else ""
        # Clean up temp product (image URL persists on CDN)
        if product_id:
            try: _delete(f"products/{product_id}.json")
            except Exception: pass
        return image_url
    except Exception as e:
        print(f"[Blog] Image upload error: {e}")
        return None

# ─── Blog/article creation ────────────────────────────────────────────────────

def get_or_create_blog(title="News"):
    data = _get("blogs.json")
    blogs = data.get("blogs", [])
    if blogs:
        return blogs[0]["id"], blogs[0].get("handle", "news")
    result = _post("blogs.json", {"blog": {"title": title, "commentable": "no"}})
    blog = result.get("blog", {})
    return blog.get("id"), blog.get("handle", "news")

def publish_article(blog_id, title, body_html, meta_description, tags, hero_url=None):
    style = """<style>
.product-embed{background:#f9f9f9;border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin:24px 0;max-width:340px;display:inline-block;vertical-align:top;}
.product-embed img{width:100%;border-radius:6px;margin-bottom:12px;}
</style>\n"""
    hero_html = (
        f'<img src="{hero_url}" alt="{title}" '
        f'style="width:100%;max-height:480px;object-fit:cover;border-radius:10px;margin-bottom:24px;">\n\n'
        if hero_url else ""
    )
    full_body = style + hero_html + body_html
    tags_str = ", ".join(tags) if isinstance(tags, list) else tags

    result = _post(f"blogs/{blog_id}/articles.json", {
        "article": {
            "title": title,
            "author": "USA Store Team",
            "body_html": full_body,
            "summary_html": meta_description,
            "tags": tags_str,
            "published": True,
            "metafields": [{
                "key": "description_tag",
                "value": meta_description,
                "type": "single_line_text_field",
                "namespace": "global",
            }],
        }
    })
    article = result.get("article", {})
    return article.get("id"), article.get("handle", "")

# ─── Main entry point ─────────────────────────────────────────────────────────

def generate_and_publish_blog(topic, dry_run=False):
    """
    Full pipeline. Returns dict with status, url, title, steps, etc.
    Possible statuses: 'needs_auth', 'dry_run', 'published', 'error'
    """
    steps = []
    def log(msg):
        steps.append(msg)
        print(f"[Blog] {msg}", flush=True)

    # Auth check
    if not is_authorized():
        return {
            "status": "needs_auth",
            "error": "Shopify not connected yet.",
            "install_url": get_install_url(),
            "steps": steps,
        }

    log(f"Topic: {topic}")
    log(f"Mode: {'DRY RUN' if dry_run else 'LIVE PUBLISH'}")

    try:
        # Step 1: Products
        log("Fetching matching products from Shopify...")
        products = fetch_products(topic, limit=10)
        log(f"Found {len(products)} matching products")
        for p in products[:5]:
            log(f"  • {p['title']} (${p['price']})")

        # Step 2: Content
        log("Writing blog post with GPT-4.1-mini...")
        content = generate_blog_content(topic, products)
        title    = content["title"]
        meta     = content["meta_description"]
        tags     = content.get("tags", [])
        body     = content["body_html"]
        log(f"Title: {title}")
        log(f"Meta: {meta}")
        log(f"Tags: {', '.join(tags)}")

        if dry_run:
            log("DRY RUN — skipping image generation and publishing")
            return {
                "status": "dry_run",
                "title": title,
                "meta_description": meta,
                "tags": tags,
                "body_html_preview": body[:600] + "...",
                "products_featured": [p["title"] for p in products[:8]],
                "steps": steps,
            }

        # Step 3: Hero image
        log("Generating hero image with DALL-E 3...")
        hero_b64 = generate_hero_image(topic)
        hero_url = None
        if hero_b64:
            log("Uploading hero image to Shopify CDN...")
            hero_url = upload_hero_image(hero_b64, topic)
            if hero_url:
                log("Hero image uploaded ✓")
            else:
                log("Hero image upload failed — publishing without image")
        else:
            log("Hero image generation failed — publishing without image")

        # Step 4: Get blog
        log("Getting Shopify blog...")
        blog_id, blog_handle = get_or_create_blog("News")
        if not blog_id:
            return {"status": "error", "error": "Could not get or create Shopify blog.", "steps": steps}

        # Step 5: Publish
        log(f"Publishing to Shopify blog '{blog_handle}'...")
        article_id, article_handle = publish_article(blog_id, title, body, meta, tags, hero_url)

        domain = _cfg()["store_domain"].replace(".myshopify.com", ".com")
        article_url = f"https://{domain}/blogs/{blog_handle}/{article_handle}"

        log(f"✓ Published! Article ID: {article_id}")
        log(f"URL: {article_url}")

        return {
            "status": "published",
            "title": title,
            "article_id": article_id,
            "article_url": article_url,
            "products_featured": [p["title"] for p in products[:8]],
            "steps": steps,
        }

    except Exception as e:
        log(f"ERROR: {e}")
        return {"status": "error", "error": str(e), "steps": steps}
