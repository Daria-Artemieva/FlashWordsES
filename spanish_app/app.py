import json
import os
import re
import sqlite3
import sys
import types
from pathlib import Path

from flask import Flask, jsonify, render_template, request

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

IS_VERCEL = os.environ.get("VERCEL") == "1"
DATABASE_URL = os.environ.get("DATABASE_URL")
USING_POSTGRES = bool(DATABASE_URL)
DEFAULT_DATA_DIR = Path("/tmp/flashwordses") if IS_VERCEL else BASE_DIR
DATA_DIR = Path(os.environ.get("DATA_DIR", str(DEFAULT_DATA_DIR))).resolve()
DATA_FILE = Path(__file__).with_name("data.json")
DB_FILE = Path(os.environ.get("DB_PATH", str(DATA_DIR / "app.db"))).resolve()
translator = Translator() if Translator else None


def get_db():
    if USING_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

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
            CREATE TABLE IF NOT EXISTS public_words (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              spanish TEXT NOT NULL,
              spanish_norm TEXT NOT NULL,
              translation TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE(spanish_norm)
            )
            """
        )
        conn.commit()
        conn.close()

    def _init_postgres():
        with get_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public_words (
                  id BIGSERIAL PRIMARY KEY,
                  spanish TEXT NOT NULL,
                  spanish_norm TEXT NOT NULL,
                  translation TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  UNIQUE(spanish_norm)
                )
                """
            )

    if USING_POSTGRES:
        _init_postgres()
        return

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


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"

    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/words", methods=["GET"])
def get_words():
    with get_db() as conn:
        if USING_POSTGRES:
            rows = conn.execute("SELECT id, spanish, translation FROM public_words ORDER BY id ASC").fetchall()
        else:
            rows = conn.execute("SELECT id, spanish, translation FROM public_words ORDER BY id ASC").fetchall()
    return jsonify([{"id": row["id"], "spanish": row["spanish"], "translation": row["translation"]} for row in rows])


@app.route("/words", methods=["POST"])
def add_word():
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
    if USING_POSTGRES:
        with get_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO public_words (spanish, spanish_norm, translation)
                VALUES (%s, %s, %s)
                ON CONFLICT (spanish_norm) DO NOTHING
                RETURNING id
                """,
                (spanish, spanish_norm, translation),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "This word already exists."}), 400
            word_id = row["id"]
    else:
        try:
            with get_db() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO public_words (spanish, spanish_norm, translation)
                    VALUES (?, ?, ?)
                    """,
                    (spanish, spanish_norm, translation),
                )
                word_id = cur.lastrowid
        except sqlite3.IntegrityError:
            return jsonify({"error": "This word already exists."}), 400

    new_word = {"id": word_id, "spanish": spanish, "translation": translation}
    return jsonify(new_word), 201


@app.route("/import", methods=["POST"])
def import_words():
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

        to_insert.append((spanish, normalize_spanish(spanish), translation))

    if to_insert:
        if USING_POSTGRES:
            with get_db() as conn:
                for args in to_insert:
                    cur = conn.execute(
                        """
                        INSERT INTO public_words (spanish, spanish_norm, translation)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (spanish_norm) DO NOTHING
                        RETURNING id
                        """,
                        args,
                    )
                    if cur.fetchone():
                        added_count += 1
        else:
            with get_db() as conn:
                before = conn.total_changes
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO public_words (spanish, spanish_norm, translation)
                    VALUES (?, ?, ?)
                    """,
                    to_insert,
                )
                added_count = conn.total_changes - before

    return jsonify({"status": "success", "count": added_count}), 201


@app.route("/words/<int:word_id>", methods=["DELETE"])
def delete_word(word_id):
    with get_db() as conn:
        if USING_POSTGRES:
            cur = conn.execute("DELETE FROM public_words WHERE id = %s", (word_id,))
        else:
            cur = conn.execute("DELETE FROM public_words WHERE id = ?", (word_id,))

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
