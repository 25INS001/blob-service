from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            # Check if column exists
            with db.engine.connect() as conn:
                # This query supports PostgreSQL which seems to be the target DB
                result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='devices' AND column_name='stats'"))
                if result.rowcount > 0:
                    print("Column 'stats' already exists.")
                    return

                print("Adding 'stats' column to 'devices' table...")
                conn.execute(text("ALTER TABLE devices ADD COLUMN stats JSON"))
                conn.commit()
                print("Migration successful.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
