import sqlite3
from config import DB_PATH
from models.branch_model import create_tables

branches = [
    ("Branch A", "Kochi, Kerala", 9.9312, 76.2673),
    ("Branch B", "Thrissur, Kerala", 10.5276, 76.2144),
    ("Branch C", "Trivandrum, Kerala", 8.5241, 76.9366),
    ("Branch D", "Calicut, Kerala", 11.2588, 75.7804)
]

def seed():
    create_tables()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM branches")  # clear old data
    for name, addr, lat, lng in branches:
        cur.execute(
            "INSERT INTO branches (name, address, lat, lng) VALUES (?, ?, ?, ?)",
            (name, addr, lat, lng)
        )
    conn.commit()
    conn.close()
    print("✅ Database seeded with branch data.")

if __name__ == "__main__":
    seed()
