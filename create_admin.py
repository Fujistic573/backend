import getpass
import os

from werkzeug.security import generate_password_hash

from app import app, db
from database import User


def get_password():
    password = os.getenv("ADMIN_PASSWORD")
    if password:
        return password

    password = getpass.getpass("Enter admin password: ")
    confirm_password = getpass.getpass("Confirm admin password: ")

    if password != confirm_password:
        raise ValueError("Passwords do not match.")

    return password


def create_admin():
    username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    password = get_password()

    if len(password) < 12:
        raise ValueError("Admin password must be at least 12 characters long.")

    with app.app_context():
        db.create_all()

        user = User.query.filter_by(username=username).first()
        if user:
            print(f"User {username} already exists.")
            return

        hashed_pw = generate_password_hash(password, method="scrypt")
        new_user = User(username=username, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        print(f"Created admin user: {username}")


if __name__ == "__main__":
    create_admin()
