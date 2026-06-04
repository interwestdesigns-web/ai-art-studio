import os
import re
import io
import json
import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from PIL import Image

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Config -- set these as ENVIRONMENT VARIABLES in Railway (Variables tab).
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FAL_KEY = os.environ.get("FAL_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Faithful 4x upscaler. Swap to "fal-ai/clarity-upscaler" for more aggressive
# detail enhancement (it can invent detail). Overridable without code changes.
FAL_UPSCALER = os.environ.get("FAL_UPSCALER", "fal-ai/aura-sr")

# Instruction-based image editor ("change X, keep the rest"). Overridable;
# "fal-ai/flux-pro/kontext/max" is a higher-quality (pricier) option.
FAL_KONTEXT = os.environ.get("FAL_KONTEXT", "fal-ai/flux-pro/kontext")

# Safety cap on final image size (pixels) to protect server memory. 40MP covers
# up to ~16x20 / 18x24 at full 300 DPI. Raise if your Railway plan has the RAM.
MAX_PIXELS = int(os.environ.get("MAX_PIXELS", "40000000"))

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Aspect ratio -> (width, height) in PORTRAIT form (width <= height). All
# multiples of 16 (GPT Image 2) with short edge >= 1024 (Seedream).
RATIO_DIMS = {
    "2:3": (1024, 1536),
    "3:4": (1152, 1536),
    "4:5": (1024, 1280),
    "5:7": (1024, 1440),
    "11:14": (1216, 1536),
    "A-Series": (1088, 1536),
    "Square": (1024, 1024),
    "16:9": (1024, 1824),
}

ASPECT_MAP = {
    "2:3": "2:3", "3:4": "3:4", "4:5": "4:5",
    "5:7": "3:4", "11:14": "4:5", "A-Series": "2:3",
    "Square": "1:1", "16:9": "9:16",
}

MODEL_CONFIG = {
    "openai/gpt-image-2": {
        "endpoint": "openai/gpt-image-2",
        "size": "image_size",
        "extra": {"quality": "medium"},
    },
    "fal-ai/flux-2-pro": {
        "endpoint": "fal-ai/flux-2-pro",
        "size": "image_size",
        "extra": {},
    },
    "fal-ai/nano-banana-pro": {
        "endpoint": "fal-ai/nano-banana-pro",
        "size": "aspect_ratio",
        "extra": {},
    },
    "fal-ai/seedream-v4-5": {
        "endpoint": "fal-ai/bytedance/seedream/v4/text-to-image",
        "size": "image_size",
        "extra": {},
    },
    "fal-ai/recraft-v4": {
        "endpoint": "fal-ai/recraft/v4.1/pro/text-to-image",
        "size": "image_size",
        "extra": {"style": "realistic_image"},
    },
}


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "AI Art Studio backend is running",
        "anthropic_key_set": bool(ANTHROPIC_API_KEY),
        "fal_key_set": bool(FAL_KEY),
        "model": ANTHROPIC_MODEL,
        "upscaler": FAL_UPSCALER,
    })


@app.route("/api/download", methods=["GET"])
def download():
    """Fetch an image server-side and return it as a real file download."""
    url = request.args.get("url", "")
    filename = request.args.get("filename", "image.png")
    if not url:
        return jsonify({"error": "missing url"}), 400
    try:
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            return jsonify({"error": f"fetch failed {r.status_code}"}), 502
        content_type = r.headers.get("Content-Type", "image/png")
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:100] or "image.png"
        return Response(r.content, headers={
            "Content-Type": content_type,
            "Content-Disposition": f'attachment; filename="{safe}"',
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/finalize", methods=["GET"])
def finalize():
    """Take an (already AI-upscaled) image, center-crop to the print aspect,
    resize to the exact print pixels, embed 300 DPI, and return as a download."""
    url = request.args.get("url", "")
    size = request.args.get("size", "")
    filename = request.args.get("filename", "artwork.png")
    if not url:
        return jsonify({"error": "missing url"}), 400
    try:
        r = requests.get(url, timeout=90)
        if r.status_code != 200:
            return jsonify({"error": f"fetch failed {r.status_code}"}), 502

        img = Image.open(io.BytesIO(r.content))
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha else "RGB")

        target = parse_target_px(size)
        if target:
            tw, th = cap_pixels(*target)
            img = crop_to_aspect(img, tw, th)
            img = img.resize((tw, th), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", dpi=(300, 300))
        buf.seek(0)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:100] or "artwork.png"
        return Response(buf.getvalue(), headers={
            "Content-Type": "image/png",
            "Content-Disposition": f'attachment; filename="{safe}"',
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def parse_target_px(label):
    """'16x24' -> 4800x7200 (inches*300). 'A4 (8.3x11.7)' -> 2490x3510.
    'Etsy 3000x2250 px' -> 3000x2250 (already pixels)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)", label or "")
    if not m:
        return None
    w = float(m.group(1))
    h = float(m.group(2))
    if "px" in (label or "").lower():
        return int(round(w)), int(round(h))
    return int(round(w * 300)), int(round(h * 300))


def cap_pixels(w, h):
    if w * h <= MAX_PIXELS:
        return w, h
    scale = (MAX_PIXELS / float(w * h)) ** 0.5
    return max(1, int(w * scale)), max(1, int(h * scale))


def crop_to_aspect(img, tw, th):
    """Center-crop img so its aspect matches tw:th (no borders)."""
    iw, ih = img.size
    target_ar = tw / float(th)
    src_ar = iw / float(ih)
    if abs(src_ar - target_ar) < 1e-3:
        return img
    if src_ar > target_ar:           # too wide -> trim sides
        new_w = int(round(ih * target_ar))
        left = (iw - new_w) // 2
        return img.crop((left, 0, left + new_w, ih))
    new_h = int(round(iw / target_ar))  # too tall -> trim top/bottom
    top = (ih - new_h) // 2
    return img.crop((0, top, iw, top + new_h))


@app.route("/api", methods=["POST"])
def api():
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "generate-prompts":
        return generate_prompts(data)
    if action == "describe-image":
        return describe_image(data)
    if action == "generate-images":
        return generate_images(data)
    if action == "poll-images":
        return poll_images(data)
    if action == "cancel-images":
        return cancel_images(data)
    if action == "upscale-start":
        return upscale_start(data)
    if action == "edit-image":
        return edit_image(data)
    if action == "remove-background":
        return remove_background(data)

    return jsonify({"error": f"Unknown or missing action: {action}"}), 200


# ---------------------------------------------------------------------------
# 1) Generate prompts with Claude
# ---------------------------------------------------------------------------
def generate_prompts(data):
    description = (data.get("description") or "").strip()
    ratio = (data.get("ratio") or "").strip()
    orientation = (data.get("orientation") or "Portrait").strip()
    images = data.get("images", []) or []

    if not ANTHROPIC_API_KEY:
        return jsonify({"prompts": [], "error": "ANTHROPIC_API_KEY is not set on the server"}), 200
    if not description and not images:
        return jsonify({"prompts": [], "error": "Provide a description, one or more images, or both"}), 200

    if images and description:
        intro = f"Use the attached image(s) as visual inspiration, along with this description: {description}\n"
    elif images:
        intro = "Use the attached image(s) as the visual inspiration for the artwork (subject, style, mood, palette).\n"
    else:
        intro = f"Customer description: {description}\n"

    instruction = (
        "You write prompts for an AI image generator that creates beautiful, "
        "print-ready wall art.\n\n"
        + intro +
        f"Aspect ratio: {ratio or 'unspecified'} ({orientation})\n\n"
        "Write 4 distinct, vivid image-generation prompts. "
        f"Compose each for a {orientation.lower()} orientation. "
        "Each prompt should be 2-3 sentences and specify subject, style, mood, color "
        "palette, lighting, and composition. Vary the artistic style across the 4 so "
        "the customer has real choices.\n\n"
        "Return ONLY a JSON array of 4 strings and nothing else -- no markdown, no keys, "
        "no commentary. Example: [\"prompt one\", \"prompt two\", \"prompt three\", \"prompt four\"]"
    )

    # Build multimodal message content: images first, then the text instruction.
    content = []
    for im in images[:6]:
        b64 = im.get("data") or ""
        mt = im.get("media_type") or "image/jpeg"
        if b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})
    content.append({"type": "text", "text": instruction})

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
                "messages": [{"role": "user", "content": content}],
            },
            timeout=90,
        )
    except Exception as e:
        return jsonify({"prompts": [], "error": f"Request to Anthropic failed: {e}"}), 200

    if resp.status_code != 200:
        return jsonify({"prompts": [], "error": f"Anthropic API {resp.status_code}: {resp.text[:500]}"}), 200

    payload = resp.json()
    text = "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    ).strip()

    prompts = parse_prompts(text)
    if not prompts:
        return jsonify({"prompts": [], "error": f"Could not parse prompts: {text[:300]}"}), 200

    return jsonify({"prompts": prompts[:4]}), 200


def describe_image(data):
    """Look at the uploaded image(s) and return a rich description the user can
    paste/edit in the Describe box."""
    images = data.get("images", []) or []
    if not ANTHROPIC_API_KEY:
        return jsonify({"description": "", "error": "ANTHROPIC_API_KEY is not set on the server"}), 200
    if not images:
        return jsonify({"description": "", "error": "No image provided"}), 200

    instruction = (
        "Describe the attached image in vivid detail, written as an image-generation "
        "prompt for wall art. Cover the subject, art style, composition, color palette, "
        "lighting, and mood in 3-5 sentences, as one flowing paragraph I could paste "
        "straight into an image generator. Return ONLY the description text -- no "
        "preamble, no quotes, no labels."
    )

    content = []
    for im in images[:6]:
        b64 = im.get("data") or ""
        mt = im.get("media_type") or "image/jpeg"
        if b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})
    content.append({"type": "text", "text": instruction})

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
                "max_tokens": 700,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=90,
        )
    except Exception as e:
        return jsonify({"description": "", "error": f"Request to Anthropic failed: {e}"}), 200

    if resp.status_code != 200:
        return jsonify({"description": "", "error": f"Anthropic API {resp.status_code}: {resp.text[:400]}"}), 200

    payload = resp.json()
    text = "".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    ).strip()

    if not text:
        return jsonify({"description": "", "error": "No description returned"}), 200
    return jsonify({"description": text}), 200


def parse_prompts(text):
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        arr = json.loads(cleaned)
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()]
    except Exception:
        pass
    lines = [re.sub(r"^\s*\d+[\.\)]\s*", "", ln).strip() for ln in cleaned.split("\n")]
    return [ln for ln in lines if len(ln) > 15]


# ---------------------------------------------------------------------------
# fal queue helper
# ---------------------------------------------------------------------------
def _submit_job(endpoint, payload):
    """Submit one fal queue job. Returns (job_dict, error_string) -- one is None."""
    try:
        r = requests.post(
            f"https://queue.fal.run/{endpoint}",
            headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code not in (200, 201):
            return None, f"{endpoint} {r.status_code}: {r.text[:200]}"
        body = r.json()
        rid = body.get("request_id")
        if not rid:
            return None, f"No request_id: {str(body)[:200]}"
        base = f"https://queue.fal.run/{endpoint}/requests/{rid}"
        job = {
            "request_id": rid,
            "status_url": body.get("status_url") or f"{base}/status",
            "response_url": body.get("response_url") or base,
            "cancel_url": body.get("cancel_url") or f"{base}/cancel",
        }
        return job, None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# 2) Generate images with fal.ai (queue: submit fast, poll later)
# ---------------------------------------------------------------------------
def build_input(model, ratio, prompt, orientation="Portrait"):
    cfg = MODEL_CONFIG.get(model)
    payload = {"prompt": prompt, "num_images": 1}
    landscape = str(orientation).lower() == "landscape"

    if cfg is None:
        w, h = RATIO_DIMS.get(ratio, (1024, 1024))
        if landscape:
            w, h = h, w
        payload["image_size"] = {"width": w, "height": h}
        return model, payload

    if cfg["size"] == "image_size":
        w, h = RATIO_DIMS.get(ratio, (1024, 1024))
        if landscape:
            w, h = h, w
        payload["image_size"] = {"width": w, "height": h}
    elif cfg["size"] == "aspect_ratio":
        asp = ASPECT_MAP.get(ratio, "1:1")
        if landscape and ":" in asp:
            a, b = asp.split(":")
            asp = f"{b}:{a}"
        payload["aspect_ratio"] = asp

    payload.update(cfg.get("extra", {}))
    return cfg["endpoint"], payload


def generate_images(data):
    prompts = data.get("prompts", [])
    model = (data.get("model") or "").strip()
    ratio = (data.get("ratio") or "Square").strip()
    orientation = (data.get("orientation") or "Portrait").strip()

    if not FAL_KEY:
        return jsonify({"jobs": [], "error": "FAL_KEY is not set on the server"}), 200
    if not prompts or not model:
        return jsonify({"jobs": [], "error": "Missing prompts or model"}), 200

    jobs, errors = [], []
    for p in prompts:
        endpoint, payload = build_input(model, ratio, p, orientation)
        job, err = _submit_job(endpoint, payload)
        if job:
            job["prompt"] = p
            job["model"] = model
            job["ratio"] = ratio
            job["orientation"] = orientation
            jobs.append(job)
        elif err:
            errors.append(err)

    out = {"jobs": jobs}
    if errors:
        out["error"] = " | ".join(errors[:4])
    return jsonify(out), 200


def poll_images(data):
    jobs = data.get("jobs", [])
    if not FAL_KEY:
        return jsonify({"images": [], "results": [], "jobs": [], "errors": ["FAL_KEY is not set on the server"]}), 200

    images, results, pending, errors = [], [], [], []
    auth = {"Authorization": f"Key {FAL_KEY}"}

    for job in jobs:
        status_url = job.get("status_url")
        response_url = job.get("response_url")
        if not status_url or not response_url:
            errors.append(f"Job missing URLs: {str(job)[:150]}")
            continue
        try:
            s = requests.get(status_url, headers=auth, timeout=30)
            if s.status_code not in (200, 202):
                errors.append(f"Status check {s.status_code}: {s.text[:200]}")
                continue
            sbody = s.json()
            status = sbody.get("status")

            if status == "COMPLETED":
                res = requests.get(response_url, headers=auth, timeout=60)
                if res.status_code == 200:
                    rb = res.json()
                    urls = []
                    img_obj = rb.get("image")
                    if isinstance(img_obj, dict) and img_obj.get("url"):
                        urls.append(img_obj["url"])
                    elif isinstance(img_obj, str) and img_obj:
                        urls.append(img_obj)
                    for img in rb.get("images", []):
                        u = img.get("url") if isinstance(img, dict) else img
                        if u:
                            urls.append(u)
                    if urls:
                        for u in urls:
                            images.append(u)
                            results.append({
                                "url": u,
                                "prompt": job.get("prompt"),
                                "model": job.get("model"),
                                "ratio": job.get("ratio"),
                                "orientation": job.get("orientation"),
                            })
                    else:
                        errors.append(f"Completed but no image url: {str(rb)[:200]}")
                else:
                    errors.append(f"Result fetch {res.status_code}: {res.text[:200]}")
            elif status in ("IN_QUEUE", "IN_PROGRESS"):
                pending.append(job)
            else:
                errors.append(f"Status '{status}': {str(sbody)[:200]}")
        except Exception as e:
            pending.append(job)
            errors.append(str(e))

    return jsonify({"images": images, "results": results, "jobs": pending, "errors": errors}), 200


def cancel_images(data):
    jobs = data.get("jobs", [])
    if not FAL_KEY:
        return jsonify({"cancelled": 0, "errors": ["FAL_KEY is not set on the server"]}), 200

    cancelled, errors = 0, []
    auth = {"Authorization": f"Key {FAL_KEY}"}
    for job in jobs:
        cancel_url = job.get("cancel_url")
        if not cancel_url:
            continue
        try:
            r = requests.put(cancel_url, headers=auth, timeout=20)
            if r.status_code in (200, 202):
                cancelled += 1
            else:
                errors.append(f"{r.status_code}: {r.text[:150]}")
        except Exception as e:
            errors.append(str(e))

    return jsonify({"cancelled": cancelled, "errors": errors}), 200


# ---------------------------------------------------------------------------
# 3) Upscale (AI) -- submit jobs; frontend polls with poll-images
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Edit an image with an instruction (FLUX Kontext) -- frontend polls as usual
# ---------------------------------------------------------------------------
def edit_image(data):
    image_url = (data.get("image_url") or "").strip()
    instruction = (data.get("instruction") or "").strip()
    if not FAL_KEY:
        return jsonify({"jobs": [], "error": "FAL_KEY is not set on the server"}), 200
    if not image_url or not instruction:
        return jsonify({"jobs": [], "error": "Need both an image and an instruction"}), 200

    job, err = _submit_job(FAL_KONTEXT, {"prompt": instruction, "image_url": image_url})
    out = {"jobs": [job] if job else []}
    if err:
        out["error"] = err
    return jsonify(out), 200


def upscale_start(data):
    image_urls = data.get("image_urls", [])
    if not FAL_KEY:
        return jsonify({"jobs": [], "error": "FAL_KEY is not set on the server"}), 200
    if not image_urls:
        return jsonify({"jobs": [], "error": "No images to upscale"}), 200

    jobs, errors = [], []
    for url in image_urls:
        payload = {"image_url": url}
        if "clarity" in FAL_UPSCALER or "ccsr" in FAL_UPSCALER:
            payload["scale"] = 4
        job, err = _submit_job(FAL_UPSCALER, payload)
        if job:
            jobs.append(job)
        elif err:
            errors.append(err)

    out = {"jobs": jobs}
    if errors:
        out["error"] = " | ".join(errors[:4])
    return jsonify(out), 200


# ---------------------------------------------------------------------------
# 4) Remove background with fal.ai (Bria RMBG)
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
                headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
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
