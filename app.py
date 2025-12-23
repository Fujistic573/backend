import os
import smtplib
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from database import db, News, ContactMessage, User, GalleryImage
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import datetime

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chitalishte.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_super_secret_key_change_this_later' # For sessions
app.config['UPLOAD_FOLDER'] = '../uploads' # Folder to store images relative to backend


db.init_app(app)

# Allow your frontend origins explicitly
# Allow all origins for development to avoid issues with file:// or different ports
CORS(app, supports_credentials=True)

# Create tables
with app.app_context():
    db.create_all()

# --- EMAIL CONFIGURATION ---
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL', EMAIL_ADDRESS)

# Проверка дали основните данни са зададени
if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
    print("ГРЕШКА: Данните за имейл (EMAIL_ADDRESS, EMAIL_PASSWORD) не са зададени като променливи на средата.")

@app.route('/send-email', methods=['POST'])
def send_email():
    try:
        # Вземи данните от формата
        name = request.form['name']
        visitor_email = request.form['email']
        message_content = request.form['message']

        # Save to Database
        new_message = ContactMessage(name=name, email=visitor_email, message=message_content)
        db.session.add(new_message)
        db.session.commit()

        if not RECIPIENT_EMAIL:
             return jsonify({
                "status": "success",
                "message": "Съобщението е запазено в базата данни (Имейл не е конфигуриран)."
            })

        # Създай съдържанието на имейла
        subject = f"Ново съобщение от сайта от {name}"
        body = f"""
        Име: {name}
        Имейл: {visitor_email}
        
        Съобщение:
        {message_content}
        """

        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = f"Сайт на с. Яворово <{EMAIL_ADDRESS}>"
        msg['To'] = RECIPIENT_EMAIL
        msg['Reply-To'] = visitor_email

        # Изпрати имейла
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp_server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())

        return jsonify({
            "status": "success",
            "message": "Съобщението е изпратено успешно и запазено!"
        })

    except Exception as e:
        print(f"Възникна грешка: {e}")
        return jsonify({
            "status": "error",
            "message": "Възникна грешка при изпращането на съобщението."
        }), 500

# --- NEWS ROUTES ---
# --- AUTH ROUTES ---
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    user = User.query.filter_by(username=username).first()

    if user and check_password_hash(user.password_hash, password):
        session['user_id'] = user.id
        return jsonify({"message": "Logged in successfully", "status": "success"}), 200
    
    return jsonify({"message": "Invalid credentials", "status": "error"}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({"message": "Logged out"}), 200

@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    if 'user_id' in session:
        return jsonify({"authenticated": True}), 200
    return jsonify({"authenticated": False}), 200

# --- Helper for protecting routes ---
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"message": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --- NEWS ROUTES ---
@app.route('/api/news', methods=['GET'])
def get_news():
    news_list = News.query.order_by(News.date_posted.desc()).all()
    return jsonify([news.to_dict() for news in news_list])

@app.route('/api/news', methods=['POST'])
@app.route('/api/news', methods=['POST'])
def add_news():
    # 1. Handle JSON (Scraper)
    if request.is_json:
        data = request.get_json()
        
        # --- DUPLICATE PREVENTION (Scraper Logic) ---
        if data.get('source_link') and "profile.php?id=" not in data['source_link']:
            existing_link = News.query.filter_by(source_link=data['source_link']).first()
            if existing_link:
                return jsonify({"message": "News already exists (link match)"}), 200

        if data.get('image_url'):
            existing_image = News.query.filter_by(image_url=data['image_url']).first()
            if existing_image:
                 return jsonify({"message": "News already exists (image match)"}), 200

        existing_title = News.query.filter_by(title=data['title']).first()
        if existing_title:
            return jsonify({"message": "News already exists (title match)"}), 200
        
        new_news = News(
            title=data['title'],
            content=data['content'],
            image_url=data.get('image_url'),
            source_link=data.get('source_link')
        )
        db.session.add(new_news)
        db.session.commit()
        return jsonify({"message": "News added successfully (Scraper)!"}), 201

    # 2. Handle Multipart/FormData (Admin Panel Manual Add)
    else:
        # Auth Check for manual add
        if 'user_id' not in session:
             return jsonify({"message": "Authentication required"}), 401
             
        title = request.form.get('title')
        content = request.form.get('content')
        file = request.files.get('image')
        
        if not title or not content:
             return jsonify({"message": "Title and Content are required"}), 400

        image_path = None
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            unique_filename = f"news_{timestamp}_{filename}"
            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            file.save(upload_path)
            # Store relative path for frontend to use
            # We will serve this via the /uploads route or /api/uploads
            # Actually, standardizing on full URL generation in frontend is better, 
            # but let's store the filename or relative path that our frontend expects.
            # The gallery stores just filename using `timestamp_filename`. 
            # We'll do same here for consistency.
            image_path = unique_filename
            
        new_news = News(
            title=title,
            content=content,
            image_url=image_path, # In frontend we will check if it starts with http
            source_link=None # Manual news usually has no external link
        )
        db.session.add(new_news)
        db.session.commit()
        return jsonify({"message": "News added successfully!"}), 201


@app.route('/api/news/<int:id>', methods=['PUT'])
@login_required # ONLY ADMIN CAN EDIT
def update_news(id):
    news_item = News.query.get_or_404(id)
    
    title = request.form.get('title')
    content = request.form.get('content')
    image = request.files.get('image')

    if title:
        news_item.title = title
    if content:
        news_item.content = content
        
    if image and image.filename != '':
        # Generate unique filename for new image
        filename = secure_filename(image.filename)
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        unique_filename = f"news_{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        image.save(file_path)
        
        # Delete old image if it was a local file
        if news_item.image_url and not news_item.image_url.startswith('http'):
             # Note: image_url might be just filename or path. 
             # We store just filename usually.
             old_file_path = os.path.join(app.config['UPLOAD_FOLDER'], news_item.image_url)
             if os.path.exists(old_file_path):
                 try:
                    os.remove(old_file_path)
                 except:
                    pass # Ignore error if file doesn't exist
        
        news_item.image_url = unique_filename

    db.session.commit()
    return jsonify({"message": "News updated successfully!", "news": news_item.to_dict()}), 200

@app.route('/api/news/<int:id>', methods=['DELETE'])
@login_required # ONLY ADMIN CAN DELETE
def delete_news(id):
    news_item = News.query.get_or_404(id)
    db.session.delete(news_item)
    db.session.commit()
    return jsonify({"message": "News deleted"}), 200


# --- GALLERY ROUTES ---
@app.route('/api/gallery', methods=['GET'])
def get_gallery():
    images = GalleryImage.query.order_by(GalleryImage.date_uploaded.desc()).all()
    return jsonify([img.to_dict() for img in images])

@app.route('/api/gallery', methods=['POST'])
@login_required # ADMIN ONLY
def upload_image():
    if 'image' not in request.files:
        return jsonify({"message": "No image part"}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"message": "No selected file"}), 400
    
    if file:
        filename = secure_filename(file.filename)
        # Ensure unique filename to prevent overwrites
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        unique_filename = f"{timestamp}_{filename}"
        
        # Save to uploads folder (ensure it exists)
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        # Ensure directory exists
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)
        
        file.save(upload_path)
        
        # Add to DB
        new_image = GalleryImage(filename=unique_filename, caption=request.form.get('caption', ''))
        db.session.add(new_image)
        db.session.commit()
        
        return jsonify({"message": "Image uploaded successfully"}), 201

@app.route('/api/gallery/<int:id>', methods=['DELETE'])
@login_required # ADMIN ONLY
def delete_image(id):
    image = GalleryImage.query.get_or_404(id)
    
    # Remove file from disk
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        
    db.session.delete(image)
    db.session.commit()
    return jsonify({"message": "Image deleted"}), 200

# Serve uploaded files
@app.route('/uploads/<filename>')
def serve_uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Ensure tables exist
    app.run(debug=True)