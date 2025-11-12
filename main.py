from flask import Flask, render_template, request, session, redirect, url_for
import random, math, csv, os, json, datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"

GOOGLE_API_KEY = "AIzaSyAQI6vnKW5-8lH24bGygQ7eNhPM79677ps"

# Load Street View locations from JSON
with open("streetview_locations.json", "r", encoding="utf-8") as f:
    ALL_LOCATIONS = json.load(f)

def haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

@app.before_request
def setup_game():
    today = datetime.date.today().isoformat()
    if session.get("last_played_date") != today:
        session.clear()
        session["score"] = 0
        session["round"] = 1
        session["results"] = []
        session["game_locations"] = get_daily_locations()  # shared for everyone
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

    # SEO data
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
    actual_lat = session.get("actual_lat")
    actual_lon = session.get("actual_lon")
    round_num = session.get("round", 1)
    score = session.get("score", 0)

    # Calculate distance & score
    distance_km = round(haversine(actual_lat, actual_lon, guessed_lat, session.get("actual_lon")), 1)
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
        "guessed_lon": float(request.form.get("lon")),
        "actual_lat": actual_lat,
        "actual_lon": actual_lon
    })
    session["results"] = results
    session["score"] = score
    session["round"] = round_num + 1

    # Redirect to round result page
    if round_num >= 5:
        return redirect(url_for("result_result"))  # Last round, go to final results
    else:
        return redirect(url_for("round_result"))  # Show round result first

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
        api_key=GOOGLE_API_KEY  # make sure this is passed
    )



@app.route("/result", methods=["GET", "POST"])
def result():
    results = session.get("results", [])
    score = session.get("score", 0)

    if not results:
        return redirect(url_for("index"))

    # Build simplified share text (emoji bars + total score)
    share_lines = ["🌎 GeoGuesser Results"]
    for r in results:
        share_lines.append(r["bar"])
    share_lines.append(f"🏁 Total Score: {score}")
    share_text = "\n".join(share_lines)

    if request.method == "POST":
        email = request.form.get("email")
        if email:
            today = datetime.date.today().isoformat()
            filename = f"leaderboard_{today}.csv"

            # Read existing entries
            entries = {}
            if os.path.isfile(filename):
                with open(filename, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        entries[row["email"]] = int(row["score"])

            # Only keep highest score
            entries[email] = max(entries.get(email, 0), score)

            # Write back
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["email", "score"])
                writer.writeheader()
                for e, s in entries.items():
                    writer.writerow({"email": e, "score": s})

            return redirect(url_for("leaderboard"))

    # SEO data for results page
    seo_title = "SightCr - See Your Virtual Travel Results & Share Your Score"
    seo_description = "Check your scores in SightCr, the virtual travel game! Share your results, see how far your guesses were, and challenge friends to explore the world."
    seo_keywords = "travel game results, geography quiz results, virtual travel score, SightCr leaderboard, explore world, online travel game"

    return render_template(
        "final_results.html",
        score=score,
        share_text=share_text,
        seo_title=seo_title,
        seo_description=seo_description,
        seo_keywords=seo_keywords
    )

@app.route("/leaderboard")
def leaderboard():
    today = datetime.date.today().isoformat()
    filename = f"leaderboard_{today}.csv"
    entries = []

    if os.path.isfile(filename):
        with open(filename, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entries.append({"email": row["email"], "score": int(row["score"])})

    entries.sort(key=lambda x: x["score"], reverse=True)

    return render_template(
        "leaderboard.html",
        entries=entries,
        seo_title="SightCr Leaderboard - See Top Global Explorers",
        seo_description="View today's top scores in SightCr!",
        seo_keywords="SightCr leaderboard, geography game scores"
    )


@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-Agent: *",
        "Disallow:",  # allow all pages
        "Sitemap: https://yourdomain.com/sitemap.xml"  # 👈 replace with your real domain
    ]
    return "\n".join(lines), 200, {"Content-Type": "text/plain"}

@app.route("/sitemap.xml")
def sitemap():
    pages = []

    # Add static routes (you can add more)
    static_routes = ["index", "leaderboard", "result"]
    for route in static_routes:
        url = url_for(route, _external=True)
        pages.append(f"<url><loc>{url}</loc></url>")

    # Optional: add last modified date
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{''.join(pages)}
</urlset>"""

    return xml, 200, {"Content-Type": "application/xml"}



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5010))
    app.run(host="0.0.0.0", port=port, debug=True)
