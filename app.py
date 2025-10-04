from flask import Flask, render_template, jsonify, request
import sqlite3
import os
from models.branch_model import create_tables
from services.distance_service import get_distance_matrix
from services.map_service import generate_map
from config import DB_PATH, GOOGLE_MAPS_API_KEY
from services.tsp_solver import optimize_daily_route

MAX_DISTANCE_PER_DAY = 180_000  # 180 km in meters

app = Flask(__name__)


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
        remaining = [i for i, b in enumerate(branches) if b[5] == 0 and i in unvisited]
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
    return render_template("index.html")


@app.route("/api/plan", methods=["POST"])
def api_plan_single_day():
    """Plan a single day route"""
    try:
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
        reset_all_branches()
        return jsonify({"success": True, "message": "All branches reset to unvisited"})
    except Exception as e:
        return jsonify({"error": f"Reset failed: {str(e)}", "success": False})


@app.route("/api/status", methods=["GET"])
def api_status():
    """Get current status of branches"""
    try:
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


@app.route("/map/day/<int:day_id>")
def show_map(day_id):
    # Just serve the generated map.html (same for all days now)
    return render_template("map.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # use clouds's port if available
    app.run(host="0.0.0.0", port=port, debug=True)