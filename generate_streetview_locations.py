import geopandas as gpd
import random
import json
import requests
import time

GOOGLE_API_KEY = "AIzaSyAQI6vnKW5-8lH24bGygQ7eNhPM79677ps"

shapefile_path = r"C:\Users\ktwom\pythonProject\guesserlocation\ne_110m_populated_places.shp"
gdf = gpd.read_file(shapefile_path)

NUM_LOCATIONS = 1000
locations = []


def has_street_view(lat, lon):
    metadata_url = (
        f"https://maps.googleapis.com/maps/api/streetview/metadata?"
        f"location={lat},{lon}&key={GOOGLE_API_KEY}"
    )
    response = requests.get(metadata_url)
    if response.status_code == 200:
        data = response.json()
        return data.get("status") == "OK"
    return False


attempts = 0
max_attempts = 10000  # Avoid infinite loop if not enough coverage spots

while len(locations) < NUM_LOCATIONS and attempts < max_attempts:
    attempts += 1
    point = gdf.sample(1).iloc[0]
    lon, lat = point.geometry.x, point.geometry.y
    heading = random.randint(0, 360)

    if has_street_view(lat, lon):
        locations.append({
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "heading": heading
        })
        print(f"Added location #{len(locations)}: {lat}, {lon}")
    else:
        print(f"No Street View at: {lat}, {lon}")

    time.sleep(0.1)  # to avoid hitting API rate limits

with open("streetview_locations.json", "w") as f:
    json.dump(locations, f, indent=2)

print(f"Generated {len(locations)} valid Street View locations in streetview_locations.json")
