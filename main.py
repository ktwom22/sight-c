# main.py
from flask import Flask, render_template, request, session, redirect, url_for, abort
import random, math, csv, os, json, datetime, requests, logging, re
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask_compress import Compress



load_dotenv()


app = Flask(__name__)
Compress(app)

# ---------- CONFIG ----------
# Use environment variables for secrets in production
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
# toggle debug via env var; never run debug=True in production
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

# Session cookie hardening
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not DEBUG  # secure cookies when not debugging (requires HTTPS)
)

# Logging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger("geoguesser")

# ---------- Load locations safely ----------
ALL_LOCATIONS = []
try:
    with open("streetview_locations.json", "r", encoding="utf-8") as f:
        ALL_LOCATIONS = json.load(f)
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning("streetview_locations.json not found or invalid: %s", e)
    ALL_LOCATIONS = []

# ---------- Helpers ----------
def is_us(loc):
    return -125 <= loc["lon"] <= -66 and 24 <= loc["lat"] <= 50

def is_europe(loc):
    return -10 <= loc["lon"] <= 40 and 35 <= loc["lat"] <= 70

def deterministic_choice(seed, seq, k=1):
    """Return deterministic choices from seq using seed string, without changing global random."""
    import random as _rand
    rnd = _rand.Random(seed)
    if k == 1:
        return rnd.choice(seq) if seq else None
    return [rnd.choice(seq) for _ in range(k)]

def get_daily_locations():
    """Return 5 deterministic locations weighted for Europe/US.
       Cache to daily_locations_YYYY-MM-DD.json so changes to ALL_LOCATIONS mid-day won't affect fairness.
    """
    today = datetime.date.today().isoformat()
    cache_file = os.path.join(os.path.dirname(__file__), f"daily_locations_{today}.json")

    if os.path.isfile(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed reading daily cache, regenerating: %s", e)

    # generate deterministically
    us_locations = [loc for loc in ALL_LOCATIONS if is_us(loc)]
    europe_locations = [loc for loc in ALL_LOCATIONS if is_europe(loc)]
    other_locations = [loc for loc in ALL_LOCATIONS if loc not in us_locations + europe_locations]

    chosen = []
    # create an RNG seeded by date so all users see same sequence
    seed = today
    for i in range(5):
        r = deterministic_choice(seed + f"-{i}-r", [0, 1, 2])[0] if False else None
        # Instead of trying to emulate the previous random thresholds exactly, use deterministic RNG:
        rnd = random.Random(f"{seed}-{i}")
        p = rnd.random()
        if p < 0.5 and europe_locations:
            chosen.append(rnd.choice(europe_locations))
        elif p < 0.8 and us_locations:
            chosen.append(rnd.choice(us_locations))
        elif other_locations:
            chosen.append(rnd.choice(other_locations))
        else:
            # fallback to any available location
            pool = europe_locations + us_locations + other_locations
            if pool:
                chosen.append(rnd.choice(pool))

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(chosen, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to write daily cache: %s", e)

    return chosen

def haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ---------- Share image (safe request) ----------
SHARE_IMAGE_FOLDER = os.path.join(os.path.dirname(__file__), "static", "share_images")
os.makedirs(SHARE_IMAGE_FOLDER, exist_ok=True)

def generate_share_image(actual_lat, actual_lon, guessed_lat, guessed_lon, round_score, distance_km, filename=None):
    """Download a Google static map safely with timeout and sanitized filename."""
    if not GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY not set; skipping share image generation.")
        return None

    if filename is None:
        # create a safe filename
        fname = f"share_{actual_lat}_{actual_lon}_{guessed_lat}_{guessed_lon}.png"
        filename = secure_filename(fname)
    filepath = os.path.join(SHARE_IMAGE_FOLDER, filename)

    map_url = (
        f"https://maps.googleapis.com/maps/api/staticmap?"
        f"size=600x400"
        f"&maptype=roadmap"
        f"&markers=color:red|label:A|{actual_lat},{actual_lon}"
        f"&markers=color:blue|label:G|{guessed_lat},{guessed_lon}"
        f"&key={GOOGLE_API_KEY}"
    )

    try:
        resp = requests.get(map_url, timeout=6)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Error fetching static map: %s", e)
        return None

    try:
        with open(filepath, "wb") as f:
            f.write(resp.content)
    except Exception as e:
        logger.warning("Failed to save map to %s: %s", filepath, e)
        return None

    # return a static url path (Flask static serves /static/...)
    static_path = "/" + os.path.relpath(filepath, start=os.path.dirname(__file__)).replace("\\", "/")
    return static_path

# ---------- Basic validation helpers ----------
EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

def is_valid_email(email: str) -> bool:
    return bool(email and EMAIL_RE.match(email))

def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default

# ---------- Flask hooks and routes ----------
@app.before_request
def setup_game():
    today = datetime.date.today().isoformat()
    if session.get("last_played_date") != today:
        # Fresh session for a new day
        session.clear()
        session["score"] = 0
        session["round"] = 1
        session["results"] = []
        session["game_locations"] = get_daily_locations()
        session["instructions_shown"] = False
        session["last_played_date"] = today

@app.route("/")
def index():
    round_num = session.get("round", 1)
    score = session.get("score", 0)

    if "game_locations" not in session or not session["game_locations"]:
        session["game_locations"] = get_daily_locations()

    if round_num > 5:
        return redirect(url_for("result"))

    loc = session["game_locations"][round_num - 1]
    session["actual_lat"] = loc.get("lat")
    session["actual_lon"] = loc.get("lon")
    session["heading"] = loc.get("heading", 0)
    show_instructions = not session.get("instructions_shown", False)

    share_image_url = url_for('static', filename='images/share_placeholder.png', _external=True)

    return render_template(
        "index.html",
        lat=loc.get("lat"),
        lon=loc.get("lon"),
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
    guessed_lat = safe_float(request.form.get("lat"))
    guessed_lon = safe_float(request.form.get("lon"))
    actual_lat = session.get("actual_lat")
    actual_lon = session.get("actual_lon")
    if actual_lat is None or actual_lon is None:
        logger.warning("Guess submitted but actual coordinates missing from session.")
        return redirect(url_for("index"))

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
    round_num = last_result.get("round", 0)

    share_image_url = generate_share_image(
        actual_lat=last_result.get("actual_lat"),
        actual_lon=last_result.get("actual_lon"),
        guessed_lat=last_result.get("guessed_lat"),
        guessed_lon=last_result.get("guessed_lon"),
        round_score=last_result.get("round_score"),
        distance_km=last_result.get("distance_km")
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

    # Build share text
    share_lines = ["🌎 GeoGuesser Results"]
    for r in results:
        share_lines.append(r.get("bar", "📍❔📍"))
    share_lines.append(f"🏁 Total Score: {score}")
    share_text = "\n".join(share_lines)

    # Leaderboard setup
    PROJECT_DIR = os.path.dirname(__file__)
    LEADERBOARD_DIR = os.path.join(PROJECT_DIR, "leaderboards")
    os.makedirs(LEADERBOARD_DIR, exist_ok=True)
    today = datetime.date.today().isoformat()
    leaderboard_file = os.path.join(LEADERBOARD_DIR, f"leaderboard_{today}.csv")

    # Handle POST (email submission) with validation
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        if email and "@" in email:
            session["email"] = email
            entries_dict = {}

            # Read existing leaderboard
            if os.path.isfile(leaderboard_file):
                with open(leaderboard_file, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            entries_dict[row["email"]] = int(row["score"])
                        except Exception:
                            continue

            # Update the user's best score
            entries_dict[email] = max(entries_dict.get(email, 0), score)

            # Write updated leaderboard
            with open(leaderboard_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["email", "score"])
                writer.writeheader()
                for e, s in entries_dict.items():
                    writer.writerow({"email": e, "score": s})

            session["freeplay_unlocked"] = True
            return redirect(url_for("result"))

    # Load leaderboard and convert emails to display names
    entries = []
    user_email = session.get("email") or ""
    user_display_name = user_email.split("@")[0] if "@" in user_email else user_email

    if os.path.isfile(leaderboard_file):
        with open(leaderboard_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    score_val = int(row["score"])
                except Exception:
                    continue
                display_name = row["email"].split("@")[0] if "@" in row["email"] else row["email"]
                entries.append({"email": display_name, "score": score_val})

    entries.sort(key=lambda x: x["score"], reverse=True)

    return render_template(
        "result.html",
        results=results,
        entries=entries,
        total_score=score,
        user_email=user_email,
        user_display_name=user_display_name,
        share_text=share_text,
        freeplay_unlocked=session.get("freeplay_unlocked", False)
    )


@app.route("/leaderboard")
def leaderboard():
    today = datetime.date.today().isoformat()
    PROJECT_DIR = os.path.dirname(__file__)
    LEADERBOARD_DIR = os.path.join(PROJECT_DIR, "leaderboards")
    filename = os.path.join(LEADERBOARD_DIR, f"leaderboard_{today}.csv")

    entries = []
    user_email = session.get("email") or ""
    user_display_name = user_email.split("@")[0] if "@" in user_email else user_email

    if os.path.isfile(filename):
        with open(filename, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    score_val = int(row["score"])
                except Exception:
                    continue
                display_name = row["email"].split("@")[0] if "@" in row["email"] else row["email"]
                entries.append({"email": display_name, "score": score_val})

    entries.sort(key=lambda x: x["score"], reverse=True)
    return render_template("leaderboard.html", entries=entries, user_email=user_email, user_display_name=user_display_name)


@app.route("/freeplay")
def freeplay():
    if not session.get("freeplay_unlocked"):
        return redirect(url_for("result"))

    # Pick a random location from all locations
    if not ALL_LOCATIONS:
        # fallback if locations are missing
        loc = {"lat": 0, "lon": 0, "heading": 0}
    else:
        loc = random.choice(ALL_LOCATIONS)

    # Store location in session for guessing
    session["freeplay_actual_lat"] = loc.get("lat")
    session["freeplay_actual_lon"] = loc.get("lon")
    session["freeplay_heading"] = loc.get("heading", 0)

    return render_template(
        "freeplay.html",
        lat=loc.get("lat"),
        lon=loc.get("lon"),
        heading=loc.get("heading", 0),
        api_key=GOOGLE_API_KEY
    )


@app.route("/freeplay_guess", methods=["POST"])
def freeplay_guess():
    guessed_lat = safe_float(request.form.get("lat"))
    guessed_lon = safe_float(request.form.get("lon"))
    actual_lat = session.get("freeplay_actual_lat")
    actual_lon = session.get("freeplay_actual_lon")

    if actual_lat is None or actual_lon is None:
        return redirect(url_for("freeplay"))

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
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
