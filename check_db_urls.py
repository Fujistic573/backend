"""Check database URLs after migration"""
import sys
sys.path.insert(0, '.')

from database import db, News, GalleryImage
from flask import Flask

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chitalishte.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

with app.app_context():
    print("=== NEWS IMAGES ===")
    news_items = News.query.limit(5).all()
    for item in news_items:
        print(f"ID {item.id}: {item.image_url}")
    
    print("\n=== GALLERY IMAGES ===")
    gallery_items = GalleryImage.query.limit(5).all()
    for item in gallery_items:
        print(f"ID {item.id}: {item.filename}")
