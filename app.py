from flask import Flask, render_template, jsonify
import sqlite3
from models.branch_model import create_tables
from services.distance_service import get_distance_matrix
from services.map_service import generate_map
from config import DB_PATH, GOOGLE_MAPS_API_KEY
from services.tsp_solver import optimize_daily_route

MAX_DISTANCE_PER_DAY = 180_000  # 180 km in meters

app = Flask(__name__)


def get_branches():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, name, address, lat, lng, is_hq FROM branches WHERE visited=0 OR is_hq=1")
    branches = cur.fetchall()
    conn.close()
    return branches


def mark_branch_visited(branch_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE branches SET visited=1 WHERE id=?", (branch_id,))
    conn.commit()
    conn.close()


def reset_branches():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE branches SET visited=0 WHERE is_hq=0")
    conn.commit()
    conn.close()


def reset_all_branches():
    """Reset all branches to unvisited before planning"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE branches SET visited=0 WHERE is_hq=0")
    affected = cur.rowcount
    conn.commit()
    conn.close()
    print(f"🔄 Reset {affected} branches to unvisited status")
    return affected


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
                    from services.tsp_solver import optimize_daily_route
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
            
            # Mark visited branches in database
            for branch_idx in day_branches_visited:
                mark_branch_visited(branches[branch_idx][0])
        
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


def validate_route_distances(branches, route, distance_matrix):
    """Validate that a route doesn't exceed distance limits"""
    total_distance = 0
    
    print(f"    Route validation for {len(route)} stops:")
    for i in range(len(route) - 1):
        from_idx = route[i]
        to_idx = route[i + 1]
        leg_distance = distance_matrix[from_idx][to_idx]
        total_distance += leg_distance
        
        from_name = branches[from_idx][1] if from_idx < len(branches) else f"Index{from_idx}"
        to_name = branches[to_idx][1] if to_idx < len(branches) else f"Index{to_idx}"
        
        print(f"      Leg {i+1}: {from_name} → {to_name} = {leg_distance/1000:.1f}km")
    
    print(f"    Total route distance: {total_distance/1000:.1f}km")
    
    if total_distance > MAX_DISTANCE_PER_DAY:
        print(f"    ⚠️ WARNING: Route exceeds {MAX_DISTANCE_PER_DAY/1000}km limit!")
        return False, total_distance
    
    return True, total_distance


def debug_distance_matrix(branches, distance_matrix):
    """Print distance matrix for debugging"""
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
        print("...")


# ------------------ Flask Routes ------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/plan", methods=["POST"])
def api_plan():
    try:
        print("🚀 Starting route planning...")
        
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
            
            day_result = {
                "day": d, 
                "distance_m": total_dist,
                "distance_km": round(total_dist/1000, 2),
                "branches_visited": branch_count_this_day,
                "stops": stops,
                "route_indices": route
            }
            
            result.append(day_result)
            print(f"  Day {d}: {branch_count_this_day} branches, {len(stops)} stops, {total_dist/1000:.1f}km")

        print(f"\n🎉 Planning completed successfully: {len(result)} days")
        return jsonify({"days": result, "success": True})
        
    except Exception as e:
        print(f"\n❌ Error in api_plan: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Planning failed: {str(e)}", "success": False})


@app.route("/map/day/<int:day_id>")
def show_map(day_id):
    # Just serve the generated map.html (same for all days now)
    return render_template("map.html")


if __name__ == "__main__":
    app.run(debug=True)
