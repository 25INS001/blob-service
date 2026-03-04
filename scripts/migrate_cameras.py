import sys
import os

# Add parent dir to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        print("Migrating devices table for cameras...")
        
        with db.engine.connect() as conn:
            # Postgres specific query to check columns
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='devices'"))
            columns = [row[0] for row in result.fetchall()]
            
            if 'available_cameras' not in columns:
                print("Adding available_cameras column...")
                conn.execute(text("ALTER TABLE devices ADD COLUMN available_cameras JSON"))
            else:
                print("available_cameras column already exists.")

            if 'active_camera_command' not in columns:
                print("Adding active_camera_command column...")
                conn.execute(text("ALTER TABLE devices ADD COLUMN active_camera_command VARCHAR(255)"))
            else:
                print("active_camera_command column already exists.")
            
            conn.commit()
            print("Migration complete.")

if __name__ == "__main__":
    migrate()
