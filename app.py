from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask import g

import sqlite3
from math import radians, sin, cos, sqrt, atan2
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
    return render_template('admin_managers.html')

# ensure route_optimization exists
@app.route('/route-optimization')
def route_optimization():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/api/plan', methods=['POST'])
def api_plan():
    """Plan next day route"""
    try:
        hq = get_hq_location()
        if not hq:
            return jsonify({'error': 'Pezhakkapilly branch not found'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, address, lat AS latitude, lng AS longitude, visited 
            FROM branches 
            WHERE visited = 0 
            AND name NOT LIKE '%Pezhakkapilly%'
        """)
        rows = cursor.fetchall()
        conn.close()
        
        unvisited = [dict(row) for row in rows]
        
        if not unvisited:
            return jsonify({'error': 'No unvisited branches', 'all_completed': True})
        
        route, total_distance = plan_route_under_180km(hq, unvisited, 180, 100, 150, 6)
        
        if not route or len(route) <= 2:
            return jsonify({'error': 'Cannot plan route within constraints'})
        
        visited_branches = route[1:-1]
        stops_display = [{'name': s.get('name'), 'address': s.get('address')} for s in route]
        
        route_data = {
            'type': 'single_day',
            'day_route': {
                'day': 1,
                'distance_km': round(total_distance, 2),
                'branches_visited': len(visited_branches),
                'remaining_branches': len(unvisited) - len(visited_branches),
                'stops': stops_display,
                'visited_branches': visited_branches
            },
            'has_more_branches': len(unvisited) > len(visited_branches)
        }
        
        session['last_route'] = route_data
        
        return jsonify({
            'success': True,
            'day_route': route_data['day_route'],
            'has_more_branches': route_data['has_more_branches']
        })
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)})

@app.route('/api/plan-multi', methods=['POST'])
def api_plan_multi():
    """Plan routes for multiple days (max 5-6 branches per day, each route < 180km)"""
    try:
        hq = get_hq_location()
        if not hq:
            return jsonify({'error': 'Pezhakkapilly branch not found'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, address, lat AS latitude, lng AS longitude, visited
            FROM branches
            WHERE name NOT LIKE '%Pezhakkapilly%'
            ORDER BY id
        """)
        rows = cursor.fetchall()
        conn.close()

        all_branches = [dict(r) for r in rows]
        remaining = [b for b in all_branches if b.get('visited') == 0]

        if not remaining:
            return jsonify({'error': 'No unvisited branches', 'all_completed': True})

        days = []
        day_num = 1
        max_days = 30  # safety cap
        # Keep planning until no remaining or cap reached
        while remaining and day_num <= max_days:
            # plan for this day
            route, total_distance = plan_route_under_180km(hq, deepcopy(remaining), max_distance=180, min_distance=100, target_distance=150, max_branches=6)

            # If planner couldn't find a viable route, break to avoid infinite loop
            if not route or len(route) <= 2:
                break

            visited_branches = route[1:-1]  # branches visited this day
            stops_display = [{'name': s.get('name'), 'address': s.get('address')} for s in route]

            days.append({
                'day': day_num,
                'distance_km': round(total_distance, 2),
                'branches_visited': len(visited_branches),
                'remaining_branches': max(0, len(remaining) - len(visited_branches)),
                'stops': stops_display,
                'visited_branches': visited_branches
            })

            # remove visited from remaining (by id)
            visited_ids = {b['id'] for b in visited_branches if 'id' in b}
            remaining = [b for b in remaining if b.get('id') not in visited_ids]

            day_num += 1

        route_data = {
            'type': 'multi_day',
            'days': days
        }
        session['last_route'] = route_data

        return jsonify({'success': True, 'days': days, 'has_more_branches': len(remaining) > 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

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

@app.route('/api/last-route')
def api_last_route():
    """Get last route"""
    route_data = session.get('last_route')
    if route_data:
        return jsonify({'success': True, 'route_data': route_data})
    return jsonify({'success': False})

@app.route('/api/reset', methods=['POST'])
def api_reset():
    """Reset all branches"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE branches SET visited = 0")
        conn.commit()
        conn.close()
        session.pop('last_route', None)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/save-visits', methods=['POST'])
def api_save_visits():
    """Save visits"""
    try:
        data = request.get_json()
        branch_ids = data.get('branch_ids', [])
        
        if not branch_ids:
            return jsonify({'error': 'No branches selected'})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(branch_ids))
        cursor.execute(f"UPDATE branches SET visited = 1 WHERE id IN ({placeholders})", branch_ids)
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'{len(branch_ids)} branches marked as visited'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/submit-visits', methods=['POST'])
def api_submit_visits():
    """Submit visits"""
    return api_save_visits()

@app.route('/map/day/<int:day_number>')
def view_map(day_number):
    """View map with route (supports single_day and multi_day)"""
    if 'user' not in session:
        return redirect(url_for('login'))

    route_data = session.get('last_route')
    if not route_data:
        return "No route data found. Please plan a route first.", 404

    # Support single_day and multi_day stored in session
    if route_data.get('type') == 'single_day':
        day_route = route_data.get('day_route')
        # for single_day, only day_number==1 is valid
        if day_number != 1:
            return "Requested day not found in planned routes.", 404
        stops = day_route.get('stops', [])
    elif route_data.get('type') == 'multi_day':
        days = route_data.get('days', [])
        if day_number < 1 or day_number > len(days):
            return "Requested day not found in planned routes.", 404
        day_route = days[day_number - 1]
        stops = day_route.get('stops', [])
    else:
        return "Invalid route data type", 404

    return render_template('map.html',
                           stops=stops,
                           day_number=day_number,
                           route_data=day_route,
                           api_key=GOOGLE_MAPS_API_KEY)

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

if __name__ == '__main__':
    print("Starting Flask application...")
    print(f"Database path: {DB_PATH}")
    print(f"Database exists: {os.path.exists(DB_PATH)}")
    print(f"Google Maps API Key loaded: {'Yes' if GOOGLE_MAPS_API_KEY else 'No'}")
    app.run(debug=True, host='127.0.0.1', port=5000)