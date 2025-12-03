import sqlite3, os, sys, json, hashlib
from werkzeug.security import check_password_hash

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'branches.db'))

def get_conn():
    return sqlite3.connect(DB_PATH, timeout=5)

def verify_password_variant(stored, plain):
    if stored is None:
        return False
    try:
        if isinstance(stored, (bytes, bytearray)):
            stored = stored.decode('utf-8', 'ignore')
        stored = str(stored).strip()
    except Exception:
        stored = str(stored)
    if not stored:
        return False
    try:
        if isinstance(stored, str) and stored.startswith('pbkdf2:'):
            return check_password_hash(stored, plain)
    except Exception:
        pass
    if isinstance(stored, str) and len(stored) == 64 and all(c in '0123456789abcdefABCDEF' for c in stored):
        try:
            return hashlib.sha256(plain.encode('utf-8')).hexdigest() == stored.lower()
        except Exception:
            pass
    try:
        if check_password_hash(stored, plain):
            return True
    except Exception:
        pass
    return stored == str(plain)

def table_cols(cur, tbl):
    cur.execute(f"PRAGMA table_info({tbl})")
    return [r[1] for r in cur.fetchall()]

def try_table(cur, tbl, username, password):
    cols = table_cols(cur, tbl)
    if 'username' not in cols:
        return None
    cur.execute(f"SELECT * FROM {tbl} WHERE username = ?", (username,))
    row = cur.fetchone()
    if not row:
        return None
    row_map = dict(zip([c[0] for c in cur.description], row)) if hasattr(row, '__iter__') and not isinstance(row, dict) else (row if isinstance(row, dict) else row)
    for fld in ('password_hash', 'password'):
        if fld in cols:
            stored = row_map.get(fld)
            if verify_password_variant(stored, password):
                return {'table': tbl, 'row': row_map}
    return None

def check(username, password, role=''):
    out = {'username': username, 'role_requested': role, 'success': False}
    conn = get_conn()
    cur = conn.cursor()
    try:
        role_l = (role or '').strip().lower()
        if role_l == 'auditor':
            res = try_table(cur, 'auditors', username, password)
            if res:
                out.update({'success': True, 'table': 'auditors', 'matched_role': res['row'].get('role')})
                return out
            return out
        order = ['users','admins','branch_managers','auditors']
        for tbl in order:
            res = try_table(cur, tbl, username, password)
            if res:
                out.update({'success': True, 'table': tbl, 'matched_role': res['row'].get('role')})
                return out
        return out
    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: python check_credentials.py <username> <password> <role>")
        print("role may be 'auditor', 'admin', 'manager' or ''")
        sys.exit(2)
    u, p, r = sys.argv[1], sys.argv[2], sys.argv[3]
    print(json.dumps(check(u,p,r), indent=2))
