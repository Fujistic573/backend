from app import app, db, User
from werkzeug.security import generate_password_hash

def create_admin():
    with app.app_context():
        db.create_all()
        
        username = "admin"
        password = "admin123" # DEFAULT PASSWORD
        
        user = User.query.filter_by(username=username).first()
        if user:
            print(f"User {username} already exists.")
        else:
            hashed_pw = generate_password_hash(password, method='scrypt')
            new_user = User(username=username, password_hash=hashed_pw)
            db.session.add(new_user)
            db.session.commit()
            print(f"Created admin user: {username} / {password}")

if __name__ == "__main__":
    create_admin()
