import os
import requests
import json
from config import GOOGLE_MAPS_API_KEY
from datetime import datetime, timezone, timedelta

def get_distance_matrix(coords):
    """
    Build a distance matrix using Google Distance Matrix API (fallback for Routes API)
    Returns:
        distance_matrix (list[list[int]]) - distances in meters
        time_matrix (list[list[int]]) - travel times in seconds
    """
    print("Using Google Distance Matrix API (standard API key compatible)...")
    
    n = len(coords)
    distance_matrix = [[0] * n for _ in range(n)]
    time_matrix = [[0] * n for _ in range(n)]
    
    # Process in chunks if needed (API limit)
    max_elements = 100  # Distance Matrix API allows up to 100 elements per request
    chunk_size = int(max_elements ** 0.5)  # Square root for matrix
    
    for i_start in range(0, n, chunk_size):
        i_end = min(i_start + chunk_size, n)
        for j_start in range(0, n, chunk_size):
            j_end = min(j_start + chunk_size, n)
            
            # Create origins and destinations for this chunk
            origins = coords[i_start:i_end]
            destinations = coords[j_start:j_end]
            
            # Build request URL
            origin_str = "|".join([f"{lat},{lng}" for lat, lng in origins])
            dest_str = "|".join([f"{lat},{lng}" for lat, lng in destinations])
            
            url = f"https://maps.googleapis.com/maps/api/distancematrix/json"
            params = {
                "origins": origin_str,
                "destinations": dest_str,
                "mode": "driving",
                "units": "metric",
                "departure_time": "now",
                "traffic_model": "best_guess",
                "key": GOOGLE_MAPS_API_KEY
            }
            
            try:
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code != 200:
                    print(f"⚠️ API Error: {response.status_code}")
                    # Fill with default values
                    for i in range(len(origins)):
                        for j in range(len(destinations)):
                            if i_start + i == j_start + j:
                                distance_matrix[i_start + i][j_start + j] = 0
                                time_matrix[i_start + i][j_start + j] = 0
                            else:
                                distance_matrix[i_start + i][j_start + j] = 50000  # 50km default
                                time_matrix[i_start + i][j_start + j] = 3600      # 1 hour default
                    continue
                
                data = response.json()
                
                if data.get("status") != "OK":
                    print(f"⚠️ API Status: {data.get('status')}")
                    continue
                
                # Process results
                for i, row in enumerate(data["rows"]):
                    for j, element in enumerate(row["elements"]):
                        matrix_i = i_start + i
                        matrix_j = j_start + j
                        
                        if element["status"] == "OK":
                            distance = element["distance"]["value"]  # meters
                            duration = element["duration"]["value"]  # seconds
                            
                            # Use traffic duration if available
                            if "duration_in_traffic" in element:
                                duration = element["duration_in_traffic"]["value"]
                            
                            distance_matrix[matrix_i][matrix_j] = distance
                            time_matrix[matrix_i][matrix_j] = duration
                            
                            print(f"Route {matrix_i}->{matrix_j}: {distance/1000:.2f} km, {duration//60} min")
                        else:
                            # Default values for failed routes
                            if matrix_i == matrix_j:
                                distance_matrix[matrix_i][matrix_j] = 0
                                time_matrix[matrix_i][matrix_j] = 0
                            else:
                                distance_matrix[matrix_i][matrix_j] = 50000  # 50km default
                                time_matrix[matrix_i][matrix_j] = 3600      # 1 hour default
                                print(f"⚠️ Route {matrix_i}->{matrix_j} failed: {element['status']}")
                
            except requests.exceptions.RequestException as e:
                print(f"⚠️ Request failed: {e}")
                # Fill with default values
                for i in range(len(origins)):
                    for j in range(len(destinations)):
                        if i_start + i == j_start + j:
                            distance_matrix[i_start + i][j_start + j] = 0
                            time_matrix[i_start + i][j_start + j] = 0
                        else:
                            distance_matrix[i_start + i][j_start + j] = 50000  # 50km default
                            time_matrix[i_start + i][j_start + j] = 3600      # 1 hour default

    return distance_matrix, time_matrix


def get_route_details(origin_coords, dest_coords):
    """
    Get route details using Google Directions API (compatible with standard API keys)
    origin_coords, dest_coords: (lat, lng) tuples
    Returns: dict with keys:
      - distance_meters (int)
      - duration_seconds (int)
      - encoded_polyline (str)  # may be empty if none
      - legs (list)             # raw legs if needed
    """
    url = "https://maps.googleapis.com/maps/api/directions/json"
    
    params = {
        "origin": f"{origin_coords[0]},{origin_coords[1]}",
        "destination": f"{dest_coords[0]},{dest_coords[1]}",
        "mode": "driving",
        "departure_time": "now",
        "traffic_model": "best_guess",
        "key": GOOGLE_MAPS_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"⚠️ Directions API Error: {response.status_code}")
            return {"distance_meters": None, "duration_seconds": None, "encoded_polyline": None, "legs": []}
        
        data = response.json()
        
        if data.get("status") != "OK" or not data.get("routes"):
            print(f"⚠️ Directions API Status: {data.get('status')}")
            return {"distance_meters": None, "duration_seconds": None, "encoded_polyline": None, "legs": []}
        
        route = data["routes"][0]
        
        # Extract distance and duration
        distance = None
        duration = None
        
        if "legs" in route and route["legs"]:
            leg = route["legs"][0]
            distance = leg.get("distance", {}).get("value")  # meters
            
            # Use traffic duration if available, otherwise regular duration
            if "duration_in_traffic" in leg:
                duration = leg["duration_in_traffic"]["value"]  # seconds
            elif "duration" in leg:
                duration = leg["duration"]["value"]  # seconds
        
        # Extract polyline
        polyline = None
        if "overview_polyline" in route:
            polyline = route["overview_polyline"].get("points")
        
        return {
            "distance_meters": distance,
            "duration_seconds": duration,
            "encoded_polyline": polyline,
            "legs": route.get("legs", [])
        }
        
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Directions API request failed: {e}")
        return {"distance_meters": None, "duration_seconds": None, "encoded_polyline": None, "legs": []}