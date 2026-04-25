from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import random
from datetime import datetime

app = Flask(__name__)
app.secret_key = "kirasensei_secret_key"


# -----------------------------
# DATABASE HELPERS
# -----------------------------
def get_db_connection():
    conn = sqlite3.connect("words.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
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

    try:
        cursor.execute("ALTER TABLE words ADD COLUMN correct_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE words ADD COLUMN wrong_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE words ADD COLUMN last_reviewed TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/learn")
def learn():
    conn = get_db_connection()
    words = conn.execute("SELECT * FROM words ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("learn.html", words=words)


@app.route("/add", methods=["GET", "POST"])
def add_word():
    if request.method == "POST":
        english = request.form["english"].strip()
        japanese = request.form["japanese"].strip()

        if english and japanese:
            conn = get_db_connection()
            conn.execute(
                "INSERT INTO words (english, japanese) VALUES (?, ?)",
                (english, japanese)
            )
            conn.commit()
            conn.close()
            return redirect(url_for("learn"))

    return render_template("add.html")


@app.route("/delete/<int:word_id>", methods=["POST"])
def delete_word(word_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("learn"))


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

    wrong_options = [word["japanese"] for word in words if word["id"] != current_word["id"]]
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


@app.route("/flashcards")
def flashcards():
    conn = get_db_connection()
    words = conn.execute("SELECT * FROM words ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("flashcards.html", words=words)


@app.route("/practice")
def practice():
    conn = get_db_connection()
    words = conn.execute("SELECT * FROM words ORDER BY RANDOM()").fetchall()
    conn.close()

    if not words:
        return render_template("practice.html", word=None, mode="all")

    word = random.choice(words)
    return render_template("practice.html", word=word, mode="all")


@app.route("/practice-weak")
def practice_weak():
    conn = get_db_connection()
    weak_words = conn.execute("""
        SELECT *
        FROM words
        WHERE COALESCE(wrong_count, 0) > COALESCE(correct_count, 0)
        ORDER BY RANDOM()
    """).fetchall()
    conn.close()

    if not weak_words:
        return render_template("practice.html", word=None, mode="weak")

    word = random.choice(weak_words)
    return render_template("practice.html", word=word, mode="weak")


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

    conn.close()

    return render_template(
        "dashboard.html",
        total_words=total_words,
        total_correct=total_correct,
        total_wrong=total_wrong,
        mastered_words=mastered_words,
        weak_words_count=weak_words_count,
        recently_reviewed=recently_reviewed
    )


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


if __name__ == "__main__":
    init_db()
    migrate_db()
    app.run(debug=True)