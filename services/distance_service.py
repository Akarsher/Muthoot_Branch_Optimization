import os
import requests
import json
from config import GOOGLE_MAPS_API_KEY
from datetime import datetime, timezone, timedelta

def get_distance_matrix(coords):
    """
    Build a distance matrix using Google Routes API with traffic-aware travel times.
    Returns:
        distance_matrix (list[list[int]]) - distances in meters
        time_matrix (list[list[int]]) - travel times in seconds
    """
    url = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

    origins = [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lng}}}} for lat, lng in coords]
    destinations = [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lng}}}} for lat, lng in coords]

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "originIndex,destinationIndex,distanceMeters,duration"
    }

    # Must be a future time in UTC
    departure_time = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")

    body = {
        "origins": origins,
        "destinations": destinations,
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": departure_time
    }

    print("Fetching distance & traffic-aware travel times from Google Routes API...")

    response = requests.post(url, headers=headers, data=json.dumps(body))

    if response.status_code != 200:
        raise Exception(f"Google Routes API Error: {response.text}")

    results = response.json()

    n = len(coords)
    distance_matrix = [[0] * n for _ in range(n)]
    time_matrix = [[0] * n for _ in range(n)]

    for row in results:
        i = row["originIndex"]
        j = row["destinationIndex"]

        distance = row.get("distanceMeters", 0)
        duration = row.get("duration", "0s")

        # Convert "123s" → 123 (int seconds)
        seconds = int(duration[:-1]) if duration.endswith("s") else 0

        distance_matrix[i][j] = distance
        time_matrix[i][j] = seconds

        # Debug log
        print(f"Route {i}->{j}: {distance/1000:.2f} km, {seconds//60} min")

    return distance_matrix, time_matrix

def get_route_details(origin_coords, dest_coords):
    """
    origin_coords, dest_coords: (lat, lng) tuples
    Returns: dict with keys:
      - distance_meters (int)
      - duration_seconds (int)
      - encoded_polyline (str)  # may be empty if none
      - legs (list)             # raw legs if needed
    """
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    # departure time slightly in future to allow "traffic-aware"
    departure_time = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")

    payload = {
        "origin": {"location": {"latLng": {"latitude": origin_coords[0], "longitude": origin_coords[1]}}},
        "destination": {"location": {"latLng": {"latitude": dest_coords[0], "longitude": dest_coords[1]}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": departure_time
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline,routes.legs"
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    if resp.status_code != 200:
        # return None or raise depending on your preference
        # Return a small dict with penalties so map rendering can continue
        return {"distance_meters": None, "duration_seconds": None, "encoded_polyline": None, "legs": []}

    data = resp.json()
    if "routes" not in data or len(data["routes"]) == 0:
        return {"distance_meters": None, "duration_seconds": None, "encoded_polyline": None, "legs": []}

    route = data["routes"][0]
    distance = route.get("distanceMeters", None)
    duration = None
    # duration may be available as seconds or formatted; check fields
    if "duration" in route:
        # route["duration"] might be e.g., "1234s" or number — handle both
        dval = route["duration"]
        if isinstance(dval, str) and dval.endswith("s"):
            try:
                duration = int(dval[:-1])
            except:
                duration = None
        elif isinstance(dval, (int, float)):
            duration = int(dval)
    elif "legs" in route and len(route["legs"])>0 and "duration" in route["legs"][0]:
        # fallback: sum legs
        duration = sum(int(leg.get("duration", 0)) for leg in route["legs"])

    poly = route.get("polyline", {}).get("encodedPolyline") or route.get("polyline", {}).get("points") or None

    return {
        "distance_meters": distance,
        "duration_seconds": duration,
        "encoded_polyline": poly,
        "legs": route.get("legs", [])
    }