# services/tsp_solver.py
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

MAX_DISTANCE_PER_DAY = 180_000  # 180 km in meters


def solve_tsp(distance_matrix):
    """
    Solves TSP for a single day with distance limit.
    HQ (index 0) is always the start and end.
    Returns (route, total_distance).
    """
    num_nodes = len(distance_matrix)
    if num_nodes <= 1:
        return [0], 0  # only HQ present

    # Create routing index manager
    manager = pywrapcp.RoutingIndexManager(num_nodes, 1, 0)  # HQ = 0
    routing = pywrapcp.RoutingModel(manager)

    # Cost callback = distance
    def distance_callback(from_index, to_index):
        f, t = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        return distance_matrix[f][t]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Add distance dimension to enforce daily max
    routing.AddDimension(
        transit_callback_index,
        0,  # no slack
        MAX_DISTANCE_PER_DAY,  # max travel per route
        True,  # start cumul at zero
        "Distance"
    )

    # Solver parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    # Solve
    solution = routing.SolveWithParameters(search_parameters)
    if not solution:
        return [], 0

    # Extract route
    index = routing.Start(0)
    route, total_distance = [], 0
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        route.append(node)
        previous_index = index
        index = solution.Value(routing.NextVar(index))
        total_distance += routing.GetArcCostForVehicle(previous_index, index, 0)
    route.append(manager.IndexToNode(index))  # return to HQ

    return route, total_distance


def plan_multi_day(distance_matrix):
    """
    Plans routes across multiple days, ensuring each day ≤ 180 km.
    Returns: list of (route, total_distance).
    """
    unvisited = set(range(1, len(distance_matrix)))  # all branches except HQ
    all_routes = []

    while unvisited:
        # Build submatrix: HQ + unvisited branches
        sub_nodes = [0] + list(unvisited)
        sub_matrix = [[distance_matrix[i][j] for j in sub_nodes] for i in sub_nodes]

        # Solve for today's route
        route, dist = solve_tsp(sub_matrix)

        if not route or dist == 0:
            break

        # Map back to original node indexes
        mapped_route = [sub_nodes[i] for i in route]
        all_routes.append((mapped_route, dist))

        # Mark visited (exclude HQ)
        for node in mapped_route:
            if node != 0:
                unvisited.discard(node)

    return all_routes
