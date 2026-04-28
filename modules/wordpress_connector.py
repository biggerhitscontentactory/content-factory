"""
wordpress_connector.py
WordPress REST API connector for Content Factory.
Handles: category management, media upload, post creation.
"""

import os
import base64
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

WP_URL      = os.environ.get("WP_URL", "https://www.officialamerica250store.com").rstrip("/")
WP_USER     = os.environ.get("WP_USER", "america250")
WP_APP_PASS = os.environ.get("WP_APP_PASS", "Jt4X yrAT Fy4Y PNkh UaYL ajYw")


def _headers() -> dict:
    creds = base64.b64encode(f"{WP_USER}:{WP_APP_PASS}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }


def test_connection() -> dict:
    """Test auth and return user info."""
    try:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/users/me",
                         headers=_headers(), timeout=15)
        if r.status_code == 200:
            u = r.json()
            return {"ok": True, "user": u.get("name"), "id": u.get("id")}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_categories() -> list:
    """Return list of {id, name, slug} for all categories."""
    try:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/categories?per_page=100",
                         headers=_headers(), timeout=15)
        if r.status_code == 200:
            return [{"id": c["id"], "name": c["name"], "slug": c["slug"]}
                    for c in r.json()]
        return []
    except Exception as e:
        logger.error(f"get_categories error: {e}")
        return []


def get_or_create_category(name: str) -> Optional[int]:
    """
    Return category ID for the given name.
    Creates the category if it doesn't exist.
    """
    cats = get_categories()
    name_lower = name.strip().lower()
    for c in cats:
        if c["name"].lower() == name_lower or c["slug"] == name_lower.replace(" ", "-"):
            return c["id"]

    # Create new category
    try:
        r = requests.post(
            f"{WP_URL}/wp-json/wp/v2/categories",
            headers=_headers(),
            json={"name": name.strip()},
            timeout=15,
        )
        if r.status_code in (200, 201):
            return r.json().get("id")
        logger.error(f"create_category error: {r.status_code} {r.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"create_category exception: {e}")
        return None


def upload_image_from_url(image_url: str, filename: str = "featured.jpg") -> Optional[int]:
    """
    Download an image from a URL and upload it to WordPress media library.
    Returns the WordPress media ID, or None on failure.
    """
    try:
        img_resp = requests.get(image_url, timeout=20)
        if img_resp.status_code != 200:
            logger.warning(f"Could not download image: {image_url}")
            return None

        creds = base64.b64encode(f"{WP_USER}:{WP_APP_PASS}".encode()).decode()
        headers = {
            "Authorization": f"Basic {creds}",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": img_resp.headers.get("Content-Type", "image/jpeg"),
        }
        r = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            headers=headers,
            data=img_resp.content,
            timeout=30,
        )
        if r.status_code in (200, 201):
            return r.json().get("id")
        logger.error(f"upload_image error: {r.status_code} {r.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"upload_image exception: {e}")
        return None


def create_post(
    title: str,
    html_content: str,
    category_id: Optional[int] = None,
    featured_media_id: Optional[int] = None,
    seo_description: str = "",
    status: str = "draft",
    tags: list = None,
) -> dict:
    """
    Create a WordPress post.
    status: 'draft' | 'publish'
    Returns dict with 'ok', 'post_id', 'url', or 'error'.
    """
    payload = {
        "title": title,
        "content": html_content,
        "status": status,
        "excerpt": seo_description,
        "format": "standard",
    }
    if category_id:
        payload["categories"] = [category_id]
    if featured_media_id:
        payload["featured_media"] = featured_media_id
    if tags:
        # Resolve/create tags and get IDs
        tag_ids = []
        for tag_name in tags[:10]:
            tid = _get_or_create_tag(tag_name)
            if tid:
                tag_ids.append(tid)
        if tag_ids:
            payload["tags"] = tag_ids

    try:
        r = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=_headers(),
            json=payload,
            timeout=30,
        )
        if r.status_code in (200, 201):
            data = r.json()
            return {
                "ok": True,
                "post_id": data.get("id"),
                "url": data.get("link"),
                "status": data.get("status"),
            }
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _get_or_create_tag(name: str) -> Optional[int]:
    """Return tag ID, creating if needed."""
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/tags",
            headers=_headers(),
            params={"search": name, "per_page": 5},
            timeout=10,
        )
        if r.status_code == 200:
            results = r.json()
            for t in results:
                if t["name"].lower() == name.lower():
                    return t["id"]
        # Create
        r2 = requests.post(
            f"{WP_URL}/wp-json/wp/v2/tags",
            headers=_headers(),
            json={"name": name},
            timeout=10,
        )
        if r2.status_code in (200, 201):
            return r2.json().get("id")
        return None
    except Exception:
        return None
