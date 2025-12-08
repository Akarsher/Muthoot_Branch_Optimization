import sqlite3
from config import DB_PATH
import hashlib

def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

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

    # Branch managers table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS branch_managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact_no TEXT NOT NULL,
            branch_id INTEGER NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(branch_id) REFERENCES branches(id)
        )
        """
    )

    # Auth tables
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS auditors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_by_admin_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by_admin_id) REFERENCES admins(id)
        )
        """
    )

    # Ensure HQ exists
    cur.execute("SELECT id FROM branches WHERE is_hq=1")
    if not cur.fetchone():
        cur.execute("""
        INSERT INTO branches (name, address, lat, lng, visited, is_hq)
        VALUES ('HQ', 'Main Headquarters', 10.0000, 76.0000, 0, 1)
        """)  # replace lat/lng with actual HQ coords

    # Ensure at least one admin exists (dev default)
    cur.execute("SELECT id FROM admins LIMIT 1")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            ("admin", _hash_password("admin123")),
        )

    conn.commit()
    conn.close()
    
    create_location_tracking_tables()

def create_location_tracking_tables():
    """Create tables for live location tracking"""
    import sqlite3
    from config import DB_PATH
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table to store real-time auditor locations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auditor_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auditor_id INTEGER NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            accuracy REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            session_id INTEGER,
            status TEXT DEFAULT 'traveling',
            FOREIGN KEY (auditor_id) REFERENCES auditors (id)
        )
    """)
    
    # Table to track tracking sessions (when auditor starts/stops tracking)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracking_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auditor_id INTEGER NOT NULL,
            start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            end_time DATETIME,
            route_data TEXT,
            total_distance REAL,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (auditor_id) REFERENCES auditors (id)
        )
    """)
    
    conn.commit()
    conn.close()
    print("✅ Location tracking tables created successfully")
