import os, shutil, datetime, sqlite3, sys
db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'branches.db'))
if not os.path.exists(db_path):
    print("Database not found:", db_path); sys.exit(1)
bak = db_path + '.bak.' + datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
shutil.copy2(db_path, bak)
print("Backup created:", bak)
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("PRAGMA table_info(branch_managers);")
cols = [r[1] for r in cur.fetchall()]
if 'password_hash' not in cols:
    print("No password_hash column found. Nothing to do.")
else:
    cur.execute("UPDATE branch_managers SET password_hash = NULL;")
    print("Cleared password_hash for", cur.rowcount, "row(s).")
    conn.commit()
conn.close()