import json
import os
import re
import sqlite3
import sys
import types
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

if "cgi" not in sys.modules:
    cgi_module = types.ModuleType("cgi")

    def parse_header(line):
        parts = [part.strip() for part in line.split(";")]
        key = parts[0]
        params = {}

        for part in parts[1:]:
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            params[name.strip().lower()] = value.strip().strip("\"")

        return key, params

    cgi_module.parse_header = parse_header
    sys.modules["cgi"] = cgi_module

try:
    from googletrans import Translator
except Exception:
    Translator = None


BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

IS_VERCEL = os.environ.get("VERCEL") == "1"
DEFAULT_DATA_DIR = Path("/tmp/flashwordses") if IS_VERCEL else BASE_DIR
DATA_DIR = Path(os.environ.get("DATA_DIR", str(DEFAULT_DATA_DIR))).resolve()
DATA_FILE = Path(__file__).with_name("data.json")
DB_FILE = Path(os.environ.get("DB_PATH", str(DATA_DIR / "app.db"))).resolve()
translator = Translator() if Translator else None


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    global DB_FILE

    def _init_at(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS words (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              spanish TEXT NOT NULL,
              spanish_norm TEXT NOT NULL,
              translation TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
              UNIQUE(user_id, spanish_norm)
            )
            """
        )
        conn.commit()
        conn.close()

    try:
        _init_at(DB_FILE)
    except (OSError, sqlite3.OperationalError):
        # Vercel Serverless Functions filesystem is read-only except /tmp.
        # If DB_PATH isn't explicitly set, fall back automatically.
        if IS_VERCEL and os.environ.get("DB_PATH") is None:
            DB_FILE = Path("/tmp/flashwordses/app.db")
            _init_at(DB_FILE)
        else:
            raise


init_db()


def normalize_spanish(text):
    return text.strip().casefold()


def contains_digits(text):
    return bool(re.search(r"\d", text))


def translate_word(spanish, target_language):
    if target_language not in {"en", "uk"}:
        target_language = "en"

    if translator is None:
        return None

    try:
        result = translator.translate(spanish, src="es", dest=target_language)
        return result.text
    except Exception:
        return None


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    with get_db() as conn:
        row = conn.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            session.pop("user_id", None)
            return None
        return {"id": row["id"], "username": row["username"]}


def login_required_json(fn):
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401
        return fn(user, *args, **kwargs)

    wrapper.__name__ = fn.__name__
    return wrapper


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


@app.route("/")
def home():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    return render_template("index.html", username=user["username"])


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if get_current_user():
            return redirect(url_for("home"))
        return render_template("login.html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not username or not password:
        return render_template("login.html", error="Username and password are required."), 400

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if not row or not check_password_hash(row["password_hash"], password):
        return render_template("login.html", error="Invalid username or password."), 401

    session["user_id"] = row["id"]
    return redirect(url_for("home"))


def _maybe_import_legacy_words_for_user(user_id: int):
    # Small convenience: if this project previously used data.json,
    # import those words into the first registered user's account.
    if not DATA_FILE.exists():
        return

    with get_db() as conn:
        any_words = conn.execute("SELECT 1 FROM words LIMIT 1").fetchone()
        if any_words:
            return

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            legacy = json.load(file)
    except Exception:
        return

    if not isinstance(legacy, list):
        return

    to_insert = []
    for item in legacy:
        if not isinstance(item, dict):
            continue
        spanish = (item.get("spanish") or "").strip()
        translation = (item.get("translation") or "").strip()
        if not spanish or not translation:
            continue
        to_insert.append((user_id, spanish, normalize_spanish(spanish), translation))

    if not to_insert:
        return

    with get_db() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO words (user_id, spanish, spanish_norm, translation)
            VALUES (?, ?, ?, ?)
            """,
            to_insert,
        )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        if get_current_user():
            return redirect(url_for("home"))
        return render_template("register.html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""

    if not username or not password or not password2:
        return render_template("register.html", error="All fields are required."), 400

    if " " in username:
        return render_template("register.html", error="Username cannot contain spaces."), 400

    if len(password) < 6:
        return render_template("register.html", error="Password must be at least 6 characters."), 400

    if password != password2:
        return render_template("register.html", error="Passwords do not match."), 400

    password_hash = generate_password_hash(password)

    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return render_template("register.html", error="This username is already taken."), 400

    session["user_id"] = user_id
    _maybe_import_legacy_words_for_user(user_id)
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/words", methods=["GET"])
@login_required_json
def get_words(user):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, spanish, translation FROM words WHERE user_id = ? ORDER BY id ASC",
            (user["id"],),
        ).fetchall()
    return jsonify([{"id": row["id"], "spanish": row["spanish"], "translation": row["translation"]} for row in rows])


@app.route("/words", methods=["POST"])
@login_required_json
def add_word(user):
    data = request.get_json(silent=True) or {}
    spanish = (data.get("spanish") or "").strip()
    translation = (data.get("translation") or "").strip()
    target_language = (data.get("target_language") or "en").strip().lower()

    if not spanish:
        return jsonify({"error": "Field 'spanish' is required."}), 400

    if contains_digits(spanish):
        return jsonify({"error": "Spanish word cannot contain numbers."}), 400

    if translation and contains_digits(translation):
        return jsonify({"error": "Translation cannot contain numbers."}), 400

    if not translation:
        translation = translate_word(spanish, target_language)
        if not translation:
            return (
                jsonify({"error": "Translation is required (auto-translation is disabled)."}),
                400,
            )

    spanish_norm = normalize_spanish(spanish)
    try:
        with get_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO words (user_id, spanish, spanish_norm, translation)
                VALUES (?, ?, ?, ?)
                """,
                (user["id"], spanish, spanish_norm, translation),
            )
            word_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "This word already exists."}), 400

    new_word = {"id": word_id, "spanish": spanish, "translation": translation}
    return jsonify(new_word), 201


@app.route("/import", methods=["POST"])
@login_required_json
def import_words(user):
    items = request.get_json(silent=True)

    if not isinstance(items, list):
        return jsonify({"error": "JSON list is required."}), 400

    added_count = 0
    to_insert = []

    for item in items:
        if not isinstance(item, dict):
            continue

        spanish = (item.get("spanish") or "").strip()
        translation = (item.get("translation") or "").strip()
        target_language = (item.get("target_language") or "en").strip().lower()

        if not spanish:
            continue

        if contains_digits(spanish):
            continue

        if translation and contains_digits(translation):
            continue

        if not translation:
            translation = translate_word(spanish, target_language)
            if not translation:
                continue

        to_insert.append((user["id"], spanish, normalize_spanish(spanish), translation))

    if to_insert:
        with get_db() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO words (user_id, spanish, spanish_norm, translation)
                VALUES (?, ?, ?, ?)
                """,
                to_insert,
            )
            added_count = conn.total_changes - before

    return jsonify({"status": "success", "count": added_count}), 201


@app.route("/words/<int:word_id>", methods=["DELETE"])
@login_required_json
def delete_word(user, word_id):
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM words WHERE id = ? AND user_id = ?",
            (word_id, user["id"]),
        )

    if cur.rowcount == 0:
        return jsonify({"error": "Word not found."}), 404

    return jsonify({"message": "Word deleted."})


@app.route("/words", methods=["OPTIONS"])
@app.route("/import", methods=["OPTIONS"])
@app.route("/words/<int:word_id>", methods=["OPTIONS"])
def options_words(word_id=None):
    return "", 204


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host=host, port=port, debug=debug)
