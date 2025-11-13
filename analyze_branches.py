import sqlite3
import os

# Path to the database
db_path = os.path.join('data', 'branches.db')

def analyze_database():
    """Analyze the branches table in the database."""
    if not os.path.exists(db_path):
        print(f"Database not found at: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get table structure
    cursor.execute("PRAGMA table_info(branches);")
    columns = cursor.fetchall()
    
    print("Columns in 'branches' table:")
    print("-" * 50)
    for col in columns:
        print(f"Column: {col[1]}, Type: {col[2]}")
    print("-" * 50)
    
    # Show sample data
    cursor.execute("SELECT * FROM branches LIMIT 5;")
    rows = cursor.fetchall()
    
    print("\nSample data (first 5 rows):")
    for row in rows:
        print(row)
    
    conn.close()

if __name__ == '__main__':
    analyze_database()