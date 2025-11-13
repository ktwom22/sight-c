import geopandas as gpd
import random
import json
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

GOOGLE_API_KEY = "AIzaSyAQI6vnKW5-8lH24bGygQ7eNhPM79677ps"
shapefile_path = r"C:\Users\ktwom\pythonProject\guesserlocation\ne_110m_populated_places.shp"
gdf = gpd.read_file(shapefile_path)

NUM_LOCATIONS = 1000
locations = []

US_BOUNDS = {"lat_min": 24, "lat_max": 50, "lon_min": -125, "lon_max": -66}
EU_BOUNDS = {"lat_min": 35, "lat_max": 70, "lon_min": -10, "lon_max": 40}


def has_street_view(lat, lon):
    """Check if Google Street View exists and is outdoor."""
    metadata_url = (
        f"https://maps.googleapis.com/maps/api/streetview/metadata?"
        f"location={lat},{lon}&key={GOOGLE_API_KEY}"
    )
    try:
        response = requests.get(metadata_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("status") == "OK" and data.get("copyright", "").lower() != "indoor"
    except requests.RequestException:
        return False
    return False


def get_region(lat, lon):
    """Return region for weighting: US, Europe, Other"""
    if US_BOUNDS["lat_min"] <= lat <= US_BOUNDS["lat_max"] and US_BOUNDS["lon_min"] <= lon <= US_BOUNDS["lon_max"]:
        return "US"
    elif EU_BOUNDS["lat_min"] <= lat <= EU_BOUNDS["lat_max"] and EU_BOUNDS["lon_min"] <= lon <= EU_BOUNDS["lon_max"]:
        return "Europe"
    else:
        return "Other"


def sample_point():
    """Randomly sample a point with weighted chance for US/Europe"""
    if random.random() < 0.7:
        candidates = gdf[gdf.geometry.x.between(-125, 40) & gdf.geometry.y.between(24, 70)]
    else:
        candidates = gdf

    if candidates.empty:
        return None

    point = candidates.sample(1).iloc[0]
    lon, lat = point.geometry.x, point.geometry.y
    heading = random.randint(0, 360)
    return lat, lon, heading


def check_and_add(point):
    """Check a single point for Street View and return dict if valid"""
    if point is None:
        return None
    lat, lon, heading = point
    if has_street_view(lat, lon):
        return {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "heading": heading,
            "region": get_region(lat, lon),
            "type": "outdoor"
        }
    return None


attempts = 0
max_attempts = 20000
threads = 10  # Number of parallel threads

with ThreadPoolExecutor(max_workers=threads) as executor:
    futures = []

    while len(locations) < NUM_LOCATIONS and attempts < max_attempts:
        attempts += 1
        point = sample_point()
        futures.append(executor.submit(check_and_add, point))

        # Collect completed futures
        for future in as_completed(futures):
            result = future.result()
            if result:
                locations.append(result)
                print(f"Added location #{len(locations)}: {result['lat']}, {result['lon']}")
            futures.remove(future)

        time.sleep(0.05)  # Slight pause to avoid hammering API

with open("streetview_locations.json", "w", encoding="utf-8") as f:
    json.dump(locations, f, indent=2)

print(f"Generated {len(locations)} valid Street View locations in streetview_locations.json")
