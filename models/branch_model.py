import sqlite3
from config import DB_PATH

def create_tables():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS branches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        visited INTEGER DEFAULT 0,
        is_hq INTEGER DEFAULT 0
    )
    """)

    # Ensure HQ exists
    cur.execute("SELECT id FROM branches WHERE is_hq=1")
    if not cur.fetchone():
        cur.execute("""
        INSERT INTO branches (name, address, lat, lng, visited, is_hq)
        VALUES ('HQ', 'Main Headquarters', 10.0000, 76.0000, 0, 1)
        """)  # replace lat/lng with actual HQ coords

    conn.commit()
    conn.close()
