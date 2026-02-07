"""
Add is_featured column to News table
Run this script once to update the database
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from database import News

with app.app_context():
    try:
        # Try to add the column using ALTER TABLE
        db.session.execute(db.text('ALTER TABLE news ADD COLUMN is_featured BOOLEAN DEFAULT 0'))
        db.session.commit()
        print("Successfully added is_featured column to news table!")
    except Exception as e:
        print(f"Column may already exist or error occurred: {e}")
        print("If column exists, this is fine. Otherwise, run: flask db migrate")
