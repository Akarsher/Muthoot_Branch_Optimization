import folium
from services.distance_service import get_route_details

def generate_map(branches, days, api_key):
    """
    Generate map with multi-day routes in different colors
    """
    if not branches:
        return
    
    # Find center point (HQ or average of all branches)
    hq_branch = next(b for b in branches if b[5] == 1)
    center_lat, center_lng = hq_branch[3], hq_branch[4]
    
    # Create map
    m = folium.Map(location=[center_lat, center_lng], zoom_start=11)
    
    # Color scheme for different days
    day_colors = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 'beige', 'darkblue', 'darkgreen']
    
    # Add routes for each day
    for day_idx, route in enumerate(days):
        day_color = day_colors[day_idx % len(day_colors)]
        
        print(f"Generating Day {day_idx + 1} route with color {day_color}")
        
        # Add route polylines
        for i in range(len(route) - 1):
            from_idx = route[i]
            to_idx = route[i + 1]
            
            from_coords = (branches[from_idx][3], branches[from_idx][4])
            to_coords = (branches[to_idx][3], branches[to_idx][4])
            
            try:
                # Get route details with polyline
                route_details = get_route_details(from_coords, to_coords)
                
                if route_details and route_details["encoded_polyline"]:
                    # Decode polyline and add to map
                    decoded_coords = decode_polyline(route_details["encoded_polyline"])
                    folium.PolyLine(
                        decoded_coords,
                        color=day_color,
                        weight=4,
                        opacity=0.7,
                        popup=f"Day {day_idx + 1}: {branches[from_idx][1]} → {branches[to_idx][1]}"
                    ).add_to(m)
                else:
                    # Fallback: straight line
                    folium.PolyLine(
                        [from_coords, to_coords],
                        color=day_color,
                        weight=2,
                        opacity=0.5,
                        dash_array="5,5"
                    ).add_to(m)
                    
            except Exception as e:
                print(f"Error getting route details: {e}")
                # Fallback: straight line
                folium.PolyLine(
                    [from_coords, to_coords],
                    color=day_color,
                    weight=2,
                    opacity=0.5,
                    dash_array="5,5"
                ).add_to(m)
    
    # Add markers for all branches
    for i, branch in enumerate(branches):
        lat, lng = branch[3], branch[4]
        name = branch[1]
        is_hq = branch[5] == 1
        
        # Determine which day this branch is visited
        day_visited = None
        for day_idx, route in enumerate(days):
            if i in route and not is_hq:  # HQ appears in all routes
                day_visited = day_idx + 1
                break
        
        # Marker styling
        if is_hq:
            icon_color = 'blue'
            marker_color = 'blue'
            popup_text = f"HQ - {name}"
        else:
            marker_color = 'green'
            icon_color = 'white'
            popup_text = f"Day {day_visited} - {name}" if day_visited else name
        
        folium.Marker(
            [lat, lng],
            popup=popup_text,
            icon=folium.Icon(color=marker_color, icon='info-sign')
        ).add_to(m)
    
    # Add legend
    legend_html = '''
    <div style="position: fixed; 
                bottom: 50px; left: 50px; width: 200px; height: auto; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding: 10px">
    <h4>Route Legend</h4>
    '''
    
    for day_idx in range(len(days)):
        color = day_colors[day_idx % len(day_colors)]
        legend_html += f'<p><span style="color:{color};">■</span> Day {day_idx + 1}</p>'
    
    legend_html += '</div>'
    m.get_root().html.add_child(folium.Element(legend_html))
    
    # Save map
    m.save('templates/map.html')
    print(f"Map saved with {len(days)} days of routes")

def decode_polyline(polyline_str):
    """Decode Google polyline to lat/lng coordinates"""
    # Implementation of polyline decoding algorithm
    # You may need to install polyline package: pip install polyline
    try:
        import polyline
        return polyline.decode(polyline_str)
    except ImportError:
        print("Warning: polyline package not installed. Using straight lines.")
        return []
