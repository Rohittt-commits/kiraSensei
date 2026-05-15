from flask import Flask, render_template, request, redirect, url_for, session, send_file
import sqlite3
import random
from datetime import datetime
import csv
import io

try:
    from google import genai
except ImportError:
    genai = None


app = Flask(__name__)
app.secret_key = "kirasensei_secret_key"

GEMINI_API_KEY = "PASTE_YOUR_API_KEY_HERE"


def generate_ai_response(prompt):
    if genai is None:
        return "google-genai package is not installed. Run: python -m pip install -U google-genai"

    if GEMINI_API_KEY == "PASTE_NEW_GEMINI_API_KEY_HERE":
        return "Please paste your Gemini API key in app.py."

    try:
        client = genai.Client(api_key=GEMINI_API_KEY.strip())
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"AI Error:\n{str(e)}"


def get_db_connection():
    conn = sqlite3.connect("words.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT NOT NULL,
            japanese TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def migrate_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    columns = [
        ("correct_count", "INTEGER DEFAULT 0"),
        ("wrong_count", "INTEGER DEFAULT 0"),
        ("last_reviewed", "TEXT"),
        ("jlpt_level", "TEXT DEFAULT 'N5'")
    ]

    for column_name, column_type in columns:
        try:
            cursor.execute(f"ALTER TABLE words ADD COLUMN {column_name} {column_type}")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/learn")
def learn():
    search = request.args.get("search", "").strip()
    level = request.args.get("level", "").strip()

    conn = get_db_connection()

    query = "SELECT * FROM words WHERE 1=1"
    params = []

    if search:
        query += " AND (english LIKE ? OR japanese LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    if level:
        query += " AND jlpt_level = ?"
        params.append(level)

    query += " ORDER BY id DESC"

    words = conn.execute(query, params).fetchall()
    conn.close()

    return render_template("learn.html", words=words, search=search, level=level)


@app.route("/add", methods=["GET", "POST"])
def add_word():
    if request.method == "POST":
        english = request.form["english"].strip()
        japanese = request.form["japanese"].strip()
        level = request.form.get("level", "N5")

        if english and japanese:
            conn = get_db_connection()
            conn.execute(
                "INSERT INTO words (english, japanese, jlpt_level) VALUES (?, ?, ?)",
                (english, japanese, level)
            )
            conn.commit()
            conn.close()

        return redirect(url_for("learn"))

    return render_template("add.html")


@app.route("/edit/<int:word_id>", methods=["GET", "POST"])
def edit_word(word_id):
    conn = get_db_connection()
    word = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()

    if word is None:
        conn.close()
        return redirect(url_for("learn"))

    if request.method == "POST":
        english = request.form["english"].strip()
        japanese = request.form["japanese"].strip()
        level = request.form.get("level", "N5")

        if english and japanese:
            conn.execute("""
                UPDATE words
                SET english = ?, japanese = ?, jlpt_level = ?
                WHERE id = ?
            """, (english, japanese, level, word_id))

            conn.commit()

        conn.close()
        return redirect(url_for("learn"))

    conn.close()
    return render_template("edit.html", word=word)


@app.route("/delete/<int:word_id>", methods=["POST"])
def delete_word(word_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("learn"))


@app.route("/flashcards")
def flashcards():
    conn = get_db_connection()
    words = conn.execute("SELECT * FROM words ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("flashcards.html", words=words)


@app.route("/practice")
def practice():
    conn = get_db_connection()
    word = conn.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    return render_template("practice.html", word=word, mode="all")


@app.route("/practice-weak")
def practice_weak():
    conn = get_db_connection()
    word = conn.execute("""
        SELECT *
        FROM words
        WHERE COALESCE(wrong_count, 0) > COALESCE(correct_count, 0)
        ORDER BY RANDOM()
        LIMIT 1
    """).fetchone()
    conn.close()
    return render_template("practice.html", word=word, mode="weak")


@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if "score" not in session:
        session["score"] = 0

    feedback = None
    feedback_type = None

    if request.method == "POST":
        selected_answer = request.form.get("answer")
        correct_answer = request.form.get("correct_answer")
        word_id = request.form.get("word_id")

        if word_id and correct_answer:
            conn = get_db_connection()

            if selected_answer == correct_answer:
                conn.execute("""
                    UPDATE words
                    SET correct_count = COALESCE(correct_count, 0) + 1,
                        last_reviewed = ?
                    WHERE id = ?
                """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), word_id))

                session["score"] += 1
                feedback = "Correct! Great job."
                feedback_type = "success"
            else:
                conn.execute("""
                    UPDATE words
                    SET wrong_count = COALESCE(wrong_count, 0) + 1,
                        last_reviewed = ?
                    WHERE id = ?
                """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), word_id))

                feedback = f"Wrong! Correct answer: {correct_answer}"
                feedback_type = "error"

            conn.commit()
            conn.close()

    conn = get_db_connection()
    words = conn.execute("SELECT * FROM words ORDER BY RANDOM()").fetchall()
    conn.close()

    if len(words) < 4:
        return render_template(
            "quiz.html",
            not_enough_words=True,
            score=session["score"],
            feedback=feedback,
            feedback_type=feedback_type
        )

    current_word = random.choice(words)

    wrong_options = [
        word["japanese"]
        for word in words
        if word["id"] != current_word["id"]
    ]

    wrong_options = random.sample(wrong_options, 3)
    options = wrong_options + [current_word["japanese"]]
    random.shuffle(options)

    return render_template(
        "quiz.html",
        current_word=current_word,
        options=options,
        score=session["score"],
        feedback=feedback,
        feedback_type=feedback_type,
        not_enough_words=False
    )


@app.route("/quiz/reset")
def reset_quiz():
    session["score"] = 0
    return redirect(url_for("quiz"))


@app.route("/weak-words")
def weak_words():
    conn = get_db_connection()
    words = conn.execute("""
        SELECT *,
               (COALESCE(wrong_count, 0) - COALESCE(correct_count, 0)) AS weakness_score
        FROM words
        WHERE COALESCE(wrong_count, 0) > COALESCE(correct_count, 0)
        ORDER BY weakness_score DESC, wrong_count DESC, id DESC
    """).fetchall()
    conn.close()

    return render_template("weak_words.html", words=words)


@app.route("/reset-progress", methods=["POST"])
def reset_progress():
    session["score"] = 0

    conn = get_db_connection()
    conn.execute("""
        UPDATE words
        SET correct_count = 0,
            wrong_count = 0,
            last_reviewed = NULL
    """)
    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    conn = get_db_connection()

    total_words = conn.execute("SELECT COUNT(*) AS count FROM words").fetchone()["count"]

    total_correct = conn.execute(
        "SELECT COALESCE(SUM(correct_count), 0) AS total FROM words"
    ).fetchone()["total"]

    total_wrong = conn.execute(
        "SELECT COALESCE(SUM(wrong_count), 0) AS total FROM words"
    ).fetchone()["total"]

    mastered_words = conn.execute("""
        SELECT COUNT(*) AS count
        FROM words
        WHERE COALESCE(correct_count, 0) >= 3
        AND COALESCE(correct_count, 0) > COALESCE(wrong_count, 0)
    """).fetchone()["count"]

    weak_words_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM words
        WHERE COALESCE(wrong_count, 0) > COALESCE(correct_count, 0)
    """).fetchone()["count"]

    recently_reviewed = conn.execute("""
        SELECT *
        FROM words
        WHERE last_reviewed IS NOT NULL
        ORDER BY last_reviewed DESC
        LIMIT 5
    """).fetchall()

    n5_count = conn.execute(
        "SELECT COUNT(*) AS count FROM words WHERE jlpt_level = 'N5'"
    ).fetchone()["count"]

    n4_count = conn.execute(
        "SELECT COUNT(*) AS count FROM words WHERE jlpt_level = 'N4'"
    ).fetchone()["count"]

    n3_count = conn.execute(
        "SELECT COUNT(*) AS count FROM words WHERE jlpt_level = 'N3'"
    ).fetchone()["count"]

    conn.close()

    return render_template(
        "dashboard.html",
        total_words=total_words,
        total_correct=total_correct,
        total_wrong=total_wrong,
        mastered_words=mastered_words,
        weak_words_count=weak_words_count,
        recently_reviewed=recently_reviewed,
        n5_count=n5_count,
        n4_count=n4_count,
        n3_count=n3_count
    )


@app.route("/ai-sensei/<int:word_id>")
def ai_sensei(word_id):
    conn = get_db_connection()
    word = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    conn.close()

    if word is None:
        return redirect(url_for("learn"))

    prompt = f"""
You are KiraSensei AI, a friendly Japanese learning tutor.

Teach this word in a fun immersive way:

English: {word['english']}
Japanese: {word['japanese']}
JLPT Level: {word['jlpt_level'] or 'N5'}

Give:
1. Anime Memory Scene
2. Example Japanese Sentence
3. Romaji
4. English Meaning
5. Beginner Usage Tip
6. Mini Practice Question
"""

    ai_response = generate_ai_response(prompt)

    return render_template("ai_sensei.html", word=word, ai_response=ai_response)


@app.route("/ai-conversation", methods=["GET", "POST"])
def ai_conversation():
    if "conversation_history" not in session:
        session["conversation_history"] = []

    scenario = request.form.get("scenario", "cafe")

    if request.method == "POST":
        user_message = request.form.get("message", "").strip()

        if user_message:
            session["conversation_history"].append({
                "role": "You",
                "message": user_message
            })

            conn = get_db_connection()
            words = conn.execute("""
                SELECT english, japanese
                FROM words
                ORDER BY RANDOM()
                LIMIT 8
            """).fetchall()
            conn.close()

            vocab_context = ", ".join([
                f"{word['english']}={word['japanese']}"
                for word in words
            ])

            prompt = f"""
You are KiraSensei AI, a friendly Japanese conversation tutor.

Scenario: {scenario}

The student is a beginner.
Reply in very simple Japanese with English support.
Use short lines.
Use some saved vocabulary if possible:
{vocab_context}

Conversation so far:
{session['conversation_history']}

Student said:
{user_message}

Reply with:
1. Simple Japanese response
2. English meaning
3. Tiny correction or tip
4. Follow-up question in simple Japanese
"""

            ai_reply = generate_ai_response(prompt)

            session["conversation_history"].append({
                "role": "AI Sensei",
                "message": ai_reply
            })

            session.modified = True

    return render_template(
        "ai_conversation.html",
        history=session["conversation_history"],
        scenario=scenario
    )


@app.route("/ai-conversation/reset")
def reset_ai_conversation():
    session["conversation_history"] = []
    return redirect(url_for("ai_conversation"))


@app.route("/reset-ai-chat")
def reset_ai_chat():
    session["conversation_history"] = []
    return redirect(url_for("ai_conversation"))


@app.route("/import-csv", methods=["POST"])
def import_csv():
    uploaded_file = request.files.get("file")

    if uploaded_file:
        stream = io.StringIO(uploaded_file.stream.read().decode("UTF8"), newline=None)
        reader = csv.reader(stream)

        conn = get_db_connection()

        for row in reader:
            if not row:
                continue

            if row[0].lower().strip() == "english":
                continue

            if len(row) >= 2:
                english = row[0].strip()
                japanese = row[1].strip()
                level = row[2].strip().upper() if len(row) >= 3 else "N5"

                if level not in ["N5", "N4", "N3"]:
                    level = "N5"

                if english and japanese:
                    conn.execute(
                        "INSERT INTO words (english, japanese, jlpt_level) VALUES (?, ?, ?)",
                        (english, japanese, level)
                    )

        conn.commit()
        conn.close()

    return redirect(url_for("learn"))


@app.route("/export-csv")
def export_csv():
    conn = get_db_connection()
    words = conn.execute("""
        SELECT english, japanese, jlpt_level, correct_count, wrong_count, last_reviewed
        FROM words
        ORDER BY id DESC
    """).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "English",
        "Japanese",
        "JLPT Level",
        "Correct Count",
        "Wrong Count",
        "Last Reviewed"
    ])

    for word in words:
        writer.writerow([
            word["english"],
            word["japanese"],
            word["jlpt_level"] or "N5",
            word["correct_count"] or 0,
            word["wrong_count"] or 0,
            word["last_reviewed"] or ""
        ])

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="kirasensei_words.csv"
    )


if __name__ == "__main__":
    init_db()
    migrate_db()
    app.run(debug=True, port=5000)