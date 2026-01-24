import sys
import os

# Add parent dir to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        print("Migrating devices table...")
        
        # Check if user_id column exists
        with db.engine.connect() as conn:
            # Postgres specific query to check columns
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='devices'"))
            columns = [row[0] for row in result.fetchall()]
            
            if 'user_id' not in columns:
                print("Adding user_id column...")
                conn.execute(text("ALTER TABLE devices ADD COLUMN user_id VARCHAR(255)"))
                conn.execute(text("CREATE INDEX ix_devices_user_id ON devices (user_id)"))
            else:
                print("user_id column already exists.")

            if 'friendly_name' not in columns:
                print("Adding friendly_name column...")
                conn.execute(text("ALTER TABLE devices ADD COLUMN friendly_name VARCHAR(255)"))
            else:
                print("friendly_name column already exists.")
            
            conn.commit()
            print("Migration complete.")

if __name__ == "__main__":
    migrate()
