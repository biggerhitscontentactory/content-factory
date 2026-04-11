"""
Content Factory - LinkedIn Carousel PDF Generator
===================================================
Converts AI-generated carousel slide outlines into a proper PDF
suitable for uploading to LinkedIn as a document/carousel post.
Uses reportlab for clean, professional slide design.
"""

import os
import time
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas
from config import OUTPUT_DIR_AI_CHANNEL

# ─── Brand Colors ─────────────────────────────────────────────────────────────
BRAND_DARK    = colors.HexColor("#1a1a2e")   # dark navy
BRAND_ACCENT  = colors.HexColor("#0077b5")   # LinkedIn blue
BRAND_LIGHT   = colors.HexColor("#f0f4f8")   # light background
BRAND_WHITE   = colors.white
BRAND_GOLD    = colors.HexColor("#f5a623")   # accent gold

# Slide dimensions (LinkedIn carousel: 1080x1080 or letter-ish)
SLIDE_WIDTH  = 8.5 * inch
SLIDE_HEIGHT = 8.5 * inch  # square slides for LinkedIn


class CarouselSlide:
    """Represents a single carousel slide."""
    def __init__(self, slide_num, headline, subtext, slide_type="body"):
        self.slide_num = slide_num
        self.headline = headline
        self.subtext = subtext
        self.slide_type = slide_type  # cover, body, cta


def draw_slide(c, slide, page_width, page_height, brand_name, total_slides):
    """Draw a single carousel slide on the canvas."""
    c.setPageSize((page_width, page_height))

    # Background
    if slide.slide_type == "cover":
        c.setFillColor(BRAND_DARK)
    elif slide.slide_type == "cta":
        c.setFillColor(BRAND_ACCENT)
    else:
        c.setFillColor(BRAND_LIGHT)
    c.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    # Accent bar at top
    c.setFillColor(BRAND_ACCENT if slide.slide_type != "cta" else BRAND_GOLD)
    c.rect(0, page_height - 0.15 * inch, page_width, 0.15 * inch, fill=1, stroke=0)

    # Slide number indicator (bottom left)
    c.setFillColor(colors.HexColor("#999999"))
    c.setFont("Helvetica", 9)
    c.drawString(0.4 * inch, 0.3 * inch, f"{slide.slide_num}/{total_slides}")

    # Brand name (bottom right)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(BRAND_ACCENT if slide.slide_type == "body" else BRAND_WHITE)
    c.drawRightString(page_width - 0.4 * inch, 0.3 * inch, brand_name)

    # Headline
    headline_color = BRAND_WHITE if slide.slide_type in ("cover", "cta") else BRAND_DARK
    c.setFillColor(headline_color)

    if slide.slide_type == "cover":
        c.setFont("Helvetica-Bold", 28)
        # Center vertically
        y_pos = page_height * 0.65
    elif slide.slide_type == "cta":
        c.setFont("Helvetica-Bold", 26)
        y_pos = page_height * 0.65
    else:
        c.setFont("Helvetica-Bold", 22)
        y_pos = page_height * 0.72

    # Word-wrap headline
    _draw_wrapped_text(c, slide.headline, 0.5 * inch, y_pos,
                       page_width - 1.0 * inch, line_height=0.38 * inch,
                       max_lines=4)

    # Subtext
    subtext_color = colors.HexColor("#cccccc") if slide.slide_type in ("cover", "cta") else colors.HexColor("#444444")
    c.setFillColor(subtext_color)
    c.setFont("Helvetica", 14)

    sub_y = page_height * 0.38 if slide.slide_type == "cover" else page_height * 0.35
    _draw_wrapped_text(c, slide.subtext, 0.5 * inch, sub_y,
                       page_width - 1.0 * inch, line_height=0.28 * inch,
                       max_lines=5)

    # Arrow hint for non-last slides
    if slide.slide_num < total_slides:
        c.setFillColor(BRAND_ACCENT)
        c.setFont("Helvetica", 16)
        c.drawRightString(page_width - 0.4 * inch, page_height * 0.5, "→")


def _draw_wrapped_text(c, text, x, y, max_width, line_height, max_lines=4):
    """Simple word-wrap text drawing."""
    if not text:
        return
    words = text.split()
    lines = []
    current_line = []
    font_size = c._fontsize if hasattr(c, '_fontsize') else 14

    for word in words:
        test_line = " ".join(current_line + [word])
        if c.stringWidth(test_line) <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
        if len(lines) >= max_lines:
            break

    if current_line and len(lines) < max_lines:
        lines.append(" ".join(current_line))

    for i, line in enumerate(lines[:max_lines]):
        c.drawString(x, y - (i * line_height), line)


def generate_carousel_pdf(content_pack, topic_slug, output_dir=None):
    """
    Generate a LinkedIn carousel PDF from a content pack.
    Returns path to the generated PDF file.
    """
    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR_AI_CHANNEL, topic_slug)
    os.makedirs(output_dir, exist_ok=True)

    carousel_data = content_pack.get("linkedin_carousel", {})
    slides_data = carousel_data.get("slides", [])
    title = carousel_data.get("title", "AI Insights")

    if not slides_data:
        print("[Carousel] No slide data found in content pack")
        return None

    # Build slide objects
    slides = []
    for i, s in enumerate(slides_data):
        slide_num = s.get("slide", i + 1)
        headline = s.get("headline", "")
        subtext = s.get("subtext", "")
        if slide_num == 1:
            slide_type = "cover"
        elif slide_num == len(slides_data):
            slide_type = "cta"
        else:
            slide_type = "body"
        slides.append(CarouselSlide(slide_num, headline, subtext, slide_type))

    # Generate PDF
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"carousel_{timestamp}.pdf"
    filepath = os.path.join(output_dir, filename)

    c = canvas.Canvas(filepath, pagesize=(SLIDE_WIDTH, SLIDE_HEIGHT))
    brand_name = "Laptops & Latitude"

    for slide in slides:
        draw_slide(c, slide, SLIDE_WIDTH, SLIDE_HEIGHT, brand_name, len(slides))
        c.showPage()

    c.save()
    print(f"[Carousel] Generated PDF: {filepath} ({len(slides)} slides)")
    return filepath


if __name__ == "__main__":
    # Test with mock data
    mock_pack = {
        "linkedin_carousel": {
            "title": "5 AI Automations That Save 10+ Hours/Week",
            "slide_count": 8,
            "slides": [
                {"slide": 1, "headline": "5 AI Automations That Save 10+ Hours/Week", "subtext": "Most business owners are still doing these manually"},
                {"slide": 2, "headline": "1. Email Outreach Sequences", "subtext": "AI writes, personalizes, and sends 500 cold emails in 30 minutes"},
                {"slide": 3, "headline": "2. Social Media Content", "subtext": "One product URL → full week of platform-native posts"},
                {"slide": 4, "headline": "3. Lead Qualification", "subtext": "AI chatbot qualifies leads 24/7, books calls while you sleep"},
                {"slide": 5, "headline": "4. Customer Support Tier 1", "subtext": "80% of support tickets resolved without human involvement"},
                {"slide": 6, "headline": "5. Inventory & Reporting", "subtext": "Daily business reports written and sent automatically"},
                {"slide": 7, "headline": "The Real Cost of Not Automating", "subtext": "10 hours/week × 52 weeks = 520 hours/year doing tasks AI can handle"},
                {"slide": 8, "headline": "Want This Built for Your Business?", "subtext": "Comment 'AUTOMATE' or DM me — I'll show you exactly what's possible"},
            ]
        }
    }

    print("Generating test carousel PDF...")
    path = generate_carousel_pdf(mock_pack, "test_carousel",
                                  output_dir="/home/ubuntu/content-factory/output/ai_channel")
    if path:
        print(f"✓ PDF saved: {path}")
    else:
        print("✗ PDF generation failed")
