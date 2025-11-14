# main.py
from flask import Flask, render_template, request, session, redirect, url_for
import random, math, os, json, datetime, requests, logging, re, sqlite3
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask_compress import Compress

load_dotenv()

app = Flask(__name__)
Compress(app)

# ---------- CONFIG ----------
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not DEBUG
)

logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger("geoguesser")

# ---------- Load locations ----------
ALL_LOCATIONS = []
try:
    with open("streetview_locations.json", "r", encoding="utf-8") as f:
        ALL_LOCATIONS = json.load(f)
except Exception as e:
    logger.warning("Failed to load locations: %s", e)

# ---------- Helpers ----------
def is_us(loc):
    return -125 <= loc["lon"] <= -66 and 24 <= loc["lat"] <= 50

def is_europe(loc):
    return -10 <= loc["lon"] <= 40 and 35 <= loc["lat"] <= 70

def get_daily_locations():
    today = datetime.date.today().isoformat()
    cache_file = os.path.join(os.path.dirname(__file__), f"daily_locations_{today}.json")

    if os.path.isfile(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass

    us_locations = [loc for loc in ALL_LOCATIONS if is_us(loc)]
    europe_locations = [loc for loc in ALL_LOCATIONS if is_europe(loc)]
    other_locations = [loc for loc in ALL_LOCATIONS if loc not in us_locations + europe_locations]

    chosen = []
    rng = random.Random(today)
    for _ in range(5):
        p = rng.random()
        if p < 0.5 and europe_locations:
            chosen.append(rng.choice(europe_locations))
        elif p < 0.8 and us_locations:
            chosen.append(rng.choice(us_locations))
        elif other_locations:
            chosen.append(rng.choice(other_locations))

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(chosen, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to write daily cache: %s", e)

    return chosen

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ---------- Share image ----------
SHARE_IMAGE_FOLDER = os.path.join(os.path.dirname(__file__), "static", "share_images")
os.makedirs(SHARE_IMAGE_FOLDER, exist_ok=True)

def generate_share_image(actual_lat, actual_lon, guessed_lat, guessed_lon, round_score, distance_km, filename=None):
    if not GOOGLE_API_KEY:
        return None
    if filename is None:
        filename = secure_filename(f"share_{actual_lat}_{actual_lon}_{guessed_lat}_{guessed_lon}.png")
    filepath = os.path.join(SHARE_IMAGE_FOLDER, filename)

    url = f"https://maps.googleapis.com/maps/api/staticmap?size=600x400&maptype=roadmap&markers=color:red|label:A|{actual_lat},{actual_lon}&markers=color:blue|label:G|{guessed_lat},{guessed_lon}&key={GOOGLE_API_KEY}"
    try:
        resp = requests.get(url, timeout=6)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
    except:
        return None

    return "/" + os.path.relpath(filepath, start=os.path.dirname(__file__)).replace("\\", "/")

# ---------- Validation ----------
EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
def is_valid_email(email): return bool(email and EMAIL_RE.match(email))
def safe_float(value, default=0.0):
    try: return float(value)
    except: return default

# ---------- SQLite leaderboard ----------
PROJECT_DIR = os.path.dirname(__file__)
DB_FILE = os.path.join(PROJECT_DIR, "leaderboard.db")

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard (
            date TEXT,
            email TEXT,
            score INTEGER,
            PRIMARY KEY(date,email)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- Flask hooks ----------
@app.before_request
def setup_game():
    today = datetime.date.today().isoformat()
    if session.get("last_played_date") != today:
        session.clear()
        session.update({
            "score":0,
            "round":1,
            "results":[],
            "game_locations": get_daily_locations(),
            "instructions_shown": False,
            "last_played_date": today
        })

# ---------- Routes ----------
@app.route("/")
def index():
    round_num = session.get("round", 1)
    score = session.get("score", 0)

    if round_num > 5:
        return redirect(url_for("result"))

    loc = session["game_locations"][round_num-1]
    session.update({"actual_lat": loc.get("lat"), "actual_lon": loc.get("lon"), "heading": loc.get("heading",0)})
    show_instructions = not session.get("instructions_shown", False)

    share_image_url = url_for('static', filename='images/share_placeholder.png', _external=True)

    return render_template("index.html", lat=loc["lat"], lon=loc["lon"], heading=loc.get("heading",0), api_key=GOOGLE_API_KEY, round=round_num, score=score, show_instructions=show_instructions)

@app.route("/guess", methods=["POST"])
def guess():
    guessed_lat = safe_float(request.form.get("lat"))
    guessed_lon = safe_float(request.form.get("lon"))
    actual_lat = session.get("actual_lat")
    actual_lon = session.get("actual_lon")
    if actual_lat is None or actual_lon is None:
        return redirect(url_for("index"))

    distance_km = haversine(actual_lat, actual_lon, guessed_lat, guessed_lon)
    round_score = max(0, int(1000 - distance_km))
    session["score"] += round_score

    bar = "📍🟥📍"
    if distance_km < 5: bar = "📍🟩📍"
    elif distance_km < 50: bar = "📍🟨📍"
    elif distance_km < 500: bar = "📍🟧📍"

    session["results"].append({
        "round": session["round"],
        "bar": bar,
        "distance_km": round(distance_km,1),
        "round_score": round_score,
        "guessed_lat": guessed_lat,
        "guessed_lon": guessed_lon,
        "actual_lat": actual_lat,
        "actual_lon": actual_lon
    })
    session["round"] += 1

    return redirect(url_for("round_result"))

@app.route("/round_result")
def round_result():
    results = session.get("results", [])
    if not results: return redirect(url_for("index"))
    last_result = results[-1]
    score = session.get("score", 0)
    share_image_url = generate_share_image(last_result["actual_lat"], last_result["actual_lon"], last_result["guessed_lat"], last_result["guessed_lon"], last_result["round_score"], last_result["distance_km"])
    return render_template("round_result.html", result=last_result, score=score, api_key=GOOGLE_API_KEY, share_image_url=share_image_url)

@app.route("/result", methods=["GET","POST"])
def result():
    results = session.get("results", [])
    score = session.get("score",0)
    if not results: return redirect(url_for("index"))

    today = datetime.date.today().isoformat()

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        if is_valid_email(email):
            session["email"] = email

            conn = get_db_connection()
            row = conn.execute(
                "SELECT score FROM leaderboard WHERE date=? AND email=?",
                (today,email)
            ).fetchone()
            existing_score = row["score"] if row else 0

            if score > existing_score:
                conn.execute(
                    "INSERT OR REPLACE INTO leaderboard(date,email,score) VALUES(?,?,?)",
                    (today,email,score)
                )
                conn.commit()
            conn.close()
            session["freeplay_unlocked"] = True
            return redirect(url_for("result"))

    # Load leaderboard for display
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT email, score FROM leaderboard WHERE date=? ORDER BY score DESC",
        (today,)
    ).fetchall()
    conn.close()

    entries = [{"email": r["email"].split("@")[0], "score": r["score"]} for r in rows]

    user_email = session.get("email", "")
    return render_template("result.html", results=results, entries=entries, total_score=score, user_email=user_email, freeplay_unlocked=session.get("freeplay_unlocked", False))

# ---------- Freeplay routes ----------
@app.route("/freeplay")
def freeplay():
    if not session.get("freeplay_unlocked"): return redirect(url_for("result"))
    loc = random.choice(ALL_LOCATIONS)
    session.update({"freeplay_actual_lat": loc["lat"], "freeplay_actual_lon": loc["lon"], "freeplay_heading": loc.get("heading",0)})
    return render_template("freeplay.html", lat=loc["lat"], lon=loc["lon"], heading=loc.get("heading",0), api_key=GOOGLE_API_KEY)

@app.route("/freeplay_guess", methods=["POST"])
def freeplay_guess():
    guessed_lat = safe_float(request.form.get("lat"))
    guessed_lon = safe_float(request.form.get("lon"))
    actual_lat = session.get("freeplay_actual_lat")
    actual_lon = session.get("freeplay_actual_lon")
    if actual_lat is None or actual_lon is None: return redirect(url_for("freeplay"))

    distance_km = round(haversine(actual_lat, actual_lon, guessed_lat, guessed_lon),1)
    distance_mi = round(distance_km*0.621371,1)
    bar="📍🟥📍"
    if distance_km<5: bar="📍🟩📍"
    elif distance_km<50: bar="📍🟨📍"
    elif distance_km<500: bar="📍🟧📍"

    share_image_url = generate_share_image(actual_lat, actual_lon, guessed_lat, guessed_lon, max(0,int(1000-distance_km)), distance_km)
    return render_template("freeplay_result.html", guessed_lat=guessed_lat, guessed_lon=guessed_lon, actual_lat=actual_lat, actual_lon=actual_lon, distance_km=distance_km, distance_mi=distance_mi, bar=bar, api_key=GOOGLE_API_KEY, share_image_url=share_image_url)

# ---------- SEO ----------
@app.route("/robots.txt")
def robots_txt():
    return "User-Agent: *\nDisallow:\nSitemap: https://sightcr.com/sitemap.xml",200,{"Content-Type":"text/plain"}

@app.route("/sitemap.xml")
def sitemap():
    static_routes=["index","result"]
    pages=[f"<url><loc>{url_for(r,_external=True)}</loc></url>" for r in static_routes]
    xml=f"<?xml version='1.0' encoding='UTF-8'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>{''.join(pages)}</urlset>"
    return xml,200,{"Content-Type":"application/xml"}

if __name__ == "__main__":
    port=int(os.environ.get("PORT",5010))
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
