import folium
import os
import requests
import polyline 

def get_route_path(origin, destination, api_key):
    """
    Get the actual road path between two points using Google Directions API.
    Returns a list of [lat, lng] points.
    """
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "mode": "driving",
        "key": api_key
    }
    resp = requests.get(url, params=params).json()
    if resp["status"] != "OK":
        return [origin, destination]  # fallback straight line

    points = polyline.decode(resp["routes"][0]["overview_polyline"]["points"])
    return points

def generate_map(branches, days, api_key, output_file="templates/map.html"):
    """
    Generate an interactive Folium map with routes for each day.
    """
    # Use HQ as map center
    hq = next(b for b in branches if b[5] == 1)
    m = folium.Map(location=[hq[3], hq[4]], zoom_start=11)

    colors = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue"]

    for day_index, route in enumerate(days, 1):
        color = colors[(day_index - 1) % len(colors)]
        for k in range(len(route) - 1):
            origin = (branches[route[k]][3], branches[route[k]][4])
            destination = (branches[route[k+1]][3], branches[route[k+1]][4])
            road_coords = get_route_path(origin, destination, api_key)
            folium.PolyLine(road_coords, color=color, weight=4, opacity=0.7).add_to(m)

        # Add markers
        for idx, stop in enumerate(route):
            b = branches[stop]
            popup = f"Day {day_index} - {b[1]}"
            folium.Marker(
                location=[b[3], b[4]],
                popup=popup,
                icon=folium.Icon(color="blue" if b[5] == 1 else "green", icon="info-sign")
            ).add_to(m)

    # Save map to file
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    m.save(output_file)
    print(f"\n✅ Map saved to {output_file}")
