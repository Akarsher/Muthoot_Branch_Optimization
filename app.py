import sqlite3
from models.branch_model import create_tables
from services.distance_service import get_distance_matrix
from config import DB_PATH

MAX_DISTANCE_PER_DAY = 180_000  # 180 km in meters


def get_branches():
    """
    Fetch all unvisited branches including HQ.
    Returns: list of tuples (id, name, address, lat, lng, is_hq)
    """
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
    """
    Greedy daily TSP planner.
    Each day starts & ends at HQ, and daily distance is capped at MAX_DISTANCE_PER_DAY.
    """
    days = []
    hq_index = next(i for i, b in enumerate(branches) if b[5] == 1)  # HQ index
    unvisited = set(i for i, b in enumerate(branches) if b[5] == 0)

    while unvisited:
        day_route = [hq_index]
        total_distance = 0

        while True:
            last = day_route[-1]
            next_branch = None
            min_dist = float("inf")

            for j in unvisited:
                d = distance_matrix[last][j] + distance_matrix[j][hq_index]  # trip including return
                if total_distance + d <= MAX_DISTANCE_PER_DAY and distance_matrix[last][j] < min_dist:
                    min_dist = distance_matrix[last][j]
                    next_branch = j

            if next_branch is None:
                break  # can't add more without exceeding limit

            day_route.append(next_branch)
            total_distance += min_dist
            unvisited.remove(next_branch)

        day_route.append(hq_index)  # return to HQ
        days.append(day_route)

        # mark visited branches
        for idx in day_route:
            if branches[idx][5] == 0:  # skip HQ
                mark_branch_visited(branches[idx][0])

    return days


if __name__ == "__main__":
    # Step 1: Ensure DB tables exist
    create_tables()

    # Step 2: Load branches
    branches = get_branches()
    if not branches:
        print("No unvisited branches found in database.")
        exit(0)

    # Step 3: Extract coordinates
    coords = [(b[3], b[4]) for b in branches]  # (lat, lng)

    # Step 4: Get distance & time matrices
    distance_matrix, time_matrix = get_distance_matrix(coords)

    # Step 5: Plan multi-day routes
    days = plan_multi_day(branches, distance_matrix, time_matrix)

    # Step 6: Print results (NO full distance matrix dump)
    for d, route in enumerate(days, 1):
        print(f"\nDay {d} Route:")
        total_dist = 0
        total_time = 0

        for k in range(len(route) - 1):
            i, j = route[k], route[k + 1]
            b = branches[i]
            print(f"  {b[1]} ({b[2]}) -> ", end="")
            total_dist += distance_matrix[i][j]
            total_time += time_matrix[i][j]

        last = branches[route[-1]]
        print(f"{last[1]} ({last[2]})")

        print(f"  Total Distance: {total_dist/1000:.2f} km")
        print(f"  Total Time (with traffic): {total_time//60} min")

    # Step 7: Reset after all routes
    reset_branches()
