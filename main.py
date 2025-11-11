from flask import Flask, render_template, request, session, redirect, url_for
import random, math, csv, os

app = Flask(__name__)
app.secret_key = "supersecretkey"

GOOGLE_API_KEY = "AIzaSyAQI6vnKW5-8lH24bGygQ7eNhPM79677ps"

# Hardcoded locations with guaranteed Street View
LOCATIONS = [
    ("Eiffel Tower, Paris", 48.8584, 2.2945),
    ("Tokyo Tower, Tokyo", 35.6586, 139.7454),
    ("Times Square, New York", 40.7580, -73.9855),
    ("Big Ben, London", 51.5007, -0.1246),
    ("Golden Gate Bridge, San Francisco", 37.8199, -122.4783)
]

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

@app.route("/")
def index():
    round_num = session.get("round", 1)
    score = session.get("score", 0)
    used_locations = session.get("used_locations", [])

    if round_num > 5:
        return redirect(url_for("email_submit"))

    # Filter out already-used locations
    available_locations = [loc for loc in LOCATIONS if loc[0] not in used_locations]

    # If all locations used, reset (or end game)
    if not available_locations:
        available_locations = LOCATIONS.copy()
        used_locations = []

    location = random.choice(available_locations)
    name, lat, lon = location
    heading = random.randint(0, 360)

    # Update session data
    used_locations.append(name)
    session["used_locations"] = used_locations
    session["actual_name"] = name
    session["actual_lat"] = lat
    session["actual_lon"] = lon
    session["round"] = round_num
    session["score"] = score

    return render_template(
        "index.html",
        lat=lat,
        lon=lon,
        heading=heading,
        api_key=GOOGLE_API_KEY,
        round=round_num,
        score=score
    )


@app.route("/guess", methods=["POST"])
def guess():
    guessed_lat = float(request.form.get("lat"))
    guessed_lon = float(request.form.get("lon"))

    actual_lat = session.get("actual_lat")
    actual_lon = session.get("actual_lon")
    actual_name = session.get("actual_name")

    round_num = session.get("round", 1)
    score = session.get("score", 0)

    distance = haversine(actual_lat, actual_lon, guessed_lat, guessed_lon)
    round_score = max(0, int(1000 - distance))
    score += round_score

    session["score"] = score
    session["round"] = round_num + 1

    return render_template(
        "result.html",
        guessed_lat=guessed_lat,
        guessed_lon=guessed_lon,
        actual_lat=actual_lat,
        actual_lon=actual_lon,
        distance=distance,
        round_score=round_score,
        score=score,
        round=round_num,
        api_key=GOOGLE_API_KEY
    )

@app.route("/next")
def next_round():
    round_num = session.get("round", 1)
    if round_num > 5:
        return redirect(url_for("email_submit"))
    return redirect(url_for("index"))

@app.route("/email", methods=["GET", "POST"])
def email_submit():
    if request.method == "POST":
        email = request.form.get("email")
        score = session.get("score", 0)
        file_exists = os.path.isfile("leaderboard.csv")
        with open("leaderboard.csv", "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["email","score"])
            writer.writerow([email, score])
        session["round"] = 1
        session["score"] = 0
        return redirect(url_for("leaderboard"))

    return render_template("email_submit.html", score=session.get("score", 0))

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

#if __name__ == "__main__":
#    app.run(debug=True, port=5010)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5010))
    app.run(host="0.0.0.0", port=port, debug=True)
