from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask import g, make_response

import sqlite3
from math import radians, sin, cos, sqrt, atan2
from math import inf
import os
from dotenv import load_dotenv
from os import getenv
from copy import deepcopy
from werkzeug.security import generate_password_hash
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)

# ensure secret key for session
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

# Database path
DB_PATH = os.path.join('data', 'branches.db')

# Google Maps API Key from .env
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

def get_db_connection():
    """Get database connection"""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points using Haversine formula"""
    if None in [lat1, lon1, lat2, lon2]:
        return 0
    
    try:
        R = 6371
        lat1_rad = radians(float(lat1))
        lat2_rad = radians(float(lat2))
        delta_lat = radians(float(lat2) - float(lat1))
        delta_lon = radians(float(lon2) - float(lon1))
        
        a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        
        distance = R * c
        return distance
    except Exception as e:
        print(f"Error calculating distance: {e}")
        return 0

def get_hq_location():
    """Return HQ branch row as dict. Prefer is_hq flag, fallback to keyword search."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM branches WHERE is_hq = 1 LIMIT 1")
    row = cur.fetchone()
    if row:
        conn.close()
        return dict(row)
    # fallback search by common keywords
    cur.execute("""
        SELECT * FROM branches
        WHERE name LIKE '%Pezhakkapilly%' OR address LIKE '%Pezhakkapilly%'
           OR name LIKE '%Muvattupuzha%' OR address LIKE '%Muvattupuzha%'
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def plan_route_under_180km(hq, branches, max_distance=180, min_distance=100, target_distance=150, max_branches=6):
    """Plan route starting and ending at HQ within distance constraints"""
    if not branches or not hq:
        return [], 0
    
    route = [hq]
    remaining_branches = branches.copy()
    current_location = hq
    total_distance = 0
    
    print(f"\n{'='*60}")
    print(f"Planning route from: {hq.get('name')}")
    print(f"Target: {min_distance}-{target_distance}km, Max: {max_distance}km")
    print(f"Max branches: {max_branches}")
    print(f"{'='*60}\n")
    
    while remaining_branches and len(route) - 1 < max_branches:
        nearest_branch = None
        min_dist = float('inf')
        
        for branch in remaining_branches:
            dist = calculate_distance(
                current_location.get('latitude'),
                current_location.get('longitude'),
                branch.get('latitude'),
                branch.get('longitude')
            )
            
            if dist < min_dist:
                min_dist = dist
                nearest_branch = branch
        
        if not nearest_branch:
            break
        
        distance_to_branch = min_dist
        distance_back_to_hq = calculate_distance(
            nearest_branch.get('latitude'),
            nearest_branch.get('longitude'),
            hq.get('latitude'),
            hq.get('longitude')
        )
        
        potential_total_distance = total_distance + distance_to_branch + distance_back_to_hq
        
        print(f"Evaluating: {nearest_branch.get('name')}")
        print(f"  Potential total: {potential_total_distance:.2f} km")
        
        if potential_total_distance <= max_distance:
            route.append(nearest_branch)
            remaining_branches.remove(nearest_branch)
            current_location = nearest_branch
            total_distance += distance_to_branch
            print(f"  ✓ ADDED\n")
            
            if len(route) - 1 >= 4 and total_distance + distance_back_to_hq >= target_distance:
                print(f"Target reached. Stopping.\n")
                break
        else:
            print(f"  ✗ SKIPPED - Would exceed limit\n")
            break
    
    if len(route) > 1:
        final_leg = calculate_distance(
            route[-1].get('latitude'),
            route[-1].get('longitude'),
            hq.get('latitude'),
            hq.get('longitude')
        )
        total_distance += final_leg
        route.append(hq)
        
        print(f"Route completed: {len(route) - 2} branches, {total_distance:.2f} km\n")
    
    return route, total_distance

def row_to_branch_dict(row):
    """
    Normalize a DB row (sqlite3.Row or dict) to a consistent branch dict:
    { id, name, address, lat, lng, visited, is_hq }
    Works with columns named 'lat'/'lng' or 'latitude'/'longitude'.
    """
    # support sqlite3.Row (mapping) and plain dict
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
    # support both lat/lng and latitude/longitude column names
    lat_raw = _get('lat')
    if lat_raw is None:
        lat_raw = _get('latitude')
    lng_raw = _get('lng')
    if lng_raw is None:
        lng_raw = _get('longitude')

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
    """
    Greedy nearest-neighbour that grows route starting/ending at HQ.
    Stops when adding next branch would make final total > max_distance_km
    or when max_branches reached. Accept only routes with total >= min_distance_km.
    Returns (route_list, total_distance_km). route_list includes HQ at start and end.
    """
    if not hq or not candidate_branches:
        return [], 0.0

    remaining = candidate_branches.copy()
    route = [hq]
    current = hq
    total = 0.0

    # greedy: pick nearest branch each step
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

        # distance from current -> best + best -> HQ (closing leg)
        back_to_hq = calculate_distance(best['lat'], best['lng'], hq['lat'], hq['lng'])
        potential_total = total + best_d + back_to_hq

        if potential_total <= max_distance_km:
            route.append(best)
            remaining.remove(best)
            current = best
            total += best_d
            # If after adding we already meet min_distance_km when considering return leg, stop
            if total + calculate_distance(current['lat'], current['lng'], hq['lat'], hq['lng']) >= min_distance_km:
                break
        else:
            # can't add this nearest branch, try remove it from candidates and try next nearest
            # but to avoid infinite loop remove it from consideration for this planning pass
            remaining.remove(best)
            # continue searching other branches in remaining
    if len(route) > 1:
        # close route to HQ
        final_leg = calculate_distance(route[-1]['lat'], route[-1]['lng'], hq['lat'], hq['lng'])
        total += final_leg
        route.append(hq)
    else:
        return [], 0.0

    return route, total

# redirect root to login page
@app.route('/')
def index():
    return redirect(url_for('login'))

# simple login route (adjust auth as needed)
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'auditor').strip()

        # replace with your real auth logic
        if username == 'admin' and password == 'admin123':
            session['user'] = username
            session['role'] = role
            # redirect admin users to admin dashboard
            if role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('route_optimization'))
        error = 'Invalid username or password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('role', None)
    return redirect(url_for('login'))

# Admin dashboard and related pages
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
    if 'user' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return redirect(url_for('route_optimization'))

    # If the client expects JSON (AJAX/fetch), return JSON list of managers
    accept = request.headers.get('Accept', '')
    if 'application/json' in accept or request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, name, contact_no, branch_id, created_at, username, approved FROM branch_managers ORDER BY id")
            rows = cur.fetchall()
            conn.close()
            managers = [dict(r) for r in rows]
            # normalize approved to int
            for m in managers:
                m['approved'] = int(m.get('approved') or 0)
            return jsonify({'success': True, 'managers': managers})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # Normal page render for browser navigation
    return render_template('admin_managers.html', user=session.get('user'))

# ensure route_optimization exists
@app.route('/route-optimization')
def route_optimization():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/api/plan', methods=['POST'])
def api_plan_one_day():
    """Plan next single day route starting/ending at Pezhakkapilly. Returns day_route (stops + distance)."""
    try:
        hq = get_hq_location()
        if not hq:
            return jsonify({'success': False, 'error': 'HQ (Pezhakkapilly) not found in DB'}), 400

        # fetch unvisited branches (exclude HQ)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM branches WHERE visited = 0 AND (is_hq IS NULL OR is_hq = 0)")
        rows = cur.fetchall()
        conn.close()
        candidates = [row_to_branch_dict(r) for r in rows]

        if not candidates:
            return jsonify({'success': False, 'error': 'No unvisited branches', 'all_completed': True})

        # plan a day (max 6 branches) with distance between 100 and 180 km
        route, total = plan_day_route(row_to_branch_dict(hq), candidates, max_branches=6, max_distance_km=180, min_distance_km=100)

        if not route or len(route) <= 2:
            # fallback: try relaxing min_distance requirement and return the best short route under max_distance
            route2, total2 = plan_day_route(row_to_branch_dict(hq), candidates, max_branches=6, max_distance_km=180, min_distance_km=0)
            if not route2 or len(route2) <= 2:
                return jsonify({'success': False, 'error': 'Could not find a viable route under constraints'}), 500
            route, total = route2, total2

        # prepare stops (convert sqlite rows/dicts to minimal info)
        stops = []
        for s in route:
            stops.append({
                'id': s.get('id'),
                'name': s.get('name'),
                'address': s.get('address'),
                'lat': s.get('lat'),
                'lng': s.get('lng')
            })

        day_route = {
            'day': 1,
            'stops': stops,
            'distance_km': round(total, 2),
            'branches_visited': max(0, len(stops) - 2),
            'remaining_branches': len(candidates) - max(0, len(stops) - 2),
            'visited_branches': [b for b in stops[1:-1]]
        }

        session['last_route'] = {'type': 'single_day', 'day_route': day_route, 'has_more_branches': day_route['remaining_branches'] > 0}

        return jsonify({'success': True, 'day_route': day_route, 'has_more_branches': day_route['remaining_branches'] > 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/plan-multi', methods=['POST'])
def api_plan_multi():
    """Plan multiple days until all branches planned or safe cap reached. Each day starts/ends at HQ, 1-6 branches, 100-180km."""
    try:
        hq = get_hq_location()
        if not hq:
            return jsonify({'success': False, 'error': 'HQ (Pezhakkapilly) not found in DB'}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM branches WHERE (is_hq IS NULL OR is_hq = 0) AND visited = 0 ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        candidates = [row_to_branch_dict(r) for r in rows]
        if not candidates:
            return jsonify({'success': False, 'error': 'No unvisited branches', 'all_completed': True})

        days = []
        day_num = 1
        max_days = 30
        remaining_candidates = candidates.copy()

        while remaining_candidates and day_num <= max_days:
            route, total = plan_day_route(row_to_branch_dict(hq), remaining_candidates, max_branches=6, max_distance_km=180, min_distance_km=100)
            if not route or len(route) <= 2:
                # try relaxed min distance (allow short day) to finish remaining
                route, total = plan_day_route(row_to_branch_dict(hq), remaining_candidates, max_branches=6, max_distance_km=180, min_distance_km=0)
                if not route or len(route) <= 2:
                    break

            stops = []
            visited_branches = []
            for s in route:
                stops.append({
                    'id': s.get('id'),
                    'name': s.get('name'),
                    'address': s.get('address'),
                    'lat': s.get('lat'),
                    'lng': s.get('lng')
                })
            visited_branches = stops[1:-1]

            days.append({
                'day': day_num,
                'stops': stops,
                'distance_km': round(total, 2),
                'branches_visited': len(visited_branches),
                'visited_branches': visited_branches
            })

            # remove visited by id
            visited_ids = {b['id'] for b in visited_branches if b.get('id') is not None}
            remaining_candidates = [c for c in remaining_candidates if c.get('id') not in visited_ids]

            day_num += 1

        route_data = {'type': 'multi_day', 'days': days}
        session['last_route'] = route_data

        return jsonify({'success': True, 'days': days, 'has_more_branches': len(remaining_candidates) > 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/status')
def api_status():
    """Get branch status"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as total FROM branches WHERE name NOT LIKE '%Pezhakkapilly%'")
        total = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as visited FROM branches WHERE visited = 1 AND name NOT LIKE '%Pezhakkapilly%'")
        visited = cursor.fetchone()['visited']
        
        conn.close()
        
        return jsonify({
            'success': True,
            'total_branches': total,
            'visited_branches': visited,
            'unvisited_branches': total - visited
        })
    except Exception as e:
        return jsonify({'error': str(e)})

# Return last planned route stored in session (used by index restore)
@app.route('/api/last-route', methods=['GET'])
def api_last_route():
    route = session.get('last_route')
    if not route:
        return jsonify({'success': True, 'route_data': None})
    return jsonify({'success': True, 'route_data': route})

# Map view: render map for a planned day (uses session['last_route'])
@app.route('/map/day/<int:day_number>')
def view_map(day_number):
    # require login if you use session-based auth; if not, remove the guard
    if 'user' not in session:
        return redirect(url_for('login'))

    route_data = session.get('last_route')
    stops = []
    route_info = {}

    if not route_data:
        # no planned route — render template which will show friendly message
        return render_template('map.html', stops=[], day_number=day_number)

    # normalize single_day vs multi_day
    if route_data.get('type') == 'single_day':
        dr = route_data.get('day_route') or {}
        if dr.get('day', 1) != day_number:
            return render_template('map.html', stops=[], day_number=day_number)
        stops = dr.get('stops', [])
        route_info = dr
    else:
        days = route_data.get('days', [])
        if day_number < 1 or day_number > len(days):
            return render_template('map.html', stops=[], day_number=day_number)
        route_info = days[day_number - 1]
        stops = route_info.get('stops', [])

    # ensure plain serializable dicts and numeric lat/lng
    safe_stops = []
    for s in stops:
        if s is None:
            continue
        st = dict(s) if not isinstance(s, dict) else s.copy()
        # try to coerce lat/lng to numbers or null
        try:
            st['lat'] = float(st['lat']) if st.get('lat') is not None else None
        except Exception:
            st['lat'] = None
        try:
            st['lng'] = float(st['lng']) if st.get('lng') is not None else None
        except Exception:
            st['lng'] = None
        safe_stops.append({'id': st.get('id'), 'name': st.get('name'), 'address': st.get('address'), 'lat': st.get('lat'), 'lng': st.get('lng')})

    return render_template('map.html', stops=safe_stops, day_number=day_number, route_info=route_info)

@app.route('/api/branches', methods=['GET'])
def api_branches():
    """Return all branches as JSON for admin UI."""
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
    """Return auditors list for admin UI."""
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

@app.route('/admin/add-auditor', methods=['POST'])
def admin_add_auditor():
    """Add a new auditor (called from admin.html)."""
    # require admin
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        data = request.get_json() or {}
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '').strip()
        if not username or not password:
            return jsonify({'success': False, 'error': 'username and password required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM auditors WHERE username = ?", (username,))
        if cur.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': 'Username already exists'}), 400

        pwd_hash = generate_password_hash(password)
        created_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        # created_by_admin_id left NULL (could be session user id mapping)
        cur.execute("""
            INSERT INTO auditors (username, password_hash, active, created_by_admin_id, created_at, role)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (username, pwd_hash, 1, None, created_at, 'auditor'))
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return jsonify({'success': True, 'message': f'Auditor created (id={new_id})', 'id': new_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/delete-auditor/<int:auditor_id>', methods=['DELETE'])
def admin_delete_auditor(auditor_id):
    """Delete auditor by id."""
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
    """Return all branch manager registrations (JSON)"""
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
    """Return pending (unapproved) branch manager registrations"""
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
    """Approve a pending branch manager"""
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

@app.route('/api/admin/managers/<int:manager_id>', methods=['DELETE'])
def api_admin_managers_delete(manager_id):
    """Delete a branch manager registration"""
    if 'user' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM branch_managers WHERE id = ?", (manager_id,))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected:
            return jsonify({'success': True, 'message': 'Manager removed'})
        return jsonify({'success': False, 'error': 'Manager not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Make session user available in all templates (prevents 'user' undefined)
@app.context_processor
def inject_user():
    return {'user': session.get('user')}

# Debug endpoint: show DB schema for branches table
@app.route('/debug/schema')
def debug_schema():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(branches);")
        cols = cur.fetchall()
        conn.close()
        schema = [{'cid': c[0], 'name': c[1], 'type': c[2], 'notnull': c[3], 'dflt_value': c[4], 'pk': c[5]} for c in cols]
        return jsonify({'success': True, 'schema': schema})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Debug endpoint: return first N rows from branches
@app.route('/debug/branches')
def debug_branches():
    limit = int(request.args.get('limit', 20))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM branches LIMIT {limit}")
        rows = cur.fetchall()
        conn.close()
        # convert sqlite3.Row to dict
        data = [dict(r) for r in rows]
        return jsonify({'success': True, 'count': len(data), 'rows': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Debug endpoint: quick stats (total / visited / unvisited)
@app.route('/debug/branches-stats')
def debug_branches_stats():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as total FROM branches")
        total = cur.fetchone()['total']
        cur.execute("SELECT COUNT(*) as visited FROM branches WHERE visited = 1")
        visited = cur.fetchone()['visited']
        conn.close()
        return jsonify({'success': True, 'total': total, 'visited': visited, 'unvisited': total - visited})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# add constants near MAX_DISTANCE_PER_DAY (or wherever constants are defined)
MIN_DISTANCE_PER_DAY = 100_000  # 100 km in meters
MAX_DISTANCE_PER_DAY = 180_000  # 180 km in meters (ensure this matches other constants)

def total_distance_m(route_indices, distance_matrix):
    """Return total distance in meters for a route expressed as indices"""
    if not route_indices or not distance_matrix:
        return 0
    total = 0
    for k in range(len(route_indices) - 1):
        i, j = route_indices[k], route_indices[k + 1]
        total += distance_matrix[i][j]
    return total

def extend_route_to_min(route_indices, branches, distance_matrix, min_m=MIN_DISTANCE_PER_DAY, max_m=MAX_DISTANCE_PER_DAY):
    """
    Greedily append remaining unvisited branches (closest to current end)
    while keeping total <= max_m, aiming to reach >= min_m.
    route_indices is a list that starts/ends at HQ index.
    """
    if not route_indices or not distance_matrix:
        return route_indices

    # Identify HQ index (start) and current visited set
    hq_index = route_indices[0]
    current_route = route_indices[:-1]  # exclude final HQ for appending logic
    remaining = set(range(len(branches))) - set(current_route)
    # Exclude HQ from candidates
    remaining.discard(hq_index)

    current_total = total_distance_m(route_indices, distance_matrix)
    # If already meets min, return
    if current_total >= min_m and current_total <= max_m:
        return route_indices

    # Greedy append loop: pick nearest remaining to current last node
    while remaining and current_total < min_m:
        last = current_route[-1]
        # compute distances from last to candidates
        candidates = sorted(remaining, key=lambda idx: distance_matrix[last][idx])
        appended = False
        for cand in candidates:
            # new route = current_route + [cand] + [hq]
            candidate_route = current_route + [cand, hq_index]
            cand_total = total_distance_m(candidate_route, distance_matrix)
            if cand_total <= max_m:
                # accept candidate
                current_route.append(cand)
                remaining.remove(cand)
                current_total = cand_total
                appended = True
                break
        if not appended:
            # no candidate can be appended without exceeding max -> break
            break

    # close route to HQ
    final_route = current_route + [hq_index]
    # Ensure we didn't exceed max (defensive)
    if total_distance_m(final_route, distance_matrix) > max_m:
        return route_indices  # keep original
    return final_route

# Replace / update your existing api handler to use the extension logic
@app.route("/api/plan", methods=["POST"])
def api_plan_single_day():
    """Plan a single day route with enforced 100-180 km constraint starting/ending at HQ"""
    try:
        if not require_role("auditor", "admin"):
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        create_tables()
        branches = get_branches()
        if not branches:
            return jsonify({"error": "No branches found in database."})

        # build coords and get distance/time matrices (meters, seconds)
        coords = [(b[3], b[4]) for b in branches]
        distance_matrix, time_matrix = get_distance_matrix(coords)

        if not distance_matrix:
            return jsonify({"error": "Failed to get distance matrix from API"})

        if len(distance_matrix) != len(branches):
            return jsonify({"error": f"Distance matrix size mismatch: {len(distance_matrix)} vs {len(branches)}"})

        # Plan a route using existing planner (may return route indices list)
        day_route = plan_single_day(branches, distance_matrix, time_matrix)

        if not day_route:
            return jsonify({"error": "No route could be generated within distance constraints"})

        # compute total and, if below minimum, try to extend while keeping under max
        total_m = total_distance_m(day_route, distance_matrix)
        if total_m < MIN_DISTANCE_PER_DAY:
            extended = extend_route_to_min(day_route, branches, distance_matrix, MIN_DISTANCE_PER_DAY, MAX_DISTANCE_PER_DAY)
            if extended and total_distance_m(extended, distance_matrix) >= MIN_DISTANCE_PER_DAY:
                day_route = extended
                total_m = total_distance_m(day_route, distance_matrix)
            else:
                # fallback behavior: attempt a relaxed plan (allow shorter days) - keep original
                pass

        # if still exceeds max, reject
        if total_m > MAX_DISTANCE_PER_DAY:
            return jsonify({"error": "Planned route exceeds maximum allowed distance", "distance_m": total_m}), 500

        # Build stops list for response
        stops = []
        for idx in day_route:
            stops.append({
                "id": branches[idx][0],
                "name": branches[idx][1],
                "address": branches[idx][2],
                "lat": branches[idx][3],
                "lng": branches[idx][4]
            })

        visited_branches = [s for s in stops if s["id"] and (not (s["id"] == branches[0][0] and s in [stops[0], stops[-1]]))]  # exclude HQ duplicates

        result = {
            "day": 1,
            "distance_m": total_m,
            "distance_km": round(total_m / 1000.0, 2),
            "branches_visited": len([i for i in day_route if branches[i][5] == 0]),
            "remaining_branches": sum(1 for b in branches if b[5] == 0) - len([i for i in day_route if branches[i][5] == 0]),
            "stops": stops,
            "route_indices": day_route,
            "visited_branches": visited_branches
        }

        # Save last route for UI restore
        store_last_route({"type": "single_day", "day_route": result, "has_more_branches": result["remaining_branches"] > 0})

        # Try generate map (non-blocking)
        try:
            generate_map(branches, [day_route], GOOGLE_MAPS_API_KEY)
        except Exception as e:
            print(f"Map generation warning: {e}")

        return jsonify({"day_route": result, "success": True, "has_more_branches": result["remaining_branches"] > 0})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Planning failed: {str(e)}", "success": False}), 500

# Provide client with API key (index.html requests /api/config)
@app.route("/api/config", methods=["GET"])
def api_config():
    """Return minimal config needed by client (safe, no secrets besides API key)."""
    return jsonify({"success": True, "googleMapsApiKey": GOOGLE_MAPS_API_KEY})

# Ensure OPTIONS requests and simple CORS headers are present (helps browser preflight)
@app.after_request
def add_cors_headers(response):
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
    return response

# Generic OPTIONS route fallback (some browsers may hit this)
@app.route("/api/<path:any_path>", methods=["OPTIONS"])
def api_options(any_path):
    resp = make_response()
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return resp

if __name__ == '__main__':
    print("Starting Flask application...")
    print(f"Database path: {DB_PATH}")
    print(f"Database exists: {os.path.exists(DB_PATH)}")
    print(f"Google Maps API Key loaded: {'Yes' if GOOGLE_MAPS_API_KEY else 'No'}")
    app.run(debug=True, host='127.0.0.1', port=5000)