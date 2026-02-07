"""
Fix database URLs to use correct R2 public URL
"""
import sys
sys.path.insert(0, '.')

from database import db, News, GalleryImage
from flask import Flask
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chitalishte.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

OLD_URL = "https://pub-c82065479da0bf779415690952349642.r2.dev"
NEW_URL = os.getenv('R2_PUBLIC_URL')

print(f"Updating URLs from {OLD_URL} to {NEW_URL}")

with app.app_context():
    # Fix Gallery
    gallery_items = GalleryImage.query.filter(GalleryImage.filename.like(f'{OLD_URL}%')).all()
    print(f"\nUpdating {len(gallery_items)} gallery items...")
    
    for item in gallery_items:
        item.filename = item.filename.replace(OLD_URL, NEW_URL)
        print(f"  Gallery ID {item.id}: {item.filename}")
    
    # Fix News  
    news_items = News.query.filter(News.image_url.like(f'{OLD_URL}%')).all()
    print(f"\nUpdating {len(news_items)} news items...")
    
    for item in news_items:
        item.image_url = item.image_url.replace(OLD_URL, NEW_URL)
        print(f"  News ID {item.id}: {item.image_url}")
    
    db.session.commit()
    print("\n✓ Database updated successfully!")
