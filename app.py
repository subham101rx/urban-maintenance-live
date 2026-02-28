from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
import os
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import requests 



app = Flask(__name__)
app.secret_key = "supersecretkey"

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ---------------- DATABASE ----------------
def get_db():
    return sqlite3.connect("database.db", timeout=10)

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            password TEXT,
            role TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            state TEXT,
            district TEXT,
            city TEXT,
            issue_type TEXT,
            severity TEXT,
            description TEXT,
            image TEXT,
            department TEXT,
            priority TEXT,
            status TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- IMAGE AI ----------------
def analyze_image(image_path):
    try:
        image = Image.open(image_path)
        image = image.resize((200, 200))
        pixels = list(image.getdata())

        total_pixels = len(pixels)

        r_total = sum(p[0] for p in pixels)
        g_total = sum(p[1] for p in pixels)
        b_total = sum(p[2] for p in pixels)

        r = r_total / total_pixels
        g = g_total / total_pixels
        b = b_total / total_pixels

        if b > 130 and g > 120:
            return "Drainage", "High"
        elif r > 140 and g > 140 and b < 100:
            return "Electrical", "Critical"
        elif r < 80 and g < 80 and b < 80:
            return "Road", "High"
        else:
            return None, None

    except:
        return None, None

# ---------------- TEXT AI ----------------
def analyze_text(description):
    text = description.lower()

    if any(word in text for word in ["flood", "overflow", "fire", "live wire", "collapsed"]):
        severity = "Critical"
    elif any(word in text for word in ["blocked", "danger", "broken", "damaged"]):
        severity = "High"
    elif any(word in text for word in ["minor", "slow", "leak"]):
        severity = "Medium"
    else:
        severity = "Low"

    if any(word in text for word in ["road", "pothole", "crack"]):
        issue_type = "Road"
    elif any(word in text for word in ["drain", "water", "flood"]):
        issue_type = "Drainage"
    elif any(word in text for word in ["light", "electric", "wire"]):
        issue_type = "Electrical"
    elif any(word in text for word in ["garbage", "waste", "dirty"]):
        issue_type = "Sanitation"
    else:
        issue_type = "Sanitation"

    return issue_type, severity

# ---------------- GPS EXTRACTION ----------------
def extract_gps(image_path):
    try:
        image = Image.open(image_path)
        exif_data = image._getexif()
        if not exif_data:
            return None

        gps_info = {}
        for tag, value in exif_data.items():
            tag_name = TAGS.get(tag)
            if tag_name == "GPSInfo":
                for key in value:
                    decode = GPSTAGS.get(key)
                    gps_info[decode] = value[key]

        if "GPSLatitude" in gps_info and "GPSLongitude" in gps_info:

            def convert(coord):
                d = coord[0][0] / coord[0][1]
                m = coord[1][0] / coord[1][1]
                s = coord[2][0] / coord[2][1]
                return d + (m / 60.0) + (s / 3600.0)

            lat = convert(gps_info["GPSLatitude"])
            lon = convert(gps_info["GPSLongitude"])
            return lat, lon

        return None
    except:
        return None

# ---------------- REVERSE GEOCODE ----------------
def reverse_geocode(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}"
        response = requests.get(url, headers={"User-Agent": "urban-system"})
        data = response.json()
        address = data.get("address", {})
        state = address.get("state", "")
        district = address.get("county", "")
        city = address.get("city", address.get("town", address.get("village", "")))
        return state, district, city
    except:
        return "", "", ""

# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("home.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (request.form["username"], request.form["password"], request.form["role"])
        )
        conn.commit()
        conn.close()
        return redirect("/login")
    return render_template("register.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (request.form["username"], request.form["password"])
        )
        user = cursor.fetchone()
        conn.close()

        if user:
            session["user_id"] = user[0]
            session["username"] = user[1]
            session["role"] = user[3]
            if user[3] == "citizen":
                return redirect("/citizen_dashboard")
            else:
                return redirect("/employee_dashboard")

        return "Invalid Login"

    return render_template("login.html")

# ---------------- CITIZEN DASHBOARD ----------------
@app.route("/citizen_dashboard", methods=["GET", "POST"])
def citizen_dashboard():

    if session.get("role") != "citizen":
        return redirect("/login")

    if request.method == "POST":

        image_file = request.files.get("image")
        description = request.form.get("description")
        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")

        state = ""
        district = ""
        city = ""
        filename = ""

        issue_type = None
        severity = None

        if image_file and image_file.filename != "":
            filename = image_file.filename
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image_file.save(filepath)

            gps = extract_gps(filepath)

            if gps:
                state, district, city = reverse_geocode(gps[0], gps[1])

            if not state and latitude and longitude:
                state, district, city = reverse_geocode(latitude, longitude)

            issue_type, severity = analyze_image(filepath)

        if not issue_type:
            if latitude and longitude and not state:
                state, district, city = reverse_geocode(latitude, longitude)

            issue_type, severity = analyze_text(description)

        department = issue_type + " Department"
        priority = severity

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO complaints
            (user_id, state, district, city, issue_type, severity, description, image, department, priority, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session["user_id"],
            state,
            district,
            city,
            issue_type,
            severity,
            description,
            filename,
            department,
            priority,
            "Pending"
        ))

        conn.commit()
        conn.close()

        return redirect("/citizen_dashboard")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, state, district, city, issue_type, severity, priority, status, image
        FROM complaints
        WHERE user_id=?
    """, (session["user_id"],))

    complaints = cursor.fetchall()
    conn.close()

    return render_template("citizen_dashboard.html", complaints=complaints)

# ---------------- EMPLOYEE DASHBOARD ----------------
@app.route("/employee_dashboard", methods=["GET", "POST"])
def employee_dashboard():

    if session.get("role") != "employee":
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()

    if request.method == "POST":
        cursor.execute(
            "UPDATE complaints SET status=? WHERE id=?",
            (request.form["new_status"], request.form["complaint_id"])
        )
        conn.commit()

    cursor.execute("""
        SELECT id, state, district, city, issue_type, severity, priority, status, image
        FROM complaints
        ORDER BY 
            CASE severity
                WHEN 'Critical' THEN 4
                WHEN 'High' THEN 3
                WHEN 'Medium' THEN 2
                WHEN 'Low' THEN 1
                ELSE 0
            END DESC,
            id DESC
    """)

    complaints = cursor.fetchall()
    conn.close()

    return render_template("employee_dashboard.html", complaints=complaints)

# ---------------- LIVE API ----------------
@app.route("/get_complaints")
def get_complaints():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, state, district, city, issue_type, severity, priority, status
        FROM complaints
        ORDER BY 
            CASE severity
                WHEN 'Critical' THEN 4
                WHEN 'High' THEN 3
                WHEN 'Medium' THEN 2
                WHEN 'Low' THEN 1
                ELSE 0
            END DESC,
            id DESC
    """)

    complaints = cursor.fetchall()
    conn.close()

    return jsonify(complaints)

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)