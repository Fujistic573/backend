import os
import shutil
from app import app, db, GalleryImage

# Source is the project root (parent of backend)
SOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../uploads')

os.makedirs(TARGET_DIR, exist_ok=True)

valid_extensions = ('.jpg', '.jpeg', '.png')

def migrate():
    with app.app_context():
        # Create tables if not exist
        db.create_all()
        
        print(f"Scanning {SOURCE_DIR} for images...")
        count = 0
        for filename in os.listdir(SOURCE_DIR):
            if filename.lower().endswith(valid_extensions) and "logo" not in filename:
                # Copy file to uploads
                src_path = os.path.join(SOURCE_DIR, filename)
                dst_path = os.path.join(TARGET_DIR, filename)
                
                if not os.path.exists(dst_path):
                    shutil.copy(src_path, dst_path)
                    print(f"Copied {filename}")
                
                # Check DB
                exists = GalleryImage.query.filter_by(filename=filename).first()
                if not exists:
                    new_img = GalleryImage(filename=filename, caption="Migrated Image")
                    db.session.add(new_img)
                    count += 1
        
        db.session.commit()
        print(f"Migration complete. Added {count} images to database.")

if __name__ == "__main__":
    migrate()
