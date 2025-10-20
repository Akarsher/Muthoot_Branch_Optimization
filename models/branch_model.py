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
