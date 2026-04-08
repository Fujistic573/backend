import datetime
import hmac
import html as html_mod
import os
import secrets
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
from database import ContactMessage, GalleryImage, News, Newspaper, User, Event, db


BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)

ALLOWED_IMAGE_EXTENSIONS_BY_TYPE = {
    "jpeg": {"jpg", "jpeg"},
    "png": {"png"},
    "gif": {"gif"},
    "webp": {"webp"},
    "bmp": {"bmp"},
    "tiff": {"tif", "tiff"},
    "avif": {"avif"},
}
IMAGE_MIME_TYPES_BY_TYPE = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "avif": "image/avif",
}
IMAGE_EXTENSION_BY_TYPE = {
    "jpeg": "jpg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
    "bmp": "bmp",
    "tiff": "tiff",
    "avif": "avif",
}
ALLOWED_PDF_EXTENSIONS = {"pdf"}
RATE_LIMITS = defaultdict(deque)


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


TRUST_PROXY_HEADERS = parse_bool(os.getenv("TRUST_PROXY_HEADERS"), default=False)
ALLOW_DEV_ORIGINS = parse_bool(
    os.getenv("ALLOW_DEV_ORIGINS"),
    default=parse_bool(os.getenv("FLASK_DEBUG"), default=False),
)
ALLOW_UNAUTHENTICATED_LOOPBACK_SCRAPER = parse_bool(
    os.getenv("ALLOW_UNAUTHENTICATED_LOOPBACK_SCRAPER"),
    default=False,
)


def default_frontend_origins():
    if not ALLOW_DEV_ORIGINS:
        return set()

    origins = {"null"}
    local_hosts = ("127.0.0.1", "localhost")
    local_ports = ("5000", "5500", "5501", "5502", "3000", "4173", "5173", "8080")

    for host in local_hosts:
        for port in local_ports:
            origins.add(f"http://{host}:{port}")

    return origins


def parse_origins():
    raw_origins = os.getenv("FRONTEND_ORIGINS", "")
    configured = {
        origin.strip().rstrip("/")
        for origin in raw_origins.split(",")
        if origin.strip()
    }
    return sorted(configured | default_frontend_origins())

# Custom CORS implementation to bypass flask_cors issues
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    print(f"--- AFTER REQUEST FIRED: origin={origin} path={request.path}")
    if origin:
        print(f"--- ADDING CORS HEADERS FOR: {origin}")
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-API-Key"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
def api_options(path):
    return "", 200

def get_client_ip():
    if TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip

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
    allowed_origins = set(parse_origins())

    for header_name in ("Origin", "Referer"):
        header_value = request.headers.get(header_name)
        if not header_value:
            continue

        raw_header = header_value.rstrip("/")
        if raw_header in allowed_origins:
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

    if not ALLOW_UNAUTHENTICATED_LOOPBACK_SCRAPER:
        return False

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


def detect_image_type(file_data):
    if file_data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if file_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if file_data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(file_data) >= 12 and file_data.startswith(b"RIFF") and file_data[8:12] == b"WEBP":
        return "webp"
    if file_data.startswith(b"BM"):
        return "bmp"
    if file_data.startswith((b"II\x2a\x00", b"MM\x00\x2a")):
        return "tiff"
    if len(file_data) >= 12:
        # AVIF is an ISOBMFF container with 'ftypavif' or 'ftypavis'
        if b"ftypavif" in file_data[:32] or b"ftypavis" in file_data[:32]:
            return "avif"
    return None


def upload_request_image(file_storage, prefix):
    if not file_storage or not file_storage.filename:
        return None

    original_name = secure_filename(file_storage.filename)
    if not original_name:
        raise ValueError("Invalid filename")

    file_data = file_storage.read()
    if not file_data:
        raise ValueError("Uploaded file is empty")

    if "." not in original_name:
        raise ValueError("Missing file extension")

    detected_image_type = detect_image_type(file_data)
    if not detected_image_type:
        raise ValueError("Uploaded file is not a valid JPG, PNG, GIF, or WEBP image")

    original_extension = original_name.rsplit(".", 1)[1].lower()
    allowed_extensions = ALLOWED_IMAGE_EXTENSIONS_BY_TYPE[detected_image_type]
    if original_extension not in allowed_extensions:
        raise ValueError("File extension does not match image content")

    content_type = IMAGE_MIME_TYPES_BY_TYPE[detected_image_type]
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_suffix = secrets.token_hex(8)
    canonical_extension = IMAGE_EXTENSION_BY_TYPE[detected_image_type]
    unique_filename = f"{prefix}_{timestamp}_{random_suffix}.{canonical_extension}"
    return upload_file_to_cloud(file_data, unique_filename, content_type)


def upload_request_pdf(file_storage, prefix):
    if not file_storage or not file_storage.filename:
        return None

    original_name = secure_filename(file_storage.filename)
    if not original_name:
        raise ValueError("Invalid filename")

    file_data = file_storage.read()
    if not file_data:
        raise ValueError("Uploaded file is empty")

    if "." not in original_name:
        raise ValueError("Missing file extension")

    extension = original_name.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_PDF_EXTENSIONS:
        raise ValueError("Only PDF files are allowed")

    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_suffix = secrets.token_hex(8)
    unique_filename = f"{prefix}_{timestamp}_{random_suffix}.pdf"
    return upload_file_to_cloud(file_data, unique_filename, "application/pdf")


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
    os.getenv("MAX_CONTENT_LENGTH", str(100 * 1024 * 1024))
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.getenv(
    "SESSION_COOKIE_SAMESITE", "Lax"
)
app.config["SESSION_COOKIE_SECURE"] = parse_bool(
    os.getenv("SESSION_COOKIE_SECURE"),
    default=False,
)

db.init_app(app)

allowed_origins = parse_origins()
# Removed conflicting CORS definition

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


@app.after_request
def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )

    if request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

    if request.path.startswith("/admin") or request.path in {
        "/api/login",
        "/api/logout",
        "/api/check-auth",
    }:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

    return response


@app.route("/send-email", methods=["POST"])
@same_origin_required
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

    subject = f"Ново съобщение от сайта: {name}"

    # Escape HTML entities in user input
    safe_name = html_mod.escape(name)
    safe_email = html_mod.escape(visitor_email)
    safe_message = html_mod.escape(message_content).replace("\n", "<br>")

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background-color:#FBF9F3; font-family: 'Segoe UI', Tahoma, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#FBF9F3; padding:30px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 4px 20px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background: linear-gradient(135deg, #A4242F, #821c25); padding:30px 40px; text-align:center;">
            <h1 style="color:#ffffff; margin:0; font-size:22px; font-weight:700; letter-spacing:0.5px;">
              &#128232; Ново съобщение от сайта
            </h1>
            <p style="color:rgba(255,255,255,0.8); margin:8px 0 0; font-size:14px;">
              НЧ "Пробуда" 1925г. — Контактна форма
            </p>
          </td>
        </tr>

        <!-- Sender Info -->
        <tr>
          <td style="padding:30px 40px 15px;">
            <table width="100%" style="background:#f8f5f0; border-radius:8px; padding:20px; border-left:4px solid #D4A373;">
              <tr>
                <td style="padding:5px 0;">
                  <span style="color:#888; font-size:12px; text-transform:uppercase; letter-spacing:1px;">Изпратено от</span><br>
                  <strong style="color:#3D352E; font-size:16px;">{safe_name}</strong>
                </td>
              </tr>
              <tr>
                <td style="padding:5px 0;">
                  <span style="color:#888; font-size:12px; text-transform:uppercase; letter-spacing:1px;">Имейл адрес</span><br>
                  <a href="mailto:{safe_email}" style="color:#A4242F; font-size:15px; text-decoration:none; font-weight:600;">{safe_email}</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Message Body -->
        <tr>
          <td style="padding:15px 40px 30px;">
            <p style="color:#888; font-size:12px; text-transform:uppercase; letter-spacing:1px; margin:0 0 10px;">Съобщение</p>
            <div style="background:#fdfcfa; border:1px solid #e0dcd1; border-radius:8px; padding:20px; color:#3D352E; font-size:15px; line-height:1.7;">
              {safe_message}
            </div>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8f5f0; padding:20px 40px; text-align:center; border-top:1px solid #e0dcd1;">
            <p style="color:#999; font-size:12px; margin:0;">
              Това съобщение е изпратено автоматично от контактната форма на сайта.<br>
              © {datetime.datetime.now().year} НЧ "Пробуда" 1925г., с. Яворово
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"Website Contact <{EMAIL_ADDRESS}>"
    msg["To"] = RECIPIENT_EMAIL
    msg["Reply-To"] = visitor_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp_server:
            smtp_server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp_server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())

            # Send a simple plain-text confirmation to the visitor
            confirm_body = (
                f"Здравейте, {name}!\n\n"
                "Благодарим Ви, че се свързахте с нас.\n"
                "Вашето съобщение беше получено успешно и ще се постараем "
                "да отговорим възможно най-скоро.\n\n"
                "С уважение,\n"
                "НЧ \"Пробуда\" 1925г.\n"
                "с. Яворово\n"
            )
            confirm_msg = MIMEText(confirm_body, "plain", "utf-8")
            confirm_msg["Subject"] = "Вашето съобщение беше получено — НЧ \"Пробуда\" 1925г."
            confirm_msg["From"] = f"НЧ Пробуда 1925г. <{EMAIL_ADDRESS}>"
            confirm_msg["To"] = visitor_email

            try:
                smtp_server.sendmail(EMAIL_ADDRESS, visitor_email, confirm_msg.as_string())
            except Exception:
                pass  # Don't fail the whole request if confirmation fails

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
    if is_rate_limited("login", limit=100, window_seconds=15 * 60):
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
@same_origin_required
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
    files = request.files.getlist("image")

    if not title or not content:
        return jsonify({"message": "Title and content are required"}), 400

    image_paths = []
    if files:
        for file_storage in files:
            if file_storage and file_storage.filename:
                try:
                    cloud_url = upload_request_image(file_storage, prefix="news")
                    image_paths.append(cloud_url)
                except ValueError as exc:
                    return jsonify({"message": f"{file_storage.filename}: {exc}"}), 400
                except Exception as exc:
                    return jsonify({"message": f"Failed to upload {file_storage.filename}: {exc}"}), 500

    final_image_url = ",".join(image_paths) if image_paths else None

    new_news = News(
        title=title,
        content=content,
        image_url=final_image_url,
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
    images = request.files.getlist("image")

    if title:
        news_item.title = title
    if content:
        news_item.content = content

    if images and any(img.filename for img in images):
        image_paths = []
        for file_storage in images:
            if file_storage and file_storage.filename:
                try:
                    cloud_url = upload_request_image(file_storage, prefix="news")
                    image_paths.append(cloud_url)
                except ValueError as exc:
                    return jsonify({"message": f"{file_storage.filename}: {exc}"}), 400
                except Exception as exc:
                    return jsonify({"message": f"Failed to upload {file_storage.filename}: {exc}"}), 500
        
        # Delete old images if they exist
        if news_item.image_url:
            for old_img in news_item.image_url.split(","):
                delete_cloud_image(old_img.strip())
                
        # We replace the entire old image string
        news_item.image_url = ",".join(image_paths)

    db.session.commit()
    return jsonify({"message": "News updated successfully", "news": news_item.to_dict()}), 200


@app.route("/api/news/<int:news_id>", methods=["DELETE"])
@login_required
@same_origin_required
def delete_news(news_id):
    news_item = News.query.get_or_404(news_id)
    if news_item.image_url:
        for img_url in news_item.image_url.split(","):
            delete_cloud_image(img_url.strip())
    db.session.delete(news_item)
    db.session.commit()
    return jsonify({"message": "News deleted successfully!"}), 200


@app.route("/api/newspapers", methods=["GET"])
def get_newspapers():
    newspapers = Newspaper.query.order_by(Newspaper.date_published.desc()).all()
    return jsonify([n.to_dict() for n in newspapers]), 200


@app.route("/api/newspapers", methods=["POST"])
@login_required
@same_origin_required
def add_newspaper():
    title = normalize_text(request.form.get("title"), max_length=200)
    pdf_file = request.files.get("pdf")
    thumbnail_file = request.files.get("thumbnail")

    if not title or not pdf_file:
        return jsonify({"message": "Title and PDF file are required"}), 400

    try:
        pdf_url = upload_request_pdf(pdf_file, prefix="newspaper")
        thumbnail_url = None
        if thumbnail_file:
            thumbnail_url = upload_request_image(thumbnail_file, prefix="newspaper_thumb")

        new_issue = Newspaper(
            title=title,
            pdf_url=pdf_url,
            thumbnail_url=thumbnail_url
        )
        db.session.add(new_issue)
        db.session.commit()
        return jsonify({"message": "Newspaper added successfully!"}), 201
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"message": f"Failed to upload: {exc}"}), 500


@app.route("/api/newspapers/<int:newspaper_id>", methods=["DELETE"])
@login_required
@same_origin_required
def delete_newspaper(newspaper_id):
    issue = Newspaper.query.get_or_404(newspaper_id)
    if issue.pdf_url:
        delete_cloud_image(issue.pdf_url)
    if issue.thumbnail_url:
        delete_cloud_image(issue.thumbnail_url)
    db.session.delete(issue)
    db.session.commit()
    return jsonify({"message": "Newspaper deleted successfully!"}), 200


@app.route("/api/gallery", methods=["GET"])
def get_gallery():
    images = GalleryImage.query.order_by(GalleryImage.date_uploaded.desc()).all()
    return jsonify([img.to_dict() for img in images])


@app.route("/api/gallery", methods=["POST"])
@login_required
@same_origin_required
def upload_image():
    files = request.files.getlist("image")
    if not files or all(not f.filename for f in files):
        return jsonify({"message": "No image selected"}), 400

    caption = normalize_text(request.form.get("caption"), max_length=255)
    uploaded = 0
    errors = []

    for file_storage in files:
        if not file_storage or not file_storage.filename:
            continue
        try:
            cloud_url = upload_request_image(file_storage, prefix="gallery")
            new_image = GalleryImage(filename=cloud_url, caption=caption)
            db.session.add(new_image)
            uploaded += 1
        except ValueError as exc:
            errors.append(f"{file_storage.filename}: {exc}")
        except Exception as exc:
            errors.append(f"{file_storage.filename}: {exc}")

    db.session.commit()

    if uploaded == 0:
        return jsonify({"message": "No images uploaded. " + "; ".join(errors)}), 400

    msg = f"{uploaded} image(s) uploaded successfully."
    if errors:
        msg += f" {len(errors)} failed: " + "; ".join(errors)
    return jsonify({"message": msg}), 201


@app.route("/api/proxy-pdf")
def proxy_pdf():
    url = request.args.get("url")
    if not url:
        return "Missing URL", 400
    
    # Simple validation: only allow R2 or own origin
    allowed_domains = ["r2.dev", "127.0.0.1", "localhost"]
    parsed_url = urlparse(url)
    if not any(domain in parsed_url.netloc for domain in allowed_domains):
        return "Unauthorized domain", 403

    import requests as py_requests
    try:
        resp = py_requests.get(url, stream=True)
        headers = dict(resp.headers)
        # Remove some headers that might cause issues
        headers.pop("Transfer-Encoding", None)
        headers.pop("Content-Encoding", None)
        return (resp.content, resp.status_code, headers.items())
    except Exception as e:
        return str(e), 500


# --- EVENTS API ---

@app.route("/api/events", methods=["GET"])
def get_events():
    # Fetch all events. In a real scenario we might order by date_event
    events = Event.query.order_by(Event.id.asc()).all()
    return jsonify({"events": [e.to_dict() for e in events]}), 200


@app.route("/api/events", methods=["POST"])
@login_required
@same_origin_required
def add_event():
    data = request.json
    if not data or not data.get("title") or not data.get("date_event"):
        return jsonify({"message": "Въведете заглавие и дата"}), 400
    
    new_event = Event(
        title=data.get("title"),
        date_event=data.get("date_event"),
        time_event=data.get("time_event", ""),
        location=data.get("location", ""),
        description=data.get("description", "")
    )
    db.session.add(new_event)
    db.session.commit()
    return jsonify({"message": "Събитието е добавено успешно!", "event": new_event.to_dict()}), 201


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
@login_required
@same_origin_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({"message": "Събитието е изтрито"}), 200


@app.route("/api/events/<int:event_id>", methods=["PUT"])
@login_required
@same_origin_required
def update_event(event_id):
    event = Event.query.get_or_404(event_id)
    data = request.json
    if not data or not data.get("title") or not data.get("date_event"):
        return jsonify({"message": "Въведете заглавие и дата"}), 400
    
    event.title = data.get("title")
    event.date_event = data.get("date_event")
    event.time_event = data.get("time_event", "")
    event.location = data.get("location", "")
    event.description = data.get("description", "")
    
    db.session.commit()
    return jsonify({"message": "Събитието е обновено!", "event": event.to_dict()}), 200


@app.route("/admin/<path:filename>")
def admin_static(filename):
    return send_from_directory(os.path.join(BASE_DIR, "..", "admin"), filename)


@app.route("/admin/")
def admin_index():
    return send_from_directory(os.path.join(BASE_DIR, "..", "admin"), "index.html")


@app.route("/<path:filename>")
def root_static(filename):
    return send_from_directory(os.path.join(BASE_DIR, ".."), filename)


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
