"""
Migrate existing local uploads to Cloudflare R2 Cloud Storage
This script:
1. Reads all local images from uploads/ folder
2. Uploads them to R2
3. Updates database URLs to point to R2
"""
import os
import sys
sys.path.insert(0, '.')

from cloud_storage import upload_file_to_cloud, R2_PUBLIC_URL
from database import db, News, GalleryImage
from flask import Flask
from dotenv import load_dotenv
import mimetypes

load_dotenv()

# Create Flask app for database context
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chitalishte.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

UPLOADS_FOLDER = '../uploads'

def get_content_type(filename):
    """Get MIME type from filename"""
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or 'application/octet-stream'

def migrate_local_files():
    """Upload all local files to R2"""
    print("=" * 50)
    print("MIGRATING LOCAL FILES TO CLOUDFLARE R2")
    print("=" * 50)
    
    if not os.path.exists(UPLOADS_FOLDER):
        print(f"Uploads folder not found: {UPLOADS_FOLDER}")
        return
    
    files = os.listdir(UPLOADS_FOLDER)
    print(f"Found {len(files)} files to migrate\n")
    
    migrated = []
    failed = []
    
    for filename in files:
        file_path = os.path.join(UPLOADS_FOLDER, filename)
        if not os.path.isfile(file_path):
            continue
            
        print(f"Uploading: {filename}...", end=" ")
        
        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            content_type = get_content_type(filename)
            cloud_url = upload_file_to_cloud(file_data, filename, content_type)
            
            migrated.append((filename, cloud_url))
            print("OK")
            
        except Exception as e:
            failed.append((filename, str(e)))
            print(f"FAILED: {e}")
    
    print(f"\n{len(migrated)} files uploaded, {len(failed)} failed")
    return migrated, failed

def update_database(migrated_files):
    """Update database URLs to point to R2"""
    print("\n" + "=" * 50)
    print("UPDATING DATABASE REFERENCES")
    print("=" * 50)
    
    # Create a mapping of old filename -> new cloud URL
    url_map = {filename: cloud_url for filename, cloud_url in migrated_files}
    
    with app.app_context():
        # Update News items
        news_items = News.query.all()
        news_updated = 0
        
        for item in news_items:
            if item.image_url and not item.image_url.startswith('http'):
                # It's a local filename, update to cloud URL
                if item.image_url in url_map:
                    item.image_url = url_map[item.image_url]
                    news_updated += 1
                    print(f"Updated news ID {item.id}: {item.title[:30]}...")
        
        # Update Gallery items
        gallery_items = GalleryImage.query.all()
        gallery_updated = 0
        
        for item in gallery_items:
            if item.filename and not item.filename.startswith('http'):
                # It's a local filename, update to cloud URL
                if item.filename in url_map:
                    item.filename = url_map[item.filename]
                    gallery_updated += 1
                    print(f"Updated gallery ID {item.id}")
        
        db.session.commit()
        
        print(f"\nUpdated {news_updated} news items")
        print(f"Updated {gallery_updated} gallery items")

def main():
    print("\n[R2 MIGRATION SCRIPT]\n")
    
    # Step 1: Upload files to R2
    migrated, failed = migrate_local_files()
    
    if not migrated:
        print("No files were migrated. Exiting.")
        return
    
    # Step 2: Update database
    update_database(migrated)
    
    print("\n" + "=" * 50)
    print("MIGRATION COMPLETE!")
    print("=" * 50)
    print("\nYour local images are now on Cloudflare R2 CDN.")
    print("You can safely backup and remove the uploads/ folder.")

if __name__ == "__main__":
    main()
