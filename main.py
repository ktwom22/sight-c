from flask import Flask, render_template, request, session, redirect, url_for
import random, math, csv, os, json, datetime, requests

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ✅ Use environment variable for security
GOOGLE_API_KEY = "AIzaSyAQI6vnKW5-8lH24bGygQ7eNhPM79677ps"

# --- Load locations safely ---
try:
    with open("streetview_locations.json", "r", encoding="utf-8") as f:
        ALL_LOCATIONS = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    ALL_LOCATIONS = []
    print("⚠️ Warning: streetview_locations.json not found or invalid!")

# --- Helper functions ---
def is_us(loc):
    return -125 <= loc["lon"] <= -66 and 24 <= loc["lat"] <= 50

def is_europe(loc):
    return -10 <= loc["lon"] <= 40 and 35 <= loc["lat"] <= 70

def get_daily_locations():
    today = datetime.date.today().isoformat()
    cache_file = f"daily_locations_{today}.json"

    if os.path.isfile(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # otherwise generate deterministically
    random.seed(today)
    us_locations = [loc for loc in ALL_LOCATIONS if is_us(loc)]
    europe_locations = [loc for loc in ALL_LOCATIONS if is_europe(loc)]
    other_locations = [loc for loc in ALL_LOCATIONS if loc not in us_locations + europe_locations]

    weighted_choices = []
    for _ in range(5):
        r = random.random()
        if r < 0.5:
            weighted_choices.append(random.choice(europe_locations))
        elif r < 0.8:
            weighted_choices.append(random.choice(us_locations))
        else:
            weighted_choices.append(random.choice(other_locations))

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(weighted_choices, f, ensure_ascii=False, indent=2)

    return weighted_choices


def haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# --- Shareable Image Setup ---
SHARE_IMAGE_FOLDER = "static/share_images"
os.makedirs(SHARE_IMAGE_FOLDER, exist_ok=True)

def generate_share_image(actual_lat, actual_lon, guessed_lat, guessed_lon, round_score, distance_km, filename=None):
    """Generates a shareable static map image (no text overlay)."""
    if filename is None:
        filename = f"share_{actual_lat}_{actual_lon}_{guessed_lat}_{guessed_lon}.png"
    filepath = os.path.join(SHARE_IMAGE_FOLDER, filename)

    map_url = (
        f"https://maps.googleapis.com/maps/api/staticmap?"
        f"size=600x400"
        f"&maptype=roadmap"
        f"&markers=color:red|label:A|{actual_lat},{actual_lon}"
        f"&markers=color:blue|label:G|{guessed_lat},{guessed_lon}"
        f"&key={GOOGLE_API_KEY}"
    )

    resp = requests.get(map_url)
    if resp.status_code != 200:
        print("Error fetching static map!")
        return None

    with open(filepath, "wb") as f:
        f.write(resp.content)

    return "/" + filepath.replace("\\", "/")

# --- Flask hooks and routes ---
@app.before_request
def setup_game():
    today = datetime.date.today().isoformat()
    # If the user hasn’t played today, initialize a new game
    if session.get("last_played_date") != today:
        session.clear()
        session["score"] = 0
        session["round"] = 1
        session["results"] = []
        session["game_locations"] = get_daily_locations()  # deterministic per day
        session["instructions_shown"] = False
        session["last_played_date"] = today


@app.route("/")
def index():
    round_num = session.get("round", 1)
    score = session.get("score", 0)

    # ✅ Safety check if session data lost
    if "game_locations" not in session or not session["game_locations"]:
        session["game_locations"] = get_daily_locations()

    if round_num > 5:
        return redirect(url_for("result"))

    loc = session["game_locations"][round_num - 1]
    session["actual_lat"] = loc["lat"]
    session["actual_lon"] = loc["lon"]
    session["heading"] = loc.get("heading", 0)
    show_instructions = not session.get("instructions_shown", False)

    share_image_url = url_for('static', filename='images/share_placeholder.png', _external=True)

    return render_template(
        "index.html",
        lat=loc["lat"],
        lon=loc["lon"],
        heading=loc.get("heading", 0),
        api_key=GOOGLE_API_KEY,
        round=round_num,
        score=score,
        show_instructions=show_instructions,
        seo_title="GeoGuesser - Play the Ultimate Travel Quiz Game",
        seo_description="Guess locations around the world and test your geography skills with GeoGuesser. Travel virtually and challenge yourself!",
        seo_keywords="travel game, geography quiz, world map game, virtual travel game, learn geography, travel challenge, GeoGuesser",
        share_image_url=share_image_url
    )

@app.route("/instructions_shown", methods=["POST"])
def instructions_shown():
    session["instructions_shown"] = True
    return "", 204

@app.route("/guess", methods=["POST"])
def guess():
    guessed_lat = float(request.form.get("lat"))
    guessed_lon = float(request.form.get("lon"))
    actual_lat = session.get("actual_lat")
    actual_lon = session.get("actual_lon")
    round_num = session.get("round", 1)
    score = session.get("score", 0)

    distance_km = round(haversine(actual_lat, actual_lon, guessed_lat, guessed_lon), 1)
    round_score = max(0, int(1000 - distance_km))
    score += round_score

    if distance_km < 5:
        bar = "📍🟩📍"
    elif distance_km < 50:
        bar = "📍🟨📍"
    elif distance_km < 500:
        bar = "📍🟧📍"
    else:
        bar = "📍🟥📍"

    results = session.get("results", [])
    results.append({
        "round": round_num,
        "bar": bar,
        "distance_km": distance_km,
        "distance_mi": round(distance_km * 0.621371, 1),
        "round_score": round_score,
        "guessed_lat": guessed_lat,
        "guessed_lon": guessed_lon,
        "actual_lat": actual_lat,
        "actual_lon": actual_lon
    })
    session["results"] = results
    session["score"] = score
    session["round"] = round_num + 1

    return redirect(url_for("round_result"))

@app.route("/round_result")
def round_result():
    results = session.get("results", [])
    if not results:
        return redirect(url_for("index"))
    last_result = results[-1]
    score = session.get("score", 0)
    round_num = last_result["round"]

    share_image_url = generate_share_image(
        actual_lat=last_result["actual_lat"],
        actual_lon=last_result["actual_lon"],
        guessed_lat=last_result["guessed_lat"],
        guessed_lon=last_result["guessed_lon"],
        round_score=last_result["round_score"],
        distance_km=last_result["distance_km"]
    )

    return render_template(
        "round_result.html",
        result=last_result,
        score=score,
        round=round_num,
        api_key=GOOGLE_API_KEY,
        share_image_url=share_image_url
    )

@app.route("/result", methods=["GET", "POST"])
def result():
    results = session.get("results", [])
    score = session.get("score", 0)
    if not results:
        return redirect(url_for("index"))

    # --- Build Share Text ---
    share_lines = ["🌎 GeoGuesser Results"]
    for r in results:
        share_lines.append(r.get("bar", "📍❔📍"))
    share_lines.append(f"🏁 Total Score: {score}")
    share_text = "\n".join(share_lines)

    # --- Leaderboard Setup ---
    LEADERBOARD_DIR = os.path.join(os.path.dirname(__file__), "leaderboards")
    os.makedirs(LEADERBOARD_DIR, exist_ok=True)
    today = datetime.date.today().isoformat()
    leaderboard_file = os.path.join(LEADERBOARD_DIR, f"leaderboard_{today}.csv")

    print(f"[DEBUG] Leaderboard file path: {leaderboard_file}")

    # --- Handle POST (email submission) ---
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        print(f"[DEBUG] Submitting email: {email} | Score: {score}")

        if email:
            session["email"] = email
            entries_dict = {}

            # Read existing leaderboard
            if os.path.isfile(leaderboard_file):
                print("[DEBUG] Existing leaderboard found, reading...")
                with open(leaderboard_file, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        entries_dict[row["email"]] = int(row["score"])

            # Update or add this user's score
            entries_dict[email] = max(entries_dict.get(email, 0), score)
            print(f"[DEBUG] Updated leaderboard entries: {entries_dict}")

            # Write updated leaderboard
            with open(leaderboard_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["email", "score"])
                writer.writeheader()
                for e, s in entries_dict.items():
                    writer.writerow({"email": e, "score": s})

            session["freeplay_unlocked"] = True
            print("[DEBUG] Leaderboard updated successfully!")
            return redirect(url_for("result"))

    # --- Load Leaderboard for Display ----
    entries = []
    user_email = session.get("email") or ""
    user_display_name = user_email.split("@")[0] if "@" in user_email else user_email

    if os.path.isfile(leaderboard_file):
        with open(leaderboard_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email_full = row["email"]
                score_val = int(row["score"])
                display_name = email_full.split("@")[0]  # only keep part before @
                entries.append({"email": display_name, "score": score_val})

    entries.sort(key=lambda x: x["score"], reverse=True)

    # --- Context ---
    user_email = session.get("email")
    score_submitted = session.get("freeplay_unlocked", False)

    print(f"[DEBUG] Displaying {len(entries)} leaderboard entries")

    return render_template(
        "result.html",
        results=results,
        entries=entries,
        total_score=score,
        user_email=user_email,
        share_text=share_text,
        freeplay_unlocked=score_submitted,
        seo_title="GeoGuesser Results - See How You Did!",
        seo_description="Check your GeoGuesser results, compare with others, and share your score.",
        seo_keywords="GeoGuesser results, travel game, geography challenge, world map game"
    )





@app.route("/leaderboard")
def leaderboard():
    today = datetime.date.today().isoformat()
    filename = f"leaderboard_{today}.csv"
    entries = []
    user_email = session.get("email")
    if os.path.isfile(filename):
        with open(filename, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entries.append({"email": row["email"], "score": int(row["score"])})
    entries.sort(key=lambda x: x["score"], reverse=True)
    return render_template("leaderboard.html", entries=entries, user_email=user_email)

@app.route("/freeplay")
def freeplay():
    if not session.get("freeplay_unlocked"):
        return redirect(url_for("result"))

    recent = session.get("freeplay_recent", [])
    available = [loc for loc in ALL_LOCATIONS if loc not in recent]
    if not available:
        available = ALL_LOCATIONS
        recent = []

    loc = random.choice(available)
    session["freeplay_actual_lat"] = loc["lat"]
    session["freeplay_actual_lon"] = loc["lon"]
    session["freeplay_heading"] = loc.get("heading", 0)
    recent.append(loc)
    session["freeplay_recent"] = recent[-10:]

    return render_template(
        "freeplay.html",
        lat=loc["lat"],
        lon=loc["lon"],
        heading=loc.get("heading", 0),
        api_key=GOOGLE_API_KEY
    )

@app.route("/freeplay_guess", methods=["POST"])
def freeplay_guess():
    guessed_lat = float(request.form.get("lat"))
    guessed_lon = float(request.form.get("lon"))
    actual_lat = session.get("freeplay_actual_lat")
    actual_lon = session.get("freeplay_actual_lon")
    distance_km = round(haversine(actual_lat, actual_lon, guessed_lat, guessed_lon), 1)
    distance_mi = round(distance_km * 0.621371, 1)

    if distance_km < 5:
        bar = "📍🟩📍"
    elif distance_km < 50:
        bar = "📍🟨📍"
    elif distance_km < 500:
        bar = "📍🟧📍"
    else:
        bar = "📍🟥📍"

    share_image_url = generate_share_image(
        actual_lat=actual_lat,
        actual_lon=actual_lon,
        guessed_lat=guessed_lat,
        guessed_lon=guessed_lon,
        round_score=max(0, int(1000 - distance_km)),
        distance_km=distance_km
    )

    return render_template(
        "freeplay_result.html",
        guessed_lat=guessed_lat,
        guessed_lon=guessed_lon,
        actual_lat=actual_lat,
        actual_lon=actual_lon,
        distance_km=distance_km,
        distance_mi=distance_mi,
        bar=bar,
        api_key=GOOGLE_API_KEY,
        share_image_url=share_image_url
    )

@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-Agent: *",
        "Disallow:",
        "Sitemap: https://sightcr.com/sitemap.xml"
    ]
    return "\n".join(lines), 200, {"Content-Type": "text/plain"}

@app.route("/sitemap.xml")
def sitemap():
    static_routes = ["index", "leaderboard", "result"]
    pages = [f"<url><loc>{url_for(r, _external=True)}</loc></url>" for r in static_routes]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{''.join(pages)}
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5010))
    app.run(host="0.0.0.0", port=port, debug=True)
