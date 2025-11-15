import geopandas as gpd
import random
import json
import requests
import time
from concurrent.futures import ThreadPoolExecutor
import traceback

GOOGLE_API_KEY = "AIzaSyAQI6vnKW5-8lH24bGygQ7eNhPM79677ps"

shapefile_path = r"C:\Users\ktwom\pythonProject\guesserlocation\ne_110m_populated_places.shp"
gdf = gpd.read_file(shapefile_path)
print(f"Loaded shapefile: {len(gdf)} populated places")

NUM_LOCATIONS = 5000
MAX_ATTEMPTS = 20000
THREADS = 10

locations = []
failures = 0

# -------------------------------------------
# Street View validation
# -------------------------------------------
def has_street_view(lat, lon):
    url = (
        "https://maps.googleapis.com/maps/api/streetview/metadata?"
        f"location={lat},{lon}&key={GOOGLE_API_KEY}"
    )
    try:
        r = requests.get(url, timeout=4)
        if r.status_code != 200:
            return False
        data = r.json()

        # Accept only outdoor images with successful status
        if data.get("status") == "OK":
            return True

        return False

    except Exception:
        return False


# -------------------------------------------
# Point sampling
# -------------------------------------------
def sample_point():
    row = gdf.sample(1).iloc[0]
    lon, lat = row.geometry.x, row.geometry.y
    heading = random.randint(0, 360)
    return lat, lon, heading


# -------------------------------------------
# Worker thread
# -------------------------------------------
def worker_check(point, attempt_number):
    if point is None:
        return None

    lat, lon, heading = point

    print(f"[Attempt {attempt_number}] Checking {lat:.5f}, {lon:.5f} ...")

    if has_street_view(lat, lon):
        print(f"✔️  Valid Street View FOUND at {lat:.5f}, {lon:.5f}")
        return {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "heading": heading
        }

    print(f"❌  No Street View at {lat:.5f}, {lon:.5f}")
    return None


# -------------------------------------------
# Main generation loop
# -------------------------------------------
def main():
    global failures

    attempts = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = {}

        while len(locations) < NUM_LOCATIONS and attempts < MAX_ATTEMPTS:
            attempts += 1
            point = sample_point()

            fut = executor.submit(worker_check, point, attempts)
            futures[fut] = attempts

            # Check finished tasks
            ready = [f for f in list(futures.keys()) if f.done()]
            for f in ready:
                attempt_id = futures.pop(f)
                try:
                    result = f.result()
                except Exception as e:
                    failures += 1
                    print(f"⚠️ Worker crashed on attempt {attempt_id}")
                    traceback.print_exc()
                    continue

                if result:
                    locations.append(result)
                    print(f"\n🎯 Added {len(locations)}/{NUM_LOCATIONS} → "
                          f"{result['lat']}, {result['lon']}\n")
                else:
                    failures += 1

            # live progress output
            elapsed = time.time() - start_time
            speed = attempts / max(elapsed, 1)
            print(f"Progress: {len(locations)}/{NUM_LOCATIONS} | Attempts: {attempts} | "
                  f"Failures: {failures} | {speed:.1f} attempts/sec\r", end="")

            time.sleep(0.02)

    print("\n\n------------------------")
    print(" Generation Complete ")
    print("------------------------")
    print(f"Valid locations: {len(locations)}")
    print(f"Total attempts: {attempts}")
    print(f"Failures: {failures}")

    # Save results
    with open("streetview_locations.json", "w", encoding="utf-8") as f:
        json.dump(locations, f, indent=2)

    print("Saved → streetview_locations.json")


# -------------------------------------------
# Run
# -------------------------------------------
if __name__ == "__main__":
    main()
