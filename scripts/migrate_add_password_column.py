import sqlite3
import os
import shutil
import datetime
import sys
import traceback

db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'branches.db')
db_path = os.path.abspath(db_path)

print("DB:", db_path)
if not os.path.exists(db_path):
    print("Database not found. Aborting.")
    raise SystemExit(1)

# create a safe backup first
try:
    bak = db_path + '.bak.' + datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
    shutil.copy2(db_path, bak)
    print("Backup created:", bak)
except Exception as e:
    print("Warning: failed to create backup:", e)

conn = None
try:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(branch_managers);")
    cols = [r[1] for r in cur.fetchall()]

    if 'password' in cols:
        print("password column already exists in branch_managers.")
    else:
        print("Adding password column to branch_managers...")
        cur.execute("ALTER TABLE branch_managers ADD COLUMN password TEXT;")
        conn.commit()
        print("Added password column to branch_managers.")

    # count rows where we will copy password_hash -> password
    cur.execute("""
        SELECT COUNT(*) FROM branch_managers
        WHERE (password IS NULL OR password = '')
          AND (password_hash IS NOT NULL AND password_hash != '')
    """)
    to_copy = cur.fetchone()[0] or 0

    if to_copy:
        print(f"Copying password_hash -> password for {to_copy} row(s)...")
        cur.execute("""
            UPDATE branch_managers
            SET password = password_hash
            WHERE (password IS NULL OR password = '') 
              AND (password_hash IS NOT NULL AND password_hash != '')
        """)
        conn.commit()
        print(f"Copied password_hash -> password for {to_copy} row(s).")
    else:
        print("No rows require copying from password_hash -> password.")

except Exception as e:
    print("Migration failed:", e)
    traceback.print_exc()
    sys.exit(1)
finally:
    if conn:
        conn.close()
    print("Migration finished.")