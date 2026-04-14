"""
HeyGen Video Generator
======================
Reads topics + scene descriptions from Google Sheet:
  Col A = video title/topic
  Col B = scene/clothing description
  Col C = avatar look ID (specific look from the Brian S Tines avatar group)
Generates a full spoken script via GPT, splits into scenes, and submits to HeyGen API v2.
- Avatar group: Brian S Tines (973f341d0e3c4459bf91d2d29734321c)
- Voice:  Brian Tines voice (cff38160a33643d7b8101d2ab989d5f1) — Essential plan, no credits
- No B-roll, no captions, avatar talking the entire video
- Target length: 7–13 minutes (configurable per run)
"""

import os
import sys
import json
import time
import math
import requests

# ── Config ────────────────────────────────────────────────────────────────────
try:
    from config import (
        HEYGEN_API_KEY, HEYGEN_AVATAR_ID, HEYGEN_VOICE_ID,
        HEYGEN_SHEET_ID, OPENAI_API_KEY, OPENAI_MODEL, DATA_DIR
    )
except ImportError:
    HEYGEN_API_KEY   = os.environ.get("HEYGEN_API_KEY", "")
    HEYGEN_AVATAR_ID = "973f341d0e3c4459bf91d2d29734321c"
    HEYGEN_VOICE_ID  = "cff38160a33643d7b8101d2ab989d5f1"
    HEYGEN_SHEET_ID  = "1xPAwaOish_Nw6Fix4xGEqeR_EfQaFwL2XcsWkfxy3q0"
    OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL     = "gpt-4o-mini"
    DATA_DIR         = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

HEYGEN_BASE    = "https://api.heygen.com"
HEYGEN_HEADERS = {
    "X-Api-Key": HEYGEN_API_KEY,
    "Content-Type": "application/json",
}

# Words per minute for Brian Tines (measured from preview — calm, conversational pace)
WORDS_PER_MINUTE = 130

# HeyGen max characters per scene text input (~500 words safe limit)
MAX_WORDS_PER_SCENE = 450

# Video resolution — 16:9 landscape for YouTube
VIDEO_WIDTH  = 1280
VIDEO_HEIGHT = 720


# ─── Google Sheets reader (public CSV export, no auth needed) ─────────────────
def read_sheet_rows(sheet_id: str) -> list[dict]:
    """
    Reads the Google Sheet via public CSV export.
    Returns list of dicts: [{"title": ..., "scene": ..., "row": N}, ...]
    Sheet must be shared as 'Anyone with link can view'.
    """
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    import csv, io
    rows = []
    reader = csv.reader(io.StringIO(resp.text))
    headers = None
    for i, row in enumerate(reader):
        if i == 0:
            headers = [h.strip().lower() for h in row]
            continue
        if not row or not row[0].strip():
            continue
        title    = row[0].strip() if len(row) > 0 else ""
        scene    = row[1].strip() if len(row) > 1 else ""
        look_id  = row[2].strip() if len(row) > 2 else ""
        if title:
            rows.append({"title": title, "scene": scene, "look_id": look_id, "row": i + 1})
    return rows


def get_unprocessed_rows(sheet_id: str, done_file: str) -> list[dict]:
    """Returns rows that haven't been processed yet (tracked in done_file JSON)."""
    done = set()
    if os.path.exists(done_file):
        try:
            done = set(json.load(open(done_file)))
        except Exception:
            done = set()

    all_rows = read_sheet_rows(sheet_id)
    return [r for r in all_rows if r["row"] not in done]


def mark_row_done(row_num: int, done_file: str):
    """Mark a row as processed."""
    done = set()
    if os.path.exists(done_file):
        try:
            done = set(json.load(open(done_file)))
        except Exception:
            done = set()
    done.add(row_num)
    os.makedirs(os.path.dirname(done_file), exist_ok=True)
    with open(done_file, "w") as f:
        json.dump(list(done), f)


# ─── GPT Script Generator ─────────────────────────────────────────────────────
def generate_script(title: str, scene_hint: str, target_minutes: int) -> str:
    """
    Uses GPT to generate a full spoken video script for the given topic.
    Target length: target_minutes * WORDS_PER_MINUTE words.
    Returns plain spoken text (no stage directions, no headers, no B-roll notes).
    """
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    target_words = target_minutes * WORDS_PER_MINUTE
    min_words    = (target_minutes - 1) * WORDS_PER_MINUTE
    max_words    = (target_minutes + 1) * WORDS_PER_MINUTE

    system_prompt = f"""You are a professional video scriptwriter for a YouTube channel called "Laptops and Latitude" 
hosted by Brian Tines — a relaxed, knowledgeable guy who talks about AI tools, automation, and business from 
beachside locations. His style is conversational, warm, and practical. He speaks directly to the camera the 
entire time — no B-roll, no cutaways, just him talking.

Write ONLY the spoken words Brian will say. 
- NO stage directions, NO scene descriptions, NO [B-roll], NO (pause), NO headers, NO bullet points
- NO captions or on-screen text references
- Write as natural spoken English — contractions, conversational flow, occasional rhetorical questions
- Start with a hook that grabs attention in the first 15 seconds
- End with a clear call to action (subscribe, comment, or check a link)
- Target length: {target_words} words (between {min_words} and {max_words} words)
- Scene context (for your awareness only, do NOT mention it): {scene_hint}"""

    user_prompt = f"Write the full spoken script for a video titled: \"{title}\""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.75,
        max_tokens=4000,
    )
    return response.choices[0].message.content.strip()


# ─── Script Splitter ──────────────────────────────────────────────────────────
def split_script_into_scenes(script: str, max_words: int = MAX_WORDS_PER_SCENE) -> list[str]:
    """
    Splits a long script into scene chunks of max_words each.
    Tries to split on sentence boundaries to avoid mid-sentence cuts.
    """
    import re
    # Split on sentence endings
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())

    scenes = []
    current_chunk = []
    current_count = 0

    for sentence in sentences:
        word_count = len(sentence.split())
        if current_count + word_count > max_words and current_chunk:
            scenes.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_count = word_count
        else:
            current_chunk.append(sentence)
            current_count += word_count

    if current_chunk:
        scenes.append(" ".join(current_chunk))

    return scenes


# ─── HeyGen API Calls ─────────────────────────────────────────────────────────
def submit_video(title: str, scenes: list[str], look_id: str = "", test: bool = False) -> str:
    """
    Submits a multi-scene video to HeyGen API v2.
    Each scene = Brian S Tines avatar talking, no B-roll, no captions.
    look_id: specific look/outfit ID from Column C of the sheet.
    Returns video_id.
    """
    # Use the look_id from Column C if provided, otherwise fall back to group avatar ID
    avatar_id_to_use = look_id if look_id else HEYGEN_AVATAR_ID

    video_inputs = []
    for scene_text in scenes:
        video_inputs.append({
            "character": {
                "type": "avatar",
                "avatar_id": avatar_id_to_use,
                "avatar_style": "normal",
            },
            "voice": {
                "type": "text",
                "input_text": scene_text,
                "voice_id": HEYGEN_VOICE_ID,
                "speed": 1.0,
            },
            # No background — uses avatar's default scene from the sheet description
            # (HeyGen doesn't support dynamic background per-scene via API on Essential plan)
        })

    payload = {
        "video_inputs": video_inputs,
        "dimension": {"width": VIDEO_WIDTH, "height": VIDEO_HEIGHT},
        "caption": False,   # No captions ever
        "title": title[:100],
    }
    if test:
        payload["test"] = True

    resp = requests.post(
        f"{HEYGEN_BASE}/v2/video/generate",
        headers=HEYGEN_HEADERS,
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("error"):
        raise RuntimeError(f"HeyGen API error: {data['error']}")

    video_id = data["data"]["video_id"]
    return video_id


def poll_video_status(video_id: str, max_wait_minutes: int = 60) -> dict:
    """
    Polls HeyGen for video completion. Returns status dict with video_url when done.
    Polls every 30 seconds up to max_wait_minutes.
    """
    deadline = time.time() + max_wait_minutes * 60
    while time.time() < deadline:
        resp = requests.get(
            f"{HEYGEN_BASE}/v1/video_status.get?video_id={video_id}",
            headers=HEYGEN_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("status", "")
        print(f"[HeyGen] Video {video_id} status: {status}")

        if status == "completed":
            return {
                "status": "completed",
                "video_id": video_id,
                "video_url": data.get("video_url", ""),
                "thumbnail_url": data.get("thumbnail_url", ""),
                "duration": data.get("duration", 0),
            }
        elif status in ("failed", "error"):
            return {
                "status": "failed",
                "video_id": video_id,
                "error": data.get("error", "Unknown error"),
            }
        time.sleep(30)

    return {"status": "timeout", "video_id": video_id}


def get_video_status(video_id: str) -> dict:
    """Single status check (non-blocking, for polling endpoint)."""
    resp = requests.get(
        f"{HEYGEN_BASE}/v1/video_status.get?video_id={video_id}",
        headers=HEYGEN_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return {
        "status": data.get("status", "unknown"),
        "video_id": video_id,
        "video_url": data.get("video_url", ""),
        "thumbnail_url": data.get("thumbnail_url", ""),
        "duration": data.get("duration", 0),
        "error": data.get("error", ""),
    }


# ─── Main Orchestrator ────────────────────────────────────────────────────────
def run_heygen_batch(
    count: int = 1,
    target_minutes: int = 10,
    test_mode: bool = False,
    progress_cb=None,
) -> list[dict]:
    """
    Main entry point. Reads sheet, generates scripts, submits to HeyGen.
    Returns list of result dicts per video.

    Args:
        count:          Number of videos to create this run
        target_minutes: Target video length in minutes (7–13)
        test_mode:      If True, uses HeyGen test mode (no credits, watermarked)
        progress_cb:    Optional callable(message: str) for live progress updates
    """
    def log(msg):
        print(msg)
        if progress_cb:
            progress_cb(msg)

    done_file = os.path.join(DATA_DIR, "heygen_done_rows.json")
    video_log  = os.path.join(DATA_DIR, "heygen_videos.json")

    # Load existing video log
    existing_videos = []
    if os.path.exists(video_log):
        try:
            existing_videos = json.load(open(video_log))
        except Exception:
            existing_videos = []

    # Get unprocessed rows from sheet
    log(f"[HeyGen] Reading Google Sheet ({HEYGEN_SHEET_ID})...")
    rows = get_unprocessed_rows(HEYGEN_SHEET_ID, done_file)
    if not rows:
        log("[HeyGen] All rows have been processed. No new videos to generate.")
        return []

    log(f"[HeyGen] Found {len(rows)} unprocessed rows. Will generate {min(count, len(rows))} video(s).")
    rows_to_process = rows[:count]
    results = []

    for idx, row in enumerate(rows_to_process):
        title   = row["title"]
        scene   = row["scene"]
        look_id = row.get("look_id", "")
        row_num = row["row"]

        log(f"\n[HeyGen] ── Video {idx+1}/{len(rows_to_process)} ──────────────────────────")
        log(f"[HeyGen] Title: {title}")
        log(f"[HeyGen] Scene: {scene[:80]}...")
        log(f"[HeyGen] Avatar look ID: {look_id if look_id else HEYGEN_AVATAR_ID + ' (group default)'}")
        log(f"[HeyGen] Target length: {target_minutes} minutes (~{target_minutes * WORDS_PER_MINUTE} words)")

        # Step 1: Generate script via GPT
        log(f"[HeyGen] Generating script via GPT ({OPENAI_MODEL})...")
        try:
            script = generate_script(title, scene, target_minutes)
            word_count = len(script.split())
            log(f"[HeyGen] Script generated: {word_count} words (~{word_count // WORDS_PER_MINUTE} min)")
        except Exception as e:
            log(f"[HeyGen] ERROR generating script: {e}")
            results.append({"title": title, "status": "script_error", "error": str(e)})
            continue

        # Step 2: Split into scenes
        scenes = split_script_into_scenes(script)
        log(f"[HeyGen] Script split into {len(scenes)} scene(s)")

        # Step 3: Submit to HeyGen
        log(f"[HeyGen] Submitting to HeyGen API (test_mode={test_mode})...")
        try:
            video_id = submit_video(title, scenes, look_id=look_id, test=test_mode)
            log(f"[HeyGen] ✓ Video submitted! video_id={video_id}")
        except Exception as e:
            log(f"[HeyGen] ERROR submitting video: {e}")
            results.append({"title": title, "status": "submit_error", "error": str(e)})
            continue

        # Step 4: Record in log
        video_record = {
            "video_id": video_id,
            "title": title,
            "scene": scene,
            "look_id": look_id,
            "row": row_num,
            "target_minutes": target_minutes,
            "word_count": word_count,
            "scene_count": len(scenes),
            "status": "processing",
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "video_url": "",
            "thumbnail_url": "",
        }
        existing_videos.append(video_record)
        with open(video_log, "w") as f:
            json.dump(existing_videos, f, indent=2)

        mark_row_done(row_num, done_file)
        log(f"[HeyGen] Row {row_num} marked as done. Video is processing on HeyGen servers.")
        log(f"[HeyGen] Check status at: https://app.heygen.com/videos/{video_id}")

        results.append({
            "title": title,
            "video_id": video_id,
            "status": "processing",
            "word_count": word_count,
            "scene_count": len(scenes),
        })

    log(f"\n[HeyGen] Batch complete. {len(results)} video(s) submitted.")
    return results


def update_video_statuses() -> list[dict]:
    """
    Checks status of all 'processing' videos and updates the log.
    Called periodically from the dashboard.
    """
    video_log = os.path.join(DATA_DIR, "heygen_videos.json")
    if not os.path.exists(video_log):
        return []

    try:
        videos = json.load(open(video_log))
    except Exception:
        return []

    updated = False
    for v in videos:
        if v.get("status") == "processing":
            try:
                status = get_video_status(v["video_id"])
                if status["status"] in ("completed", "failed"):
                    v["status"]        = status["status"]
                    v["video_url"]     = status.get("video_url", "")
                    v["thumbnail_url"] = status.get("thumbnail_url", "")
                    v["duration"]      = status.get("duration", 0)
                    v["completed_at"]  = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    updated = True
            except Exception as e:
                print(f"[HeyGen] Status check error for {v['video_id']}: {e}")

    if updated:
        with open(video_log, "w") as f:
            json.dump(videos, f, indent=2)

    return videos


def get_all_videos() -> list[dict]:
    """Returns all videos from the log."""
    video_log = os.path.join(DATA_DIR, "heygen_videos.json")
    if not os.path.exists(video_log):
        return []
    try:
        return json.load(open(video_log))
    except Exception:
        return []


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HeyGen Video Generator")
    parser.add_argument("--count",   type=int, default=1,  help="Number of videos to generate")
    parser.add_argument("--minutes", type=int, default=10, help="Target video length in minutes (7-13)")
    parser.add_argument("--test",    action="store_true",  help="Use HeyGen test mode (watermarked, no credits)")
    parser.add_argument("--status",  action="store_true",  help="Check and update status of processing videos")
    args = parser.parse_args()

    if args.status:
        videos = update_video_statuses()
        for v in videos:
            print(f"  [{v['status']:12s}] {v['title'][:60]} | {v.get('video_url', '')[:60]}")
    else:
        results = run_heygen_batch(
            count=args.count,
            target_minutes=max(7, min(13, args.minutes)),
            test_mode=args.test,
        )
        for r in results:
            print(f"  [{r['status']:12s}] {r['title'][:60]} | video_id={r.get('video_id', 'N/A')}")
