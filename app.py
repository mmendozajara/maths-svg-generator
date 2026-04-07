"""Web interface for the Maths SVG Image Generator.

Run locally:
    python app.py

Share via ngrok:
    python app.py --share

Opens at http://localhost:5000 (or a public ngrok URL with --share)
"""

import io
import json
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file

from config import ImageGenConfig
from svg_generator import generate_svg
from jsx_embed import (
    format_draft_image,
    format_draft_image_url,
    parse_jsx_placeholders,
    apply_jsx_replacements,
)
from upload_imgur import upload_svg

try:
    from llm_client import LLMClient
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from utils.llm_client import LLMClient

app = Flask(__name__, template_folder="templates", static_folder="output")
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ---------------------------------------------------------------------------
# Globals — initialized on startup
# ---------------------------------------------------------------------------
config: ImageGenConfig = None
client: LLMClient = None
_upload_results = {}  # upload_id -> {"status": "pending"|"done"|"error", ...}
_upload_lock = threading.Lock()


def _init():
    global config, client
    if config is not None:
        return  # already initialized
    config = ImageGenConfig()
    if not config.api_key:
        print("ERROR: OPENROUTER_API_KEY not set in .env")
        sys.exit(1)
    client = LLMClient(api_key=config.api_key, max_retries=config.max_retries)
    config.ensure_output_dir()
    print(f"Model: {config.model}")
    print(f"Upload: {'imgbb' if config.imgbb_api_key else 'imgur' if config.imgur_client_id else 'NONE (set IMGBB_API_KEY)'}")


# Initialize on import so gunicorn workers pick it up
_init()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Generate a single SVG diagram."""
    data = request.get_json()
    desc = data.get("description", "").strip()
    if not desc:
        return jsonify({"error": "Description is required"}), 400

    w = data.get("width", config.default_width)
    h = data.get("height", config.default_height)
    do_upload = data.get("upload", True)
    name = data.get("name", "")
    fix_instructions = data.get("fix_instructions", "")

    start = time.time()
    try:
        svg_string, metadata = generate_svg(
            client, desc, config, w, h,
            initial_fix_instructions=fix_instructions,
        )
    except (RuntimeError, ValueError) as e:
        return jsonify({"error": str(e)}), 500
    elapsed = time.time() - start

    # Save SVG locally
    if name:
        safe = _sanitize(name)
    else:
        safe = f"{_sanitize(metadata.get('type', 'diagram'))}_{int(time.time())}"
    filename = f"{safe}.svg"
    (config.output_dir / filename).write_text(svg_string, encoding="utf-8")

    # Extract cached PNG bytes (if available) to avoid re-rendering for upload
    cached_png = metadata.pop("_png_bytes", None)

    result = {
        "svg": svg_string,
        "metadata": metadata,
        "filename": filename,
        "elapsed": round(elapsed, 1),
    }

    # Return SVG immediately; upload in background if requested
    result["draft_image"] = format_draft_image(svg_string, metadata, w, h)

    if do_upload and config.has_upload_key:
        upload_id = uuid.uuid4().hex[:8]
        result["upload_id"] = upload_id
        with _upload_lock:
            _upload_results[upload_id] = {"status": "pending"}

        def _bg_upload(uid, svg, width, height, meta, png):
            try:
                ur = upload_svg(
                    svg_content=svg, width=width, height=height,
                    title=meta.get("title", ""),
                    description=meta.get("accessibility_description", ""),
                    png_bytes=png,
                )
                with _upload_lock:
                    _upload_results[uid] = {
                        "status": "done",
                        "hosted_url": ur["url"],
                        "draft_image": format_draft_image_url(ur["url"], meta, width, height),
                    }
            except Exception as e:
                with _upload_lock:
                    _upload_results[uid] = {"status": "error", "error": str(e)}

        threading.Thread(
            target=_bg_upload,
            args=(upload_id, svg_string, w, h, metadata, cached_png),
            daemon=True,
        ).start()

    return jsonify(result)


@app.route("/api/upload-status/<upload_id>")
def api_upload_status(upload_id):
    """Poll for background upload result."""
    with _upload_lock:
        entry = _upload_results.get(upload_id)
        if entry and entry["status"] != "pending":
            _upload_results.pop(upload_id, None)
    if entry is None:
        return jsonify({"status": "unknown"}), 404
    return jsonify(entry)


@app.route("/api/batch", methods=["POST"])
def api_batch():
    """Batch generate multiple SVG diagrams."""
    data = request.get_json()
    items = data.get("items", [])
    do_upload = data.get("upload", True)

    if not items:
        return jsonify({"error": "No items provided"}), 400

    results = []
    total_start = time.time()

    for i, item in enumerate(items):
        desc = item.get("description", "").strip()
        if not desc:
            results.append({"index": i, "error": "Empty description", "status": "skipped"})
            continue

        w = item.get("width", config.default_width)
        h = item.get("height", config.default_height)
        name = item.get("name", "")

        start = time.time()
        try:
            svg_string, metadata = generate_svg(client, desc, config, w, h)
        except (RuntimeError, ValueError) as e:
            results.append({"index": i, "description": desc, "error": str(e), "status": "failed"})
            continue
        elapsed = time.time() - start

        if name:
            safe = _sanitize(name)
        else:
            safe = f"{_sanitize(metadata.get('type', 'diagram'))}_{int(time.time())}_{i}"
        filename = f"{safe}.svg"
        (config.output_dir / filename).write_text(svg_string, encoding="utf-8")

        # Extract cached PNG bytes to avoid re-rendering for upload
        cached_png = metadata.pop("_png_bytes", None)

        entry = {
            "index": i,
            "description": desc,
            "svg": svg_string,
            "metadata": metadata,
            "filename": filename,
            "elapsed": round(elapsed, 1),
            "status": "ok",
        }

        if do_upload and config.has_upload_key:
            try:
                upload_result = upload_svg(
                    svg_content=svg_string,
                    width=w,
                    height=h,
                    title=metadata.get("title", "Maths Diagram"),
                    description=metadata.get("accessibility_description", ""),
                    png_bytes=cached_png,
                )
                entry["hosted_url"] = upload_result["url"]
                entry["draft_image"] = format_draft_image_url(
                    upload_result["url"], metadata, w, h
                )
            except Exception as e:
                entry["upload_error"] = str(e)
                entry["draft_image"] = format_draft_image(svg_string, metadata, w, h)
        else:
            entry["draft_image"] = format_draft_image(svg_string, metadata, w, h)

        results.append(entry)

    total_elapsed = time.time() - total_start
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    uploaded_count = sum(1 for r in results if r.get("hosted_url"))

    summary = {
        "total": len(items),
        "generated": ok_count,
        "uploaded": uploaded_count,
        "failed": len(items) - ok_count,
        "total_time": round(total_elapsed, 1),
    }

    return jsonify({"results": results, "summary": summary})


@app.route("/api/batch/download", methods=["POST"])
def api_batch_download():
    """Download batch results as a ZIP of SVG files."""
    data = request.get_json()
    filenames = data.get("filenames", [])

    if not filenames:
        return jsonify({"error": "No filenames provided"}), 400

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in filenames:
            safe = Path(fname).name  # prevent path traversal
            fpath = config.output_dir / safe
            if fpath.exists() and fpath.suffix == ".svg":
                zf.writestr(safe, fpath.read_text(encoding="utf-8"))

    buf.seek(0)
    timestamp = int(time.time())
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"maths_svgs_{timestamp}.zip",
    )


@app.route("/api/jsx/parse", methods=["POST"])
def api_jsx_parse():
    """Parse a JSX file and return placeholder images that need generation."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    content = file.read().decode("utf-8")
    placeholders = parse_jsx_placeholders(content)

    return jsonify(
        {
            "filename": file.filename,
            "total_placeholders": len(placeholders),
            "placeholders": placeholders,
            "content": content,
        }
    )


@app.route("/api/jsx/build", methods=["POST"])
def api_jsx_build():
    """Build modified JSX with generated DraftImage replacements."""
    data = request.get_json()
    original = data.get("original_content", "")
    replacements = data.get("replacements", [])
    filename = data.get("filename", "output.jsx")

    if not original:
        return jsonify({"error": "No original content provided"}), 400
    if not replacements:
        return jsonify({"error": "No replacements provided"}), 400

    modified = apply_jsx_replacements(original, replacements)

    # Return as downloadable file
    buf = io.BytesIO(modified.encode("utf-8"))
    buf.seek(0)

    # Generate output filename
    base = Path(filename).stem
    out_name = f"{base}_with_images.jsx"

    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name=out_name,
    )


def _sanitize(name: str) -> str:
    safe = name.lower().strip().replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c in "_-")
    return safe[:80] or "diagram"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Maths SVG Image Generator")
    parser.add_argument(
        "--share", action="store_true",
        help="Share via ngrok (requires NGROK_AUTH_TOKEN in .env)",
    )
    parser.add_argument(
        "--port", type=int, default=5000,
        help="Port to run on (default: 5000)",
    )
    args = parser.parse_args()

    _init()

    port = int(os.getenv("PORT", args.port))

    if args.share:
        ngrok_token = os.getenv("NGROK_AUTH_TOKEN", "")
        if not ngrok_token or ngrok_token == "paste-your-token-here":
            print("\nERROR: NGROK_AUTH_TOKEN not set in .env")
            print("  1. Sign up at https://dashboard.ngrok.com/signup")
            print("  2. Copy your auth token from https://dashboard.ngrok.com/get-started/your-authtoken")
            print("  3. Add to .env:  NGROK_AUTH_TOKEN=your-token-here")
            sys.exit(1)

        try:
            from pyngrok import ngrok, conf
            conf.get_default().auth_token = ngrok_token
            tunnel = ngrok.connect(port)
            public_url = tunnel.public_url

            print("\n  Maths SVG Image Generator")
            print(f"  Local:  http://localhost:{port}")
            print(f"  Public: {public_url}")
            print(f"\n  Share this URL with others: {public_url}")
            print("  Press Ctrl+C to stop\n")
        except ImportError:
            print("\nERROR: pyngrok not installed. Run: python -m pip install pyngrok")
            sys.exit(1)
        except Exception as e:
            print(f"\nERROR: ngrok failed to start: {e}")
            sys.exit(1)
    else:
        print("\n  Maths SVG Image Generator")
        print(f"  http://localhost:{port}")
        print(f"  (use --share to get a public URL)\n")

    app.run(debug=False, port=port)
