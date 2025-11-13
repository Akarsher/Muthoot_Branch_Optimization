import os
import sqlite3
import json
import argparse
from pprint import pprint

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
    return [dict(r) for r in cur.fetchall()]

def branches_checks(conn):
    cur = conn.cursor()
    info = {}
    info['total'] = row_count(conn, 'branches')
    # visited / unvisited
    cur.execute("SELECT COUNT(*) AS c FROM branches WHERE visited = 1")
    info['visited'] = cur.fetchone()['c']
    info['unvisited'] = info['total'] - info['visited']
    # HQ lookup (common keywords)
    cur.execute("""
        SELECT id,name,address,lat,lng,visited
        FROM branches
        WHERE name LIKE '%Pezhakkapilly%' OR address LIKE '%Pezhakkapilly%' 
           OR name LIKE '%Muvattupuzha%' OR address LIKE '%Muvattupuzha%'
        LIMIT 20
    """)
    info['hq_candidates'] = [dict(r) for r in cur.fetchall()]
    # missing lat/lng
    cur.execute("""
        SELECT id,name,address,lat,lng
        FROM branches
        WHERE lat IS NULL OR lng IS NULL OR trim(lat) = '' OR trim(lng) = ''
        LIMIT 50
    """)
    info['missing_latlng_sample'] = [dict(r) for r in cur.fetchall()]
    # distinct value types for lat/lng (quick sanity)
    cur.execute("SELECT DISTINCT typeof(lat) as tlat, typeof(lng) as tlng FROM branches LIMIT 10")
    info['latlng_types'] = [dict(r) for r in cur.fetchall()]
    return info

def analyze(db_path, sample_limit=10, to_json=None):
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
    conn.close()
    if to_json:
        with open(to_json, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    return out

def main():
    parser = argparse.ArgumentParser(description="Analyze SQLite DB tables (branches.db)")
    parser.add_argument('--db', default=os.path.join(os.path.dirname(__file__), 'data', 'branches.db'), help='Path to SQLite DB')
    parser.add_argument('--sample', type=int, default=10, help='Rows sample limit per table')
    parser.add_argument('--json', help='Write analysis to JSON file')
    args = parser.parse_args()

    try:
        result = analyze(args.db, sample_limit=args.sample, to_json=args.json)
        print("\nDatabase analysis summary:\n")
        print("DB path:", result['db_path'])
        print("Tables found:", ", ".join(result['tables']) if result['tables'] else "None")
        if 'branches' in result['tables']:
            bc = result['branches_checks']
            print(f"\nBranches: total={bc['total']}, visited={bc['visited']}, unvisited={bc['unvisited']}")
            print(f"HQ candidates (by name/address keywords): {len(bc['hq_candidates'])}")
            if bc['hq_candidates']:
                print(" Sample HQ rows:")
                pprint(bc['hq_candidates'][:5])
            print(f"Rows missing lat/lng: {len(bc['missing_latlng_sample'])} (showing up to sample limit)")
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