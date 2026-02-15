from app import app, db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE devices ADD COLUMN terminal_requested BOOLEAN DEFAULT FALSE"))
            print("Added terminal_requested")
        except Exception as e:
            print(f"terminal_requested might exist: {e}")
            
        try:
            conn.execute(text("ALTER TABLE devices ADD COLUMN terminal_port INTEGER"))
            print("Added terminal_port")
        except Exception as e:
            print(f"terminal_port might exist: {e}")
            
        conn.commit()
        print("Migration finished")
