"""
Analyzes GPX files to extract maximum speed limits along a route using OpenStreetMap data via the Overpass API, and visualizes the results on an interactive map
"""

from datetime import datetime
import time
import argparse
import folium
from folium.plugins import MarkerCluster
import gpxpy
import overpy
import requests
import numpy as np

# OSM speed code mapping (France-specific)
SPEED_CODE_MAPPING = {
    'FR:urban': 50,
    'FR:rural': 80,
    'FR:trunk': 110,
    'FR:motorway': 130
}

def parse_arguments():
    """ Parse command line arguments """
    parser = argparse.ArgumentParser(
        description="Analyze a GPX file and generate an interactive map showing speed limits."
    )
    parser.add_argument('--file', '-f', required=True, help="Path to the GPX file")
    parser.add_argument('--limit-speed', '-l', type=int, default=110, help="Speed threshold in km/h (default: 110)")
    parser.add_argument('--max-points', '-m', type=int, default=400, help="Maximum number of GPS points to query (default: 400)")
    return parser.parse_args()

def load_gpx_points(filepath):
    """ Load GPS points from a GPX file """
    with open(filepath, 'r', encoding='utf-8') as f:
        gpx = gpxpy.parse(f)
    points = [(pt.latitude, pt.longitude)
              for track in gpx.tracks
              for segment in track.segments
              for pt in segment.points]
    return points

def get_sample_points(points, max_points):
    """ Evenly sample GPS points if there are too many """
    if len(points) <= max_points:
        return points
    indices = np.linspace(0, len(points) - 1, max_points, dtype=int)
    return [points[i] for i in indices]

def query_max_speed(latitude, longitude):
    """ Query Overpass API to get the max speed limit at a location """
    query = f"""
    [out:json][timeout:60];
    way(around:30,{latitude},{longitude})['highway']['maxspeed'];
    out tags;
    """
    try:
        response = requests.post(
            'https://overpass-api.de/api/interpreter',
            data={'data': query},
            timeout=60
        )
        if response.status_code == 200:
            data = response.json()
            speeds = [el['tags']['maxspeed'] for el in data['elements'] if 'maxspeed' in el.get('tags', {})]
            return speeds[0] if speeds else None
    except Exception as e:
        print(f"API Error: {e}")
    return None

def parse_speed(val):
    """ Parse speed value from Overpass response into integer km/h """
    try:
        if val in SPEED_CODE_MAPPING:
            return SPEED_CODE_MAPPING[val]
        return int(val.split()[0])
    except Exception as _:
        return None

def collect_speed_data(points, limit_speed):
    """ Collect max speed data for each point """
    results = []
    print('⏳ Querying Overpass API...')
    for i, (lat, lon) in enumerate(points):
        max_speed = query_max_speed(lat, lon)
        if max_speed is not None:
            speed_val = parse_speed(max_speed)
            if speed_val is not None and speed_val >= limit_speed:
                print(f"\033[91m[{i+1}/{len(points)}] ({lat:.5f}, {lon:.5f}) → {speed_val} km/h ⚠️\033[0m")
            else:
                print(f"[{i+1}/{len(points)}] ({lat:.5f}, {lon:.5f}) → {speed_val} km/h")
        else:
            print(f"[{i+1}/{len(points)}] ({lat:.5f}, {lon:.5f}) → Unknown speed")

        results.append({'lat': lat, 'lon': lon, 'maxspeed': max_speed})
        time.sleep(1.2)  # avoid Overpass rate limiting
    return results

def get_bounding_box(points):
    """ Calculate bounding box from GPS points """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return min(lats), min(lons), max(lats), max(lons)

def get_fuel_stations(bbox):
    """ Query Overpass API for fuel stations within a bounding box """
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:60];
    (
      node['amenity'='fuel']['fuel:octane_98']( {south}, {west}, {north}, {east} );
      node['amenity'='fuel']['fuel:octane_95']( {south}, {west}, {north}, {east} );
    );
    out center;
    """
    api = overpy.Overpass()
    result = api.query(query)
    stations = []
    for node in result.nodes:
        has_sp95 = node.tags.get('fuel:octane_95') == 'yes'
        has_sp98 = node.tags.get('fuel:octane_98') == 'yes'
        stations.append({
            'lat': float(node.lat),
            'lon': float(node.lon),
            'sp95': has_sp95,
            'sp98': has_sp98,
            'name': node.tags.get('name', 'Station-service')
        })
    return stations

def add_fuel_stations_to_map(speed_map, stations):
    """ Add fuel stations to the map with markers """
    for station in stations:
        popup = f"{station['name']}<br>"
        popup += "✅ SP98<br>" if station["sp98"] else "❌ SP98<br>"
        popup += "✅ SP95" if station["sp95"] else "❌ SP95"
        color = "green" if station["sp95"] and station["sp98"] else "orange"
        folium.Marker(
            location=[station['lat'], station['lon']],
            popup=popup,
            icon=folium.Icon(color=color, icon='tint', prefix='fa')
        ).add_to(speed_map)

def build_speed_map(points, results, limit_speed):
    """ Build an interactive map with speed info """
    start_lat, start_lon = points[0]
    speed_map = folium.Map(location=[start_lat, start_lon], zoom_start=11)

    bounding_box = get_bounding_box(points)
    stations = get_fuel_stations(bounding_box)
    add_fuel_stations_to_map(speed_map, stations)

    cluster = MarkerCluster()

    # Layer groups
    fast_group = folium.FeatureGroup(name=f"Speed ≥ {limit_speed} km/h", show=True)
    slow_group = folium.FeatureGroup(name=f"Speed < {limit_speed} km/h", show=True)
    unknown_group = folium.FeatureGroup(name='Unknown speed', show=True)

    # Add markers
    for pt in results:
        speed_raw = pt['maxspeed']
        color = 'gray'
        label = 'Unknown'
        try:
            speed_val = parse_speed(speed_raw)
            if speed_val is not None:
                label = f"{speed_val} km/h"
                color = 'red' if speed_val >= limit_speed else 'blue'
        except Exception as _:
            label = str(speed_raw)
        folium.Marker(
            location=[pt['lat'], pt['lon']],
            popup=f"Maxspeed: {label}",
            icon=folium.Icon(color=color)
        ).add_to(cluster)

    # Draw lines
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
            if seg_speed >= limit_speed:
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

    # Add everything to map
    #cluster.add_to(speed_map)
    fast_group.add_to(speed_map)
    slow_group.add_to(speed_map)
    unknown_group.add_to(speed_map)
    folium.LayerControl(collapsed=False).add_to(speed_map)

    # Legend
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
        <span style="color: red;">■</span> ≥ {limit_speed} km/h<br>
        <span style="color: blue;">■</span> &lt; {limit_speed} km/h<br>
        <span style="color: gray;">■</span> Unknown<br>
    </div>
    '''
    speed_map.get_root().html.add_child(folium.Element(legend_html))
    return speed_map

def main():
    """ Main function to load GPX, sample points, collect speed data, and generate map """
    args = parse_arguments()
    gpx_file_path = args.file
    limit_speed = args.limit_speed
    max_points = args.max_points
    points = load_gpx_points(gpx_file_path)
    print(f"Total GPS points: {len(points)}")
    sampled_points = get_sample_points(points, max_points)
    print(f"Sampled {len(sampled_points)} points")
    results = collect_speed_data(sampled_points, limit_speed)
    speed_map = build_speed_map(sampled_points, results, limit_speed)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"speed_map_{timestamp}.html"
    speed_map.save(filename)
    print(f"✅ Map generated: '{filename}' (open it in your browser)")


if __name__ == "__main__":
    main()
