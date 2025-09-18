from flask import Flask, render_template, jsonify
import sqlite3
from models.branch_model import create_tables
from services.distance_service import get_distance_matrix
from services.map_service import generate_map
from config import DB_PATH, GOOGLE_MAPS_API_KEY

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


def plan_multi_day(branches, distance_matrix, time_matrix):
    days = []
    hq_index = next(i for i, b in enumerate(branches) if b[5] == 1)
    unvisited = set(i for i, b in enumerate(branches) if b[5] == 0)

    while unvisited:
        day_route = [hq_index]
        total_distance = 0

        while True:
            last = day_route[-1]
            next_branch = None
            min_dist = float("inf")

            for j in unvisited:
                d = distance_matrix[last][j] + distance_matrix[j][hq_index]
                if total_distance + d <= MAX_DISTANCE_PER_DAY and distance_matrix[last][j] < min_dist:
                    min_dist = distance_matrix[last][j]
                    next_branch = j

            if next_branch is None:
                break

            day_route.append(next_branch)
            total_distance += min_dist
            unvisited.remove(next_branch)

        day_route.append(hq_index)
        days.append(day_route)

        for idx in day_route:
            if branches[idx][5] == 0:
                mark_branch_visited(branches[idx][0])

    return days


# ------------------ Flask Routes ------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/plan", methods=["POST"])
def api_plan():
    create_tables()
    branches = get_branches()
    if not branches:
        return jsonify({"error": "No unvisited branches found in database."})

    coords = [(b[3], b[4]) for b in branches]
    distance_matrix, time_matrix = get_distance_matrix(coords)
    days = plan_multi_day(branches, distance_matrix, time_matrix)

    # Generate map for each day
    generate_map(branches, days, GOOGLE_MAPS_API_KEY)

    # Build JSON response
    result = []
    for d, route in enumerate(days, 1):
        total_dist = 0
        stops = []
        for k in range(len(route) - 1):
            i, j = route[k], route[k + 1]
            total_dist += distance_matrix[i][j]
            stops.append({"name": branches[i][1], "address": branches[i][2]})
        stops.append({"name": branches[route[-1]][1], "address": branches[route[-1]][2]})
        result.append({"day": d, "distance_m": total_dist, "stops": stops})

    reset_branches()
    return jsonify({"days": result})


@app.route("/map/day/<int:day_id>")
def show_map(day_id):
    # Just serve the generated map.html (same for all days now)
    return render_template("map.html")


if __name__ == "__main__":
    app.run(debug=True)
