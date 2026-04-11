"""
Content Factory Web App
========================
Browser-based admin panel for managing the content factory.
Runs on Railway.app — no SSH or command line needed.
"""

import os
import sys
import json
import subprocess
import threading
import hashlib
from datetime import datetime
from functools import wraps
import re
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, flash, send_from_directory)

# ─── App Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cf-secret-2026-usa-store")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
LOG_DIR   = os.path.join(BASE_DIR, "logs")
MOD_DIR   = os.path.join(BASE_DIR, "modules")

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, MOD_DIR)

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ─── Auth ─────────────────────────────────────────────────────────────────────
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "America250")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Incorrect password. Please try again."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─── Dashboard ────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return render_template("dashboard.html")

# ─── API: Stats ───────────────────────────────────────────────────────────────
@app.route("/api/stats")
@login_required
def api_stats():
    try:
        queue_file = os.path.join(DATA_DIR, "queue.json")
        history_file = os.path.join(DATA_DIR, "post_history.json")
        counts_file = os.path.join(DATA_DIR, "daily_counts.json")

        # Queue stats
        queue_data = {}
        if os.path.exists(queue_file):
            with open(queue_file) as f:
                queue_data = json.load(f)

        products = queue_data.get("products", [])
        position = queue_data.get("position", 0)
        total = len(products)
        ready = total - position

        # Post history
        history = {}
        if os.path.exists(history_file):
            with open(history_file) as f:
                history = json.load(f)
        posted_ever = len(history)

        # Daily counts
        daily_counts = {}
        if os.path.exists(counts_file):
            with open(counts_file) as f:
                data = json.load(f)
                today = datetime.now().strftime("%Y-%m-%d")
                daily_counts = data.get(today, {})

        daily_limits = {
            "pinterest": int(os.environ.get("LIMIT_PINTEREST", 25)),
            "instagram": int(os.environ.get("LIMIT_INSTAGRAM", 1)),
            "facebook":  int(os.environ.get("LIMIT_FACEBOOK", 2)),
            "tiktok":    int(os.environ.get("LIMIT_TIKTOK", 1)),
            "linkedin":  int(os.environ.get("LIMIT_LINKEDIN", 2)),
            "twitter":   int(os.environ.get("LIMIT_TWITTER", 4)),
        }

        # Queue preview
        preview = []
        for p in products[position:position+10]:
            preview.append({
                "title": p.get("title", ""),
                "price": p.get("price", 0),
                "tier": p.get("tier", 3),
            })

        # Recent activity log
        activity = []
        activity_file = os.path.join(LOG_DIR, "activity.jsonl")
        if os.path.exists(activity_file):
            with open(activity_file) as f:
                lines = f.readlines()
            for line in reversed(lines[-20:]):
                try:
                    activity.append(json.loads(line.strip()))
                except Exception:
                    pass

        return jsonify({
            "ready_to_post": ready,
            "total_products": total,
            "queue_position": position,
            "products_posted_ever": posted_ever,
            "in_cooldown": max(0, posted_ever - ready),
            "daily_counts": daily_counts,
            "daily_limits": daily_limits,
            "queue_preview": preview,
            "activity": activity[:10],
            "sprint_mode": True,
            "sprint_end": "July 4, 2026",
        })
    except Exception as e:
        return jsonify({"error": str(e)})


# ─── API: Run Batch ───────────────────────────────────────────────────────────
@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    data = request.json or {}
    mode = data.get("mode", "ecommerce")
    count = int(data.get("count", 3))
    dry_run = data.get("dry_run", False)
    product_url = data.get("product_url", "")

    runner_path = os.path.join(MOD_DIR, "runner.py")
    cmd = [sys.executable, runner_path, "--mode", mode, "--count", str(count)]
    if dry_run:
        cmd.append("--dry-run")
    if product_url:
        cmd.extend(["--product-url", product_url])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=180, cwd=BASE_DIR,
            env={**os.environ, "PYTHONPATH": f"{BASE_DIR}:{MOD_DIR}"}
        )
        output = (result.stdout + result.stderr).strip()

        # Log activity
        _log_activity({
            "timestamp": datetime.now().isoformat(),
            "action": f"run_{mode}",
            "count": count,
            "dry_run": dry_run,
            "success": result.returncode == 0,
            "summary": output[-200:] if output else ""
        })

        # Parse structured preview JSON if present
        preview_data = None
        if "__PREVIEW_JSON_START__" in output:
            try:
                start = output.index("__PREVIEW_JSON_START__") + len("__PREVIEW_JSON_START__")
                end = output.index("__PREVIEW_JSON_END__")
                json_str = output[start:end].strip()
                preview_data = json.loads(json_str)
                # Remove the JSON block from the log output
                output = output[:output.index("__PREVIEW_JSON_START__")].strip()
            except Exception as pe:
                pass  # If parsing fails, just show raw output

        return jsonify({
            "output": output,
            "success": result.returncode == 0,
            "preview": preview_data,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"output": "Timed out after 3 minutes", "success": False, "preview": None})
    except Exception as e:
        return jsonify({"output": f"Error: {str(e)}", "success": False, "preview": None})


# ─── API: Rebuild Queue ───────────────────────────────────────────────────────
@app.route("/api/rebuild_queue", methods=["POST"])
@login_required
def api_rebuild_queue():
    build_path = os.path.join(MOD_DIR, "build_queue.py")
    try:
        result = subprocess.run(
            [sys.executable, build_path],
            capture_output=True, text=True, timeout=60, cwd=BASE_DIR,
            env={**os.environ, "PYTHONPATH": f"{BASE_DIR}:{MOD_DIR}"}
        )
        output = (result.stdout + result.stderr).strip()
        _log_activity({
            "timestamp": datetime.now().isoformat(),
            "action": "rebuild_queue",
            "success": result.returncode == 0,
            "summary": output[-200:] if output else ""
        })
        return jsonify({"output": output, "success": result.returncode == 0})
    except Exception as e:
        return jsonify({"output": f"Error: {str(e)}", "success": False})


# ─── API: Get OneUp Accounts ──────────────────────────────────────────────────
@app.route("/api/get_accounts", methods=["POST"])
@login_required
def api_get_accounts():
    runner_path = os.path.join(MOD_DIR, "runner.py")
    try:
        result = subprocess.run(
            [sys.executable, runner_path, "--mode", "get_accounts"],
            capture_output=True, text=True, timeout=30, cwd=BASE_DIR,
            env={**os.environ, "PYTHONPATH": f"{BASE_DIR}:{MOD_DIR}"}
        )
        output = (result.stdout + result.stderr).strip()
        return jsonify({"output": output})
    except Exception as e:
        return jsonify({"output": f"Error: {str(e)}"})


# ─── API: Schedule Log ────────────────────────────────────────────────────────
@app.route("/api/schedule_log")
@login_required
def api_schedule_log():
    try:
        log_file = os.path.join(LOG_DIR, "scheduled_ecommerce.jsonl")
        entries = []
        if os.path.exists(log_file):
            with open(log_file) as f:
                for line in f:
                    try:
                        entries.append(json.loads(line.strip()))
                    except Exception:
                        pass
        return jsonify({"entries": entries[-50:]})
    except Exception as e:
        return jsonify({"entries": [], "error": str(e)})


# ─── API: Add AI Channel Topic ────────────────────────────────────────────────
@app.route("/api/add_topic", methods=["POST"])
@login_required
def api_add_topic():
    """Add a new AI channel topic to the local queue (no Google Sheets needed)."""
    data = request.json or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"success": False, "error": "Topic is required"})

    topic_file = os.path.join(DATA_DIR, "ai_topics.jsonl")
    entry = {
        "topic": topic,
        "pillar": data.get("pillar", "AI Development"),
        "target_client": data.get("target_client", "Business owners looking to automate with AI"),
        "pain_point": data.get("pain_point", ""),
        "proof_element": data.get("proof_element", ""),
        "cta": data.get("cta", "DM me 'AI' to learn more"),
        "status": "pending",
        "added_at": datetime.now().isoformat(),
    }
    with open(topic_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return jsonify({"success": True, "message": "Topic added to queue"})


# ─── API: Get AI Topics ───────────────────────────────────────────────────────
@app.route("/api/ai_topics")
@login_required
def api_ai_topics():
    topic_file = os.path.join(DATA_DIR, "ai_topics.jsonl")
    topics = []
    if os.path.exists(topic_file):
        with open(topic_file) as f:
            for line in f:
                try:
                    topics.append(json.loads(line.strip()))
                except Exception:
                    pass
    return jsonify({"topics": list(reversed(topics[-20:]))})


# ─── API: Config Check ────────────────────────────────────────────────────────
@app.route("/api/config_status")
@login_required
def api_config_status():
    return jsonify({
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "oneup": bool(os.environ.get("ONEUP_API_KEY")),
        "google_sheets": bool(os.environ.get("AI_CHANNEL_SHEET_ID")),
        "oneup_pinterest": bool(os.environ.get("ONEUP_PINTEREST_ID")),
        "oneup_instagram": bool(os.environ.get("ONEUP_INSTAGRAM_ID")),
        "oneup_facebook": bool(os.environ.get("ONEUP_FACEBOOK_ID")),
        "oneup_linkedin": bool(os.environ.get("ONEUP_LINKEDIN_ID")),
    })


# ─── Serve Generated Output Images ──────────────────────────────────────────
@app.route("/output/<path:filepath>")
@login_required
def serve_output(filepath):
    """Serve generated images from the output directory."""
    output_dir = os.path.join(BASE_DIR, "output")
    # Security: only allow image files
    if not filepath.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "Not allowed", 403
    return send_from_directory(output_dir, filepath)


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _log_activity(entry):
    activity_file = os.path.join(LOG_DIR, "activity.jsonl")
    with open(activity_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ─── Health Check ─────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
