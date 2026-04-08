import getpass
import os

from werkzeug.security import generate_password_hash

from app import app, db
from database import User


def reset_admin_password():
    username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"Error: User '{username}' does not exist. Run create_admin.py instead.")
            return

        password = getpass.getpass("Enter NEW admin password: ")
        confirm_password = getpass.getpass("Confirm NEW admin password: ")

        if password != confirm_password:
            print("Error: Passwords do not match.")
            return
            
        if len(password) < 12:
            print("Error: Admin password must be at least 12 characters long.")
            return

        user.password_hash = generate_password_hash(password, method="scrypt")
        db.session.commit()
        print(f"Successfully updated password for user: {username}")


if __name__ == "__main__":
    reset_admin_password()
