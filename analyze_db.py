import os
import sqlite3
import json
import argparse
from pprint import pprint
from werkzeug.security import generate_password_hash

def open_db(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def list_tables(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return [r['name'] for r in cur.fetchall()]

def table_schema(conn, table):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [dict(r) for r in cur.fetchall()]

def row_count(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    return cur.fetchone()['c']

def sample_rows(conn, table, limit=10):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table} LIMIT {limit}")
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def has_column(conn, table, column):
    cols = [c['name'] for c in table_schema(conn, table)]
    return column in cols

def safe_execute(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur

def branches_checks(conn):
    cur = conn.cursor()
    info = {}
    info['total'] = row_count(conn, 'branches')
    # visited / unvisited (tolerant if visited column missing)
    if has_column(conn, 'branches', 'visited'):
        cur.execute("SELECT COUNT(*) AS c FROM branches WHERE visited = 1")
        info['visited'] = cur.fetchone()['c']
        info['unvisited'] = info['total'] - info['visited']
    else:
        info['visited'] = None
        info['unvisited'] = None

    # HQ detection: prefer explicit is_hq column
    if has_column(conn, 'branches', 'is_hq'):
        cur.execute("SELECT id,name,address,lat,lng,visited FROM branches WHERE is_hq=1")
        info['hq_rows'] = [dict(r) for r in cur.fetchall()]
    else:
        # fallback: search by common HQ keywords
        cur.execute("""
            SELECT id,name,address,lat,lng,visited
            FROM branches
            WHERE name LIKE '%Pezhakkapilly%' OR address LIKE '%Pezhakkapilly%'
               OR name LIKE '%Muvattupuzha%' OR address LIKE '%Muvattupuzha%'
            LIMIT 20
        """)
        info['hq_candidates'] = [dict(r) for r in cur.fetchall()]

    # missing lat/lng (tolerant to numeric/text storage)
    cur.execute("""
        SELECT id,name,address,lat,lng
        FROM branches
        WHERE lat IS NULL OR lng IS NULL OR trim(CAST(lat AS TEXT)) = '' OR trim(CAST(lng AS TEXT)) = ''
        LIMIT 50
    """)
    info['missing_latlng_sample'] = [dict(r) for r in cur.fetchall()]

    # distinct value types for lat/lng (quick sanity)
    cur.execute("SELECT DISTINCT typeof(lat) as tlat, typeof(lng) as tlng FROM branches LIMIT 10")
    info['latlng_types'] = [dict(r) for r in cur.fetchall()]

    return info

def hash_plain_passwords(conn, table, id_col='id', pw_col='password'):
    """
    Detect plaintext passwords in `table` and hash them in-place.
    Returns number of rows hashed.
    """
    if table not in list_tables(conn):
        return 0
    cols = [c['name'] for c in table_schema(conn, table)]
    if pw_col not in cols:
        return 0
    cur = conn.cursor()
    cur.execute(f"SELECT {id_col} as uid, {pw_col} as pw FROM {table}")
    to_hash = []
    for r in cur.fetchall():
        pw = r['pw']
        if pw and isinstance(pw, str) and not (pw.startswith('pbkdf2:') or pw.startswith('$')):
            to_hash.append((r['uid'], pw))
    if not to_hash:
        return 0
    for uid, raw in to_hash:
        newhash = generate_password_hash(str(raw))
        safe_execute(conn, f"UPDATE {table} SET {pw_col}=? WHERE {id_col}=?", (newhash, uid))
    conn.commit()
    return len(to_hash)

def ensure_auditors_table(conn):
    """
    Create auditors table if missing (schema aligned with app expectations).
    """
    if 'auditors' not in list_tables(conn):
        safe_execute(conn, """
            CREATE TABLE IF NOT EXISTS auditors (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT,
              email TEXT,
              phone TEXT,
              password TEXT,
              approved INTEGER DEFAULT 0,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        return True
    return False

def analyze(db_path, sample_limit=10, to_json=None, do_fix=False):
    conn = open_db(db_path)
    out = {}
    out['db_path'] = os.path.abspath(db_path)
    out['tables'] = list_tables(conn)
    out['tables_info'] = {}

    for t in out['tables']:
        try:
            out['tables_info'][t] = {
                'schema': table_schema(conn, t),
                'row_count': row_count(conn, t),
                'sample_rows': sample_rows(conn, t, limit=sample_limit)
            }
        except Exception as e:
            out['tables_info'][t] = {'error': str(e)}

    # branches-specific checks if table exists
    if 'branches' in out['tables']:
        out['branches_checks'] = branches_checks(conn)

        # If fix flag set, apply safe fixes
        if do_fix:
            print("\nApplying fixes to branches table where safe...")

            # 1) Ensure lat/lng columns exist
            cols = [c['name'] for c in table_schema(conn, 'branches')]
            added_cols = []
            if 'lat' not in cols:
                print(" - Adding 'lat' column.")
                safe_execute(conn, "ALTER TABLE branches ADD COLUMN lat REAL;")
                added_cols.append('lat')
            if 'lng' not in cols:
                print(" - Adding 'lng' column.")
                safe_execute(conn, "ALTER TABLE branches ADD COLUMN lng REAL;")
                added_cols.append('lng')
            if added_cols:
                conn.commit()
                print("  Added columns:", added_cols)

            # 2) Copy latitude/longitude -> lat/lng if present and lat/lng empty
            cols = [c['name'] for c in table_schema(conn, 'branches')]
            if 'latitude' in cols or 'longitude' in cols:
                print(" - Copying latitude/longitude into lat/lng where missing.")
                cur = conn.execute("SELECT rowid, latitude, longitude, lat, lng FROM branches;")
                updates = []
                for r in cur.fetchall():
                    rowid = r['rowid']
                    lat = r['lat']
                    lng = r['lng']
                    lat2 = r['latitude'] if 'latitude' in r.keys() else None
                    lng2 = r['longitude'] if 'longitude' in r.keys() else None
                    need = False
                    new_lat = lat
                    new_lng = lng
                    if (lat is None or str(lat).strip() == '') and (lat2 is not None and str(lat2).strip() != ''):
                        new_lat = lat2
                        need = True
                    if (lng is None or str(lng).strip() == '') and (lng2 is not None and str(lng2).strip() != ''):
                        new_lng = lng2
                        need = True
                    if need:
                        updates.append((new_lat, new_lng, rowid))
                if updates:
                    for new_lat, new_lng, rowid in updates:
                        safe_execute(conn, "UPDATE branches SET lat=?, lng=? WHERE rowid=?", (new_lat, new_lng, rowid))
                    conn.commit()
                    print(f"  Copied lat/lng into {len(updates)} rows.")
                else:
                    print("  No lat/lng copies required.")

            # 3) Normalize visited to 0/1 if column exists
            if 'visited' in [c['name'] for c in table_schema(conn, 'branches')]:
                print(" - Normalizing 'visited' values to 0/1.")
                cur = conn.execute("SELECT rowid, visited FROM branches;")
                changed = 0
                for r in cur.fetchall():
                    v = r['visited']
                    newv = 0
                    if v is None:
                        newv = 0
                    else:
                        try:
                            newv = int(v)
                            newv = 1 if newv else 0
                        except Exception:
                            sval = str(v).strip().lower()
                            newv = 1 if sval in ('1','true','t','yes','y') else 0
                    if newv != v:
                        safe_execute(conn, "UPDATE branches SET visited=? WHERE rowid=?", (newv, r['rowid']))
                        changed += 1
                if changed:
                    conn.commit()
                print(f"  Normalized visited on {changed} rows.")

            # 4) Ensure single HQ if is_hq exists
            if 'is_hq' in [c['name'] for c in table_schema(conn, 'branches')]:
                cur = conn.execute("SELECT rowid FROM branches WHERE is_hq=1 ORDER BY rowid;")
                hqs = [r['rowid'] for r in cur.fetchall()]
                if len(hqs) > 1:
                    print(f" - Multiple HQs found ({len(hqs)}). Clearing all but first (rowid={hqs[0]}).")
                    for rid in hqs[1:]:
                        safe_execute(conn, "UPDATE branches SET is_hq=0 WHERE rowid=?", (rid,))
                    conn.commit()
                    print("  Cleared extra HQ flags.")
                elif len(hqs) == 0:
                    print(" - No HQ found; marking first branch as HQ.")
                    first = conn.execute("SELECT rowid FROM branches ORDER BY rowid LIMIT 1;").fetchone()
                    if first:
                        safe_execute(conn, "UPDATE branches SET is_hq=1 WHERE rowid=?", (first['rowid'],))
                        conn.commit()
                        print(f"  Marked rowid={first['rowid']} as HQ.")

    # users table: detect plaintext passwords and optionally hash when --fix
    if 'users' in out['tables']:
        cols = [c['name'] for c in table_schema(conn, 'users')]
        if 'password' in cols:
            cur = conn.execute("SELECT id, username, password FROM users;")
            plain = []
            for r in cur.fetchall():
                pw = r['password']
                if pw and isinstance(pw, str) and not (pw.startswith('pbkdf2:') or pw.startswith('$')):
                    plain.append((r['id'], r['username']))
            out['users_plain_password_count'] = len(plain)
            if do_fix and plain:
                print(f"\nHashing {len(plain)} plaintext passwords in users table.")
                for uid, uname in plain:
                    row = conn.execute("SELECT password FROM users WHERE id=?", (uid,)).fetchone()
                    if row:
                        raw = row['password']
                        newhash = generate_password_hash(str(raw))
                        safe_execute(conn, "UPDATE users SET password=? WHERE id=?", (newhash, uid))
                conn.commit()
                print("  Hashed plaintext passwords.")
        else:
            out['users_plain_password_count'] = None

    # auditors table: report and optionally create/hash
    if 'auditors' in out['tables']:
        cols = [c['name'] for c in table_schema(conn, 'auditors')]
        out['auditors_schema'] = cols
        if 'password' in cols:
            cur = conn.execute("SELECT id, name, password FROM auditors;")
            plain = []
            for r in cur.fetchall():
                pw = r['password']
                if pw and isinstance(pw, str) and not (pw.startswith('pbkdf2:') or pw.startswith('$')):
                    plain.append((r['id'], r['name']))
            out['auditors_plain_password_count'] = len(plain)
            if do_fix and plain:
                cnt = hash_plain_passwords(conn, 'auditors', id_col='id', pw_col='password')
                print(f"  Hashed {cnt} plaintext passwords in auditors table.")
        else:
            out['auditors_plain_password_count'] = None
    else:
        out['auditors_schema'] = None
        out['auditors_plain_password_count'] = None
        if do_fix:
            created = ensure_auditors_table(conn)
            if created:
                print("Created 'auditors' table.")

    # managers table: detect and optionally hash plaintext passwords
    if 'managers' in out['tables']:
        cols = [c['name'] for c in table_schema(conn, 'managers')]
        out['managers_schema'] = cols
        if 'password' in cols:
            cur = conn.execute("SELECT id, name, password FROM managers;")
            plain = []
            for r in cur.fetchall():
                pw = r['password']
                if pw and isinstance(pw, str) and not (pw.startswith('pbkdf2:') or pw.startswith('$')):
                    plain.append((r['id'], r['name']))
            out['managers_plain_password_count'] = len(plain)
            if do_fix and plain:
                cnt = hash_plain_passwords(conn, 'managers', id_col='id', pw_col='password')
                print(f"  Hashed {cnt} plaintext passwords in managers table.")
        else:
            out['managers_plain_password_count'] = None

    conn.close()

    if to_json:
        with open(to_json, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

    return out

def main():
    # use the real DB location under the project data/ directory
    default_db = os.path.join(os.path.dirname(__file__), 'data', 'branches.db')
    parser = argparse.ArgumentParser(description="Analyze SQLite DB tables (branches.db)")
    parser.add_argument('--db', default=default_db, help='Path to SQLite DB (default: branches.db in project root)')
    parser.add_argument('--sample', type=int, default=10, help='Rows sample limit per table')
    parser.add_argument('--json', help='Write analysis to JSON file')
    parser.add_argument('--fix', action='store_true', help='Apply safe fixes (add lat/lng, copy latitude/longitude, normalize visited, ensure single HQ, hash plaintext passwords, create auditors table)')
    args = parser.parse_args()

    try:
        result = analyze(args.db, sample_limit=args.sample, to_json=args.json, do_fix=args.fix)
        print("\nDatabase analysis summary:\n")
        print("DB path:", result['db_path'])
        print("Tables found:", ", ".join(result['tables']) if result['tables'] else "None")
        if 'branches' in result['tables']:
            bc = result['branches_checks']
            print(f"\nBranches: total={bc.get('total')}, visited={bc.get('visited')}, unvisited={bc.get('unvisited')}")
            if 'hq_rows' in bc:
                print(f"HQ rows found: {len(bc.get('hq_rows') or [])}")
                if bc.get('hq_rows'):
                    pprint(bc['hq_rows'][:5])
            else:
                cand = bc.get('hq_candidates') or []
                print(f"HQ candidates (by name/address keywords): {len(cand)}")
                if cand:
                    pprint(cand[:5])
            print(f"Rows missing lat/lng (sample): {len(bc.get('missing_latlng_sample') or [])}")
            if bc.get('missing_latlng_sample'):
                pprint(bc['missing_latlng_sample'][:5])
            print("Lat/Lng stored types sample:")
            pprint(bc.get('latlng_types'))
        # auditors summary
        if result.get('auditors_schema') is not None:
            print("\nAuditors table present. Columns:", result['auditors_schema'])
            print("Auditors plaintext password count:", result.get('auditors_plain_password_count'))
        else:
            print("\nAuditors table: NOT PRESENT")
        # managers summary
        if result.get('managers_schema') is not None:
            print("\nManagers table present. Columns:", result['managers_schema'])
            print("Managers plaintext password count:", result.get('managers_plain_password_count'))
        # users summary
        if 'users' in result['tables']:
            print("Users plaintext password count:", result.get('users_plain_password_count'))
        print("\nPer-table schema and sample counts:")
        for t, info in result['tables_info'].items():
            print(f"\nTable: {t}")
            if 'error' in info:
                print(" Error:", info['error'])
                continue
            print(" Columns:")
            for col in info['schema']:
                print(f"  - {col['name']} ({col['type']}) pk={col['pk']}")
            print(" Row count:", info['row_count'])
            print(" Sample rows (first up to sample limit):")
            for r in info['sample_rows'][:min(len(info['sample_rows']), 5)]:
                print("  ", {k: (v if v is not None else None) for k,v in r.items()})
        if args.json:
            print(f"\nWrote full report to {args.json}")
    except Exception as e:
        print("Error during analysis:", e)

if __name__ == '__main__':
    main()