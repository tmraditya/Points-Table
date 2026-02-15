import sys
# Force unbuffered output so logs show immediately on Render
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

"""
main_web.py — Flask-based scoreboard server for online hosting.

This is a hosted version of main.py that:
  1. Runs a Flask web server to serve the scoreboard HTML and generated image.
  2. Uses a background thread to regenerate the scoreboard image periodically.
  3. Serves everything from a single process — no separate static file server needed.

Usage:
  pip install flask Pillow requests
  python main_web.py

The scoreboard will be available at http://localhost:5000/
"""

import os
import time
import threading
import requests
from io import BytesIO
from flask import Flask, send_file, Response
from PIL import Image, ImageDraw, ImageFont

# --- Configuration ---
IMAGE_PATH = "zutsu cs  stream ptt@3x.png"
OUTPUT_PATH = "output_stream.png"
LOGO_DIR = "logos"       # Folder containing team logos as tag.png
LOGO_SIZE = 30           # Default logo width & height (square)

# Google Sheets API config
API_KEY = "AIzaSyCQsWb6Q1iAu4A9wcrA_oZKrJlzkGEs1NY"
SHEET_ID = "1XXQHJDiAoM0JPQGjVxrctFJNfCOrH0a-PC1wefCc9Q8"
RANGE = "RANKING!A5:K16"  # Rows 5–16 contain the 12 teams

# Column indices in the sheet row (0-based)
COL_TEAM_NAME = 3    # Column D
COL_LOGO_TAG = 4     # Column E  (used as logos/tag.png)
COL_MP = 5           # Column F
COL_BOOYAH = 6       # Column G
COL_ELIMS = 7        # Column H
COL_PLACE_PTS = 8    # Column I
COL_TOTAL = 10       # Column K

# --- Flask App ---
app = Flask(__name__)

# Get the directory where this script lives (for resolving relative paths)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Font Setup (Chakra Petch) ---
FONT_PATH = os.path.join(BASE_DIR, "ChakraPetch-Medium2.ttf")
FONT_BOLD_PATH = os.path.join(BASE_DIR, "ChakraPetch-Bold.ttf")
FONT_SIZE = 18

try:
    font = ImageFont.truetype(FONT_PATH, size=FONT_SIZE)
    font_bold = ImageFont.truetype(FONT_BOLD_PATH, size=FONT_SIZE)
except OSError:
    print(f"[WARNING] Could not load Chakra Petch fonts. Falling back to default.")
    font = ImageFont.load_default()
    font_bold = font

# Font cache for per-team sizes (populated on demand)
_font_cache = {}
_font_bold_cache = {}

def get_font(size):
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.truetype(FONT_PATH, size=size)
        except OSError:
            _font_cache[size] = font
    return _font_cache[size]

def get_font_bold(size):
    if size not in _font_bold_cache:
        try:
            _font_bold_cache[size] = ImageFont.truetype(FONT_BOLD_PATH, size=size)
        except OSError:
            _font_bold_cache[size] = font_bold
    return _font_bold_cache[size]

# --- Coordinates ---
ROW_LOGO_SIZE = 110
ROW_NAME_FS = 85
ROW_NUM_FS = 85

team_positions = [
    # ── Team 1 — large featured card (top-left) ──
    {"logo": (95, 195), "logo_size": 370, "logo_box": (638, 1348, 1200, 1735), "name_fs": 140, "num_fs": 105, "bold": True, "name": (235, 200), "name_box": (1501, 1313, 2745, 1537), "mp": (230, 265), "mp_box": (1466, 1619, 1713, 1744), "booyah": (290, 265), "booyah_box": (1714, 1619, 2003, 1744), "elims": (345, 265), "elims_box": (2004, 1619, 2221, 1744), "place": (385, 265), "place_box": (2222, 1619, 2440, 1744), "total": (420, 265), "total_box": (2513, 1619, 2756, 1744)},

    # ── Teams 2–5 — left-side rows ──
    {"logo": (465, 1974), "logo_size": ROW_LOGO_SIZE, "logo_box": (465, 1974, 613, 2120), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (614, 1974), "name_box": (614, 1974, 1464, 2120), "name_align": "left", "mp": (1589, 1974), "mp_box": (1465, 1974, 1714, 2120), "booyah": (1858, 1974), "booyah_box": (1716, 1974, 2000, 2120), "elims": (2110, 1974), "elims_box": (2001, 1974, 2220, 2120), "place": (2329, 1974), "place_box": (2221, 1974, 2438, 2120), "total": (2677, 1974), "total_box": (2590, 1974, 2765, 2120)},
    {"logo": (465, 2204), "logo_size": ROW_LOGO_SIZE, "logo_box": (465, 2204, 613, 2350), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (614, 2204), "name_box": (614, 2204, 1464, 2350), "name_align": "left", "mp": (1589, 2204), "mp_box": (1465, 2204, 1714, 2350), "booyah": (1858, 2204), "booyah_box": (1716, 2204, 2000, 2350), "elims": (2110, 2204), "elims_box": (2001, 2204, 2220, 2350), "place": (2329, 2204), "place_box": (2221, 2204, 2438, 2350), "total": (2677, 2204), "total_box": (2590, 2204, 2765, 2350)},
    {"logo": (465, 2434), "logo_size": ROW_LOGO_SIZE, "logo_box": (465, 2434, 613, 2580), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (614, 2434), "name_box": (614, 2434, 1464, 2580), "name_align": "left", "mp": (1589, 2434), "mp_box": (1465, 2434, 1714, 2580), "booyah": (1858, 2434), "booyah_box": (1716, 2434, 2000, 2580), "elims": (2110, 2434), "elims_box": (2001, 2434, 2220, 2580), "place": (2329, 2434), "place_box": (2221, 2434, 2438, 2580), "total": (2677, 2434), "total_box": (2590, 2434, 2765, 2580)},
    {"logo": (465, 2664), "logo_size": ROW_LOGO_SIZE, "logo_box": (465, 2664, 613, 2810), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (614, 2664), "name_box": (614, 2664, 1464, 2810), "name_align": "left", "mp": (1589, 2664), "mp_box": (1465, 2664, 1714, 2810), "booyah": (1858, 2664), "booyah_box": (1716, 2664, 2000, 2810), "elims": (2110, 2664), "elims_box": (2001, 2664, 2220, 2810), "place": (2329, 2664), "place_box": (2221, 2664, 2438, 2810), "total": (2677, 2664), "total_box": (2590, 2664, 2765, 2810)},

    # ── Teams 6–12 — right-side rows ──
    {"logo": (3221, 1306), "logo_size": ROW_LOGO_SIZE, "logo_box": (3221, 1306, 3361, 1445), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (3362, 1306), "name_box": (3362, 1306, 4158, 1445), "name_align": "left", "mp": (4283, 1306), "mp_box": (4159, 1306, 4408, 1445), "booyah": (4547, 1306), "booyah_box": (4409, 1306, 4686, 1445), "elims": (4799, 1306), "elims_box": (4687, 1306, 4911, 1445), "place": (5025, 1306), "place_box": (4912, 1306, 5138, 1445), "total": (5391, 1306), "total_box": (5302, 1306, 5480, 1445)},
    {"logo": (3221, 1531), "logo_size": ROW_LOGO_SIZE, "logo_box": (3221, 1531, 3361, 1670), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (3362, 1531), "name_box": (3362, 1531, 4158, 1670), "name_align": "left", "mp": (4283, 1531), "mp_box": (4159, 1531, 4408, 1670), "booyah": (4547, 1531), "booyah_box": (4409, 1531, 4686, 1670), "elims": (4799, 1531), "elims_box": (4687, 1531, 4911, 1670), "place": (5025, 1531), "place_box": (4912, 1531, 5138, 1670), "total": (5391, 1531), "total_box": (5302, 1531, 5480, 1670)},
    {"logo": (3221, 1756), "logo_size": ROW_LOGO_SIZE, "logo_box": (3221, 1756, 3361, 1895), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (3362, 1756), "name_box": (3362, 1756, 4158, 1895), "name_align": "left", "mp": (4283, 1756), "mp_box": (4159, 1756, 4408, 1895), "booyah": (4547, 1756), "booyah_box": (4409, 1756, 4686, 1895), "elims": (4799, 1756), "elims_box": (4687, 1756, 4911, 1895), "place": (5025, 1756), "place_box": (4912, 1756, 5138, 1895), "total": (5391, 1756), "total_box": (5302, 1756, 5480, 1895)},
    {"logo": (3221, 1981), "logo_size": ROW_LOGO_SIZE, "logo_box": (3221, 1981, 3361, 2120), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (3362, 1981), "name_box": (3362, 1981, 4158, 2120), "name_align": "left", "mp": (4283, 1981), "mp_box": (4159, 1981, 4408, 2120), "booyah": (4547, 1981), "booyah_box": (4409, 1981, 4686, 2120), "elims": (4799, 1981), "elims_box": (4687, 1981, 4911, 2120), "place": (5025, 1981), "place_box": (4912, 1981, 5138, 2120), "total": (5391, 1981), "total_box": (5302, 1981, 5480, 2120)},
    {"logo": (3221, 2206), "logo_size": ROW_LOGO_SIZE, "logo_box": (3221, 2206, 3361, 2345), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (3362, 2206), "name_box": (3362, 2206, 4158, 2345), "name_align": "left", "mp": (4283, 2206), "mp_box": (4159, 2206, 4408, 2345), "booyah": (4547, 2206), "booyah_box": (4409, 2206, 4686, 2345), "elims": (4799, 2206), "elims_box": (4687, 2206, 4911, 2345), "place": (5025, 2206), "place_box": (4912, 2206, 5138, 2345), "total": (5391, 2206), "total_box": (5302, 2206, 5480, 2345)},
    {"logo": (3221, 2431), "logo_size": ROW_LOGO_SIZE, "logo_box": (3221, 2431, 3361, 2570), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (3362, 2431), "name_box": (3362, 2431, 4158, 2570), "name_align": "left", "mp": (4283, 2431), "mp_box": (4159, 2431, 4408, 2570), "booyah": (4547, 2431), "booyah_box": (4409, 2431, 4686, 2570), "elims": (4799, 2431), "elims_box": (4687, 2431, 4911, 2570), "place": (5025, 2431), "place_box": (4912, 2431, 5138, 2570), "total": (5391, 2431), "total_box": (5302, 2431, 5480, 2570)},
    {"logo": (3221, 2656), "logo_size": ROW_LOGO_SIZE, "logo_box": (3221, 2656, 3361, 2795), "name_fs": ROW_NAME_FS, "num_fs": ROW_NUM_FS, "name": (3362, 2656), "name_box": (3362, 2656, 4158, 2795), "name_align": "left", "mp": (4283, 2656), "mp_box": (4159, 2656, 4408, 2795), "booyah": (4547, 2656), "booyah_box": (4409, 2656, 4686, 2795), "elims": (4799, 2656), "elims_box": (4687, 2656, 4911, 2795), "place": (5025, 2656), "place_box": (4912, 2656, 5138, 2795), "total": (5391, 2656), "total_box": (5302, 2656, 5480, 2795)},
]


def fetch_sheet_data():
    """Fetch team data from Google Sheets via GAPI REST API."""
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{RANGE}?key={API_KEY}"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    rows = data.get("values", [])

    teams = []
    for row in rows:
        padded = row + [""] * (11 - len(row))
        teams.append({
            "name":     padded[COL_TEAM_NAME],
            "logo_tag": padded[COL_LOGO_TAG],
            "mp":       padded[COL_MP],
            "booyah":   padded[COL_BOOYAH],
            "elims":    padded[COL_ELIMS],
            "place":    padded[COL_PLACE_PTS],
            "total":    padded[COL_TOTAL],
        })
    return teams


def draw_team(img, draw, pos, rank, team, text_color="black"):
    """Draw one team's logo and data at the specified coordinate positions."""
    tag = team.get("logo_tag", "").strip()
    if tag:
        # Case-insensitive logo lookup (Linux is case-sensitive unlike Windows)
        logos_dir = os.path.join(BASE_DIR, LOGO_DIR)
        logo_path = None
        if os.path.isdir(logos_dir):
            target = f"{tag}.png".lower()
            for f in os.listdir(logos_dir):
                if f.lower() == target:
                    logo_path = os.path.join(logos_dir, f)
                    break
        if logo_path and os.path.exists(logo_path):
            logo = Image.open(logo_path).convert("RGBA")
            if "logo_box" in pos:
                s = pos.get("logo_size", LOGO_SIZE)
                logo = logo.resize((s, s), Image.LANCZOS)
                bx1, by1, bx2, by2 = pos["logo_box"]
                box_w, box_h = bx2 - bx1, by2 - by1
                paste_x = bx1 + (box_w - s) // 2
                paste_y = by1 + (box_h - s) // 2
                img.paste(logo, (paste_x, paste_y), logo)
            else:
                s = pos.get("logo_size", LOGO_SIZE)
                logo = logo.resize((s, s), Image.LANCZOS)
                img.paste(logo, pos["logo"], logo)
        else:
            print(f"  [WARN] Logo not found: {logo_path}")

    nf = get_font_bold(pos.get("name_fs", FONT_SIZE))
    all_bold = pos.get("bold", False)
    nf_num = get_font_bold(pos.get("num_fs", FONT_SIZE)) if all_bold else get_font(pos.get("num_fs", FONT_SIZE))
    nf_num_b = get_font_bold(pos.get("num_fs", FONT_SIZE))

    if "name_box" in pos:
        x1, y1, x2, y2 = pos["name_box"]
        cy = (y1 + y2) / 2
        if pos.get("name_align") == "left":
            draw.text((x1, cy), team["name"], fill=text_color, font=nf, anchor="lm")
        else:
            cx = (x1 + x2) / 2
            draw.text((cx, cy), team["name"], fill=text_color, font=nf, anchor="mm")
    else:
        draw.text(pos["name"], team["name"], fill=text_color, font=nf)

    for key, fnt in [("mp", nf_num), ("booyah", nf_num), ("elims", nf_num), ("place", nf_num), ("total", nf_num_b)]:
        box_key = f"{key}_box"
        if box_key in pos:
            x1, y1, x2, y2 = pos[box_key]
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            draw.text((cx, cy), team[key], fill=text_color, font=fnt, anchor="mm")
        else:
            draw.text(pos[key], team[key], fill=text_color, font=fnt)


# Store the last error for the /debug route
_last_error = None

def generate_scoreboard():
    """Generate the scoreboard image and save it to OUTPUT_PATH."""
    global _last_error
    try:
        print("Fetching data from Google Sheets...")
        teams = fetch_sheet_data()
        print(f"Loaded {len(teams)} teams.")

        template_path = os.path.join(BASE_DIR, IMAGE_PATH)
        print(f"Looking for template at: {template_path}")
        print(f"Template exists: {os.path.exists(template_path)}")
        if os.path.exists(template_path):
            img = Image.open(template_path).convert("RGBA")
        else:
            print(f"[WARNING] Template not found: {template_path} — using transparent canvas.")
            img = Image.new("RGBA", (876, 492), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        for i, team in enumerate(teams):
            if i >= len(team_positions):
                break
            draw_team(img, draw, team_positions[i], i + 1, team)

        output_path = os.path.join(BASE_DIR, OUTPUT_PATH)
        temp_path = output_path + ".tmp"
        img.save(temp_path, format="PNG")
        os.replace(temp_path, output_path)
        print(f"Scoreboard saved to: {output_path}")
        _last_error = None
    except Exception as e:
        _last_error = str(e)
        print(f"[ERROR in generate_scoreboard] {e}")
        import traceback
        traceback.print_exc()
        raise


# --- Background Thread for Image Generation ---
POLLING_INTERVAL = 10  # seconds between each refresh

def scoreboard_loop():
    """Continuously regenerate the scoreboard image in the background."""
    print(f"[BG] Scoreboard loop started (refresh every {POLLING_INTERVAL}s)")
    while True:
        try:
            generate_scoreboard()
        except Exception as e:
            print(f"[ERROR] {e}")
        time.sleep(POLLING_INTERVAL)


# --- Flask Routes ---

@app.route("/")
def index():
    """Serve the scoreboard HTML page."""
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Live Scoreboard</title>
<style>
  * { margin: 0; padding: 0; }
  body { background: transparent; overflow: hidden; }
  img {
    position: absolute;
    top: 0; left: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
</style>
</head>
<body>
  <img id="scoreboard" src="/scoreboard.png" />
  <script>
    const img = document.getElementById('scoreboard');
    // Reload the image every 5 seconds with a cache-busting param
    setInterval(() => {
      const newImg = new Image();
      newImg.onload = () => {
        img.src = newImg.src;
      };
      newImg.src = '/scoreboard.png?t=' + Date.now();
    }, 3000);
  </script>
</body>
</html>"""


@app.route("/debug")
def debug_info():
    """Show diagnostic info to troubleshoot deployment issues."""
    files = os.listdir(BASE_DIR)
    output_path = os.path.join(BASE_DIR, OUTPUT_PATH)
    template_path = os.path.join(BASE_DIR, IMAGE_PATH)
    logos_path = os.path.join(BASE_DIR, LOGO_DIR)
    logo_files = os.listdir(logos_path) if os.path.isdir(logos_path) else ["FOLDER NOT FOUND"]
    info = {
        "base_dir": BASE_DIR,
        "all_files": files,
        "template_exists": os.path.exists(template_path),
        "template_path": template_path,
        "output_exists": os.path.exists(output_path),
        "output_path": output_path,
        "font_exists": os.path.exists(FONT_PATH),
        "font_bold_exists": os.path.exists(FONT_BOLD_PATH),
        "logos_folder": logo_files,
        "last_error": _last_error,
    }
    import json
    return Response(json.dumps(info, indent=2), mimetype="application/json")


@app.route("/scoreboard.png")
def scoreboard_image():
    """Serve the latest generated scoreboard image."""
    output_path = os.path.join(BASE_DIR, OUTPUT_PATH)
    if os.path.exists(output_path):
        return send_file(output_path, mimetype="image/png")
    else:
        # Return a 1x1 transparent PNG as placeholder
        return Response(b"", status=404, mimetype="text/plain")


# --- Entry Point ---
if __name__ == "__main__":
    # Print startup diagnostics
    print(f"=== STARTUP DIAGNOSTICS ===")
    print(f"BASE_DIR: {BASE_DIR}")
    print(f"Files in BASE_DIR: {os.listdir(BASE_DIR)}")
    print(f"Template exists: {os.path.exists(os.path.join(BASE_DIR, IMAGE_PATH))}")
    print(f"Font exists: {os.path.exists(FONT_PATH)}")
    print(f"Font bold exists: {os.path.exists(FONT_BOLD_PATH)}")
    print(f"===========================")

    # Generate the first scoreboard immediately before starting the server
    print("Generating initial scoreboard...")
    try:
        generate_scoreboard()
    except Exception as e:
        print(f"[WARNING] Initial generation failed: {e}")
        import traceback
        traceback.print_exc()

    # Start the background thread for periodic regeneration
    bg_thread = threading.Thread(target=scoreboard_loop, daemon=True)
    bg_thread.start()

    # Get port from environment variable (hosting platforms set this)
    port = int(os.environ.get("PORT", 5000))
    print(f"\n=== Scoreboard server running at http://localhost:{port}/ ===\n")
    app.run(host="0.0.0.0", port=port, debug=False)
