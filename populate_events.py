from database import db, Event
from app import app

with app.app_context():
    events_data = [
        {
            "title": "Ден на лозаря - Трифон Зарезан", 
            "date_event": "2026-02-14", 
            "time_event": "10:30", 
            "location": "Площада пред читалището", 
            "description": "Традиционно зарязване на лозите с участието на фолклорния ансамбъл. Заповядайте на чаша домашно вино и кръшно българско хоро!"
        },
        {
            "title": "Баба Марта бързала...", 
            "date_event": "2026-03-01", 
            "time_event": "14:00", 
            "location": "Голям салон на читалището", 
            "description": "Творческа работилница за деца и възрастни за изработване на традиционни мартеници. Материалите са осигурени от нас."
        },
        {
            "title": "Празник на буквите", 
            "date_event": "2026-05-24", 
            "time_event": "18:30", 
            "location": "Лятна сцена", 
            "description": "Тържествен концерт по случай Деня на светите братя Кирил и Методий. Изпълнения на самодейните състави към читалището."
        }
    ]
    
    added_count = 0
    for ed in events_data:
        # Check if an event with this title already exists
        if not Event.query.filter_by(title=ed['title']).first():
            new_event = Event(**ed)
            db.session.add(new_event)
            added_count += 1
            
    db.session.commit()
    print(f"Added {added_count} events to the database.")
