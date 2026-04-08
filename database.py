from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500))
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    source_link = db.Column(db.String(500))  # Link to Facebook post if applicable
    is_featured = db.Column(db.Boolean, default=False)  # For pinned/featured news

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'image_url': self.image_url,
            'date_posted': self.date_posted.strftime('%Y-%m-%d %H:%M:%S'),
            'source_link': self.source_link,
            'is_featured': self.is_featured
        }

class ContactMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    date_sent = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'message': self.message,
            'date_sent': self.date_sent.strftime('%Y-%m-%d %H:%M:%S')
        }

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

class GalleryImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(255), nullable=True)
    date_uploaded = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'caption': self.caption,
            'date_uploaded': self.date_uploaded.strftime('%Y-%m-%d %H:%M:%S')
        }

class Newspaper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    pdf_url = db.Column(db.String(500), nullable=False)
    thumbnail_url = db.Column(db.String(500))  # Link to cover image
    date_published = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'pdf_url': self.pdf_url,
            'thumbnail_url': self.thumbnail_url,
            'date_published': self.date_published.strftime('%Y-%m-%d %H:%M:%S')
        }

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    date_event = db.Column(db.String(50), nullable=False) # e.g., "2026-05-24" or "24 Май"
    time_event = db.Column(db.String(50))                 # e.g., "18:30 ч."
    location = db.Column(db.String(200))                  # e.g., "Лятна сцена"
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'date_event': self.date_event,
            'time_event': self.time_event,
            'location': self.location,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
