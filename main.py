import os
import re
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Config -- set these as ENVIRONMENT VARIABLES in Railway (Variables tab).
# Do NOT hardcode keys here.
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FAL_KEY = os.environ.get("FAL_KEY", "")
# If prompts ever fail with a "model" error, just change this env var --
# no code edit needed. Good fallbacks: claude-opus-4-8, claude-haiku-4-5-20251001
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Aspect ratio -> (width, height) used when generating images.
RATIO_DIMS = {
    "2:3": (1024, 1536),
    "3:4": (1152, 1536),
    "4:5": (1024, 1280),
    "5:7": (1097, 1536),
    "11:14": (1206, 1536),
    "A-Series": (1086, 1536),
    "Square": (1024, 1024),
    "16:9": (1536, 864),
}


@app.route("/", methods=["GET"])
def home():
    """Health check -- visit this URL in a browser to confirm keys are loaded."""
    return jsonify({
        "message": "AI Art Studio backend is running",
        "anthropic_key_set": bool(ANTHROPIC_API_KEY),
        "fal_key_set": bool(FAL_KEY),
        "model": ANTHROPIC_MODEL,
    })


@app.route("/api", methods=["POST"])
def api():
    """Single endpoint the frontend talks to. Branches on the 'action' field."""
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "generate-prompts":
        return generate_prompts(data)
    if action == "generate-images":
        return generate_images(data)
    if action == "remove-background":
        return remove_background(data)

    return jsonify({"error": f"Unknown or missing action: {action}"}), 200


# ---------------------------------------------------------------------------
# 1) Generate prompts with Claude
# ---------------------------------------------------------------------------
def generate_prompts(data):
    description = (data.get("description") or "").strip()
    ratio = (data.get("ratio") or "").strip()

    if not ANTHROPIC_API_KEY:
        return jsonify({"prompts": [], "error": "ANTHROPIC_API_KEY is not set on the server"}), 200
    if not description:
        return jsonify({"prompts": [], "error": "Missing description"}), 200

    instruction = (
        "You write prompts for an AI image generator that creates beautiful, "
        "print-ready wall art.\n\n"
        f"Customer description: {description}\n"
        f"Aspect ratio: {ratio or 'unspecified'}\n\n"
        "Write 4 distinct, vivid image-generation prompts based on the description. "
        "Each prompt should be 2-3 sentences and specify subject, style, mood, color "
        "palette, lighting, and composition. Vary the artistic style across the 4 so "
        "the customer has real choices.\n\n"
        "Return ONLY a JSON array of 4 strings and nothing else -- no markdown, no keys, "
        "no commentary. Example: [\"prompt one\", \"prompt two\", \"prompt three\", \"prompt four\"]"
    )

    try:
        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "content-type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": instruction}],
            },
            timeout=60,
        )
    except Exception as e:
        return jsonify({"prompts": [], "error": f"Request to Anthropic failed: {e}"}), 200

    if resp.status_code != 200:
        return jsonify({
            "prompts": [],
            "error": f"Anthropic API {resp.status_code}: {resp.text[:500]}"
        }), 200

    payload = resp.json()
    text = "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    ).strip()

    prompts = parse_prompts(text)
    if not prompts:
        return jsonify({
            "prompts": [],
            "error": f"Could not parse prompts from model output: {text[:300]}"
        }), 200

    return jsonify({"prompts": prompts[:4]}), 200


def parse_prompts(text):
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    # Preferred: a clean JSON array
    try:
        arr = json.loads(cleaned)
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()]
    except Exception:
        pass
    # Fallback: split lines, drop "1." / "1)" numbering and short fragments
    lines = [re.sub(r"^\s*\d+[\.\)]\s*", "", ln).strip() for ln in cleaned.split("\n")]
    return [ln for ln in lines if len(ln) > 15]


# ---------------------------------------------------------------------------
# 2) Generate images with fal.ai
# ---------------------------------------------------------------------------
def generate_images(data):
    prompts = data.get("prompts", [])
    model = (data.get("model") or "").strip()
    ratio = (data.get("ratio") or "Square").strip()

    if not FAL_KEY:
        return jsonify({"images": [], "error": "FAL_KEY is not set on the server"}), 200
    if not prompts or not model:
        return jsonify({"images": [], "error": "Missing prompts or model"}), 200

    width, height = RATIO_DIMS.get(ratio, (1024, 1024))
    images, errors = [], []

    for p in prompts:
        try:
            r = requests.post(
                f"https://fal.run/{model}",
                headers={
                    "Authorization": f"Key {FAL_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": p,
                    "image_size": {"width": width, "height": height},
                    "num_images": 1,
                },
                timeout=180,
            )
            if r.status_code != 200:
                errors.append(f"{model} {r.status_code}: {r.text[:200]}")
                continue
            body = r.json()
            for img in body.get("images", []):
                url = img.get("url") if isinstance(img, dict) else img
                if url:
                    images.append(url)
        except Exception as e:
            errors.append(str(e))

    out = {"images": images}
    if errors:
        out["error"] = " | ".join(errors[:4])
    return jsonify(out), 200


# ---------------------------------------------------------------------------
# 3) Remove background with fal.ai (Bria RMBG)
# ---------------------------------------------------------------------------
def remove_background(data):
    image_urls = data.get("image_urls", [])
    if not FAL_KEY:
        return jsonify({"images": image_urls, "error": "FAL_KEY is not set on the server"}), 200

    results, errors = [], []
    for url in image_urls:
        try:
            r = requests.post(
                "https://fal.run/fal-ai/bria/background/remove",
                headers={
                    "Authorization": f"Key {FAL_KEY}",
                    "Content-Type": "application/json",
                },
                json={"image_url": url},
                timeout=180,
            )
            if r.status_code != 200:
                errors.append(f"{r.status_code}: {r.text[:200]}")
                results.append(url)
                continue
            body = r.json()
            new_url = None
            if isinstance(body.get("image"), dict):
                new_url = body["image"].get("url")
            elif body.get("images"):
                first = body["images"][0]
                new_url = first.get("url") if isinstance(first, dict) else first
            results.append(new_url or url)
        except Exception as e:
            errors.append(str(e))
            results.append(url)

    out = {"images": results}
    if errors:
        out["error"] = " | ".join(errors[:4])
    return jsonify(out), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
