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
    """Reset daily game if first visit today"""
    today = datetime.date.today().isoformat()
    if session.get("last_played_date") != today:
        session.clear()
        session["score"] = 0
        session["round"] = 1
        session["results"] = []
        session["game_locations"] = random.sample(ALL_LOCATIONS, 5)
        session["last_played_date"] = today
        session["instructions_shown"] = False  # Add instructions flag

@app.route("/instructions_shown", methods=["POST"])
def instructions_shown():
    session["instructions_shown"] = True
    return "", 204

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

    return render_template(
        "index.html",
        lat=loc["lat"],
        lon=loc["lon"],
        heading=loc.get("heading", 0),
        api_key=GOOGLE_API_KEY,
        round=round_num,
        score=score,
        show_instructions=show_instructions
    )

@app.route("/guess", methods=["POST"])
def guess():
    guessed_lat = float(request.form.get("lat"))
    guessed_lon = float(request.form.get("lon"))

    actual_lat = session.get("actual_lat")
    actual_lon = session.get("actual_lon")
    round_num = session.get("round", 1)
    score = session.get("score", 0)

    # Calculate distance
    distance_km = round(haversine(actual_lat, actual_lon, guessed_lat, guessed_lon), 1)
    distance_mi = round(distance_km * 0.621371, 1)

    # Scoring
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

    # Store round result
    results = session.get("results", [])
    results.append({
        "round": round_num,
        "bar": bar,
        "distance_km": distance_km,
        "distance_mi": distance_mi,
        "round_score": round_score,
        "guessed_lat": guessed_lat,
        "guessed_lon": guessed_lon,
        "actual_lat": actual_lat,
        "actual_lon": actual_lon
    })
    session["results"] = results
    session["score"] = score
    session["round"] = round_num + 1

    return redirect(url_for("result"))

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
            file_exists = os.path.isfile("leaderboard.csv")
            with open("leaderboard.csv", "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["email", "score"])
                if not file_exists:
                    writer.writeheader()
                writer.writerow({"email": email, "score": score})
            return redirect(url_for("leaderboard"))

    return render_template("final_results.html", score=score, share_text=share_text)

@app.route("/next")
def next_round():
    round_num = session.get("round", 1)
    if round_num > 5:
        return redirect(url_for("result"))
    return redirect(url_for("index"))

@app.route("/leaderboard")
def leaderboard():
    entries = []
    if os.path.isfile("leaderboard.csv"):
        with open("leaderboard.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entries.append({"email": row["email"], "score": int(row["score"])})
    entries.sort(key=lambda x: x["score"], reverse=True)
    return render_template("leaderboard.html", entries=entries)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5010))
    app.run(host="0.0.0.0", port=port, debug=True)
