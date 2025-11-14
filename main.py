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

# Session cookie hardening
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
except (FileNotFoundError, json.JSONDecodeError) as e:
    logger.warning("streetview_locations.json not found or invalid: %s", e)
    ALL_LOCATIONS = []

# ---------- SQLite setup ----------
DB_FILE = os.path.join(os.path.dirname(__file__), "leaderboard.db")

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS leaderboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                score INTEGER NOT NULL,
                date TEXT NOT NULL
            )
        """)
        conn.commit()

init_db()

# ---------- Helpers ----------
EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

def is_valid_email(email: str) -> bool:
    return bool(email and EMAIL_RE.match(email))

def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default

def is_us(loc):
    return -125 <= loc["lon"] <= -66 and 24 <= loc["lat"] <= 50

def is_europe(loc):
    return -10 <= loc["lon"] <= 40 and 35 <= loc["lat"] <= 70

def deterministic_choice(seed, seq, k=1):
    import random as _rand
    rnd = _rand.Random(seed)
    if k == 1:
        return rnd.choice(seq) if seq else None
    return [rnd.choice(seq) for _ in range(k)]

def get_daily_locations():
    today = datetime.date.today().isoformat()
    cache_file = os.path.join(os.path.dirname(__file__), f"daily_locations_{today}.json")
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed reading daily cache, regenerating: %s", e)

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
    a = math.sin(dphi / 2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

SHARE_IMAGE_FOLDER = os.path.join(os.path.dirname(__file__), "static", "share_images")
os.makedirs(SHARE_IMAGE_FOLDER, exist_ok=True)

def generate_share_image(actual_lat, actual_lon, guessed_lat, guessed_lon, round_score, distance_km, filename=None):
    if not GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY not set; skipping share image generation.")
        return None
    if filename is None:
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
        with open(filepath, "wb") as f:
            f.write(resp.content)
        static_path = "/" + os.path.relpath(filepath, start=os.path.dirname(__file__)).replace("\\", "/")
        return static_path
    except Exception as e:
        logger.warning("Failed to fetch/save map: %s", e)
        return None

# ---------- Flask hooks ----------
@app.before_request
def setup_game():
    today = datetime.date.today().isoformat()
    if session.get("last_played_date") != today:
        session.clear()
        session["score"] = 0
        session["round"] = 1
        session["results"] = []
        session["game_locations"] = get_daily_locations()
        session["instructions_shown"] = False
        session["last_played_date"] = today

# ---------- Routes ----------
@app.route("/")
def index():
    round_num = session.get("round", 1)
    score = session.get("score", 0)
    if "game_locations" not in session or not session["game_locations"]:
        session["game_locations"] = get_daily_locations()
    if round_num > 5:
        return redirect(url_for("result"))
    loc = session["game_locations"][round_num-1]
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
        share_image_url=share_image_url
    )

@app.route("/guess", methods=["POST"])
def guess():
    guessed_lat = safe_float(request.form.get("lat"))
    guessed_lon = safe_float(request.form.get("lon"))
    actual_lat = session.get("actual_lat")
    actual_lon = session.get("actual_lon")
    if actual_lat is None or actual_lon is None:
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
    share_lines = ["🌎 GeoGuesser Results"]
    for r in results:
        share_lines.append(r.get("bar", "📍❔📍"))
    share_lines.append(f"🏁 Total Score: {score}")
    share_text = "\n".join(share_lines)

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        if is_valid_email(email):
            session["email"] = email
            today = datetime.date.today().isoformat()
            with sqlite3.connect(DB_FILE) as conn:
                c = conn.cursor()
                # Check existing score
                c.execute("SELECT score FROM leaderboard WHERE email=? AND date=?", (email, today))
                row = c.fetchone()
                if row:
                    best_score = max(row[0], score)
                    c.execute("UPDATE leaderboard SET score=? WHERE email=? AND date=?", (best_score, email, today))
                else:
                    c.execute("INSERT INTO leaderboard (email, score, date) VALUES (?, ?, ?)", (email, score, today))
                conn.commit()
            session["freeplay_unlocked"] = True
            return redirect(url_for("result"))

    # Load leaderboard
    entries = []
    user_email = session.get("email") or ""
    user_display_name = user_email.split("@")[0] if "@" in user_email else user_email
    today = datetime.date.today().isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT email, score FROM leaderboard WHERE date=? ORDER BY score DESC", (today,))
        for row in c.fetchall():
            display_name = row[0].split("@")[0] if "@" in row[0] else row[0]
            entries.append({"email": display_name, "score": row[1]})

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
    entries = []
    user_email = session.get("email") or ""
    user_display_name = user_email.split("@")[0] if "@" in user_email else user_email
    today = datetime.date.today().isoformat()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT email, score FROM leaderboard WHERE date=? ORDER BY score DESC", (today,))
        for row in c.fetchall():
            display_name = row[0].split("@")[0] if "@" in row[0] else row[0]
            entries.append({"email": display_name, "score": row[1]})
    return render_template("leaderboard.html", entries=entries, user_email=user_email, user_display_name=user_display_name)

# --- Freeplay routes omitted for brevity; same as before ---

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5010))
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
