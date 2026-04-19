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
import uuid
from datetime import datetime
from functools import wraps
import re
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, flash, send_from_directory)

# ─── App Setup ────────────────────────────────────────────────────────────────
from datetime import timedelta
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cf-secret-2026-usa-store")
# Keep session alive for 30 days — prevents expiry during long DALL-E runs
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_NAME"] = "cf_session"
# NOTE: SESSION_COOKIE_SECURE intentionally NOT set — Railway's proxy handles HTTPS
# Setting it to True breaks cookie delivery through Railway's load balancer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
LOG_DIR   = os.path.join(BASE_DIR, "logs")
MOD_DIR   = os.path.join(BASE_DIR, "modules")

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, MOD_DIR)

os.makedirs(DATA_DIR, exist_ok=True)

# ─── Shopify Blog module (lazy-safe import) ───────────────────────────────────
try:
    from shopify_blog import (
        shopify_configured, is_authorized, get_install_url,
        exchange_code_for_token, verify_shopify_hmac,
        fetch_products, generate_and_publish_blog,
    )
    _shopify_blog_ok = True
except ImportError as _e:
    _shopify_blog_ok = False
    def shopify_configured(): return False
    def is_authorized(): return False
    def get_install_url(): return "#"
    def exchange_code_for_token(code): return ""
    def verify_shopify_hmac(p): return False
    def fetch_products(k, limit=10): return []
    def generate_and_publish_blog(t, dry_run=False): return {"status": "error", "error": str(_e)}
os.makedirs(LOG_DIR, exist_ok=True)

# ─── Auth ─────────────────────────────────────────────────────────────────────
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "America250")

# File-based token store — persists across Railway worker processes
# Token is generated on login and embedded in the dashboard HTML
import secrets as _secrets
_TOKENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "auth_tokens.json")
os.makedirs(os.path.dirname(_TOKENS_FILE), exist_ok=True)

def _load_tokens():
    try:
        with open(_TOKENS_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def _save_token(token):
    tokens = _load_tokens()
    tokens.add(token)
    # Keep only the last 50 tokens to prevent unbounded growth
    tokens = set(list(tokens)[-50:])
    with open(_TOKENS_FILE, "w") as f:
        json.dump(list(tokens), f)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check session cookie first (page loads)
        if session.get("logged_in"):
            return f(*args, **kwargs)
        # Check X-Auth-Token header (API calls from JS) — file-based, works across workers
        token = request.headers.get("X-Auth-Token", "")
        if token and token in _load_tokens():
            return f(*args, **kwargs)
        # Not authenticated
        if request.path.startswith("/api/"):
            return jsonify({"error": "session_expired", "redirect": "/login"}), 401
        return redirect(url_for("login"))
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            session.permanent = True
            # Generate a token for JS API calls (stored in localStorage)
            token = _secrets.token_hex(24)
            _save_token(token)
            # Pass token to template via session so JS can store it
            session["api_token"] = token
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
    return render_template("dashboard.html", api_token=session.get("api_token", ""))

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
            "youtube":   int(os.environ.get("LIMIT_YOUTUBE", 1)),
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


# ─── File-based Job Store ─────────────────────────────────────────────────────
# Jobs are persisted to disk so polling works even if Railway spawns a new
# process instance between the POST /api/run and GET /api/run/status calls.
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)
_jobs_lock = threading.Lock()


def _job_path(job_id):
    return os.path.join(JOBS_DIR, f"{job_id}.json")


def _read_job(job_id):
    try:
        with open(_job_path(job_id), "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_job(job_id, data):
    with _jobs_lock:
        try:
            with open(_job_path(job_id), "w") as f:
                json.dump(data, f)
        except Exception:
            pass


def _update_job(job_id, updates):
    with _jobs_lock:
        try:
            path = _job_path(job_id)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except Exception:
                data = {}
            data.update(updates)
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass


def _run_job_worker(job_id, cmd, mode, count, dry_run):
    """Background thread: runs subprocess and streams output to job file."""
    _update_job(job_id, {"status": "running", "output": "Starting..."})

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=BASE_DIR,
            env={**os.environ, "PYTHONPATH": f"{BASE_DIR}:{MOD_DIR}"}
        )
        lines = []
        for line in proc.stdout:
            lines.append(line.rstrip())
            visible = [l for l in lines if not l.startswith("__")]
            _update_job(job_id, {"output": "\n".join(visible[-80:])})

        proc.wait()
        output = "\n".join(lines)

        # Parse structured preview JSON
        preview_data = None
        if "__PREVIEW_JSON_START__" in output:
            try:
                start = output.index("__PREVIEW_JSON_START__") + len("__PREVIEW_JSON_START__")
                end = output.index("__PREVIEW_JSON_END__")
                preview_data = json.loads(output[start:end].strip())
                output = output[:output.index("__PREVIEW_JSON_START__")].strip()
            except Exception:
                pass

        success = proc.returncode == 0
        _log_activity({
            "timestamp": datetime.now().isoformat(),
            "action": f"run_{mode}",
            "count": count,
            "dry_run": dry_run,
            "success": success,
            "summary": output[-200:] if output else ""
        })

        _update_job(job_id, {
            "status": "done",
            "output": output,
            "preview": preview_data,
            "success": success,
            "finished_at": datetime.now().isoformat(),
        })

    except Exception as e:
        _update_job(job_id, {
            "status": "error",
            "output": f"Job error: {str(e)}",
            "preview": None,
            "success": False,
            "finished_at": datetime.now().isoformat(),
        })


# ─── API: Run Batch (async) ───────────────────────────────────────────────────
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

    job_id = str(uuid.uuid4())[:8]
    _write_job(job_id, {
        "status": "queued",
        "output": "Queued...",
        "preview": None,
        "success": None,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "mode": mode,
        "count": count,
        "dry_run": dry_run,
    })

    t = threading.Thread(target=_run_job_worker,
                         args=(job_id, cmd, mode, count, dry_run),
                         daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/run/status/<job_id>")
@login_required
def api_run_status(job_id):
    """Poll job status — reads from disk so it works across Railway process instances."""
    job = _read_job(job_id)
    if not job:
        return jsonify({"error": "Job not found", "job_id": job_id}), 404
    return jsonify({
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "output": job.get("output", ""),
        "preview": job.get("preview"),
        "success": job.get("success"),
        "finished_at": job.get("finished_at"),
    })


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


# ─── API: Pinterest Board Manager ───────────────────────────────────────────────────────
@app.route("/api/boards", methods=["GET"])
@login_required
def api_boards():
    """Return cached board list and current board config."""
    try:
        sys.path.insert(0, MOD_DIR)
        from board_manager import load_board_config, get_all_boards
        config = load_board_config()
        return jsonify({
            "boards": config.get("boards", []),
            "tier_map": config.get("tier_map", {}),
            "category_map": config.get("category_map", {}),
            "default_board_id": config.get("default_board_id", ""),
            "repin_boards": config.get("repin_boards", []),
            "last_fetched": config.get("last_fetched"),
        })
    except Exception as e:
        return jsonify({"error": str(e), "boards": []})


@app.route("/api/boards/refresh", methods=["POST"])
@login_required
def api_boards_refresh():
    """Fetch boards from Pinterest API and refresh cache."""
    try:
        sys.path.insert(0, MOD_DIR)
        from board_manager import refresh_boards
        ok, msg, boards = refresh_boards()
        return jsonify({"success": ok, "message": msg, "boards": boards})
    except Exception as e:
        return jsonify({"success": False, "message": str(e), "boards": []})


@app.route("/api/boards/save", methods=["POST"])
@login_required
def api_boards_save():
    """Save tier_map, category_map, default_board_id, repin_boards config."""
    try:
        sys.path.insert(0, MOD_DIR)
        from board_manager import (
            update_tier_map, update_category_map,
            update_default_board, update_repin_boards
        )
        data = request.json or {}
        if "tier_map" in data:
            update_tier_map(data["tier_map"])
        if "category_map" in data:
            update_category_map(data["category_map"])
        if "default_board_id" in data:
            update_default_board(data["default_board_id"])
        if "repin_boards" in data:
            update_repin_boards(data["repin_boards"])
        return jsonify({"success": True, "message": "Board config saved"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


# ─── API: Pinterest Manual Board Add/Delete ───────────────────────────────────
@app.route("/api/boards/add", methods=["POST"])
@login_required
def api_boards_add():
    """Manually add a board by name and ID (no Pinterest API needed)."""
    try:
        sys.path.insert(0, MOD_DIR)
        from board_manager import load_board_config, save_board_config
        data = request.json or {}
        board_id   = (data.get("id") or "").strip()
        board_name = (data.get("name") or "").strip()
        if not board_id or not board_name:
            return jsonify({"success": False, "message": "Both board ID and board name are required"})
        config = load_board_config()
        boards = config.get("boards", [])
        # Check for duplicate
        if any(b["id"] == board_id for b in boards):
            return jsonify({"success": False, "message": f"Board ID '{board_id}' already exists"})
        boards.append({
            "id": board_id,
            "name": board_name,
            "description": data.get("description", ""),
            "pin_count": 0,
            "privacy": "PUBLIC",
            "owner": "",
            "manual": True,
        })
        config["boards"] = boards
        if not config.get("default_board_id"):
            config["default_board_id"] = board_id
        save_board_config(config)
        return jsonify({"success": True, "message": f"Board '{board_name}' added", "boards": boards})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route("/api/boards/delete", methods=["POST"])
@login_required
def api_boards_delete():
    """Remove a manually-added board by ID."""
    try:
        sys.path.insert(0, MOD_DIR)
        from board_manager import load_board_config, save_board_config
        data = request.json or {}
        board_id = (data.get("id") or "").strip()
        if not board_id:
            return jsonify({"success": False, "message": "board ID required"})
        config = load_board_config()
        before = len(config.get("boards", []))
        config["boards"] = [b for b in config.get("boards", []) if b["id"] != board_id]
        # Clean up references
        config["repin_boards"] = [b for b in config.get("repin_boards", []) if b != board_id]
        if config.get("default_board_id") == board_id:
            config["default_board_id"] = config["boards"][0]["id"] if config["boards"] else ""
        for k, v in list(config.get("tier_map", {}).items()):
            if v == board_id:
                del config["tier_map"][k]
        for k, v in list(config.get("category_map", {}).items()):
            if v == board_id:
                del config["category_map"][k]
        save_board_config(config)
        removed = before - len(config["boards"])
        return jsonify({"success": True, "message": f"Removed {removed} board(s)", "boards": config["boards"]})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# ─── API: Pinterest Repinner ───────────────────────────────────────────────────────────────
@app.route("/api/repin", methods=["POST"])
@login_required
def api_repin():
    """Run a Pinterest repinning session."""
    data = request.json or {}
    dry_run = data.get("dry_run", True)

    runner_path = os.path.join(MOD_DIR, "runner.py")
    cmd = [sys.executable, runner_path, "--mode", "repin"]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=300, cwd=BASE_DIR,
            env={**os.environ, "PYTHONPATH": f"{BASE_DIR}:{MOD_DIR}"}
        )
        output = (result.stdout + result.stderr).strip()

        # Parse structured repin JSON if present
        repin_data = None
        if "__REPIN_JSON_START__" in output:
            try:
                start = output.index("__REPIN_JSON_START__") + len("__REPIN_JSON_START__")
                end = output.index("__REPIN_JSON_END__")
                repin_data = json.loads(output[start:end].strip())
                output = output[:output.index("__REPIN_JSON_START__")].strip()
            except Exception:
                pass

        _log_activity({
            "timestamp": datetime.now().isoformat(),
            "action": "repin",
            "dry_run": dry_run,
            "success": result.returncode == 0,
            "summary": output[-200:] if output else ""
        })

        return jsonify({
            "output": output,
            "success": result.returncode == 0,
            "repin_data": repin_data,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"output": "Repin session timed out after 5 minutes", "success": False})
    except Exception as e:
        return jsonify({"output": f"Error: {str(e)}", "success": False})


# ─── API: Repin Log ───────────────────────────────────────────────────────────────────────
@app.route("/api/repin_log")
@login_required
def api_repin_log():
    log_file = os.path.join(DATA_DIR, "repin_log.json")
    entries = []
    if os.path.exists(log_file):
        with open(log_file) as f:
            for line in f:
                try:
                    entries.append(json.loads(line.strip()))
                except Exception:
                    pass
    return jsonify({"entries": list(reversed(entries[-50:]))})



# ─── API: Instagram Warmup ────────────────────────────────────────────────────
@app.route("/api/warmup/instagram", methods=["POST"])
@login_required
def api_ig_warmup():
    """Run an Instagram warmup session (like, view, follow)."""
    data = request.json or {}
    dry_run = data.get("dry_run", True)
    runner_path = os.path.join(MOD_DIR, "runner.py")
    cmd = [sys.executable, runner_path, "--mode", "ig_warmup"]
    if dry_run:
        cmd.append("--dry-run")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=300, cwd=BASE_DIR,
            env={**os.environ, "PYTHONPATH": f"{BASE_DIR}:{MOD_DIR}"}
        )
        output = result.stdout + result.stderr
        try:
            lines = [l for l in result.stdout.strip().split("\n") if l.startswith("{")]
            result_data = json.loads(lines[-1]) if lines else {}
        except Exception:
            result_data = {}
        return jsonify({"success": result.returncode == 0, "output": output, "warmup_data": result_data})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "output": "Timeout after 5 minutes"})
    except Exception as e:
        return jsonify({"success": False, "output": str(e)})

@app.route("/api/warmup/instagram/log")
@login_required
def api_ig_warmup_log():
    """Return recent Instagram warmup log entries."""
    log_file = os.path.join(LOG_DIR, "ig_warmup.jsonl")
    entries = []
    if os.path.exists(log_file):
        with open(log_file) as f:
            for line in f:
                try:
                    entries.append(json.loads(line.strip()))
                except Exception:
                    pass
    return jsonify({"entries": list(reversed(entries[-50:]))})

# ─── API: TikTok Warmup ───────────────────────────────────────────────────────
@app.route("/api/warmup/tiktok", methods=["POST"])
@login_required
def api_tiktok_warmup():
    """Run a TikTok warmup session (like, view, follow)."""
    data = request.json or {}
    dry_run = data.get("dry_run", True)
    runner_path = os.path.join(MOD_DIR, "runner.py")
    cmd = [sys.executable, runner_path, "--mode", "tiktok_warmup"]
    if dry_run:
        cmd.append("--dry-run")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=300, cwd=BASE_DIR,
            env={**os.environ, "PYTHONPATH": f"{BASE_DIR}:{MOD_DIR}"}
        )
        output = result.stdout + result.stderr
        try:
            lines = [l for l in result.stdout.strip().split("\n") if l.startswith("{")]
            result_data = json.loads(lines[-1]) if lines else {}
        except Exception:
            result_data = {}
        return jsonify({"success": result.returncode == 0, "output": output, "warmup_data": result_data})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "output": "Timeout after 5 minutes"})
    except Exception as e:
        return jsonify({"success": False, "output": str(e)})

@app.route("/api/warmup/tiktok/log")
@login_required
def api_tiktok_warmup_log():
    """Return recent TikTok warmup log entries."""
    log_file = os.path.join(LOG_DIR, "tiktok_warmup.jsonl")
    entries = []
    if os.path.exists(log_file):
        with open(log_file) as f:
            for line in f:
                try:
                    entries.append(json.loads(line.strip()))
                except Exception:
                    pass
    return jsonify({"entries": list(reversed(entries[-50:]))})

# ─── API: Config Check ────────────────────────────────────────────────────────────────
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
        "oneup_tiktok": bool(os.environ.get("ONEUP_TIKTOK_ID")),
        "oneup_youtube": bool(os.environ.get("ONEUP_YOUTUBE_ID")),
        "higgsfield": bool(os.environ.get("HIGGSFIELD_API_KEY")),
        "heygen_usa_store": bool(os.environ.get("HEYGEN_API_KEY")) and os.environ.get("HEYGEN_USA_STORE_ENABLED", "true").lower() == "true",
        "pinterest_token": bool(os.environ.get("PINTEREST_ACCESS_TOKEN")),
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


# ─── API: HeyGen Video Generator ────────────────────────────────────────────────────
@app.route("/api/heygen/run", methods=["POST"])
@login_required
def api_heygen_run():
    """Start a HeyGen video generation batch job (async)."""
    body = request.get_json(force=True, silent=True) or {}
    count          = max(1, min(10, int(body.get("count", 1))))
    target_minutes = max(7, min(13, int(body.get("minutes", 10))))
    test_mode      = bool(body.get("test", False))

    job_id = str(uuid.uuid4())[:8]
    _write_job(job_id, {"status": "queued", "output": "Starting HeyGen batch...", "result": None,
                        "started_at": datetime.now().isoformat()})

    def run_job():
        lines = []
        def cb(msg):
            lines.append(msg)
            _update_job(job_id, {"status": "running", "output": "\n".join(lines)})

        try:
            from modules.heygen_video import run_heygen_batch
            results = run_heygen_batch(
                count=count,
                target_minutes=target_minutes,
                test_mode=test_mode,
                progress_cb=cb,
            )
            _update_job(job_id, {"status": "done", "output": "\n".join(lines),
                                  "result": results, "finished_at": datetime.now().isoformat()})
        except Exception as e:
            lines.append(f"[ERROR] {e}")
            import traceback
            lines.append(traceback.format_exc())
            _update_job(job_id, {"status": "error", "output": "\n".join(lines),
                                  "result": None, "finished_at": datetime.now().isoformat()})

    threading.Thread(target=run_job, daemon=True).start()
    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/heygen/videos")
@login_required
def api_heygen_videos():
    """Return all HeyGen videos from the log, with refreshed statuses."""
    try:
        from modules.heygen_video import update_video_statuses
        videos = update_video_statuses()
    except Exception as e:
        return jsonify({"error": str(e), "videos": []})
    return jsonify({"videos": videos})


@app.route("/api/heygen/status/<video_id>")
@login_required
def api_heygen_video_status(video_id):
    """Check status of a single HeyGen video."""
    try:
        from modules.heygen_video import get_video_status
        status = get_video_status(video_id)
    except Exception as e:
        return jsonify({"error": str(e)})
    return jsonify(status)


@app.route("/api/heygen/sheet_preview")
@login_required
def api_heygen_sheet_preview():
    """Return the first 20 unprocessed rows from the Google Sheet."""
    try:
        from modules.heygen_video import get_unprocessed_rows
        from config import HEYGEN_SHEET_ID, DATA_DIR as cfg_data
        import os as _os
        done_file = _os.path.join(cfg_data, "heygen_done_rows.json")
        rows = get_unprocessed_rows(HEYGEN_SHEET_ID, done_file)[:20]
    except Exception as e:
        return jsonify({"error": str(e), "rows": []})
    return jsonify({"rows": rows, "total": len(rows)})




# ─── Shopify OAuth ────────────────────────────────────────────────────────────
@app.route("/shopify/install")
@login_required
def shopify_install():
    """Redirect user to Shopify OAuth approval page."""
    url = get_install_url()
    return redirect(url)

@app.route("/shopify/callback")
def shopify_callback():
    """Handle Shopify OAuth callback — exchange code for token."""
    params = dict(request.args)
    code = params.get("code", "")
    if not code:
        return "Missing OAuth code. Please try connecting again.", 400
    try:
        token = exchange_code_for_token(code)
        if token:
            return redirect("/?shopify=connected#blog")
        return "OAuth failed — no token returned.", 400
    except Exception as e:
        return f"OAuth error: {e}", 500

# ─── Shopify Blog Generator ──────────────────────────────────────────────────────
@app.route("/api/blog/generate", methods=["POST"])
@login_required
def api_blog_generate():
    data = request.json or {}
    topic = data.get("topic", "").strip()
    dry_run = data.get("dry_run", False)
    if not topic:
        return jsonify({"error": "Topic is required"}), 400
    if not shopify_configured():
        return jsonify({"error": "SHOPIFY_API_KEY or SHOPIFY_STORE_DOMAIN not set in Railway Variables."}), 400

    def stream():
        import sys
        import io
        # Capture stdout for streaming
        result = generate_and_publish_blog(topic, dry_run=dry_run)
        yield json.dumps(result)

    try:
        result = generate_and_publish_blog(topic, dry_run=dry_run)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/blog/products", methods=["GET"])
@login_required
def api_blog_products():
    keyword = request.args.get("keyword", "patriotic")
    try:
        products = fetch_products(keyword, limit=12)
        return jsonify({"products": products})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/blog/status")
@login_required
def api_blog_status():
    authorized = is_authorized()
    return jsonify({
        "shopify_configured": shopify_configured(),
        "shopify_authorized": authorized,
        "shopify_domain": os.environ.get("SHOPIFY_STORE_DOMAIN", ""),
        "install_url": get_install_url() if not authorized else None,
    })

# ─── Health Check ────────────────────────────────────────────────────────────────────

@app.route("/api/manual-post", methods=["POST"])
@login_required
def api_manual_post():
    """Generate images + copy-paste content pack for a single product URL."""
    import sys, os
    MOD_DIR = os.path.join(os.path.dirname(__file__), "modules")
    if MOD_DIR not in sys.path:
        sys.path.insert(0, MOD_DIR)
    from shopify_connector import get_product_by_url, extract_product_data
    from content_engine import generate_ecommerce_content_pack
    from image_generator import generate_manual_post_images

    data = request.get_json() or {}
    product_url = data.get("product_url", "").strip()
    if not product_url:
        return jsonify({"error": "product_url is required"}), 400

    try:
        raw = get_product_by_url(product_url)
        if not raw:
            return jsonify({
                "error": (
                    "Could not fetch product data from that URL. "
                    "Make sure it is a valid OfficialUSAStore.com product page URL "
                    "(e.g. https://www.officialusastore.com/products/product-handle). "
                    "URLs with /collections/ in the path are also supported."
                )
            }), 404
        product = extract_product_data(raw)
        if not product:
            return jsonify({"error": "Could not parse product data from Shopify response"}), 500

        # Generate content pack
        content_pack = generate_ecommerce_content_pack(product)
        if "error" in content_pack:
            return jsonify({"error": content_pack["error"]}), 500

        # Generate images using actual product photo
        handle = product.get("handle", "manual")
        out_dir = os.path.join(
            os.path.dirname(__file__), "output", "manual", handle
        )
        image_paths = generate_manual_post_images(product, out_dir, content_pack=content_pack)

        # Convert absolute paths to relative for serving
        base = os.path.join(os.path.dirname(__file__), "output")
        rel_images = {}
        for platform, paths in image_paths.items():
            rel_images[platform] = [
                os.path.relpath(p, base) for p in paths
            ]

        return jsonify({
            "product": {
                "title": product.get("title"),
                "url": product.get("url"),
                "primary_image": product.get("primary_image"),
            },
            "content": content_pack,
            "images": rel_images,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/filler-post", methods=["POST"])
@login_required
def api_filler_post():
    """Generate engagement filler content (no product links) for a theme keyword."""
    import sys, os
    MOD_DIR = os.path.join(os.path.dirname(__file__), "modules")
    if MOD_DIR not in sys.path:
        sys.path.insert(0, MOD_DIR)
    from content_filler import generate_filler_content, generate_filler_images

    data = request.get_json() or {}
    theme = (data.get("theme") or "").strip()
    if not theme:
        return jsonify({"error": "theme is required"}), 400
    if len(theme) > 120:
        return jsonify({"error": "theme is too long (max 120 chars)"}), 400

    try:
        # Generate GPT content pack
        content = generate_filler_content(theme)
        if "error" in content:
            return jsonify({"error": content["error"]}), 500

        # Generate images
        import re
        safe_theme = re.sub(r'[^a-z0-9]+', '_', theme.lower()).strip('_')[:40]
        out_dir = os.path.join(
            os.path.dirname(__file__), "output", "filler", safe_theme
        )
        image_paths = generate_filler_images(theme, content, out_dir)

        # Convert absolute paths to relative web paths
        base = os.path.join(os.path.dirname(__file__), "output")
        rel_images = {}
        for platform, paths in image_paths.items():
            rel_images[platform] = [
                os.path.relpath(p, base) for p in paths
            ]

        return jsonify({
            "theme": theme,
            "content": content,
            "images": rel_images,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
