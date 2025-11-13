from flask import Flask, render_template, request, session, redirect, url_for
import random, math, csv, os, json, datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"

GOOGLE_API_KEY = "AIzaSyAQI6vnKW5-8lH24bGygQ7eNhPM79677ps"

# Load Street View locations
with open("streetview_locations.json", "r", encoding="utf-8") as f:
    ALL_LOCATIONS = json.load(f)


def get_daily_locations():
    """Return 5 deterministic locations shared by all users for the day."""
    today = datetime.date.today().isoformat()
    random.seed(today)
    return random.sample(ALL_LOCATIONS, 5)


def haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


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


@app.route("/")
def index():
    round_num = session.get("round", 1)
    score = session.get("score", 0)

    if round_num > 5:
        return redirect(url_for("result"))

    loc = session["game_locations"][round_num - 1]
    session["actual_lat"] = loc["lat"]
    session["actual_lon"] = loc["lon"]
    session["heading"] = loc.get("heading", 0)
    show_instructions = not session.get("instructions_shown", False)

    seo_title = "GeoGuesser - Play the Ultimate Travel Quiz Game"
    seo_description = "Guess locations around the world and test your geography skills with GeoGuesser. Travel virtually and challenge yourself!"
    seo_keywords = "travel game, geography quiz, world map game, virtual travel game, learn geography, travel challenge, GeoGuesser"

    return render_template(
        "index.html",
        lat=loc["lat"],
        lon=loc["lon"],
        heading=loc.get("heading", 0),
        api_key=GOOGLE_API_KEY,
        round=round_num,
        score=score,
        show_instructions=show_instructions,
        seo_title=seo_title,
        seo_description=seo_description,
        seo_keywords=seo_keywords
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

    # Distance & score
    distance_km = round(haversine(actual_lat, actual_lon, guessed_lat, guessed_lon), 1)
    round_score = max(0, int(1000 - distance_km))
    score += round_score

    # Distance bar
    if distance_km < 5:
        bar = "📍🟩📍"
    elif distance_km < 50:
        bar = "📍🟨📍"
    elif distance_km < 500:
        bar = "📍🟧📍"
    else:
        bar = "📍🟥📍"

    # Store result
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
    return render_template(
        "round_result.html",
        result=last_result,
        score=score,
        round=round_num,
        api_key=GOOGLE_API_KEY
    )


@app.route("/result", methods=["GET", "POST"])
def result():
    results = session.get("results", [])
    score = session.get("score", 0)

    if not results:
        return redirect(url_for("index"))

    share_lines = ["🌎 GeoGuesser Results"]
    for r in results:
        share_lines.append(r["bar"])
    share_lines.append(f"🏁 Total Score: {score}")
    share_text = "\n".join(share_lines)

    # Handle email submission for leaderboard
    if request.method == "POST":
        email = request.form.get("email")
        if email:
            session["email"] = email
            today = datetime.date.today().isoformat()
            filename = f"leaderboard_{today}.csv"

            entries_dict = {}
            if os.path.isfile(filename):
                with open(filename, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        entries_dict[row["email"]] = int(row["score"])

            # Keep the highest score
            entries_dict[email] = max(entries_dict.get(email, 0), score)

            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["email", "score"])
                writer.writeheader()
                for e, s in entries_dict.items():
                    writer.writerow({"email": e, "score": s})

            session["freeplay_unlocked"] = True
            return redirect(url_for("result"))

    # Check if freeplay is unlocked
    score_submitted = session.get("freeplay_unlocked", False)

    # Load today's leaderboard
    today = datetime.date.today().isoformat()
    filename = f"leaderboard_{today}.csv"
    entries = []
    user_email = session.get("email")
    if os.path.isfile(filename):
        with open(filename, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entries.append({"email": row["email"], "score": int(row["score"])})

    # Sort descending by score
    entries.sort(key=lambda x: x["score"], reverse=True)

    return render_template(
        "result.html",  # Use the new combined template
        score=score,
        results=results,
        share_text=share_text,
        entries=entries,
        user_email=user_email,
        freeplay_unlocked=score_submitted
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
    """Free play mode — only unlocked after leaderboard submission."""
    if not session.get("freeplay_unlocked"):
        return redirect(url_for("result"))

    recent = session.get("freeplay_recent", [])

    # Filter locations that haven't been recently used
    available = [loc for loc in ALL_LOCATIONS if loc not in recent]
    if not available:
        # Reset if all locations have been used
        available = ALL_LOCATIONS
        recent = []

    loc = random.choice(available)

    # Update session
    recent.append(loc)
    session["freeplay_recent"] = recent[-10:]  # keep last 10 used

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

    return render_template(
        "freeplay_result.html",
        guessed_lat=guessed_lat,
        guessed_lon=guessed_lon,
        actual_lat=actual_lat,
        actual_lon=actual_lon,
        distance_km=distance_km,
        distance_mi=distance_mi,
        bar=bar,
        api_key=GOOGLE_API_KEY
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
