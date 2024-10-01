import pandas as pd
import json
import geopandas as gpd
from shapely.wkt import loads as wkt_loads
from matplotlib import colormaps, colors
import warnings
import numpy as np

# -----------------------
# Configuration
# -----------------------

# File paths
POLYGON_CSV = 'polygon_boundary1.csv'
COORDINATES_CSV = 'coordinates.csv'
OUTPUT_GEOJSON = 'polygons_with_intensity.geojson'

# -----------------------
# Suppress Specific Warnings
# -----------------------

# Suppress GeoPandas UserWarning about GeoSeries.notna()
warnings.filterwarnings('ignore', 'GeoSeries.notna', UserWarning)

# -----------------------
# Step 1: Load and Process Polygons
# -----------------------

# Load the polygons from 'polygon_boundary1.csv'
try:
    polygon_df = pd.read_csv(POLYGON_CSV)
    print(f"Loaded {len(polygon_df)} polygons from '{POLYGON_CSV}'.")
except FileNotFoundError:
    print(f"Error: File '{POLYGON_CSV}' not found.")
    exit(1)
except Exception as e:
    print(f"Error reading '{POLYGON_CSV}': {e}")
    exit(1)

# Parse the WKT geometries and handle invalid polygons
def parse_polygon(wkt_str, row_index):
    try:
        polygon = wkt_loads(wkt_str)
        if not polygon.is_valid:
            print(f"Invalid polygon at row {row_index}: Attempting to fix.")
            polygon = polygon.buffer(0)  # Attempt to fix the polygon
            if not polygon.is_valid:
                print(f"Failed to fix polygon at row {row_index}. Skipping.")
                return None
        return polygon
    except Exception as e:
        print(f"Error parsing WKT at row {row_index}: {e}")
        return None

polygon_df['geometry'] = polygon_df.apply(lambda row: parse_polygon(row['WKT'], row.name), axis=1)

# Drop rows with invalid geometries
initial_polygon_count = len(polygon_df)
polygon_df = polygon_df.dropna(subset=['geometry'])
dropped_polygons = initial_polygon_count - len(polygon_df)
if dropped_polygons > 0:
    print(f"Dropped {dropped_polygons} invalid polygons.")

# Create a GeoDataFrame for polygons
polygon_gdf = gpd.GeoDataFrame(polygon_df, geometry='geometry')
polygon_gdf.crs = "EPSG:4326"  # Set coordinate reference system to WGS84

# Initialize points_count to 0
polygon_gdf['points_count'] = 0

# -----------------------
# Step 2: Load and Process Coordinates
# -----------------------

# Load the coordinates from 'coordinates.csv' (comma-separated)
try:
    coordinates_df = pd.read_csv(COORDINATES_CSV, dtype=str)
    print(f"Total records in '{COORDINATES_CSV}': {len(coordinates_df)}")
except FileNotFoundError:
    print(f"Error: File '{COORDINATES_CSV}' not found.")
    exit(1)
except Exception as e:
    print(f"Error reading '{COORDINATES_CSV}': {e}")
    exit(1)

# Ensure column names are correct
coordinates_df.columns = coordinates_df.columns.str.strip()

# Verify 'destination' column exists
if 'destination' not in coordinates_df.columns:
    print(f"Error: Column 'destination' not found in '{COORDINATES_CSV}'. Available columns: {coordinates_df.columns.tolist()}")
    exit(1)

# Count of records where 'destination' is missing
destination_missing_count = coordinates_df['destination'].isnull().sum()
print(f"Number of records where 'destination' is missing: {destination_missing_count}")

# Initialize counters
counters = {'json_parse_errors': 0, 'lat_long_missing': 0}

# Extract latitude and longitude from the 'destination' JSON strings
def extract_lat_long(destination):
    if pd.isnull(destination):
        counters['lat_long_missing'] += 1
        return pd.Series([None, None])
    try:
        # Replace double double-quotes with single double-quotes
        destination = destination.replace('""', '"').strip('"')
        # Parse the JSON data
        data = json.loads(destination)
        # Extract latitude and longitude
        latitude = data.get('latitude', None)
        longitude = data.get('longitude', None)
        if latitude is None or longitude is None:
            counters['lat_long_missing'] += 1
        return pd.Series([latitude, longitude])
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        counters['json_parse_errors'] += 1
        return pd.Series([None, None])

# Apply the function to extract latitude and longitude
coordinates_df[['latitude', 'longitude']] = coordinates_df['destination'].apply(extract_lat_long)

# Log parsing errors and missing lat/lng
print(f"Number of JSON parsing errors: {counters['json_parse_errors']}")
print(f"Number of records where latitude or longitude is missing after parsing: {counters['lat_long_missing']}")

# Convert latitude and longitude to numeric, handling errors
coordinates_df['latitude'] = pd.to_numeric(coordinates_df['latitude'], errors='coerce')
coordinates_df['longitude'] = pd.to_numeric(coordinates_df['longitude'], errors='coerce')

# Count number of records with invalid latitude or longitude after conversion
invalid_lat_long = coordinates_df[['latitude', 'longitude']].isnull().any(axis=1).sum()
print(f"Number of records with invalid latitude or longitude after conversion: {invalid_lat_long}")

# Drop rows with invalid coordinates
coordinates_df = coordinates_df.dropna(subset=['latitude', 'longitude'])

# Filter out coordinates outside valid ranges
valid_range_mask = (
    (coordinates_df['latitude'] >= -90) & (coordinates_df['latitude'] <= 90) &
    (coordinates_df['longitude'] >= -180) & (coordinates_df['longitude'] <= 180)
)
out_of_range_count = (~valid_range_mask).sum()
print(f"Number of records with latitude or longitude outside valid ranges: {out_of_range_count}")

# Keep only valid range coordinates
coordinates_df = coordinates_df[valid_range_mask]

# Record the number of valid records before any deduplication
valid_records_before_dedup = len(coordinates_df)
print(f"Number of valid records after cleaning: {valid_records_before_dedup}")

# Round coordinates to 6 decimal places to handle floating-point precision
coordinates_df['latitude'] = coordinates_df['latitude'].round(6)
coordinates_df['longitude'] = coordinates_df['longitude'].round(6)

# Count occurrences of each coordinate before removing duplicates
coordinates_df['count'] = 1
coordinates_counts = coordinates_df.groupby(['latitude', 'longitude']).agg({'count': 'sum'}).reset_index()

total_unique_coordinates = len(coordinates_counts)
print(f"Total number of unique coordinates: {total_unique_coordinates}")

# Number of duplicates
duplicates_count = valid_records_before_dedup - total_unique_coordinates
print(f"Number of duplicate records: {duplicates_count}")

# Create GeoDataFrame for coordinates with counts
coordinates_counts['geometry'] = gpd.points_from_xy(coordinates_counts['longitude'], coordinates_counts['latitude'])
coordinates_gdf = gpd.GeoDataFrame(coordinates_counts, geometry='geometry')
coordinates_gdf.crs = "EPSG:4326"  # Set CRS to WGS84

# -----------------------
# Step 3: Spatial Join to Count Points in Polygons
# -----------------------

# Perform spatial join to find which points fall within which polygons
joined_gdf = gpd.sjoin(coordinates_gdf, polygon_gdf, how='left', predicate='within')

# Number of points assigned to polygons
points_assigned = joined_gdf['index_right'].notnull().sum()
print(f"Number of unique coordinates assigned to polygons: {points_assigned}")

# Number of points not assigned to any polygon
points_not_assigned = joined_gdf['index_right'].isnull().sum()
print(f"Number of unique coordinates not assigned to any polygon: {points_not_assigned}")

# Total counts of points assigned to polygons (including duplicates)
points_in_polygons = joined_gdf.groupby('index_right')['count'].sum().reset_index()

# Merge the counts back into the polygon GeoDataFrame
polygon_gdf = polygon_gdf.reset_index().merge(points_in_polygons, left_on='index', right_on='index_right', how='left')

# Fill NaN counts with 0 (polygons with no points)
polygon_gdf['points_count'] = polygon_gdf['count'].fillna(0).astype(int)

# Number of polygons with zero points
polygons_with_zero_points = (polygon_gdf['points_count'] == 0).sum()
print(f"Number of polygons with zero points: {polygons_with_zero_points}")

# -----------------------
# Step 4: Assign Colors Based on Counts
# -----------------------

# Apply logarithmic scaling to points_count to handle skewed data
polygon_gdf['log_points_count'] = np.log1p(polygon_gdf['points_count'])

# Normalize log-transformed counts to [0, 1]
norm = colors.Normalize(vmin=polygon_gdf['log_points_count'].min(), vmax=polygon_gdf['log_points_count'].max())

# Choose a perceptually uniform colormap
cmap = colormaps['viridis']  # Options: 'viridis', 'plasma', 'inferno', 'magma', 'cividis'

# Function to get color from colormap using log-scaled counts
def get_continuous_color(points_count):
    rgba = cmap(norm(np.log1p(points_count)))
    return colors.to_hex(rgba)

# Apply the color function
polygon_gdf['color'] = polygon_gdf['points_count'].apply(get_continuous_color)

# -----------------------
# Step 5: Prepare Data for GeoJSON Output
# -----------------------

# Ensure 'description' field has no NaN values
polygon_gdf['description'] = polygon_gdf['description'].fillna('')

# Select the required columns
output_gdf = polygon_gdf[['name', 'description', 'points_count', 'color', 'geometry']]

# -----------------------
# Step 6: Export to GeoJSON
# -----------------------

try:
    output_gdf.to_file(OUTPUT_GEOJSON, driver='GeoJSON')
    print(f"GeoJSON file '{OUTPUT_GEOJSON}' has been saved successfully.")
except Exception as e:
    print(f"Error writing GeoJSON file '{OUTPUT_GEOJSON}': {e}")
    exit(1)
