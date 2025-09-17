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
