import sqlite3

DB_PATH = "branches.db"

def get_all_branches(include_visited=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if include_visited:
        cursor.execute("SELECT id, name, address, lat, lng, visited, is_hq FROM branches")
    else:
        cursor.execute("SELECT id, name, address, lat, lng, visited, is_hq FROM branches WHERE visited = 0")
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "name": row[1],
            "address": row[2],
            "lat": row[3],
            "lng": row[4],
            "visited": row[5],
            "is_hq": bool(row[6])
        }
        for row in rows
    ]

def get_auditor(username):
    conn = sqlite3.connect('auditors.db')
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM auditors WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"username": row[0]}  # return just username for now
    return None

def mark_branches_visited(branch_ids):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany("UPDATE branches SET visited = 1 WHERE id = ?", [(bid,) for bid in branch_ids])
    conn.commit()
    conn.close()

def reset_visits():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE branches SET visited = 0")
    conn.commit()
    conn.close()

def get_headquarters():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, address, lat, lng FROM branches WHERE is_hq = 1 LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "name": row[1],
            "address": row[2],
            "lat": row[3],
            "lng": row[4]
        }
    return None


