from flask import Flask, render_template, jsonify, request, redirect, url_for, session
import sqlite3
import os
import time
from werkzeug.utils import secure_filename
from models.branch_model import create_tables
from services.distance_service import get_distance_matrix
from services.map_service import generate_map
from config import DB_PATH, GOOGLE_MAPS_API_KEY, SECRET_KEY
from services.tsp_solver import optimize_daily_route
import re
import time

MAX_DISTANCE_PER_DAY = 180_000  # 180 km in meters

app = Flask(__name__)
app.secret_key = SECRET_KEY


# Global variable to store last route data
last_route_data = None

def store_last_route(route_data):
    """Store the last route data globally"""
    global last_route_data
    last_route_data = route_data

def get_last_route():
    """Get the last stored route data"""
    global last_route_data
    return last_route_data

# Try to initialize DB at import time
_DB_INIT_DONE = False
try:
    create_tables()
    _DB_INIT_DONE = True
except Exception as e:
    print(f"⚠️ DB init at import warning: {e}")

@app.before_request
def _ensure_db_initialized_guard():
    global _DB_INIT_DONE
    if not _DB_INIT_DONE:
        try:
            create_tables()
            _DB_INIT_DONE = True
        except Exception as e:
            print(f"⚠️ DB init (before_request) warning: {e}")


def get_branches():
    """Get all branches from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, address, lat, lng, is_hq, visited 
        FROM branches 
        ORDER BY is_hq DESC, name
    """)
    branches = cursor.fetchall()
    conn.close()
    return branches

def get_non_hq_branches():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM branches WHERE is_hq = 0 ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return rows


# --------------- Auth Helpers ---------------
import hashlib

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def current_user():
    return session.get("user")

def require_role(*roles):
    user = current_user()
    if not user or user.get("role") not in roles:
        return False
    return True

def get_db():
    return sqlite3.connect(DB_PATH)


def mark_branch_visited(branch_id):
    """Mark a branch as visited"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE branches SET visited = 1 WHERE id = ?", (branch_id,))
    conn.commit()
    conn.close()


def reset_all_branches():
    """Reset all branches to unvisited before planning"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE branches SET visited = 0 WHERE is_hq = 0")
    conn.commit()
    conn.close()
    print("🔄 All branches reset to unvisited")


def ensure_branch_manager_columns():
    """Ensure branch_managers table exists and has required columns (password_hash)."""
    try:
        conn = get_db()
        cur = conn.cursor()
        # Make sure tables exist first
        try:
            create_tables()
        except Exception:
            pass
        cur.execute("PRAGMA table_info(branch_managers)")
        cols = [r[1] for r in cur.fetchall()]
        if len(cols) == 0:
            # Table missing; create via create_tables()
            try:
                create_tables()
            except Exception:
                pass
        else:
            if "password_hash" not in cols:
                cur.execute("ALTER TABLE branch_managers ADD COLUMN password_hash TEXT DEFAULT ''")
                conn.commit()
            if "approved" not in cols:
                cur.execute("ALTER TABLE branch_managers ADD COLUMN approved INTEGER DEFAULT 0")
                conn.commit()
        conn.close()
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        print(f"ensure_branch_manager_columns warning: {e}")


def plan_single_day(branches, distance_matrix, time_matrix, use_tsp_optimization=True):
    """
    Plan a single day route visiting as many unvisited branches as possible within 180km
    """
    hq_index = next(i for i, b in enumerate(branches) if b[5] == 1)
    unvisited = set(i for i, b in enumerate(branches) if b[5] == 0 and (len(b) <= 6 or b[6] == 0))
    
    if not unvisited:
        return None  # No unvisited branches
    
    day_route = [hq_index]  # Start at HQ
    day_distance = 0
    day_branches_visited = []
    
    print(f"Planning single day route with max {MAX_DISTANCE_PER_DAY/1000}km")
    print(f"HQ at index {hq_index}, {len(unvisited)} unvisited branches available")
    
    # Keep adding branches until we can't fit any more
    added_branch = True
    while added_branch and unvisited:
        added_branch = False
        current_position = day_route[-1]
        best_branch = None
        min_distance = float('inf')
        
        # Try each unvisited branch
        for branch_idx in unvisited:
            # Distance from current position to this branch
            leg_distance = distance_matrix[current_position][branch_idx]
            
            # Distance from this branch back to HQ (for return trip)
            return_distance = distance_matrix[branch_idx][hq_index]
            
            # Total distance if we add this branch and return to HQ
            total_with_this_branch = day_distance + leg_distance + return_distance
            
            #print(f"  Branch {branch_idx} ({branches[branch_idx][1]}): "
                  #f"current {day_distance/1000:.1f}km + leg {leg_distance/1000:.1f}km + return {return_distance/1000:.1f}km = {total_with_this_branch/1000:.1f}km")
            
            # Check if this branch fits within the daily limit
            if total_with_this_branch <= MAX_DISTANCE_PER_DAY:
                # Among feasible branches, pick the nearest one (greedy)
                if leg_distance < min_distance:
                    min_distance = leg_distance
                    best_branch = branch_idx
                    added_branch = True
        
        # Add the best branch if found
        if best_branch is not None:
            day_route.append(best_branch)
            day_distance += min_distance  # Add only the leg distance for now
            unvisited.remove(best_branch)
            day_branches_visited.append(best_branch)
            
            #print(f"✅ Added branch {best_branch} ({branches[best_branch][1]})")
            #print(f"   Running distance: {day_distance/1000:.1f}km")
        else:
            print(f"❌ No more branches can fit within {MAX_DISTANCE_PER_DAY/1000}km limit")
    
    # Complete the day by returning to HQ
    if len(day_route) > 1:  # Only if we visited at least one branch
        final_return_distance = distance_matrix[day_route[-1]][hq_index]
        day_route.append(hq_index)
        day_distance += final_return_distance
        
        #print(f"🏠 Return to HQ: +{final_return_distance/1000:.1f}km")
        #print(f"📊 Final distance: {day_distance/1000:.1f}km")
        #print(f"📍 Visited {len(day_branches_visited)} branches: {[branches[i][1] for i in day_branches_visited]}")
        #print(f"🗺️ Route: {' → '.join([branches[i][1] for i in day_route])}")
        
        # Optimize route order with TSP if requested and beneficial
        if use_tsp_optimization and len(day_branches_visited) > 2:
            #print(f"🔄 Optimizing route order with TSP...")
            try:
                optimized_route = optimize_daily_route(
                    distance_matrix, 
                    day_branches_visited, 
                    hq_index, 
                    MAX_DISTANCE_PER_DAY
                )
                
                if optimized_route and len(optimized_route) >= len(day_route):
                    # Calculate optimized distance
                    opt_distance = 0
                    for i in range(len(optimized_route) - 1):
                        opt_distance += distance_matrix[optimized_route[i]][optimized_route[i + 1]]
                    
                    print(f"   TSP distance: {opt_distance/1000:.1f}km vs original {day_distance/1000:.1f}km")
                    
                    if opt_distance <= MAX_DISTANCE_PER_DAY and opt_distance < day_distance:
                        day_route = optimized_route
                        day_distance = opt_distance
                        #print(f"✅ Using TSP optimized route (saved {(day_distance - opt_distance)/1000:.1f}km)")
                        print(f"🗺️ Optimized: {' → '.join([branches[i][1] for i in day_route])}")
                    else:
                        print(f"➡️ Keeping original route (TSP didn't improve or exceeded limit)")
                
            except Exception as e:
                print(f"⚠️ TSP optimization failed: {e}")
        
        # Don't automatically mark branches as visited - let user confirm them
        # for branch_idx in day_branches_visited:
        #     mark_branch_visited(branches[branch_idx][0])
        
        return day_route
    else:
        print(f"⚠️ No branches could be visited")
        return None


def plan_multi_day(branches, distance_matrix, time_matrix, use_tsp_optimization=True):
    """
    Plan multi-day routes visiting as many branches as possible within 180km per day
    """
    days = []
    hq_index = next(i for i, b in enumerate(branches) if b[5] == 1)
    unvisited = set(i for i, b in enumerate(branches) if b[5] == 0)
    
    day_count = 1
    print(f"Planning routes with max {MAX_DISTANCE_PER_DAY/1000}km per day")
    print(f"HQ at index {hq_index}, {len(unvisited)} branches available")
    print(f"Goal: Visit as many branches as possible within distance limit")
    
    while unvisited:
        day_route = [hq_index]  # Start at HQ
        day_distance = 0
        day_branches_visited = []
        
        print(f"\n--- Planning Day {day_count} ---")
        print(f"Available branches: {len(unvisited)}")
        
        # Keep adding branches until we can't fit any more
        added_branch = True
        while added_branch and unvisited:
            added_branch = False
            current_position = day_route[-1]
            best_branch = None
            min_distance = float('inf')
            
            # Try each unvisited branch
            for branch_idx in unvisited:
                # Distance from current position to this branch
                leg_distance = distance_matrix[current_position][branch_idx]
                
                # Distance from this branch back to HQ (for return trip)
                return_distance = distance_matrix[branch_idx][hq_index]
                
                # Total distance if we add this branch and return to HQ
                total_with_this_branch = day_distance + leg_distance + return_distance
                
                print(f"    Branch {branch_idx} ({branches[branch_idx][1]}): "
                      f"current {day_distance/1000:.1f}km + leg {leg_distance/1000:.1f}km + return {return_distance/1000:.1f}km = {total_with_this_branch/1000:.1f}km")
                
                # Check if this branch fits within the daily limit
                if total_with_this_branch <= MAX_DISTANCE_PER_DAY:
                    # Among feasible branches, pick the nearest one (greedy)
                    if leg_distance < min_distance:
                        min_distance = leg_distance
                        best_branch = branch_idx
                        added_branch = True
            
            # Add the best branch if found
            if best_branch is not None:
                day_route.append(best_branch)
                day_distance += min_distance  # Add only the leg distance for now
                unvisited.remove(best_branch)
                day_branches_visited.append(best_branch)
                
                print(f"  ✅ Added branch {best_branch} ({branches[best_branch][1]})")
                print(f"     Running distance: {day_distance/1000:.1f}km")
            else:
                print(f"  ❌ No more branches can fit within {MAX_DISTANCE_PER_DAY/1000}km limit")
        
        # Complete the day by returning to HQ
        if len(day_route) > 1:  # Only if we visited at least one branch
            final_return_distance = distance_matrix[day_route[-1]][hq_index]
            day_route.append(hq_index)
            day_distance += final_return_distance
            
            print(f"  🏠 Return to HQ: +{final_return_distance/1000:.1f}km")
            print(f"  📊 Day {day_count} final distance: {day_distance/1000:.1f}km")
            print(f"  📍 Visited {len(day_branches_visited)} branches: {[branches[i][1] for i in day_branches_visited]}")
            print(f"  🗺️ Route: {' → '.join([branches[i][1] for i in day_route])}")
            
            # Optimize route order with TSP if requested and beneficial
            if use_tsp_optimization and len(day_branches_visited) > 2:
                print(f"  🔄 Optimizing route order with TSP...")
                try:
                    optimized_route = optimize_daily_route(
                        distance_matrix, 
                        day_branches_visited, 
                        hq_index, 
                        MAX_DISTANCE_PER_DAY
                    )
                    
                    if optimized_route and len(optimized_route) >= len(day_route):
                        # Calculate optimized distance
                        opt_distance = 0
                        for i in range(len(optimized_route) - 1):
                            opt_distance += distance_matrix[optimized_route[i]][optimized_route[i + 1]]
                        
                        print(f"     TSP distance: {opt_distance/1000:.1f}km vs original {day_distance/1000:.1f}km")
                        
                        if opt_distance <= MAX_DISTANCE_PER_DAY and opt_distance < day_distance:
                            day_route = optimized_route
                            day_distance = opt_distance
                            print(f"  ✅ Using TSP optimized route (saved {(day_distance - opt_distance)/1000:.1f}km)")
                            print(f"  🗺️ Optimized: {' → '.join([branches[i][1] for i in day_route])}")
                        else:
                            print(f"  ➡️ Keeping original route (TSP didn't improve or exceeded limit)")
                    
                except Exception as e:
                    print(f"  ⚠️ TSP optimization failed: {e}")
            
            days.append(day_route)
            
            # Don't automatically mark branches as visited - let user confirm them
            # for branch_idx in day_branches_visited:
            #     mark_branch_visited(branches[branch_idx][0])
        
        else:
            print(f"  ⚠️ No branches could be visited on Day {day_count}")
            break  # No progress possible
        
        day_count += 1
        
        # Safety check
        if day_count > 10:
            print("⚠️ Safety limit: stopping after 10 days")
            break
    
    # Show final summary
    total_branches_visited = sum(len([i for i in route if branches[i][5] == 0]) for route in days)
    total_branches_available = len([b for b in branches if b[5] == 0])
    
    print(f"\n🎉 Planning completed!")
    print(f"📊 Generated {len(days)} days of routes")
    print(f"📍 Visited {total_branches_visited} out of {total_branches_available} branches")
    
    if total_branches_visited < total_branches_available:
        remaining = [i for i in range(len(branches)) if branches[i][5] == 0 and i in unvisited]
        print(f"⚠️ Remaining unvisited branches: {[branches[i][1] for i in remaining]}")
    
    return days


def debug_distance_matrix(branches, distance_matrix):
    '''"""Print distance matrix for debugging"""
    n = len(branches)
    print(f"\n📊 Distance Matrix ({n}x{n}) in km:")
    
    # Print header
    print("From\\To  ", end="")
    for j in range(min(n, 8)):  # Limit to first 8 to avoid clutter
        print(f"{j:6}", end="")
    if n > 8:
        print("  ...")
    else:
        print()
    
    # Print rows
    for i in range(min(n, 8)):
        branch_name = branches[i][1][:8] if len(branches[i][1]) > 8 else branches[i][1]
        print(f"{i}({branch_name:8})", end="")
        for j in range(min(n, 8)):
            if distance_matrix[i][j] == 999999:
                print("  ∞   ", end="")
            else:
                dist_km = distance_matrix[i][j] / 1000
                print(f"{dist_km:6.1f}", end="")
        if n > 8:
            print("  ...")
        else:
            print()
    
    if n > 8:
        print("  ⋮")'''


# ------------------ Flask Routes ------------------

@app.route("/")
def index():
    # If not logged in, redirect to explicit /login page
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    # Route users to their appropriate home pages
    role = user.get("role")
    if role == "admin":
        return redirect(url_for("admin_dashboard"))
    if role == "manager":
        return redirect(url_for("manager_dashboard"))
    # default auditor landing
    return render_template("index.html", user=user)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    # Ensure tables exist before attempting to query
    try:
        create_tables()
    except Exception as e:
        print(f"⚠️ DB init during login warning: {e}")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "auditor")  # 'admin' or 'auditor' or 'manager'
    if role == "manager":
        ensure_branch_manager_columns()
    conn = get_db()
    cur = conn.cursor()
    # Query appropriate table and include 'active' for auditors
    if role == "admin":
        table = "admins"
        cur.execute("SELECT id, username, password_hash FROM admins WHERE username = ?", (username,))
    elif role == "manager":
        table = "branch_managers"
        # For managers, use contact_no as the login identifier (entered in the username field)
        ensure_branch_manager_columns()
        # Now authenticate managers by their Name (case-insensitive)
        cur.execute(
            "SELECT id, name, contact_no, branch_id, password_hash, approved "
            "FROM branch_managers WHERE name = ? COLLATE NOCASE",
            (username,)
        )
    else:
        table = "auditors"
        cur.execute("SELECT id, username, password_hash, active FROM auditors WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return render_template("login.html", error="Invalid credentials")
    # Determine password hash index based on role query shape
    if role == "manager":
        pw_hash = row[4]
    else:
        pw_hash = row[2]
    if pw_hash != hash_password(password):
        return render_template("login.html", error="Invalid credentials")
    # if auditor, check active flag
    if table == "auditors" and (len(row) < 4 or row[3] != 1):
        return render_template("login.html", error="Auditor is inactive")
    # if manager, require approved flag
    if table == "branch_managers":
        approved = 0 if len(row) < 6 else (row[5] or 0)
        if approved != 1:
            return render_template("login.html", error="Manager is pending approval")

    # Build session payload per role
    if role == "manager":
        session["user"] = {
            "id": row[0],
            "username": row[1],  # manager name
            "contact_no": row[2],
            "branch_id": row[3],
            "role": "manager",
        }
        return redirect(url_for("manager_dashboard"))
    else:
        session["user"] = {"id": row[0], "username": row[1], "role": role}
        if role == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("index"))


# ----- Branch Manager Registration -----
@app.route("/register_manager", methods=["GET"])
def register_manager_page():
    # Publicly accessible to allow managers to register
    branches = get_non_hq_branches()
    return render_template("register_manager.html", branches=branches)


@app.route("/register_manager", methods=["POST"])
def register_manager_submit():
    try:
        name = request.form.get("name", "").strip()
        contact_no = request.form.get("contact_no", "").strip()
        branch_id = request.form.get("branch_id", "").strip()
        password = request.form.get("password", "")
        if not name or not contact_no or not branch_id:
            return render_template("register_manager.html", error="All fields are required", branches=get_non_hq_branches())
        if not password:
            return render_template("register_manager.html", error="Password is required", branches=get_non_hq_branches())
        ensure_branch_manager_columns()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # New or update: set password; keep approved default 0 on (re)registration
        cur.execute(
            "INSERT OR REPLACE INTO branch_managers (id, name, contact_no, branch_id, password_hash, approved) "
            "VALUES ((SELECT id FROM branch_managers WHERE branch_id = ?), ?, ?, ?, ?, 0)",
            (int(branch_id), name, contact_no, int(branch_id), hash_password(password))
        )
        conn.commit()
        conn.close()
        return render_template("register_manager.html", success=True, branches=get_non_hq_branches())
    except Exception as e:
        return render_template("register_manager.html", error=str(e), branches=get_non_hq_branches())


# ------------- Branch Manager Dashboard -------------
@app.route("/manager", methods=["GET"])
def manager_dashboard():
    if not require_role("manager"):
        return redirect(url_for("login"))
    # Load assigned branch details
    user = current_user()
    branch = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, address, lat, lng, visited FROM branches WHERE id = ?", (user.get("branch_id"),))
        branch = cur.fetchone()
        conn.close()
    except Exception:
        branch = None
    return render_template("manager/dashboard.html", user=user, branch=branch)


@app.route("/manager/mark-visited", methods=["POST"])
def manager_mark_visited():
    if not require_role("manager"):
        return redirect(url_for("login"))
    user = current_user()
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE branches SET visited = 1 WHERE id = ?", (user.get("branch_id"),))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Manager mark visited failed: {e}")
    return redirect(url_for("manager_dashboard"))


@app.route('/manager/profile', methods=['GET'])
def manager_view_profile():
    if not require_role("manager"):
        return redirect(url_for("login"))
    user = current_user()
    # Load branch info
    branch = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, address, lat, lng, visited FROM branches WHERE id = ?", (user.get("branch_id"),))
        branch = cur.fetchone()
        conn.close()
    except Exception:
        branch = None
    return render_template('manager/viewprofile.html', user=user, branch=branch)


@app.route('/manager/branch/edit', methods=['GET'])
def manager_branch_edit_page():
    if not require_role("manager"):
        return redirect(url_for("login"))
    user = current_user()
    branch = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, address, lat, lng FROM branches WHERE id = ?", (user.get("branch_id"),))
        branch = cur.fetchone()
        conn.close()
    except Exception:
        branch = None
    return render_template('manager/edit_branchdetails.html', user=user, branch=branch)


@app.route('/manager/branch/update', methods=['POST'])
def manager_branch_update():
    if not require_role("manager"):
        return redirect(url_for("login"))
    user = current_user()
    name = (request.form.get('name') or '').strip()
    address = (request.form.get('address') or '').strip()
    lat = request.form.get('lat')
    lng = request.form.get('lng')
    errors = []
    # Validate
    if not name:
        errors.append('Branch name is required')
    try:
        lat_val = float(lat)
        lng_val = float(lng)
    except Exception:
        errors.append('Latitude and Longitude must be valid numbers')
        lat_val = None
        lng_val = None
    if errors:
        # Reload a page with errors - default send back to edit page
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id, name, address, lat, lng FROM branches WHERE id = ?", (user.get("branch_id"),))
            branch = cur.fetchone()
            conn.close()
        except Exception:
            branch = None
        return render_template('manager/edit_branchdetails.html', user=user, branch=branch, error='; '.join(errors))
    # Persist
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE branches SET name = ?, address = ?, lat = ?, lng = ? WHERE id = ?",
            (name, address, lat_val, lng_val, user.get('branch_id'))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        return render_template('manager/edit_branchdetails.html', user=user, branch=(user.get('branch_id'), name, address, lat, lng), error=str(e))
    # Redirect back to dashboard after update
    return redirect(url_for('manager_dashboard'))


@app.route("/api/branches/list", methods=["GET"])
def api_branches_list():
    try:
        rows = get_non_hq_branches()
        return jsonify({"success": True, "items": [{"id": r[0], "name": r[1]} for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin", methods=["GET"])
def admin_dashboard():
    if not require_role("admin"):
        return redirect(url_for("login"))
    return render_template("admin.html", user=current_user())


@app.route("/admin/register-auditor", methods=["POST"])
def admin_register_auditor():
    if not require_role("admin"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required"}), 400
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO auditors (username, password_hash, created_by_admin_id) VALUES (?, ?, ?)",
            (username, hash_password(password), current_user()["id"]),
        )
        conn.commit()
        return jsonify({"success": True, "message": f"Auditor '{username}' created"})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Username already exists"}), 409
    finally:
        conn.close()

# New endpoint: admin can add branches
@app.route("/admin/add-branch", methods=["POST"])
def admin_add_branch():
    if not require_role("admin"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    try:
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        address = (data.get("address") or "").strip()
        lat = data.get("lat")
        lng = data.get("lng")
        is_hq = int(data.get("is_hq") or 0)

        if not name:
            return jsonify({"success": False, "error": "Branch name is required"}), 400
        if lat is None or lng is None:
            return jsonify({"success": False, "error": "Latitude and longitude required"}), 400

        # Validate numeric coordinates
        try:
            lat = float(lat)
            lng = float(lng)
        except ValueError:
            return jsonify({"success": False, "error": "Invalid latitude or longitude"}), 400

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO branches (name, address, lat, lng, is_hq, visited)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (name, address, lat, lng, is_hq))
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": f"Branch '{name}' added"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/delete-branch/<int:branch_id>", methods=["DELETE"])
def admin_delete_branch(branch_id):
    if not require_role("admin"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # First, check if the branch exists
        cur.execute("SELECT name, is_hq FROM branches WHERE id = ?", (branch_id,))
        branch = cur.fetchone()
        
        if not branch:
            return jsonify({"success": False, "error": "Branch not found"}), 404
        
        branch_name, is_hq = branch[0], branch[1]
        
        # Prevent deletion of HQ if it's the only HQ
        if is_hq:
            cur.execute("SELECT COUNT(*) FROM branches WHERE is_hq = 1")
            hq_count = cur.fetchone()[0]
            if hq_count <= 1:
                return jsonify({"success": False, "error": "Cannot delete the only headquarters"}), 400
        
        # Delete the branch
        cur.execute("DELETE FROM branches WHERE id = ?", (branch_id,))
        
        if cur.rowcount == 0:
            return jsonify({"success": False, "error": "Branch not found or already deleted"}), 404
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": f"Branch '{branch_name}' deleted successfully"})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/auditors", methods=["GET"])
def api_list_auditors():
    if not require_role("admin"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, username, active, created_at FROM auditors ORDER BY username")
        rows = cur.fetchall()
        conn.close()
        items = [
            {"id": r[0], "username": r[1], "active": r[2], "created_at": r[3]}
            for r in rows
        ]
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/plan", methods=["POST"])
def api_plan_single_day():
    """Plan a single day route"""
    try:
        # auditors and admins can plan
        if not require_role("auditor", "admin"):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        print("🚀 Starting single day route planning...")
        
        create_tables()
        
        # Get all branches (don't reset - we want to track visited ones)
        branches = get_branches()
        
        if not branches:
            print("❌ No branches found in database")
            return jsonify({"error": "No branches found in database."})

        print(f"📍 Found {len(branches)} branches:")
        hq_count = sum(1 for b in branches if b[5] == 1)
        branch_count = sum(1 for b in branches if b[5] == 0)
        unvisited_count = sum(1 for b in branches if b[5] == 0 and (len(b) <= 6 or b[6] == 0))
        
        for i, branch in enumerate(branches):
            visited_status = ""
            if len(branch) > 6 and branch[6] == 1:
                visited_status = " (visited)"
            branch_type = "HQ" if branch[5] == 1 else f"Branch{visited_status}"
            print(f"  {i}: {branch[1]} ({branch_type}) at ({branch[3]:.4f}, {branch[4]:.4f})")
        
        print(f"  Summary: {hq_count} HQ, {unvisited_count} unvisited branches")
        
        if hq_count != 1:
            return jsonify({"error": f"Expected exactly 1 HQ, found {hq_count}"})
        
        if unvisited_count == 0:
            return jsonify({"error": "All branches have been visited", "all_completed": True})

        # Get distance matrix
        print(f"\n🗺️ Fetching distance matrix for {len(branches)} locations...")
        coords = [(b[3], b[4]) for b in branches]
        
        distance_matrix, time_matrix = get_distance_matrix(coords)
        
        # Validate distance matrix
        if not distance_matrix:
            return jsonify({"error": "Failed to get distance matrix from Google API"})
        
        if len(distance_matrix) != len(branches):
            return jsonify({"error": f"Distance matrix size mismatch: {len(distance_matrix)} vs {len(branches)}"})
        
        # Debug distance matrix
        debug_distance_matrix(branches, distance_matrix)
        
        # Plan single day route
        print(f"\n🗓️ Planning single day route...")
        day_route = plan_single_day(branches, distance_matrix, time_matrix)
        
        if not day_route:
            return jsonify({"error": "No route could be generated within distance constraints"})
        
        # Generate map for single day
        print(f"\n🗺️ Generating map...")
        try:
            generate_map(branches, [day_route], GOOGLE_MAPS_API_KEY)
            print("✅ Map generated successfully")
        except Exception as map_error:
            print(f"⚠️ Map generation failed: {map_error}")

        # Build JSON response
        print(f"\n📋 Building response...")
        total_dist = 0
        stops = []
        
        for k in range(len(day_route) - 1):
            i, j = day_route[k], day_route[k + 1]
            leg_distance = distance_matrix[i][j]
            total_dist += leg_distance
            
            stops.append({
                "name": branches[i][1], 
                "address": branches[i][2],
                "index": i,
                "lat": branches[i][3],
                "lng": branches[i][4]
            })
        
        # Add final stop
        final_idx = day_route[-1]
        stops.append({
            "name": branches[final_idx][1], 
            "address": branches[final_idx][2],
            "index": final_idx,
            "lat": branches[final_idx][3],
            "lng": branches[final_idx][4]
        })
        
        branch_count_this_day = len([i for i in day_route if branches[i][5] == 0])
        remaining_branches = sum(1 for b in branches if b[5] == 0 and (len(b) <= 6 or b[6] == 0))
        
        # Get branches that will be visited (excluding HQ)
        visited_branches = []
        for i in day_route:
            if branches[i][5] == 0:  # Not HQ
                visited_branches.append({
                    "id": branches[i][0],
                    "name": branches[i][1],
                    "address": branches[i][2],
                    "lat": branches[i][3],
                    "lng": branches[i][4]
                })
        
        result = {
            "day": 1, 
            "distance_m": total_dist,
            "distance_km": round(total_dist/1000, 2),
            "branches_visited": branch_count_this_day,
            "remaining_branches": remaining_branches,
            "stops": stops,
            "route_indices": day_route,
            "visited_branches": visited_branches
        }
        
        # Store the route data for future retrieval
        route_data = {
            "type": "single_day",
            "day_route": result,
            "has_more_branches": remaining_branches > 0
        }
        store_last_route(route_data)
        
        print(f"✅ Single day planning completed: {branch_count_this_day} branches, {len(stops)} stops, {total_dist/1000:.1f}km")
        print(f"📊 Remaining branches: {remaining_branches}")
        
        return jsonify({"day_route": result, "success": True, "has_more_branches": remaining_branches > 0})
        
    except Exception as e:
        print(f"\n❌ Error in api_plan_single_day: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Planning failed: {str(e)}", "success": False})


@app.route("/api/plan-multi", methods=["POST"])
def api_plan_multi_day():
    """Plan all remaining days at once (original behavior)"""
    try:
        if not require_role("auditor", "admin"):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        print("🚀 Starting multi-day route planning...")
        
        create_tables()
        
        # Reset all branches to unvisited before planning
        reset_all_branches()
        
        branches = get_branches()
        
        if not branches:
            print("❌ No branches found in database")
            return jsonify({"error": "No branches found in database."})

        print(f"📍 Found {len(branches)} branches:")
        hq_count = sum(1 for b in branches if b[5] == 1)
        branch_count = sum(1 for b in branches if b[5] == 0)
        
        for i, branch in enumerate(branches):
            branch_type = "HQ" if branch[5] == 1 else "Branch"
            print(f"  {i}: {branch[1]} ({branch_type}) at ({branch[3]:.4f}, {branch[4]:.4f})")
        
        print(f"  Summary: {hq_count} HQ, {branch_count} branches")
        
        if hq_count != 1:
            return jsonify({"error": f"Expected exactly 1 HQ, found {hq_count}"})

        # Get distance matrix
        print(f"\n🗺️ Fetching distance matrix for {len(branches)} locations...")
        coords = [(b[3], b[4]) for b in branches]
        
        distance_matrix, time_matrix = get_distance_matrix(coords)
        
        # Validate distance matrix
        if not distance_matrix:
            return jsonify({"error": "Failed to get distance matrix from Google API"})
        
        if len(distance_matrix) != len(branches):
            return jsonify({"error": f"Distance matrix size mismatch: {len(distance_matrix)} vs {len(branches)}"})
        
        # Debug distance matrix
        debug_distance_matrix(branches, distance_matrix)
        
        # Plan multi-day routes
        print(f"\n🗓️ Planning multi-day routes...")
        days = plan_multi_day(branches, distance_matrix, time_matrix)
        
        if not days:
            return jsonify({"error": "No routes could be generated within distance constraints"})
        
        # Generate map
        print(f"\n🗺️ Generating map...")
        try:
            generate_map(branches, days, GOOGLE_MAPS_API_KEY)
            print("✅ Map generated successfully")
        except Exception as map_error:
            print(f"⚠️ Map generation failed: {map_error}")

        # Build JSON response
        print(f"\n📋 Building response...")
        result = []
        
        for d, route in enumerate(days, 1):
            total_dist = 0
            stops = []
            
            for k in range(len(route) - 1):
                i, j = route[k], route[k + 1]
                leg_distance = distance_matrix[i][j]
                total_dist += leg_distance
                
                stops.append({
                    "name": branches[i][1], 
                    "address": branches[i][2],
                    "index": i,
                    "lat": branches[i][3],
                    "lng": branches[i][4]
                })
            
            # Add final stop
            final_idx = route[-1]
            stops.append({
                "name": branches[final_idx][1], 
                "address": branches[final_idx][2],
                "index": final_idx,
                "lat": branches[final_idx][3],
                "lng": branches[final_idx][4]
            })
            
            branch_count_this_day = len([i for i in route if branches[i][5] == 0])
            
            # Get branches that will be visited (excluding HQ)
            visited_branches = []
            for i in route:
                if branches[i][5] == 0:  # Not HQ
                    visited_branches.append({
                        "id": branches[i][0],
                        "name": branches[i][1],
                        "address": branches[i][2],
                        "lat": branches[i][3],
                        "lng": branches[i][4]
                    })
            
            day_result = {
                "day": d, 
                "distance_m": total_dist,
                "distance_km": round(total_dist/1000, 2),
                "branches_visited": branch_count_this_day,
                "stops": stops,
                "route_indices": route,
                "visited_branches": visited_branches
            }
            
            result.append(day_result)
            print(f"  Day {d}: {branch_count_this_day} branches, {len(stops)} stops, {total_dist/1000:.1f}km")

        print(f"\n🎉 Planning completed successfully: {len(result)} days")
        
        # Store the route data for future retrieval
        route_data = {
            "type": "multi_day",
            "days": result
        }
        store_last_route(route_data)
        
        return jsonify({"days": result, "success": True})
        
    except Exception as e:
        print(f"\n❌ Error in api_plan_multi_day: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Planning failed: {str(e)}", "success": False})


@app.route("/api/save-visits", methods=["POST"])
def api_save_visits():
    """Save selected branches as visited (but keep selection window open)"""
    try:
        data = request.get_json()
        branch_ids = data.get('branch_ids', [])
        
        if not branch_ids:
            return jsonify({"error": "No branch IDs provided", "success": False})
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        for branch_id in branch_ids:
            cursor.execute("UPDATE branches SET visited = 1 WHERE id = ?", (branch_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": f"Saved {len(branch_ids)} branches as visited", "action": "save"})
        
    except Exception as e:
        return jsonify({"error": f"Failed to save visits: {str(e)}", "success": False})


@app.route("/api/submit-visits", methods=["POST"])
def api_submit_visits():
    """Submit and close the selection window"""
    try:
        data = request.get_json()
        branch_ids = data.get('branch_ids', [])
        
        # Save any selected branches first
        if branch_ids:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            for branch_id in branch_ids:
                cursor.execute("UPDATE branches SET visited = 1 WHERE id = ?", (branch_id,))
            
            conn.commit()
            conn.close()
        
        return jsonify({
            "success": True, 
            "message": f"Submitted {len(branch_ids)} branches and closed the window",
            "action": "submit"
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to submit visits: {str(e)}", "success": False})


@app.route("/api/last-route", methods=["GET"])
def api_get_last_route():
    """Get the last planned route data"""
    try:
        last_route = get_last_route()
        if last_route:
            return jsonify({"success": True, "route_data": last_route})
        else:
            return jsonify({"success": False, "message": "No previous route found"})
        
    except Exception as e:
        return jsonify({"error": f"Failed to get last route: {str(e)}", "success": False})


@app.route("/api/branches", methods=["GET"])
def api_get_branches():
    """Get current branch states"""
    try:
        branches = get_branches()
        branch_list = []
        for branch in branches:
            branch_list.append({
                "id": branch[0],
                "name": branch[1],
                "address": branch[2],
                "lat": branch[3],
                "lng": branch[4],
                "is_hq": branch[5],
                "visited": branch[6] if len(branch) > 6 else 0
            })
        
        return jsonify({"success": True, "branches": branch_list})
        
    except Exception as e:
        return jsonify({"error": f"Failed to get branches: {str(e)}", "success": False})


@app.route("/api/reset", methods=["POST"])
def api_reset_branches():
    """Reset all branches to unvisited state"""
    try:
        if not require_role("auditor", "admin"):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        reset_all_branches()
        return jsonify({"success": True, "message": "All branches reset to unvisited"})
    except Exception as e:
        return jsonify({"error": f"Reset failed: {str(e)}", "success": False})


@app.route("/api/status", methods=["GET"])
def api_status():
    """Get current status of branches"""
    try:
        if not require_role("auditor", "admin"):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        branches = get_branches()
        total_branches = sum(1 for b in branches if b[5] == 0)
        visited_branches = sum(1 for b in branches if b[5] == 0 and len(b) > 6 and b[6] == 1)
        unvisited_branches = total_branches - visited_branches
        
        return jsonify({
            "success": True,
            "total_branches": total_branches,
            "visited_branches": visited_branches,
            "unvisited_branches": unvisited_branches,
            "all_completed": unvisited_branches == 0
        })
    except Exception as e:
        return jsonify({"error": f"Status check failed: {str(e)}", "success": False})


@app.route("/api/visited-branches", methods=["GET"])
def api_visited_branches():
    """List visited branches (non-HQ)"""
    try:
        if not require_role("admin", "auditor"):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, address FROM branches WHERE is_hq = 0 AND visited = 1 ORDER BY name"
        )
        rows = cur.fetchall()
        conn.close()
        items = [{"id": r[0], "name": r[1], "address": r[2]} for r in rows]
        return jsonify({"success": True, "count": len(items), "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/map/day/<int:day_id>")
def show_map(day_id):
    # Admin can visit generated path also; both roles can view maps
    if not require_role("auditor", "admin"):
        return redirect(url_for("login"))
    return render_template("map.html")


@app.route("/admin/branches", methods=["GET"])
def admin_branches_page():
    if not require_role("admin"):
        return redirect(url_for("login"))
    return render_template("branch_management.html", user=current_user())


# ---------------- Manager Registrations (Admin) ----------------
@app.route("/admin/managers", methods=["GET"])
def admin_managers_page():
    if not require_role("admin"):
        return redirect(url_for("login"))
    return render_template("admin_managers.html", user=current_user())


@app.route("/api/admin/managers/pending", methods=["GET"])
def api_admin_managers_pending():
    if not require_role("admin"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    try:
        ensure_branch_manager_columns()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT m.id, m.name, m.contact_no, m.branch_id, m.approved, b.name, b.address FROM branch_managers m "
            "LEFT JOIN branches b ON b.id = m.branch_id WHERE m.approved = 0 ORDER BY m.name"
        )
        rows = cur.fetchall()
        conn.close()
        items = [
            {"id": r[0], "name": r[1], "contact_no": r[2], "branch_id": r[3], "approved": r[4], "branch_name": r[5], "branch_address": r[6]}
            for r in rows
        ]
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/admin/managers", methods=["GET"])
def api_admin_managers_all():
    if not require_role("admin"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    try:
        ensure_branch_manager_columns()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT m.id, m.name, m.contact_no, m.branch_id, m.approved, b.name, b.address FROM branch_managers m "
            "LEFT JOIN branches b ON b.id = m.branch_id ORDER BY m.approved DESC, m.name"
        )
        rows = cur.fetchall()
        conn.close()
        items = [
            {"id": r[0], "name": r[1], "contact_no": r[2], "branch_id": r[3], "approved": r[4], "branch_name": r[5], "branch_address": r[6]}
            for r in rows
        ]
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/admin/managers/<int:mid>/approve", methods=["POST"])
def api_admin_manager_approve(mid):
    if not require_role("admin"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE branch_managers SET approved = 1 WHERE id = ?", (mid,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/admin/managers/<int:mid>", methods=["DELETE"])
def api_admin_manager_delete(mid):
    if not require_role("admin"):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM branch_managers WHERE id = ?", (mid,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ----------------- small fixes: remove duplicate endpoints & provide helpers -----------------

def get_auditor(username):
    """Return auditor record as a dict or None."""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Inspect existing columns and build a safe select list
        cur.execute("PRAGMA table_info(auditors)")
        cols = [r[1] for r in cur.fetchall()]

        preferred = ["id", "username", "active", "created_at", "email", "name", "phone", "avatar"]
        select_cols = [c for c in preferred if c in cols]
        if not select_cols:
            conn.close()
            return None

        sql = "SELECT " + ", ".join(select_cols) + " FROM auditors WHERE username = ?"
        cur.execute(sql, (username,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None

        auditor = {"role": "auditor"}
        for idx, col in enumerate(select_cols):
            auditor[col] = row[idx]

        return auditor
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return None


# Lightweight "login as" helper route for testing / quick links.
# NOTE: renamed to avoid colliding with the main /login endpoint.
@app.route('/login_as/<username>')
def login_as(username):
    auditor = get_auditor(username)
    if auditor:
        # Set session user in the same shape used by the main login flow
        session['user'] = {
            "id": auditor.get("id"),
            "username": auditor.get("username"),
            "role": "auditor",
            "name": auditor.get("name"),
            "email": auditor.get("email"),
        }
        return redirect(url_for('auditor_profile'))
    return "Auditor not found", 404


# Canonical auditor profile route that checks session["user"] and renders the template.
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def ensure_auditor_columns():
    """Add name,email,phone,avatar columns to auditors table if missing (safe no-op if present)."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(auditors)")
        cols = [r[1] for r in cur.fetchall()]
        if "name" not in cols:
            cur.execute("ALTER TABLE auditors ADD COLUMN name TEXT")
        if "email" not in cols:
            cur.execute("ALTER TABLE auditors ADD COLUMN email TEXT")
        if "phone" not in cols:
            cur.execute("ALTER TABLE auditors ADD COLUMN phone TEXT")
        if "avatar" not in cols:
            cur.execute("ALTER TABLE auditors ADD COLUMN avatar TEXT")
        conn.commit()
    except Exception:
        # ignore DB alter errors (concurrency / first-run edge cases), page still works
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

# Replace or add this auditor_profile route (GET + POST)
@app.route('/auditor/profile', methods=['GET', 'POST'])
def auditor_profile():
    user_session = session.get('user')
    if not user_session:
        return redirect(url_for('login'))
    if user_session.get('role') != 'auditor':
        return redirect(url_for('index'))

    ensure_auditor_columns()

    errors = {}
    form_values = {}

    if request.method == 'POST':
        name = (request.form.get('name') or "").strip()
        email = (request.form.get('email') or "").strip()
        phone = (request.form.get('phone') or "").strip()

        form_values = {"name": name, "email": email, "phone": phone}

        # Validation only if field provided (fields are optional)
        if name:
            if not re.match(r'^[A-Za-z ]+$', name):
                errors['name'] = "Name must contain only letters and spaces."
            elif len(name) < 2:
                errors['name'] = "Name is too short."

        if email:
            if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
                errors['email'] = "Invalid email address."

        if phone:
            digits = re.sub(r'\D', '', phone)
            if len(digits) != 10:
                errors['phone'] = "Phone number must have exactly 10 digits."
            else:
                phone = digits  # normalize to digits only

        # avatar optional
        avatar_rel = None
        avatar_file = request.files.get('avatar')
        if avatar_file and avatar_file.filename:
            if allowed_file(avatar_file.filename):
                ext = avatar_file.filename.rsplit('.', 1)[1].lower()
                filename = secure_filename(f"{user_session.get('username')}_{int(time.time())}.{ext}")
                save_path = os.path.join(UPLOAD_FOLDER, filename)
                avatar_file.save(save_path)
                avatar_rel = os.path.join('uploads', filename).replace("\\", "/")
            else:
                errors['avatar'] = "Unsupported file type."

        if not errors:
            # Persist only the provided fields (so uploading only avatar is allowed)
            try:
                conn = get_db()
                cur = conn.cursor()
                updates = []
                params = []
                if name:
                    updates.append("name = ?"); params.append(name)
                if email:
                    updates.append("email = ?"); params.append(email)
                if phone:
                    updates.append("phone = ?"); params.append(phone)
                if avatar_rel:
                    updates.append("avatar = ?"); params.append(avatar_rel)
                if updates:
                    params.append(user_session["id"])
                    sql = f"UPDATE auditors SET {', '.join(updates)} WHERE id = ?"
                    cur.execute(sql, params)
                    conn.commit()
                conn.close()
            except Exception as e:
                print(f"⚠️ Could not persist auditor profile to DB: {e}")

            # Update session so user sees changes immediately
            sess = session.setdefault("user", {})
            if name:
                sess["name"] = name
            if email:
                sess["email"] = email
            if phone:
                sess["phone"] = phone
            if avatar_rel:
                sess["avatar"] = avatar_rel
            session.modified = True

            return redirect(url_for('auditor_profile'))

    # Build context from DB (preferred) so values persist across logout/login
    auditor_db = get_auditor(user_session.get('username')) or {}

    user_context = {
        "id": auditor_db.get("id") or user_session.get("id"),
        "username": auditor_db.get("username") or user_session.get("username"),
        "role": auditor_db.get("role") or user_session.get("role", "auditor"),
        "name": auditor_db.get("name") or user_session.get("name") or "",
        "email": auditor_db.get("email") or user_session.get("email") or "",
        "phone": auditor_db.get("phone") or user_session.get("phone") or "",
        "avatar": auditor_db.get("avatar") or user_session.get("avatar") or None,
    }

    # If there was a submitted form (validation failed), prefer submitted values so inputs keep what user typed
    for k, v in form_values.items():
        if v is not None:
            user_context[k] = v

    return render_template('auditor_profile.html', user=user_context, errors=errors)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # use clouds's port if available
    app.run(host="0.0.0.0", port=port, debug=True)