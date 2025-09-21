import sqlite3
from config import DB_PATH

def add_branch(name, address):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO branches (name, address) VALUES (?, ?)", (name, address))
    conn.commit()
    conn.close()

def get_unvisited_branches():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, name, address FROM branches WHERE visited=0")
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_visited(branch_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE branches SET visited=1 WHERE id=?", (branch_id,))
    conn.commit()
    conn.close()

def reset_visits():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE branches SET visited=0")
    conn.commit()
    conn.close()

def get_all_branches_with_status():
    """Get all branches with their visit status for debugging"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, address, lat, lng, is_hq, visited 
        FROM branches 
        ORDER BY is_hq DESC, name
    """)
    branches = cur.fetchall()
    conn.close()
    return branches

def reset_all_visits():
    """Reset all branches to unvisited (except HQ)"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE branches SET visited=0 WHERE is_hq=0")
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected

def get_branch_count_summary():
    """Get summary of branch counts by type and status"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    summary = {}
    
    # Count by type
    cur.execute("SELECT is_hq, COUNT(*) FROM branches GROUP BY is_hq")
    for is_hq, count in cur.fetchall():
        key = "hq" if is_hq else "branches"
        summary[key] = count
    
    # Count by visit status
    cur.execute("SELECT visited, COUNT(*) FROM branches WHERE is_hq=0 GROUP BY visited")
    for visited, count in cur.fetchall():
        key = "visited" if visited else "unvisited"
        summary[key] = count
    
    conn.close()
    return summary
