# services/tsp_solver.py
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

MAX_DISTANCE_PER_DAY = 180_000  # 180 km in meters


def solve_tsp(distance_matrix, max_distance_per_day=None):
    """
    Solve TSP with optional distance constraint for single day
    If max_distance_per_day is provided, ensures route doesn't exceed limit
    """
    if not distance_matrix or len(distance_matrix) < 2:
        return []
    
    # Create the routing index manager
    manager = pywrapcp.RoutingIndexManager(len(distance_matrix), 1, 0)
    
    # Create Routing Model
    routing = pywrapcp.RoutingModel(manager)
    
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return distance_matrix[from_node][to_node]
    
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    
    # Add distance constraint if specified
    if max_distance_per_day:
        dimension_name = 'Distance'
        routing.AddDimension(
            transit_callback_index,
            0,  # no slack
            max_distance_per_day,  # maximum distance
            True,  # start cumul to zero
            dimension_name
        )
        distance_dimension = routing.GetDimensionOrDie(dimension_name)
        distance_dimension.SetGlobalSpanCostCoefficient(100)
    
    # Setting first solution heuristic
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    
    # Solve the problem
    solution = routing.SolveWithParameters(search_parameters)
    
    if solution:
        route = []
        index = routing.Start(0)
        
        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        
        # Add the end node (return to start)
        route.append(manager.IndexToNode(index))
        
        return route
    
    return []


def solve_tsp_for_subset(distance_matrix, branch_indices, depot_index=0):
    """
    Solve TSP for a subset of branches (used for optimizing individual days)
    Used by multi-day planning algorithm in app.py
    """
    if not branch_indices:
        return [depot_index]
    
    # Create subset distance matrix
    all_indices = [depot_index] + list(branch_indices)
    subset_matrix = []
    
    for i in all_indices:
        row = []
        for j in all_indices:
            row.append(distance_matrix[i][j])
        subset_matrix.append(row)
    
    # Solve TSP for subset
    subset_route = solve_tsp(subset_matrix)
    
    if not subset_route:
        return [depot_index]
    
    # Convert back to original indices
    original_route = [all_indices[i] for i in subset_route if i < len(all_indices)]
    
    return original_route


def optimize_daily_route(distance_matrix, branch_indices, hq_index=0, max_distance=None):
    """
    Optimize the order of branches for a single day using TSP
    Returns optimized route that starts and ends at HQ
    """
    if not branch_indices:
        return [hq_index]
    
    # Use TSP to find optimal order
    optimized_route = solve_tsp_for_subset(distance_matrix, branch_indices, hq_index)
    
    # Validate distance constraint if provided
    if max_distance and optimized_route:
        total_distance = 0
        for i in range(len(optimized_route) - 1):
            total_distance += distance_matrix[optimized_route[i]][optimized_route[i + 1]]
        
        if total_distance > max_distance:
            print(f"⚠️ TSP route ({total_distance/1000:.1f}km) exceeds limit ({max_distance/1000:.1f}km)")
            # Return simple route if TSP violates constraint
            return [hq_index] + list(branch_indices) + [hq_index]
    
    return optimized_route


def plan_multi_day(distance_matrix):
    """
    Plans routes across multiple days, ensuring each day ≤ 180 km.
    Returns: list of (route, total_distance).
    """
    unvisited = set(range(1, len(distance_matrix)))  # all branches except HQ
    all_routes = []

    while unvisited:
        # Solve for today's route
        route = solve_tsp_for_subset(distance_matrix, unvisited, depot_index=0)

        if not route or len(route) <= 1:
            break

        # Calculate total distance for the route
        total_distance = sum(
            distance_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1)
        )

        all_routes.append((route, total_distance))

        # Mark visited (exclude HQ)
        for node in route:
            if node != 0:
                unvisited.discard(node)

    return all_routes
