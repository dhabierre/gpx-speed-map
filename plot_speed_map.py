import folium
from folium.plugins import MarkerCluster
import gpxpy
import requests
import time
import numpy as np

# Configuration
GPX_FILE_PATH = 'data/input.gpx'
LIMIT_SPEED = 110  # Speed limit in km/h
MAX_POINTS = 500   # Max number of queried points

# OSM speed code mapping (France-specific)
SPEED_CODE_MAPPING = {
    'FR:urban': 50,
    'FR:rural': 80,
    'FR:trunk': 110,
    'FR:motorway': 130
}

# Load the GPX file
with open(GPX_FILE_PATH, 'r') as f:
    gpx = gpxpy.parse(f)

# Extract GPS points
points = []
for track in gpx.tracks:
    for segment in track.segments:
        for point in segment.points:
            points.append((point.latitude, point.longitude))

print(f"Total GPS points: {len(points)}")

# Sample points evenly
if len(points) <= MAX_POINTS:
    sampled_points = points
else:
    indices = np.linspace(0, len(points) - 1, MAX_POINTS, dtype=int)
    sampled_points = [points[i] for i in indices]

print(f"Sampled {len(sampled_points)} points")

# Overpass API query function
def query_max_speed(lat, lon):
    query = f"""
    [out:json][timeout:25];
    way(around:30,{lat},{lon})["highway"]["maxspeed"];
    out tags;
    """
    response = requests.post('https://overpass-api.de/api/interpreter', data={'data': query})
    if response.status_code == 200:
        data = response.json()
        speeds = [el['tags']['maxspeed'] for el in data['elements'] if 'maxspeed' in el.get('tags', {})]
        return speeds[0] if speeds else None
    return None

# Collect speed limit data
results = []
print("⏳ Querying Overpass API...")
for i, (lat, lon) in enumerate(sampled_points):
    max_speed = query_max_speed(lat, lon)
    speed_val = None

    if max_speed is not None:
        try:
            if max_speed in SPEED_CODE_MAPPING:
                speed_val = SPEED_CODE_MAPPING[max_speed]
            else:
                speed_val = int(max_speed.split()[0])

            if speed_val >= LIMIT_SPEED:
                print(f"\033[91m[{i+1}/{len(sampled_points)}] ({lat:.5f}, {lon:.5f}) → {speed_val} km/h ⚠️\033[0m")
            else:
                print(f"[{i+1}/{len(sampled_points)}] ({lat:.5f}, {lon:.5f}) → {speed_val} km/h")
        except:
            print(f"[{i+1}/{len(sampled_points)}] ({lat:.5f}, {lon:.5f}) → Maxspeed: {max_speed}")
    else:
        print(f"[{i+1}/{len(sampled_points)}] ({lat:.5f}, {lon:.5f}) → Unknown speed")

    results.append({'lat': lat, 'lon': lon, 'maxspeed': max_speed})
    time.sleep(1.2)  # Prevent rate limiting

# Create map
start_lat, start_lon = points[0]
map = folium.Map(location=[start_lat, start_lon], zoom_start=11)
cluster = MarkerCluster() #.add_to(m)

# Add markers with popup
for pt in results:
    speed_raw = pt['maxspeed']
    color = 'gray'
    label = 'Unknown'

    try:
        if speed_raw in SPEED_CODE_MAPPING:
            speed_val = SPEED_CODE_MAPPING[speed_raw]
        else:
            speed_val = int(speed_raw.split()[0])

        label = f"{speed_val} km/h"
        color = 'red' if speed_val >= LIMIT_SPEED else 'blue'
    except:
        label = str(speed_raw)

    folium.Marker(
        location=[pt['lat'], pt['lon']],
        popup=f"Maxspeed: {label}",
        icon=folium.Icon(color=color)
    ).add_to(cluster)

# Create FeatureGroups
fast_group = folium.FeatureGroup(name=f"Speed ≥ {LIMIT_SPEED} km/h", show=True)
slow_group = folium.FeatureGroup(name=f"Speed < {LIMIT_SPEED} km/h", show=True)
unknown_group = folium.FeatureGroup(name='Unknown speed', show=True)

# Helper function
def parse_speed(val):
    try:
        if val in SPEED_CODE_MAPPING:
            return SPEED_CODE_MAPPING[val]
        return int(val.split()[0])
    except:
        return None

# Draw colored polylines
for i in range(len(results) - 1):
    lat1, lon1 = results[i]['lat'], results[i]['lon']
    lat2, lon2 = results[i+1]['lat'], results[i+1]['lon']

    s1 = parse_speed(results[i]['maxspeed'])
    s2 = parse_speed(results[i+1]['maxspeed'])

    seg_speed = max(filter(None, [s1, s2]), default=None)

    color = 'gray'
    label = 'Unknown speed'
    group = unknown_group

    if seg_speed is not None:
        label = f"{seg_speed} km/h"
        if seg_speed >= LIMIT_SPEED:
            color = 'red'
            group = fast_group
        else:
            color = 'blue'
            group = slow_group

    folium.PolyLine(
        [(lat1, lon1), (lat2, lon2)],
        color=color,
        weight=4,
        popup=folium.Popup(f"Maxspeed: {label}", show=False)
    ).add_to(group)

# Add layers to map
fast_group.add_to(map)
slow_group.add_to(map)
unknown_group.add_to(map)

# Add interactive filter control
folium.LayerControl(collapsed=False).add_to(map)

# Legend HTML
legend_html = f'''
<div style="
    position: fixed;
    bottom: 40px;
    left: 40px;
    width: 180px;
    height: 120px;
    background-color: white;
    border:2px solid grey;
    z-index:9999;
    font-size:14px;
    padding: 10px;
    box-shadow: 2px 2px 6px rgba(0,0,0,0.3);
">
    <b>Speed Legend</b><br>
    <span style="color: red;">■</span> ≥ {LIMIT_SPEED} km/h<br>
    <span style="color: blue;">■</span> &lt; {LIMIT_SPEED} km/h<br>
    <span style="color: gray;">■</span> Unknown<br>
</div>
'''
map.get_root().html.add_child(folium.Element(legend_html))

# Save map
map.save('speed_map.html')
print("✅ Map generated: 'speed_map.html' (open it in your browser)")
