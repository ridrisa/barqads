import csv
import json
from shapely.geometry import Point, Polygon
from shapely.wkt import loads as wkt_loads
import pandas as pd

# Load the CSV files
polygon_df = pd.read_csv('polygon_boundary1.csv')
coordinates_df = pd.read_csv('coordinates.csv')

# Initialize polygons list
polygons = []

# Step 1: Parse the polygon boundaries with validation
for index, row in polygon_df.iterrows():
    polygon_wkt = row['WKT'].strip()
    try:
        polygon = wkt_loads(polygon_wkt)
        if not polygon.is_valid:
            print(f"Invalid polygon on row {index}: Attempting to fix")
            polygon = polygon.buffer(0)  # Attempt to fix the polygon
        
        polygons.append({
            "polygon": polygon,
            "name": row['name'],
            "description": row['description'] if not pd.isna(row['description']) else "",
            "points_count": 0  # Initialize points count
        })
    except Exception as e:
        print(f"Error parsing WKT on row {index}: {e}")

# Function to determine if a coordinate is valid
def is_valid_coordinate(lat, lng):
    try:
        lat = float(lat)
        lng = float(lng)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):  # Latitude [-90, 90], Longitude [-180, 180]
            return False
        return lat != 0.0 and lng != 0.0  # Exclude zero coordinates
    except (ValueError, TypeError):
        return False

# Step 2: Parse the coordinates and count them per polygon
for index, row in coordinates_df.iterrows():
    try:
        coordinates = json.loads(row['destination'])
        lat = coordinates.get('latitude', '')
        lng = coordinates.get('longitude', '')

        if not is_valid_coordinate(lat, lng):
            print(f"Skipping invalid coordinate on row {index}: {row['destination']}")
            continue

        point = Point(float(lng), float(lat))

        # Count points within each polygon
        matched = False
        for polygon in polygons:
            try:
                if polygon['polygon'].contains(point):
                    polygon['points_count'] += 1
                    matched = True
                    break  # Each point belongs to one polygon
            except Exception as e:  # Catch any geometry-related issues
                print(f"Error with polygon {polygon['name']} and point {point}: {e}")

        if not matched:
            print(f"Point {point} did not match any polygon.")
    
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        print(f"Error processing coordinates on row {index}: {row['destination']} - {e}")

# Step 3: Find the minimum and maximum point counts
min_count = min(polygon['points_count'] for polygon in polygons)
max_count = max(polygon['points_count'] for polygon in polygons)

# Step 4: Dynamic color intensity based on min and max counts
def get_dynamic_color(points_count, min_count, max_count):
    if max_count == min_count:
        return '#f8d5cc'  # Default color if all counts are the same
    intensity = (points_count - min_count) / (max_count - min_count)
    
    # Map the intensity to a color range
    color_scale = [
        (0.2, '#f8d5cc'),
        (0.4, '#f4bfb6'),
        (0.6, '#f1a8a5'),
        (0.8, '#ee8f9a'),
        (1.0, '#ec739b')
    ]
    
    for threshold, color in color_scale:
        if intensity <= threshold:
            return color
    return '#ec739b'  # Fallback color

# Convert polygons with intensity to GeoJSON features
features = []
for polygon in polygons:
    color = get_dynamic_color(polygon['points_count'], min_count, max_count)
    features.append({
        "type": "Feature",
        "geometry": polygon['polygon'].__geo_interface__,
        "properties": {
            "name": polygon['name'],
            "description": polygon['description'],
            "points_count": polygon['points_count'],
            "color": color
        }
    })

# Step 5: Create a GeoJSON feature collection
geojson_data = {
    "type": "FeatureCollection",
    "features": features
}

# Step 6: Save the GeoJSON data to a file
output_file = 'polygons_with_intensity.geojson'
with open(output_file, 'w') as geojson_file:
    json.dump(geojson_data, geojson_file, indent=4)

print(f"GeoJSON file '{output_file}' has been saved successfully.")
