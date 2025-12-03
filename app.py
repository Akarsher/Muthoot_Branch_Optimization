from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, g, make_response
import sqlite3
from math import radians, sin, cos, sqrt, atan2, inf
import os
from dotenv import load_dotenv
from os import getenv
from copy import deepcopy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import hashlib
from werkzeug.utils import secure_filename

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

# Database path (absolute)
DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'branches.db')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

def get_db_connection():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn

def calculate_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 0.0
    try:
        R = 6371.0
        lat1_rad = radians(float(lat1))
        lat2_rad = radians(float(lat2))
        delta_lat = radians(float(lat2) - float(lat1))
        delta_lon = radians(float(lon2) - float(lon1))
        a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c
    except Exception:
        return 0.0

def get_hq_location():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM branches WHERE is_hq = 1 LIMIT 1")
    row = cur.fetchone()
    if row:
        conn.close()
        return dict(row)
    cur.execute("""
        SELECT * FROM branches
        WHERE name LIKE '%Pezhakkapilly%' OR address LIKE '%Pezhakkapilly%'
           OR name LIKE '%Muvattupuzha%' OR address LIKE '%Muvattupuzha%'
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def row_to_branch_dict(row):
    try:
        keys = set(row.keys())
        def _get(k, default=None):
            return row[k] if k in keys else default
    except Exception:
        def _get(k, default=None):
            return row.get(k, default)

    branch_id = _get('id') or _get('branch_id') or None
    name = _get('name') or _get('branch_name') or ''
    address = _get('address') or _get('addr') or _get('branch_address') or ''
    lat_raw = _get('lat') if _get('lat') is not None else _get('latitude')
    lng_raw = _get('lng') if _get('lng') is not None else _get('longitude')
    try:
        lat = float(lat_raw) if lat_raw is not None else None
    except Exception:
        lat = None
    try:
        lng = float(lng_raw) if lng_raw is not None else None
    except Exception:
        lng = None
    try:
        visited = int(_get('visited')) if _get('visited') is not None else 0
    except Exception:
        visited = 0
    try:
        is_hq = int(_get('is_hq')) if _get('is_hq') is not None else 0
    except Exception:
        is_hq = 0

    return {
        'id': branch_id,
        'name': name,
        'address': address,
        'lat': lat,
        'lng': lng,
        'visited': visited,
        'is_hq': is_hq
    }

def plan_day_route(hq, candidate_branches, max_branches=6, max_distance_km=180, min_distance_km=100):
    if not hq or not candidate_branches:
        return [], 0.0
    remaining = candidate_branches.copy()
    route = [hq]
    current = hq
    total = 0.0
    while remaining and (len(route) - 1) < max_branches:
        best = None
        best_d = inf
        for b in remaining:
            lat1, lng1 = current.get('lat'), current.get('lng')
            lat2, lng2 = b.get('lat'), b.get('lng')
            if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
                continue
            d = calculate_distance(lat1, lng1, lat2, lng2)
            if d < best_d:
                best_d = d
                best = b
        if not best:
            break
        back_to_hq = calculate_distance(best['lat'], best['lng'], hq['lat'], hq['lng'])
        potential_total = total + best_d + back_to_hq
        if potential_total <= max_distance_km:
            route.append(best)
            remaining.remove(best)
            current = best
            total += best_d
            if total + calculate_distance(current['lat'], current['lng'], hq['lat'], hq['lng']) >= min_distance_km:
                break
        else:
            remaining.remove(best)
    if len(route) > 1:
        final_leg = calculate_distance(route[-1]['lat'], route[-1]['lng'], hq['lat'], hq['lng'])
        total += final_leg
        route.append(hq)
    else:
        return [], 0.0
    return route, total

# simple root redirect
@app.route('/')
def index():
    return redirect(url_for('login'))

def verify_password_variant(stored, plain):
    if not stored:
        return False
    try:
        # werkzeug hashed formats (pbkdf2)
        if isinstance(stored, str) and stored.startswith('pbkdf2:'):
            return check_password_hash(stored, plain)
    except Exception:
        pass
    # if stored looks like a 64-char hex string, try SHA256
    if isinstance(stored, str) and len(stored) == 64 and all(c in '0123456789abcdefABCDEF' for c in stored):
        try:
            return hashlib.sha256(plain.encode('utf-8')).hexdigest() == stored
        except Exception:
            pass
    # try check_password_hash defensively
    try:
        if check_password_hash(stored, plain):
            return True
    except Exception:
        pass
    # fallback plaintext compare
    return str(stored) == str(plain)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Simplified, explicit auditor auth path to ensure auditors can log in.
    Keeps existing non-auditor logic unchanged below this block.
    """
    if request.method == 'GET':
        return render_template('login.html')

    username = (request.form.get('username') or '').strip()
    password = (request.form.get('password') or '')
    role = (request.form.get('role') or '').strip().lower()

    if not username or not password:
        flash('Username and password are required.', 'error')
        return redirect(url_for('login'))

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Explicit auditor flow first when role == 'auditor'
        if role == 'auditor':
            cur.execute("SELECT id, username, password_hash, password, role, active, name, email, phone FROM auditors WHERE username = ?", (username,))
            row = cur.fetchone()
            conn.close()

            if not row:
                flash('Invalid username or password.', 'error')
                return redirect(url_for('login'))

            # Prefer the hashed password; fall back to plaintext 'password' column if present
            stored_hash = row['password_hash'] if 'password_hash' in row.keys() else None
            stored_plain = row['password'] if 'password' in row.keys() else None

            ok = False
            if stored_hash:
                try:
                    ok = check_password_hash(stored_hash, password)
                except Exception:
                    ok = False
            if not ok and stored_plain:
                ok = (str(stored_plain) == str(password))

            if not ok:
                flash('Invalid username or password.', 'error')
                return redirect(url_for('login'))

            # check active flag if present
            active = row['active'] if 'active' in row.keys() else None
            if active is not None and str(active) not in ('1', 'True', 'true'):
                flash('Account not active.', 'error')
                return redirect(url_for('login'))

            session.clear()
            session['auditor_id'] = row['id'] if 'id' in row.keys() else None
            session['user'] = row['username'] if 'username' in row.keys() else username
            session['role'] = (row['role'] if 'role' in row.keys() else 'auditor').lower()
            # previously rendered auditor_profile.html here; redirect to route optimization index
            # keep auditor info in session and redirect to main index (route_optimization)
            # auditor profile will be available at /auditor/profile
            return redirect(url_for('route_optimization'))

        # Non-auditor flow: fall back to existing logic (users/admins/managers/auditors)
        # users
        cur.execute("SELECT id, username, password, role FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if row:
            stored = row['password'] if 'password' in row.keys() else None
            if stored:
                try:
                    if check_password_hash(stored, password) or str(stored) == password:
                        session.clear()
                        session['user'] = row['username']
                        session['user_id'] = row['id']
                        session['role'] = (row['role'] or 'user').lower()
                        flash('Logged in.', 'success')
                        if session['role'] == 'admin':
                            return redirect(url_for('admin_dashboard'))
                        if session['role'] == 'auditor':
                            return redirect(url_for('auditor_dashboard'))
                        return redirect(url_for('route_optimization'))
                except Exception:
                    pass

        # admins
        cur.execute("SELECT id, username, password_hash FROM admins WHERE username = ?", (username,))
        row = cur.fetchone()
        if row:
            stored_hash = row['password_hash'] if 'password_hash' in row.keys() else None
            if stored_hash and check_password_hash(stored_hash, password):
                session.clear()
                session['user'] = row['username']
                session['user_id'] = row['id']
                session['role'] = 'admin'
                flash('Logged in as admin.', 'success')
                return redirect(url_for('admin_dashboard'))

        # branch_managers
        cur.execute("SELECT id, username, password_hash, approved FROM branch_managers WHERE username = ?", (username,))
        row = cur.fetchone()
        if row:
            stored_hash = row['password_hash'] if 'password_hash' in row.keys() else None
            if stored_hash and check_password_hash(stored_hash, password):
                session.clear()
                session['user'] = row['username']
                session['user_id'] = row['id']
                session['role'] = 'manager'
                session['approved'] = int(row['approved'] or 0) if 'approved' in row.keys() else 0
                flash('Logged in as branch manager.', 'success')
                return redirect(url_for('route_optimization'))

        # auditors fallback (if role not specified)
        cur.execute("SELECT id, username, password_hash, password, active, role FROM auditors WHERE username = ?", (username,))
        row = cur.fetchone()
        if row:
            stored_hash = row['password_hash'] if 'password_hash' in row.keys() else None
            stored_plain = row['password'] if 'password' in row.keys() else None
            ok = False
            if stored_hash:
                try:
                    ok = check_password_hash(stored_hash, password)
                except Exception:
                    ok = False
            if not ok and stored_plain:
                ok = (str(stored_plain) == str(password))
            if ok:
                active = row['active'] if 'active' in row.keys() else None
                if active is not None and str(active) not in ('1', 'True', 'true'):
                    flash('Account not active.', 'error')
                    return redirect(url_for('login'))
                session.clear()
                session['auditor_id'] = row['id']
                session['user'] = row['username']
                session['role'] = (row.get('role') or 'auditor').lower()
                flash('Logged in as auditor.', 'success')
                return redirect(url_for('auditor_dashboard'))

        flash('Invalid username or password.', 'error')
        return redirect(url_for('login'))

    except Exception as e:
        import traceback; traceback.print_exc()
        flash('Login error: ' + str(e), 'error')
        return redirect(url_for('login'))
    finally:
        try:
            if conn:
                conn.close()
        except:
            pass

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return redirect(url_for('route_optimization'))
    return render_template('admin.html', user=session.get('user'))

@app.route('/admin/branch-management')
def branch_management():
    if 'user' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return redirect(url_for('route_optimization'))
    return render_template('branch_management.html')

@app.route('/admin/managers')
def admin_managers():
    if 'user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    accept = request.headers.get('Accept', '')
    if 'application/json' in accept or request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, name, contact_no, branch_id, created_at, username, approved FROM branch_managers ORDER BY id")
            rows = cur.fetchall()
            conn.close()
            managers = [dict(r) for r in rows]
            for m in managers:
                m['approved'] = int(m.get('approved') or 0)
            return jsonify({'success': True, 'managers': managers})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    return render_template('admin_managers.html', user=session.get('user'))

@app.route('/admin/add_auditor', methods=['GET', 'POST'])
def add_auditor():
    """
    Create auditor in data/branches.db.
    Stores password_hash and (per your request) raw password in password column.
    """
    if request.method == 'POST':
        payload = request.get_json(silent=True) or request.form or {}
        username = (payload.get('username') or '').strip()
        password = (payload.get('password') or '').strip()
        name = payload.get('name') or None
        email = payload.get('email') or None
        phone = payload.get('phone') or None
        role = payload.get('role') or 'auditor'
        active = 1 if str(payload.get('active', '1')).lower() in ('1','true','yes','on') else 0
        created_by = session.get('user_id') or None

        if not username or not password:
            flash('Username and password are required.', 'error')
            return redirect(url_for('admin_dashboard'))

        pw_hash = generate_password_hash(password)
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT id FROM auditors WHERE username = ?", (username,))
            if cur.fetchone():
                conn.close()
                if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                    return jsonify({'success': False, 'error': 'Username already exists'}), 400
                flash('Username already exists', 'error')
                return redirect(url_for('admin_dashboard'))

            cur.execute("""
                INSERT INTO auditors
                  (username, password_hash, password, active, created_by_admin_id, created_at, name, email, phone, avatar, role)
                VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
            """, (username, pw_hash, password, active, created_by, name, email, phone, None, role))
            conn.commit()
            new_id = cur.lastrowid
            cur.execute("SELECT id, username, password_hash, password FROM auditors WHERE id = ?", (new_id,))
            verify = cur.fetchone()
            conn.close()
            if not verify:
                if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                    return jsonify({'success': False, 'error': 'Insert verification failed'}), 500
                flash('Auditor creation failed (verification).', 'error')
                return redirect(url_for('admin_dashboard'))
            if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({'success': True, 'message': f'Auditor created (id={new_id})', 'id': new_id})
            flash('Auditor created successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except:
                    pass
            if request.is_json or 'application/json' in request.headers.get('Accept', ''):
                return jsonify({'success': False, 'error': str(e)}), 500
            flash('Failed to create auditor: ' + str(e), 'error')
            return redirect(url_for('admin_dashboard'))
    return render_template('admin_add_auditor.html')

# Provide backwards-compatible dash route used elsewhere (delegates to add_auditor)
@app.route('/admin/add-auditor', methods=['POST'])
def admin_add_auditor_dash():
    return add_auditor()

@app.route('/route-optimization')
def route_optimization():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/api/plan', methods=['POST'])
def api_plan_one_day():
    """Plan next single day route starting/ending at HQ using plan_day_route."""
    try:
        hq_row = get_hq_location()
        if not hq_row:
            return jsonify({'success': False, 'error': 'HQ not found'}), 400
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM branches WHERE visited = 0 AND (is_hq IS NULL OR is_hq = 0)")
        rows = cur.fetchall()
        conn.close()
        candidates = [row_to_branch_dict(r) for r in rows]
        if not candidates:
            return jsonify({'success': True, 'day_route': None, 'all_completed': True})
        hq = row_to_branch_dict(hq_row)
        route, total_km = plan_day_route(hq, candidates, max_branches=6, max_distance_km=180, min_distance_km=100)
        if not route or len(route) <= 2:
            route2, total2 = plan_day_route(hq, candidates, max_branches=6, max_distance_km=180, min_distance_km=0)
            if not route2 or len(route2) <= 2:
                return jsonify({'success': False, 'error': 'Could not find viable route'}), 500
            route, total_km = route2, total2
        stops = []
        for s in route:
            if isinstance(s, dict):
                stops.append({
                    'id': s.get('id'),
                    'name': s.get('name'),
                    'address': s.get('address'),
                    'lat': s.get('lat'),
                    'lng': s.get('lng'),
                })
            else:
                # sqlite3.Row mapping
                stops.append({
                    'id': s['id'] if 'id' in s.keys() else None,
                    'name': s['name'] if 'name' in s.keys() else None,
                    'address': s['address'] if 'address' in s.keys() else None,
                    'lat': s['lat'] if 'lat' in s.keys() else None,
                    'lng': s['lng'] if 'lng' in s.keys() else None,
                })
        day_route = {
            'day': 1,
            'stops': stops,
            'distance_km': round(total_km, 2),
            'branches_visited': max(0, len(stops) - 2),
            'remaining_branches': len(candidates) - max(0, len(stops) - 2),
            'visited_branches': stops[1:-1]
        }
        session['last_route'] = {'type': 'single_day', 'day_route': day_route, 'has_more_branches': day_route['remaining_branches'] > 0}
        return jsonify({'success': True, 'day_route': day_route, 'has_more_branches': day_route['remaining_branches'] > 0})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/branches', methods=['GET'])
def api_branches():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name, address, lat, lng, visited, is_hq FROM branches ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        branches = [dict(r) for r in rows]
        for b in branches:
            b['visited'] = int(b.get('visited') or 0)
            b['is_hq'] = int(b.get('is_hq') or 0)
        return jsonify({'success': True, 'branches': branches})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auditors', methods=['GET'])
def api_auditors():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, username, role, active, created_at, name, email, phone, avatar FROM auditors ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        auditors = [dict(r) for r in rows]
        return jsonify({'success': True, 'auditors': auditors})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/delete-auditor/<int:auditor_id>', methods=['DELETE'])
def admin_delete_auditor(auditor_id):
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM auditors WHERE id = ?", (auditor_id,))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected:
            return jsonify({'success': True, 'message': 'Auditor deleted'})
        return jsonify({'success': False, 'error': 'Auditor not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/managers', methods=['GET'])
def api_admin_managers():
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT bm.id, bm.name, bm.contact_no, bm.branch_id, bm.created_at, bm.username,
                   bm.approved, b.name AS branch_name, b.address AS branch_address
            FROM branch_managers bm
            LEFT JOIN branches b ON bm.branch_id = b.id
            ORDER BY bm.id
        """)
        rows = cur.fetchall()
        conn.close()
        items = [dict(r) for r in rows]
        for m in items:
            m['approved'] = int(m.get('approved') or 0)
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/managers/pending', methods=['GET'])
def api_admin_managers_pending():
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT bm.id, bm.name, bm.contact_no, bm.branch_id, bm.created_at, bm.username,
                   bm.approved, b.name AS branch_name, b.address AS branch_address
            FROM branch_managers bm
            LEFT JOIN branches b ON bm.branch_id = b.id
            WHERE bm.approved = 0 OR bm.approved IS NULL
            ORDER BY bm.id
        """)
        rows = cur.fetchall()
        conn.close()
        items = [dict(r) for r in rows]
        for m in items:
            m['approved'] = int(m.get('approved') or 0)
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/managers/<int:manager_id>/approve', methods=['POST'])
def api_admin_managers_approve(manager_id):
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE branch_managers SET approved = 1 WHERE id = ?", (manager_id,))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected:
            return jsonify({'success': True, 'message': 'Manager approved'})
        return jsonify({'success': False, 'error': 'Manager not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.context_processor
def inject_user():
    return {'user': session.get('user')}

@app.after_request
def add_cors_headers(response):
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
    return response

@app.route('/auditor/login', methods=['POST'])
def auditor_login_deprecated():
    return redirect(url_for('login'))

@app.route('/auditor/profile', methods=['GET', 'POST'])
def auditor_profile():
    """Render and update auditor profile page for currently logged-in auditor."""
    if 'auditor_id' not in session:
        return redirect(url_for('login'))

    auditor_id = session.get('auditor_id')
    upload_dir = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'auditors')
    os.makedirs(upload_dir, exist_ok=True)

    if request.method == 'POST':
        # get form fields
        name = (request.form.get('name') or None)
        email = (request.form.get('email') or None)
        phone = (request.form.get('phone') or None)

        avatar_path = None
        file = request.files.get('avatar')
        if file and getattr(file, 'filename', None):
            filename = secure_filename(file.filename)
            # prefix with auditor id + timestamp to avoid collisions
            ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            filename = f"{auditor_id}_{ts}_{filename}"
            save_path = os.path.join(upload_dir, filename)
            try:
                file.save(save_path)
                # path stored relative to static/
                avatar_path = f"uploads/auditors/{filename}"
            except Exception as e:
                flash('Failed to save avatar: ' + str(e), 'error')

        # persist fields to DB (update only provided values)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            # build update dynamically
            updates = []
            params = []
            if name is not None:
                updates.append("name = ?"); params.append(name)
            if email is not None:
                updates.append("email = ?"); params.append(email)
            if phone is not None:
                updates.append("phone = ?"); params.append(phone)
            if avatar_path:
                updates.append("avatar = ?"); params.append(avatar_path)
            if updates:
                params.append(auditor_id)
                sql = "UPDATE auditors SET " + ", ".join(updates) + " WHERE id = ?"
                cur.execute(sql, tuple(params))
                conn.commit()
            conn.close()
            flash('Profile updated successfully.', 'success')
        except Exception as e:
            import traceback; traceback.print_exc()
            flash('Failed to update profile: ' + str(e), 'error')

        return redirect(url_for('auditor_profile'))

    # GET: render profile
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM auditors WHERE id = ?", (auditor_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            flash('Auditor not found', 'error')
            return redirect(url_for('login'))
        auditor = dict(row) if hasattr(row, 'keys') else row
        # pass both `user` and `auditor` so templates using either key work
        return render_template('auditor_profile.html', auditor=auditor, user=auditor)
    except Exception as e:
        import traceback; traceback.print_exc()
        flash('Unable to load profile: ' + str(e), 'error')
        return redirect(url_for('route_optimization'))

@app.route('/map/day/<int:day_number>')
def map_day(day_number):
    """
    Render map.html for the requested planned-day using the last route stored in session.
    If no last_route in session, redirect back to planner with a flash message.
    """
    lr = session.get('last_route')
    if not lr:
        flash('No planned route available. Please click "Plan Next Day" first.', 'error')
        return redirect(url_for('route_optimization'))

    # single_day format: {'type':'single_day', 'day_route': {...}, 'has_more_branches': bool}
    if lr.get('type') == 'single_day':
        day_route = lr.get('day_route') or {}
        # day_number should match the stored day (usually 1)
        if day_number != int(day_route.get('day', 1)):
            flash('Requested day not available for the last planned route.', 'error')
            return redirect(url_for('route_optimization'))
        stops = day_route.get('stops', [])
        return render_template('map.html', stops=stops, day_number=day_number)

    # multi-day format: store days as list under 'days'
    if lr.get('type') in ('multi_day',):
        days = lr.get('days') or []
        idx = day_number - 1
        if idx < 0 or idx >= len(days):
            flash('Requested day not available in planned multi-day route.', 'error')
            return redirect(url_for('route_optimization'))
        stops = days[idx].get('stops', [])
        return render_template('map.html', stops=stops, day_number=day_number)

    # fallback: unknown structure
    flash('Saved route has unexpected format.', 'error')
    return redirect(url_for('route_optimization'))

@app.route('/map')
def map_default():
    """Redirect to day 1 map for convenience."""
    return redirect(url_for('map_day', day_number=1))

if __name__ == '__main__':
    print("Starting Flask application...")
    print(f"Database path: {DB_PATH}")
    print(f"Database exists: {os.path.exists(DB_PATH)}")
    print(f"Google Maps API Key loaded: {'Yes' if GOOGLE_MAPS_API_KEY else 'No'}")
    app.run(debug=True, host='127.0.0.1', port=5000)