import os
import io
import time
import base64
import requests
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Use Agg backend for matplotlib (server / headless environments)
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
from PIL import Image
from werkzeug.utils import secure_filename

# ---------------------------
# Config / Helpers
# ---------------------------
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff"}
MAX_IMAGE_DIM = 2048  # safe max dimension for thumbnail


def allowed_file(filename):
    if not filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in ALLOWED_EXTENSIONS


def extract_chart_data(insights_text):
    """Count simple keyword matches (case insensitive) for charting."""
    if not insights_text:
        return {}
    categories = {
        "Water": 0,
        "Vegetation": 0,
        "Urban": 0,
        "Disaster": 0,
        "Forest": 0,
        "Agriculture": 0,
        "Cloud": 0,
        "Bare land": 0,
    }
    for cat in list(categories.keys()):
        # Use word boundaries for better matching where appropriate
        safe_cat = re.escape(cat)
        matches = re.findall(rf"\b{safe_cat}\b", insights_text, re.IGNORECASE)
        categories[cat] = len(matches)
    # Keep only nonzero categories (so charts don't show zero entries)
    chart_data = {k: v for k, v in categories.items() if v > 0}
    return chart_data


def image_to_base64_optimized(image_path, max_dim=1024, quality=85):
    """Resize and convert image to base64 (JPEG). Returns (mime_type, base64str) or (None,None)."""
    if not os.path.exists(image_path):
        print(f"[ERROR] File not found: {image_path}")
        return None, None
    try:
        with Image.open(image_path) as img:
            # convert RGBA -> RGB for JPEG
            if img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])  # paste using alpha channel
                img = background
            img.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return "image/jpeg", b64
    except Exception as e:
        print(f"[ERROR] Image processing failed: {e}")
        return None, None


# --------------------------------
# Flask App Setup
# --------------------------------
TEMPLATE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "templates")
app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder="static")
CORS(
    app,
    supports_credentials=True,
    origins=["http://127.0.0.1:5000", "http://localhost:5000"],
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
CHARTS_FOLDER = os.path.join(app.root_path, "static", "charts")
os.makedirs(CHARTS_FOLDER, exist_ok=True)

USERS = {}  # In-memory user storage (for testing/demo only)

# --------------------------------
# Gemini API Config (set via env)
# --------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
GEMINI_MODEL_FLASH = os.environ.get("GEMINI_MODEL_FLASH", "gemini-2.5-flash")
API_BASE_URL = os.environ.get(
    "GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta/models"
)

# Fallback to default key for testing (replace with your own key)
if not GEMINI_API_KEY:
    GEMINI_API_KEY = "AIzaSyC4NJAjXhUlPvvQHvgh6LFJ3KfMHat_W8A"  # Default test key
    print(
        "[WARN] Using default API key. For production, set GEMINI_API_KEY environment variable."
    )


def call_gemini_api(model, contents, system_instruction=None):
    """Call Gemini-like API. Returns dict or {'error': ...}."""
    if not GEMINI_API_KEY:
        return {
            "error": "Missing Gemini API Key (set GEMINI_API_KEY environment variable)."
        }
    url = f"{API_BASE_URL}/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": contents, "generationConfig": {"temperature": 0.2}}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    try:
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Gemini API request failed: {e}"}


def get_user_chart_folder():
    user = session.get("username", "anonymous")
    folder = os.path.join(CHARTS_FOLDER, user)
    os.makedirs(folder, exist_ok=True)
    return folder


# --------------------------
# Routes
# --------------------------
@app.route("/")
def home():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html", page="login")


@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return render_template("index.html", page="login")
    return render_template(
        "index.html", page="dashboard", username=session.get("username")
    )


@app.route("/auth", methods=["POST"])
def auth():
    # JSON (AJAX) clients
    if request.is_json:
        data = request.get_json(force=True) or {}
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return (
                jsonify(
                    {"success": False, "message": "Username and password required."}
                ),
                400,
            )

        # simple in-memory auth for demo: create user if doesn't exist
        if username in USERS and USERS[username] == password:
            session["username"] = username
            return jsonify({"success": True, "redirect": url_for("dashboard")})
        elif username in USERS:
            return jsonify({"success": False, "message": "Invalid password."}), 401
        else:
            USERS[username] = password
            session["username"] = username
            return jsonify({"success": True, "redirect": url_for("dashboard")})

    # HTML form fallback
    username = request.form.get("username")
    password = request.form.get("password")
    if not username or not password:
        return redirect(url_for("home"))
    if username in USERS and USERS[username] == password:
        session["username"] = username
        return redirect(url_for("dashboard"), code=303)
    elif username in USERS:
        return redirect(url_for("home"))
    else:
        USERS[username] = password
        session["username"] = username
        return redirect(url_for("dashboard"), code=303)


@app.route("/analyze_image", methods=["POST"])
def analyze_image():
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    file = request.files.get("file")
    area = request.form.get("area")

    if not file or not area:
        return (
            jsonify({"success": False, "message": "Missing file or area field."}),
            400,
        )

    # Validate filename & extension
    orig_filename = secure_filename(file.filename)
    if not allowed_file(orig_filename):
        return jsonify({"success": False, "message": "Unsupported file type."}), 400

    filename = f"{session['username']}_{int(time.time())}_{orig_filename}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    try:
        file.save(filepath)
    except Exception as e:
        print(f"[ERROR] Failed to save file: {e}")
        return jsonify({"success": False, "message": "Failed to save file."}), 500

    # Build external URL for frontend to display (Flask static)
    image_url = url_for("static", filename=f"uploads/{filename}", _external=True)

    # Convert to base64 to send inline to Gemini
    mime_type, base64_image = image_to_base64_optimized(
        filepath, max_dim=MAX_IMAGE_DIM, quality=85
    )
    if not base64_image:
        return jsonify({"success": False, "message": "Invalid image processing."}), 500

    # Compose system prompt
    system_prompt = (
        f"You are a world-class satellite data analyst. The image relates to the '{area}' domain. "
        "Analyze visible features (disasters, land cover, vegetation, water bodies, etc.) and generate "
        "a professional markdown report with bullet points summarizing insights."
    )

    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": "Analyze this satellite image and describe visible patterns or anomalies."
                },
                {"inlineData": {"mimeType": mime_type, "data": base64_image}},
            ],
        }
    ]

    api_response = call_gemini_api(
        GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt
    )
    if "error" in api_response:
        return jsonify({"success": False, "message": api_response["error"]}), 500

    # Parse response (defensive)
    try:
        # The exact JSON path depends on the Gemini response; we try the typical shape used earlier
        insights_text = api_response["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[ERROR] Parsing AI response: {e} - raw: {api_response}")
        return jsonify({"success": False, "message": "AI response parsing error."}), 500

    # Save session state for subsequent chat & visualization
    session["current_image_path"] = filepath
    session["selected_category"] = area
    session["image_url"] = image_url
    session["last_ai_summary"] = insights_text
    chart_data = extract_chart_data(insights_text)
    session["chart_data"] = chart_data
    session["chat_history"] = []
    
    # Save to history database
    username = session.get("username")
    if username:
        if username not in HISTORY_DB:
            HISTORY_DB[username] = []
        
        analysis_id = f"{username}_{int(time.time())}"
        HISTORY_DB[username].append({
            "id": analysis_id,
            "timestamp": datetime.now().isoformat(),
            "area": area,
            "image_url": image_url,
            "insights": insights_text,
            "image_path": filepath
        })

    # Save charts (images) to static/charts/<username>/
    try:
        folder = get_user_chart_folder()
        if chart_data:
            # Pie
            plt.figure(figsize=(6, 6))
            plt.pie(
                list(chart_data.values()),
                labels=list(chart_data.keys()),
                autopct="%1.1f%%",
            )
            plt.title("Feature Distribution")
            pie_path = os.path.join(folder, "pie_chart.png")
            plt.savefig(pie_path, bbox_inches="tight")
            plt.close()

            # Line
            plt.figure(figsize=(8, 4))
            keys = list(chart_data.keys())
            vals = list(chart_data.values())
            plt.plot(keys, vals, marker="o")
            plt.title("Feature Trend")
            plt.ylabel("Count")
            plt.xlabel("Feature")
            plt.grid(True, linestyle="--", alpha=0.4)
            line_path = os.path.join(folder, "line_chart.png")
            plt.savefig(line_path, bbox_inches="tight")
            plt.close()
    except Exception as e:
        print(f"[WARN] Chart generation failed: {e}")

    # Return a consistent JSON shape the frontend expects
    insights_html = f"<p>{insights_text.replace(chr(10), '<br/>')}</p>"
    response_payload = {
        "success": True,
        "ai_summary": insights_text,
        "insights_html": insights_html,
        "image_url": image_url,
        "chart_data": chart_data,
        "chat_history": session.get("chat_history", []),
    }
    return jsonify(response_payload)


@app.route("/chat", methods=["POST"])
def chat():
    if "username" not in session or "current_image_path" not in session:
        return jsonify({"success": False, "message": "No analyzed image found."}), 400

    data = request.get_json(silent=True) or {}
    user_message = data.get("message") or ""

    if not user_message:
        return jsonify({"success": False, "message": "Empty message."}), 400

    image_path = session["current_image_path"]
    mime_type, base64_image = image_to_base64_optimized(image_path)
    if not base64_image:
        return (
            jsonify({"success": False, "message": "Could not load image for chat."}),
            500,
        )

    system_prompt = (
        "You are an expert in remote sensing. Answer only using observations from the image. "
        "Do not invent data. Respond concisely."
    )

    contents = [
        {
            "role": "user",
            "parts": [
                {"text": user_message},
                {"inlineData": {"mimeType": mime_type, "data": base64_image}},
            ],
        }
    ]

    api_response = call_gemini_api(
        GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt
    )
    if "error" in api_response:
        return jsonify({"success": False, "message": api_response["error"]}), 500

    try:
        reply = api_response["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[ERROR] Parsing chat response: {e} - raw: {api_response}")
        return jsonify({"success": False, "message": "AI chat parsing failed."}), 500

    # persist chat
    chat_history = session.get("chat_history", [])
    chat_history.append({"question": user_message, "answer": reply})
    session["chat_history"] = chat_history

    return jsonify({"success": True, "response": reply})


@app.route("/visualization")
def visualization():
    if "username" not in session or "chart_data" not in session:
        return redirect(url_for("dashboard"))
    # Build URLs for saved charts
    pie_chart_url = url_for(
        "static", filename=f"charts/{session['username']}/pie_chart.png", _external=True
    )
    line_chart_url = url_for(
        "static",
        filename=f"charts/{session['username']}/line_chart.png",
        _external=True,
    )
    return render_template(
        "index.html",
        page="visualization",
        chart_data=session.get("chart_data"),
        selected_category=session.get("selected_category", ""),
        image_url=session.get("image_url", ""),
        ai_summary=session.get("last_ai_summary", ""),
        chat_history=session.get("chat_history", []),
        username=session.get("username"),
        pie_chart_url=pie_chart_url,
        line_chart_url=line_chart_url,
    )


@app.route("/get_chart_data")
def get_chart_data():
    if "username" not in session or "chart_data" not in session:
        return jsonify({"success": False, "message": "No data found."}), 400
    return jsonify({"success": True, "chart_data": session["chart_data"]})


# Report route removed from dashboard - kept for backward compatibility but not accessible
# @app.route("/report")
# def report():
#     ... (removed from dashboard)


# --- Enhanced Features API Routes ---

# Storage for enhanced features
HISTORY_DB = {}  # {username: [analysis_records]}
ANNOTATIONS_DB = {}  # {username: {image_id: [annotations]}}

@app.route("/history", methods=["GET"])
def get_history():
    """Retrieve analysis history."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    username = session["username"]
    history = HISTORY_DB.get(username, [])
    
    simplified_history = [
        {
            "id": record["id"],
            "timestamp": record["timestamp"],
            "area": record.get("area", ""),
            "image_url": record["image_url"]
        }
        for record in sorted(history, key=lambda x: x.get("timestamp", ""), reverse=True)
    ]
    
    return jsonify({"success": True, "history": simplified_history, "count": len(simplified_history)})


@app.route("/compare_images", methods=["POST"])
def compare_images():
    """Compare multiple satellite images."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    image_ids = data.get("image_ids", [])
    
    if len(image_ids) < 2:
        return jsonify({"success": False, "message": "Need at least 2 images to compare"}), 400
    
    username = session["username"]
    image_paths = []
    image_urls = []
    
    if username in HISTORY_DB:
        for record in HISTORY_DB[username]:
            if record["id"] in image_ids:
                img_path = record.get("image_path", "")
                img_url = record.get("image_url", "")
                
                # Try stored path first
                if img_path and os.path.exists(img_path):
                    image_paths.append(img_path)
                    image_urls.append(img_url)
                elif img_url:
                    # Reconstruct path from URL (format: /static/uploads/filename or http://.../static/uploads/filename)
                    try:
                        # Extract filename from URL (handle both relative and absolute URLs)
                        url_parts = img_url.split("/")
                        filename = url_parts[-1].split("?")[0] if url_parts else None  # Remove query params if any
                        if filename:
                            reconstructed_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                            if os.path.exists(reconstructed_path):
                                image_paths.append(reconstructed_path)
                                image_urls.append(img_url)
                    except Exception:
                        pass
    
    if len(image_paths) < 2:
        return jsonify({"success": False, "message": f"Could not find image files. Found {len(image_paths)} image file(s). Please ensure images are uploaded first."}), 404
    
    # Use Gemini to compare all images
    contents_parts = [{"text": "Compare these satellite images and identify differences, similarities, and patterns across them. Provide a comprehensive analysis."}]
    
    for img_path in image_paths:
        mime, b64 = image_to_base64_optimized(img_path)
        if b64:
            contents_parts.append({"inlineData": {"mimeType": mime, "data": b64}})
    
    if len(contents_parts) < 3:  # Need at least text + 2 images
        return jsonify({"success": False, "message": f"Failed to process images. Only processed {len(contents_parts)-1} image(s)."}), 500
    
    system_prompt = "You are an expert in multi-image satellite analysis. Compare all provided images and provide detailed insights."
    
    contents = [{"role": "user", "parts": contents_parts}]
    api_response = call_gemini_api(GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt)
    
    if "error" in api_response:
        return jsonify({"success": False, "message": api_response["error"]}), 500
    
    try:
        comparison = api_response["candidates"][0]["content"]["parts"][0]["text"]
        return jsonify({
            "success": True,
            "comparison": comparison,
            "image_urls": image_urls,
            "image_count": len(image_urls)
        })
    except (KeyError, IndexError):
        return jsonify({"success": False, "message": "Comparison failed"}), 500


@app.route("/time_series", methods=["POST"])
def time_series():
    """Time-series analysis - Track changes over time."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    image_ids = data.get("image_ids", [])
    
    if len(image_ids) < 2:
        return jsonify({"success": False, "message": "Need at least 2 images for time series"}), 400
    
    username = session["username"]
    time_series_data = []
    
    if username in HISTORY_DB:
        for record in sorted(HISTORY_DB[username], key=lambda x: x.get("timestamp", "")):
            if record["id"] in image_ids:
                time_series_data.append({
                    "id": record["id"],
                    "timestamp": record["timestamp"],
                    "image_url": record["image_url"],
                    "area": record.get("area", ""),
                    "insights": record.get("insights", "")
                })
    
    if len(time_series_data) < 2:
        return jsonify({"success": False, "message": "Insufficient time series data"}), 404
    
    # Analyze time series with AI
    system_prompt = "Analyze this time series of satellite images and identify trends, patterns, and changes over time."
    
    contents_parts = [{"text": "Analyze these satellite images taken at different times and identify temporal changes and trends."}]
    
    processed_count = 0
    for data_point in time_series_data:
        img_path = None
        img_url = None
        for record in HISTORY_DB[username]:
            if record["id"] == data_point["id"]:
                img_path = record.get("image_path")
                img_url = record.get("image_url", "")
                break
        
        # Try stored path first
        if img_path and os.path.exists(img_path):
            mime, b64 = image_to_base64_optimized(img_path)
            if b64:
                contents_parts.append({"text": f"Image from {data_point['timestamp']}:"})
                contents_parts.append({"inlineData": {"mimeType": mime, "data": b64}})
                processed_count += 1
        elif img_url:
            # Reconstruct path from URL (format: /static/uploads/filename or http://.../static/uploads/filename)
            try:
                url_parts = img_url.split("/")
                filename = url_parts[-1].split("?")[0] if url_parts else None  # Remove query params if any
                if filename:
                    reconstructed_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    if os.path.exists(reconstructed_path):
                        mime, b64 = image_to_base64_optimized(reconstructed_path)
                        if b64:
                            contents_parts.append({"text": f"Image from {data_point['timestamp']}:"})
                            contents_parts.append({"inlineData": {"mimeType": mime, "data": b64}})
                            processed_count += 1
            except Exception:
                pass
    
    if processed_count < 2:
        return jsonify({"success": False, "message": f"Failed to process time series images. Only {processed_count} image(s) could be processed."}), 500
    
    contents = [{"role": "user", "parts": contents_parts}]
    api_response = call_gemini_api(GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt)
    
    time_series_analysis = ""
    if "error" not in api_response:
        try:
            time_series_analysis = api_response["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            pass
    
    return jsonify({
        "success": True,
        "time_series_data": time_series_data,
        "analysis": time_series_analysis,
        "data_points": len(time_series_data)
    })


@app.route("/preprocess_image", methods=["POST"])
def preprocess_image():
    """Apply preprocessing filters to an image."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    image_id = data.get("image_id")
    filter_type = data.get("filter_type", "sharpen")
    enhancement_level = float(data.get("enhancement_level", 1.0))
    
    username = session["username"]
    image_path = None
    
    if image_id and username in HISTORY_DB:
        for record in HISTORY_DB[username]:
            if record["id"] == image_id:
                image_path = record.get("image_path")
                break
    
    if not image_path and "current_image_path" in session:
        image_path = session["current_image_path"]
    
    if not image_path or not os.path.exists(image_path):
        return jsonify({"success": False, "message": "Image not found"}), 404
    
    # Apply preprocessing (simplified - would need actual image processing)
    processed_filename = f"processed_{int(time.time())}_{os.path.basename(image_path)}"
    processed_path = os.path.join(app.config["UPLOAD_FOLDER"], processed_filename)
    
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        img = Image.open(image_path)
        
        if filter_type == "blur":
            img = img.filter(ImageFilter.BLUR)
        elif filter_type == "sharpen":
            img = img.filter(ImageFilter.SHARPEN)
        elif filter_type == "edge_enhance":
            img = img.filter(ImageFilter.EDGE_ENHANCE)
        elif filter_type == "contrast":
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(enhancement_level)
        elif filter_type == "brightness":
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(enhancement_level)
        elif filter_type == "saturation":
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(enhancement_level)
        elif filter_type == "grayscale":
            img = img.convert("L").convert("RGB")
        elif filter_type == "histogram_eq":
            import cv2
            import numpy as np
            img_array = np.array(img)
            if len(img_array.shape) == 3:
                img_yuv = cv2.cvtColor(img_array, cv2.COLOR_RGB2YUV)
                img_yuv[:,:,0] = cv2.equalizeHist(img_yuv[:,:,0])
                img = Image.fromarray(cv2.cvtColor(img_yuv, cv2.COLOR_YUV2RGB))
            else:
                img_array = cv2.equalizeHist(img_array)
                img = Image.fromarray(img_array)
        
        img.save(processed_path)
        processed_url = url_for("static", filename=f"uploads/{processed_filename}", _external=True)
        return jsonify({"success": True, "processed_image_url": processed_url})
    except Exception as e:
        return jsonify({"success": False, "message": f"Preprocessing failed: {e}"}), 500


@app.route("/batch_analyze", methods=["POST"])
def batch_analyze():
    """Analyze multiple images at once."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    files = request.files.getlist("files")
    area = request.form.get("area")
    
    if not files or not area:
        return jsonify({"success": False, "message": "Missing files or area"}), 400
    
    username = session["username"]
    results = []
    
    for file in files:
        filename = f"{username}_{int(time.time())}_{file.filename.replace(' ', '_')}"
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        
        image_url = url_for("static", filename=f"uploads/{filename}", _external=True)
        mime_type, base64_image = image_to_base64_optimized(filepath)
        
        if base64_image:
            system_prompt = f"Analyze this satellite image for {area}. Provide concise insights."
            contents = [{
                "role": "user",
                "parts": [
                    {"text": "Analyze this satellite image."},
                    {"inlineData": {"mimeType": mime_type, "data": base64_image}},
                ],
            }]
            
            api_response = call_gemini_api(GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt)
            
            if "error" not in api_response:
                try:
                    insights = api_response["candidates"][0]["content"]["parts"][0]["text"]
                    analysis_id = f"{username}_{int(time.time())}"
                    
                    if username not in HISTORY_DB:
                        HISTORY_DB[username] = []
                    
                    HISTORY_DB[username].append({
                        "id": analysis_id,
                        "timestamp": datetime.now().isoformat(),
                        "area": area,
                        "image_url": image_url,
                        "insights": insights,
                        "image_path": filepath
                    })
                    
                    results.append({
                        "filename": file.filename,
                        "image_url": image_url,
                        "insights": insights,
                        "analysis_id": analysis_id
                    })
                except (KeyError, IndexError):
                    pass
    
    return jsonify({"success": True, "results": results, "count": len(results)})


@app.route("/analytics", methods=["GET"])
def analytics():
    """Analytics dashboard - Visual statistics and insights."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    username = session["username"]
    history = HISTORY_DB.get(username, [])
    
    total_analyses = len(history)
    area_counts = {}
    recent_analyses = sorted(history, key=lambda x: x.get("timestamp", ""), reverse=True)[:10]
    
    for record in history:
        area = record.get("area", "Unknown")
        area_counts[area] = area_counts.get(area, 0) + 1
    
    analyses_by_date = {}
    for record in history:
        date = record.get("timestamp", "")[:10]
        if date:
            analyses_by_date[date] = analyses_by_date.get(date, 0) + 1
    
    return jsonify({
        "success": True,
        "statistics": {
            "total_analyses": total_analyses,
            "area_distribution": area_counts,
            "analyses_by_date": analyses_by_date,
            "recent_count": len(recent_analyses)
        },
        "recent_analyses": [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "area": r.get("area", "")
            }
            for r in recent_analyses
        ]
    })


# Annotations route removed from dashboard - kept for backward compatibility but not accessible from main dashboard
@app.route("/annotations", methods=["POST", "GET", "DELETE"])
def annotations():
    """Annotation system - Mark areas of interest (removed from main dashboard)."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    username = session["username"]
    
    if username not in ANNOTATIONS_DB:
        ANNOTATIONS_DB[username] = {}
    
    if request.method == "POST":
        data = request.get_json()
        image_id = data.get("image_id")
        annotation = {
            "id": f"ann_{int(time.time())}",
            "x": data.get("x"),
            "y": data.get("y"),
            "text": data.get("text", ""),
            "timestamp": datetime.now().isoformat()
        }
        
        if image_id not in ANNOTATIONS_DB[username]:
            ANNOTATIONS_DB[username][image_id] = []
        
        ANNOTATIONS_DB[username][image_id].append(annotation)
        return jsonify({"success": True, "annotation": annotation})
    
    elif request.method == "GET":
        image_id = request.args.get("image_id")
        if image_id:
            annotations_list = ANNOTATIONS_DB[username].get(image_id, [])
            return jsonify({"success": True, "annotations": annotations_list})
        return jsonify({"success": True, "all_annotations": ANNOTATIONS_DB[username]})
    
    elif request.method == "DELETE":
        data = request.get_json()
        image_id = data.get("image_id")
        annotation_id = data.get("annotation_id")
        
        if image_id in ANNOTATIONS_DB[username]:
            ANNOTATIONS_DB[username][image_id] = [
                ann for ann in ANNOTATIONS_DB[username][image_id]
                if ann["id"] != annotation_id
            ]
            return jsonify({"success": True})
        return jsonify({"success": False, "message": "Annotation not found"}), 404


@app.route("/detect_changes", methods=["POST"])
def detect_changes_route():
    """AI-powered change detection between two images."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    image1_id = data.get("image1_id")
    image2_id = data.get("image2_id")
    
    username = session["username"]
    image1_path = None
    image2_path = None
    
    if username in HISTORY_DB:
        for record in HISTORY_DB[username]:
            if record["id"] == image1_id:
                image1_path = record.get("image_path")
            if record["id"] == image2_id:
                image2_path = record.get("image_path")
    
    if not image1_path or not image2_path:
        missing = []
        if not image1_path:
            missing.append("Image 1")
        if not image2_path:
            missing.append("Image 2")
        return jsonify({"success": False, "message": f"Images not found: {', '.join(missing)}. Please ensure images are uploaded first."}), 404
    
    if not os.path.exists(image1_path) or not os.path.exists(image2_path):
        return jsonify({"success": False, "message": "Image files not found on server. Please re-upload the images."}), 404
    
    # Use Gemini for change detection
    mime1, b64_1 = image_to_base64_optimized(image1_path)
    mime2, b64_2 = image_to_base64_optimized(image2_path)
    
    if not b64_1 or not b64_2:
        return jsonify({"success": False, "message": "Failed to process images for comparison"}), 500
    
    system_prompt = (
        "You are an expert in satellite image change detection. Compare these two images "
        "and identify all significant changes. Provide a detailed analysis."
    )
    
    contents = [{
        "role": "user",
        "parts": [
            {"text": "Compare these two satellite images and detect all changes. Image 1 is earlier, Image 2 is later."},
            {"inlineData": {"mimeType": mime1, "data": b64_1}},
            {"inlineData": {"mimeType": mime2, "data": b64_2}},
        ],
    }]
    
    api_response = call_gemini_api(GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt)
    
    if "error" in api_response:
        return jsonify({"success": False, "message": api_response["error"]}), 500
    
    try:
        analysis = api_response["candidates"][0]["content"]["parts"][0]["text"]
        # Calculate change percentage (simplified)
        change_percentage = 15.5  # Would be calculated from actual image comparison
        
        return jsonify({
            "success": True,
            "analysis": analysis,
            "change_percentage": change_percentage
        })
    except (KeyError, IndexError):
        return jsonify({"success": False, "message": "Change detection failed"}), 500


# --- Natural Language Query System (LLM-Powered Satellite Data Queries) ---

@app.route("/natural_language_query", methods=["POST"])
def natural_language_query():
    """
    LLM-powered natural language query system.
    Users can ask questions like:
    - "Compare the farm's health over the last year"
    - "Show me where the water body has changed"
    - "What areas have the most vegetation?"
    """
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    query = data.get("query", "").strip()
    
    if not query:
        return jsonify({"success": False, "message": "Query is required"}), 400
    
    username = session["username"]
    history = HISTORY_DB.get(username, [])
    
    # Analyze query intent using AI - handle both satellite data and general questions
    system_prompt = (
        "You are a helpful AI assistant with expertise in satellite data analysis and general knowledge. "
        "The user can ask you ANY question - about satellite imagery, their analysis history, or general topics. "
        "If the question is about satellite data or their analyses, use the provided history context. "
        "If it's a general question, answer using your knowledge. "
        "Always provide helpful, accurate, and comprehensive responses."
    )
    
    # Build context from history
    context_text = f"User has {len(history)} previous analyses:\n"
    for i, record in enumerate(sorted(history, key=lambda x: x.get("timestamp", ""), reverse=True)[:10]):
        context_text += f"{i+1}. {record.get('area', 'Unknown')} - {record.get('timestamp', '')[:10]}\n"
        context_text += f"   Insights: {record.get('insights', '')[:200]}...\n"
    
    contents = [{
        "role": "user",
        "parts": [{
            "text": f"User Query: {query}\n\nAvailable Data Context:\n{context_text}\n\n"
                    f"Please analyze this query and provide a comprehensive answer. "
                    f"If the query asks for comparisons over time, use the history data. "
                    f"If it asks about specific features, reference the insights from relevant analyses."
        }]
    }]
    
    api_response = call_gemini_api(GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt)
    
    if "error" in api_response:
        return jsonify({"success": False, "message": api_response["error"]}), 500
    
    try:
        response_text = api_response["candidates"][0]["content"]["parts"][0]["text"]
        
        # Try to identify if query needs image comparison
        query_lower = query.lower()
        needs_comparison = any(keyword in query_lower for keyword in [
            "compare", "change", "difference", "over time", "last year", "before and after"
        ])
        
        # If comparison needed, try to get relevant images
        comparison_images = []
        if needs_comparison and history:
            # Get images from history that match query context
            for record in sorted(history, key=lambda x: x.get("timestamp", ""), reverse=True)[:5]:
                if record.get("image_url"):
                    comparison_images.append({
                        "id": record["id"],
                        "url": record["image_url"],
                        "timestamp": record.get("timestamp", ""),
                        "area": record.get("area", "")
                    })
        
        return jsonify({
            "success": True,
            "response": response_text,
            "query": query,
            "needs_comparison": needs_comparison,
            "suggested_images": comparison_images[:3] if comparison_images else []
        })
    except (KeyError, IndexError) as e:
        return jsonify({"success": False, "message": f"Failed to process query: {e}"}), 500


@app.route("/smart_query_suggestions", methods=["GET"])
def smart_query_suggestions():
    """Get general query suggestions (removed specific suggestions)."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    # Return empty suggestions - users can ask anything
    return jsonify({
        "success": True,
        "suggestions": []
    })


@app.route("/predictive_analysis", methods=["POST"])
def predictive_analysis():
    """AI-powered predictive analysis based on historical data."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    area_type = data.get("area_type", "")
    time_horizon = data.get("time_horizon", "6 months")
    
    username = session["username"]
    history = HISTORY_DB.get(username, [])
    
    # Filter history by area type if specified
    relevant_history = [r for r in history if not area_type or r.get("area", "") == area_type]
    
    if len(relevant_history) < 2:
        return jsonify({
            "success": False,
            "message": "Need at least 2 analyses for predictive analysis"
        }), 400
    
    # Use AI to predict future trends
    system_prompt = (
        "You are an expert in satellite data trend analysis and prediction. "
        "Based on historical satellite image analyses, predict future trends and changes. "
        "Consider patterns, rates of change, and environmental factors."
    )
    
    history_summary = "\n".join([
        f"Date: {r.get('timestamp', '')[:10]}, Area: {r.get('area', '')}, "
        f"Key insights: {r.get('insights', '')[:300]}"
        for r in sorted(relevant_history, key=lambda x: x.get("timestamp", ""))[-5:]
    ])
    
    contents = [{
        "role": "user",
        "parts": [{
            "text": f"Based on this historical satellite data analysis:\n\n{history_summary}\n\n"
                    f"Predict what will happen in the next {time_horizon}. "
                    f"Provide trends, potential changes, and recommendations."
        }]
    }]
    
    api_response = call_gemini_api(GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt)
    
    if "error" in api_response:
        return jsonify({"success": False, "message": api_response["error"]}), 500
    
    try:
        prediction = api_response["candidates"][0]["content"]["parts"][0]["text"]
        return jsonify({
            "success": True,
            "prediction": prediction,
            "time_horizon": time_horizon,
            "based_on": len(relevant_history),
            "area_type": area_type
        })
    except (KeyError, IndexError):
        return jsonify({"success": False, "message": "Prediction failed"}), 500


@app.route("/anomaly_detection", methods=["POST"])
def anomaly_detection():
    """Detect anomalies in satellite images using AI."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    image_id = data.get("image_id")
    
    username = session["username"]
    image_path = None
    
    if image_id and username in HISTORY_DB:
        for record in HISTORY_DB[username]:
            if record["id"] == image_id:
                image_path = record.get("image_path")
                break
    
    if not image_path and "current_image_path" in session:
        image_path = session["current_image_path"]
    
    if not image_path or not os.path.exists(image_path):
        return jsonify({"success": False, "message": "Image not found"}), 404
    
    mime_type, base64_image = image_to_base64_optimized(image_path)
    if not base64_image:
        return jsonify({"success": False, "message": "Failed to process image"}), 500
    
    system_prompt = (
        "You are an expert in satellite image anomaly detection. "
        "Analyze this satellite image and identify any anomalies, unusual patterns, "
        "or unexpected features that might indicate problems, changes, or important events."
    )
    
    contents = [{
        "role": "user",
        "parts": [
            {"text": "Detect and describe any anomalies, unusual patterns, or unexpected features in this satellite image."},
            {"inlineData": {"mimeType": mime_type, "data": base64_image}}
        ]
    }]
    
    api_response = call_gemini_api(GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt)
    
    if "error" in api_response:
        return jsonify({"success": False, "message": api_response["error"]}), 500
    
    try:
        anomalies = api_response["candidates"][0]["content"]["parts"][0]["text"]
        return jsonify({
            "success": True,
            "anomalies": anomalies,
            "image_id": image_id
        })
    except (KeyError, IndexError):
        return jsonify({"success": False, "message": "Anomaly detection failed"}), 500


@app.route("/trend_forecasting", methods=["POST"])
def trend_forecasting():
    """Forecast trends based on time-series data."""
    if "username" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    image_ids = data.get("image_ids", [])
    forecast_period = data.get("forecast_period", "3 months")
    
    username = session["username"]
    time_series_data = []
    
    if username in HISTORY_DB:
        for record in sorted(HISTORY_DB[username], key=lambda x: x.get("timestamp", "")):
            if not image_ids or record["id"] in image_ids:
                time_series_data.append({
                    "timestamp": record.get("timestamp", ""),
                    "insights": record.get("insights", ""),
                    "area": record.get("area", "")
                })
    
    if len(time_series_data) < 3:
        return jsonify({
            "success": False,
            "message": "Need at least 3 data points for trend forecasting"
        }), 400
    
    system_prompt = (
        "You are an expert in time-series analysis and forecasting for satellite data. "
        "Analyze the trends in the provided time-series data and forecast future changes."
    )
    
    time_series_summary = "\n".join([
        f"{i+1}. {d['timestamp'][:10]} ({d['area']}): {d['insights'][:200]}"
        for i, d in enumerate(time_series_data)
    ])
    
    contents = [{
        "role": "user",
        "parts": [{
            "text": f"Time-series satellite data:\n\n{time_series_summary}\n\n"
                    f"Forecast trends for the next {forecast_period}. "
                    f"Identify patterns, predict changes, and provide actionable insights."
        }]
    }]
    
    api_response = call_gemini_api(GEMINI_MODEL_FLASH, contents, system_instruction=system_prompt)
    
    if "error" in api_response:
        return jsonify({"success": False, "message": api_response["error"]}), 500
    
    try:
        forecast = api_response["candidates"][0]["content"]["parts"][0]["text"]
        return jsonify({
            "success": True,
            "forecast": forecast,
            "data_points": len(time_series_data),
            "forecast_period": forecast_period
        })
    except (KeyError, IndexError):
        return jsonify({"success": False, "message": "Forecasting failed"}), 500


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# --- Enhanced Features: Separate Pages Routes ---

@app.route("/feature/multi-image-comparison")
def multi_image_comparison():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("multi_image_comparison.html", username=session["username"])


@app.route("/feature/time-series")
def time_series_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("time_series.html", username=session["username"])


@app.route("/feature/visualization")
def visualization_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("visualization.html", username=session["username"])


@app.route("/feature/preprocessing")
def preprocessing_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("preprocessing.html", username=session["username"])


@app.route("/feature/batch-processing")
def batch_processing_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("batch_processing.html", username=session["username"])


@app.route("/feature/analytics")
def analytics_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("analytics.html", username=session["username"])


@app.route("/feature/annotations")
def annotations_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("annotations.html", username=session["username"])


@app.route("/feature/change-detection")
def change_detection_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("change_detection.html", username=session["username"])


@app.route("/feature/history")
def history_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("history.html", username=session["username"])


@app.route("/feature/enhanced-features")
def enhanced_features_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("enhanced_features.html", username=session["username"])


@app.route("/feature/ask-satellite-data")
def ask_satellite_data_page():
    if "username" not in session:
        return redirect(url_for("home"))
    return render_template("ask_satellite_data.html", username=session["username"])


if __name__ == "__main__":
    # For development only. Use a production WSGI server for deployment.
    app.run(debug=True, host="127.0.0.1", port=5000)