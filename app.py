import datetime
import hmac
import os
import smtplib
import time
from collections import defaultdict, deque
from email.mime.text import MIMEText
from functools import wraps
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from cloud_storage import (
    delete_file_from_cloud,
    extract_filename_from_url,
    upload_file_to_cloud,
)
from database import ContactMessage, GalleryImage, News, User, db


BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)

DEFAULT_FRONTEND_ORIGINS = {
    "http://127.0.0.1:5000",
    "http://localhost:5000",
    "null",
}
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
RATE_LIMITS = defaultdict(deque)


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_origins():
    raw_origins = os.getenv("FRONTEND_ORIGINS", "")
    configured = {
        origin.strip().rstrip("/")
        for origin in raw_origins.split(",")
        if origin.strip()
    }
    return sorted(configured | DEFAULT_FRONTEND_ORIGINS)


def get_client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_rate_limited(bucket, limit, window_seconds):
    key = f"{bucket}:{get_client_ip()}"
    now = time.time()
    entries = RATE_LIMITS[key]

    while entries and now - entries[0] > window_seconds:
        entries.popleft()

    if len(entries) >= limit:
        return True

    entries.append(now)
    return False


def is_trusted_request_origin():
    expected = urlparse(request.host_url)

    for header_name in ("Origin", "Referer"):
        header_value = request.headers.get(header_name)
        if not header_value:
            continue

        parsed = urlparse(header_value)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != expected.netloc:
            return False

    return True


def same_origin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not is_trusted_request_origin():
            return jsonify({"message": "Untrusted request origin"}), 403
        return view_func(*args, **kwargs)

    return wrapped


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"message": "Authentication required"}), 401
        return view_func(*args, **kwargs)

    return wrapped


def get_scraper_api_key():
    return (os.getenv("SCRAPER_API_KEY") or "").strip()


def is_loopback_request():
    return get_client_ip() in {"127.0.0.1", "::1", "localhost"}


def scraper_request_authorized():
    expected_key = get_scraper_api_key()
    provided_key = request.headers.get("X-API-Key", "")

    if expected_key:
        return hmac.compare_digest(provided_key, expected_key)

    # Keep local automation working even if an API key is not configured.
    return is_loopback_request() and not request.headers.get("Origin")


def normalize_text(value, max_length=None):
    if not isinstance(value, str):
        return ""

    cleaned = value.strip()
    if max_length is not None:
        cleaned = cleaned[:max_length]
    return cleaned


def sanitize_external_url(value):
    if not value:
        return None

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    return value


def is_allowed_image(filename, content_type):
    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return False

    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    return normalized_type in ALLOWED_IMAGE_MIME_TYPES


def upload_request_image(file_storage, prefix):
    if not file_storage or not file_storage.filename:
        return None

    original_name = secure_filename(file_storage.filename)
    if not original_name:
        raise ValueError("Invalid filename")

    content_type = file_storage.mimetype or file_storage.content_type or ""
    if not is_allowed_image(original_name, content_type):
        raise ValueError("Only JPG, PNG, GIF, and WEBP images are allowed")

    file_data = file_storage.read()
    if not file_data:
        raise ValueError("Uploaded file is empty")

    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    unique_filename = f"{prefix}_{timestamp}_{original_name}"
    return upload_file_to_cloud(file_data, unique_filename, content_type)


def delete_cloud_image(file_url):
    filename = extract_filename_from_url(file_url)
    if filename:
        delete_file_from_cloud(filename)


app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///chitalishte.db",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = (
    os.getenv("SECRET_KEY")
    or os.getenv("FLASK_SECRET_KEY")
    or os.urandom(32).hex()
)
app.config["UPLOAD_FOLDER"] = os.path.abspath(os.path.join(BASE_DIR, "..", "uploads"))
app.config["MAX_CONTENT_LENGTH"] = int(
    os.getenv("MAX_CONTENT_LENGTH", str(8 * 1024 * 1024))
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
app.config["SESSION_COOKIE_SECURE"] = parse_bool(
    os.getenv("SESSION_COOKIE_SECURE"),
    default=False,
)

db.init_app(app)

CORS(
    app,
    supports_credentials=True,
    resources={
        r"/api/*": {"origins": parse_origins()},
        r"/send-email": {"origins": parse_origins()},
        r"/admin.*": {"origins": parse_origins()},
    },
)

with app.app_context():
    db.create_all()

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", EMAIL_ADDRESS)
ADMIN_DIR = os.path.join(BASE_DIR, "..", "admin")

if not os.getenv("SECRET_KEY") and not os.getenv("FLASK_SECRET_KEY"):
    print("WARNING: SECRET_KEY is not set. A temporary key was generated for this run.")

if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
    print("WARNING: EMAIL_ADDRESS or EMAIL_PASSWORD is not configured.")


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({"message": "File is too large"}), 413


@app.route("/send-email", methods=["POST"])
def send_email():
    if is_rate_limited("contact-form", limit=5, window_seconds=15 * 60):
        return jsonify({"status": "error", "message": "Too many requests. Try again later."}), 429

    name = normalize_text(request.form.get("name"), max_length=100)
    visitor_email = normalize_text(request.form.get("email"), max_length=120)
    message_content = normalize_text(request.form.get("message"))

    if not name or not visitor_email or not message_content:
        return jsonify({"status": "error", "message": "All fields are required."}), 400

    if "@" not in visitor_email or "." not in visitor_email.split("@")[-1]:
        return jsonify({"status": "error", "message": "Invalid email address."}), 400

    new_message = ContactMessage(name=name, email=visitor_email, message=message_content)
    db.session.add(new_message)
    db.session.commit()

    if not RECIPIENT_EMAIL:
        return jsonify(
            {
                "status": "success",
                "message": "Message saved successfully.",
            }
        )

    subject = f"New website message from {name}"
    body = f"Name: {name}\nEmail: {visitor_email}\n\nMessage:\n{message_content}"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"Website Contact <{EMAIL_ADDRESS}>"
    msg["To"] = RECIPIENT_EMAIL
    msg["Reply-To"] = visitor_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp_server:
            smtp_server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp_server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
    except Exception as exc:
        print(f"Email send failed: {exc}")
        return jsonify(
            {
                "status": "error",
                "message": "Message was saved, but the email could not be sent.",
            }
        ), 502

    return jsonify({"status": "success", "message": "Message sent successfully."})


@app.route("/api/login", methods=["POST"])
@same_origin_required
def login():
    if is_rate_limited("login", limit=10, window_seconds=15 * 60):
        return jsonify({"message": "Too many login attempts", "status": "error"}), 429

    data = request.get_json(silent=True) or {}
    username = normalize_text(data.get("username"), max_length=80)
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"message": "Username and password are required", "status": "error"}), 400

    user = User.query.filter_by(username=username).first()

    if user and check_password_hash(user.password_hash, password):
        session.clear()
        session["user_id"] = user.id
        return jsonify({"message": "Logged in successfully", "status": "success"}), 200

    return jsonify({"message": "Invalid credentials", "status": "error"}), 401


@app.route("/api/logout", methods=["POST"])
@same_origin_required
def logout():
    session.clear()
    return jsonify({"message": "Logged out"}), 200


@app.route("/api/check-auth", methods=["GET"])
def check_auth():
    return jsonify({"authenticated": "user_id" in session}), 200


@app.route("/api/news", methods=["GET"])
def get_news():
    page = max(request.args.get("page", 1, type=int), 1)
    limit = request.args.get("limit", 10, type=int)
    limit = min(max(limit, 1), 50)
    search = request.args.get("search", "", type=str).strip()

    query = News.query

    if search:
        search_filter = f"%{search}%"
        query = query.filter((News.title.like(search_filter)) | (News.content.like(search_filter)))

    query = query.order_by(News.date_posted.desc())
    total = query.count()
    news_items = query.offset((page - 1) * limit).limit(limit).all()

    return jsonify(
        {
            "news": [news.to_dict() for news in news_items],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit if total else 0,
        }
    )


@app.route("/api/news/<int:news_id>", methods=["GET"])
def get_single_news(news_id):
    news = News.query.get(news_id)
    if not news:
        return jsonify({"error": "News not found"}), 404
    return jsonify(news.to_dict())


@app.route("/api/news", methods=["POST"])
def add_news():
    if request.is_json:
        if not scraper_request_authorized():
            return jsonify({"message": "Scraper authentication required"}), 401

        data = request.get_json(silent=True) or {}
        title = normalize_text(data.get("title"), max_length=200)
        content = normalize_text(data.get("content"))
        image_url = sanitize_external_url(data.get("image_url"))
        source_link = sanitize_external_url(data.get("source_link"))

        if not title or not content:
            return jsonify({"message": "Title and content are required"}), 400

        if source_link and "profile.php?id=" not in source_link:
            existing_link = News.query.filter_by(source_link=source_link).first()
            if existing_link:
                return jsonify({"message": "News already exists (link match)"}), 200

        if image_url:
            existing_image = News.query.filter_by(image_url=image_url).first()
            if existing_image:
                return jsonify({"message": "News already exists (image match)"}), 200

        existing_title = News.query.filter_by(title=title).first()
        if existing_title:
            return jsonify({"message": "News already exists (title match)"}), 200

        new_news = News(
            title=title,
            content=content,
            image_url=image_url,
            source_link=source_link,
        )
        db.session.add(new_news)
        db.session.commit()
        return jsonify({"message": "News added successfully (scraper)!"}), 201

    if "user_id" not in session:
        return jsonify({"message": "Authentication required"}), 401

    if not is_trusted_request_origin():
        return jsonify({"message": "Untrusted request origin"}), 403

    title = normalize_text(request.form.get("title"), max_length=200)
    content = normalize_text(request.form.get("content"))
    file_storage = request.files.get("image")

    if not title or not content:
        return jsonify({"message": "Title and content are required"}), 400

    image_path = None
    if file_storage and file_storage.filename:
        try:
            image_path = upload_request_image(file_storage, prefix="news")
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400
        except Exception as exc:
            return jsonify({"message": f"Failed to upload image: {exc}"}), 500

    new_news = News(
        title=title,
        content=content,
        image_url=image_path,
        source_link=None,
    )
    db.session.add(new_news)
    db.session.commit()
    return jsonify({"message": "News added successfully!"}), 201


@app.route("/api/news/<int:news_id>", methods=["PUT"])
@login_required
@same_origin_required
def update_news(news_id):
    news_item = News.query.get_or_404(news_id)

    title = normalize_text(request.form.get("title"), max_length=200)
    content = normalize_text(request.form.get("content"))
    image = request.files.get("image")

    if title:
        news_item.title = title
    if content:
        news_item.content = content

    if image and image.filename:
        try:
            cloud_url = upload_request_image(image, prefix="news")
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400
        except Exception as exc:
            return jsonify({"message": f"Failed to upload image: {exc}"}), 500

        delete_cloud_image(news_item.image_url)
        news_item.image_url = cloud_url

    db.session.commit()
    return jsonify({"message": "News updated successfully!", "news": news_item.to_dict()}), 200


@app.route("/api/news/<int:news_id>", methods=["DELETE"])
@login_required
@same_origin_required
def delete_news(news_id):
    news_item = News.query.get_or_404(news_id)
    delete_cloud_image(news_item.image_url)
    db.session.delete(news_item)
    db.session.commit()
    return jsonify({"message": "News deleted"}), 200


@app.route("/api/gallery", methods=["GET"])
def get_gallery():
    images = GalleryImage.query.order_by(GalleryImage.date_uploaded.desc()).all()
    return jsonify([img.to_dict() for img in images])


@app.route("/api/gallery", methods=["POST"])
@login_required
@same_origin_required
def upload_image():
    file_storage = request.files.get("image")
    if not file_storage:
        return jsonify({"message": "No image part"}), 400
    if not file_storage.filename:
        return jsonify({"message": "No selected file"}), 400

    try:
        cloud_url = upload_request_image(file_storage, prefix="gallery")
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"message": f"Upload failed: {exc}"}), 500

    caption = normalize_text(request.form.get("caption"), max_length=255)
    new_image = GalleryImage(filename=cloud_url, caption=caption)
    db.session.add(new_image)
    db.session.commit()

    return jsonify({"message": "Image uploaded successfully"}), 201


@app.route("/api/gallery/<int:image_id>", methods=["DELETE"])
@login_required
@same_origin_required
def delete_image(image_id):
    image = GalleryImage.query.get_or_404(image_id)
    delete_cloud_image(image.filename)
    db.session.delete(image)
    db.session.commit()
    return jsonify({"message": "Image deleted"}), 200


@app.route("/uploads/<path:filename>")
def serve_uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/admin")
@app.route("/admin/")
@app.route("/admin/index.html")
def serve_admin():
    if "user_id" not in session:
        return """<!DOCTYPE html>
<html lang="bg">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
        .login-box { background: #16213e; padding: 40px; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.3); width: 380px; }
        .login-box h2 { color: #e94560; text-align: center; margin-bottom: 30px; }
        .login-box input { width: 100%; padding: 12px 16px; margin-bottom: 16px; border: 1px solid #0f3460; border-radius: 8px; background: #0f3460; color: white; font-size: 14px; }
        .login-box input::placeholder { color: #888; }
        .login-box button { width: 100%; padding: 12px; background: #e94560; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }
        .login-box button:hover { background: #c73652; }
        #error { color: #e94560; text-align: center; margin-top: 10px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>Admin Panel</h2>
        <input type="text" id="username" placeholder="Username" autofocus>
        <input type="password" id="password" placeholder="Password">
        <button onclick="doLogin()">Login</button>
        <p id="error"></p>
    </div>
    <script>
        document.getElementById('password').addEventListener('keypress', function (event) {
            if (event.key === 'Enter') {
                doLogin();
            }
        });

        function doLogin() {
            fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    username: document.getElementById('username').value,
                    password: document.getElementById('password').value
                })
            })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (data.status === 'success') {
                    window.location.reload();
                } else {
                    document.getElementById('error').innerText = data.message;
                }
            })
            .catch(function () {
                document.getElementById('error').innerText = 'Connection error';
            });
        }
    </script>
</body>
</html>""", 200

    return send_from_directory(ADMIN_DIR, "index.html")


@app.route("/admin/<path:filename>")
def serve_admin_assets(filename):
    if filename in {"", "index.html"}:
        return serve_admin()
    if "user_id" not in session:
        return jsonify({"message": "Authentication required"}), 401
    return send_from_directory(ADMIN_DIR, filename)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(debug=parse_bool(os.getenv("FLASK_DEBUG"), default=False))
