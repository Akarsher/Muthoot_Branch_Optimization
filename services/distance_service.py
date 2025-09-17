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
