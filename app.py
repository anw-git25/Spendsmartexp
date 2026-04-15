from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import functools

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_secret")
DATABASE = os.path.join(app.root_path, "spendsmart.db")

CATEGORY_DEFAULTS = [
    "Food",
    "Travel",
    "Bills",
    "Shopping",
    "Entertainment",
    "Others",
]


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE RESTRICT
        )
        """
    )
    conn.commit()

    existing = cursor.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    if existing == 0:
        cursor.executemany("INSERT INTO categories (name) VALUES (?)", [(name,) for name in CATEGORY_DEFAULTS])
        conn.commit()
    conn.close()


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped_view


@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        conn = get_db_connection()
        g.user = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()


def format_currency(value):
    return f"₹{value:,.2f}"


@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not name or not email or not password:
            flash("Please fill in all fields.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            conn = get_db_connection()
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                flash("An account with this email already exists.", "error")
                conn.close()
            else:
                hashed = generate_password_hash(password)
                conn.execute(
                    "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                    (name, email, hashed),
                )
                conn.commit()
                conn.close()
                flash("Registration successful. Please log in.", "success")
                return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password"], password):
            flash("Invalid email or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db_connection()
    user_id = session["user_id"]

    totals = conn.execute(
        "SELECT SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) AS income, "
        "SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) AS expense "
        "FROM transactions WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    recent = conn.execute(
        "SELECT t.id, t.title, t.amount, t.type, t.created_at, c.name AS category "
        "FROM transactions t "
        "JOIN categories c ON t.category_id = c.id "
        "WHERE t.user_id = ? "
        "ORDER BY t.created_at DESC LIMIT 6",
        (user_id,),
    ).fetchall()

    chart_data = conn.execute(
        "SELECT c.name AS category, SUM(t.amount) AS total "
        "FROM transactions t "
        "JOIN categories c ON t.category_id = c.id "
        "WHERE t.user_id = ? AND t.type = 'expense' "
        "GROUP BY c.name "
        "ORDER BY total DESC",
        (user_id,),
    ).fetchall()
    conn.close()

    income_total = totals["income"] or 0.0
    expense_total = totals["expense"] or 0.0
    balance = income_total - expense_total

    return render_template(
        "dashboard.html",
        income=format_currency(income_total),
        expense=format_currency(expense_total),
        balance=format_currency(balance),
        recent=recent,
        chart_data=chart_data,
        categories=[row["category"] for row in chart_data],
        amounts=[row["total"] for row in chart_data],
    )


@app.route("/transactions", methods=["GET", "POST"])
@login_required
def transactions():
    conn = get_db_connection()
    user_id = session["user_id"]
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        amount = request.form.get("amount", "").strip()
        category_id = request.form.get("category")
        tx_type = request.form.get("type")

        if not title or not amount or not category_id or tx_type not in ("income", "expense"):
            flash("Please complete all fields to add a transaction.", "error")
        else:
            try:
                amount_value = float(amount)
                conn.execute(
                    "INSERT INTO transactions (user_id, category_id, title, amount, type) VALUES (?, ?, ?, ?, ?)",
                    (user_id, category_id, title, amount_value, tx_type),
                )
                conn.commit()
                flash("Transaction added successfully.", "success")
                return redirect(url_for("transactions"))
            except ValueError:
                flash("Please enter a valid amount.", "error")

    transactions = conn.execute(
        "SELECT t.id, t.title, t.amount, t.type, t.created_at, c.name AS category "
        "FROM transactions t "
        "JOIN categories c ON t.category_id = c.id "
        "WHERE t.user_id = ? "
        "ORDER BY t.created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()

    return render_template(
        "transactions.html",
        categories=categories,
        transactions=transactions,
        format_currency=format_currency,
    )


@app.route("/transaction/<int:transaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id):
    conn = get_db_connection()
    user_id = session["user_id"]
    transaction = conn.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    ).fetchone()
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if transaction is None:
        conn.close()
        flash("Transaction not found.", "error")
        return redirect(url_for("transactions"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        amount = request.form.get("amount", "").strip()
        category_id = request.form.get("category")
        tx_type = request.form.get("type")

        if not title or not amount or not category_id or tx_type not in ("income", "expense"):
            flash("Please complete all fields.", "error")
        else:
            try:
                amount_value = float(amount)
                conn.execute(
                    "UPDATE transactions SET title = ?, amount = ?, category_id = ?, type = ? WHERE id = ? AND user_id = ?",
                    (title, amount_value, category_id, tx_type, transaction_id, user_id),
                )
                conn.commit()
                conn.close()
                flash("Transaction updated successfully.", "success")
                return redirect(url_for("transactions"))
            except ValueError:
                flash("Please enter a valid amount.", "error")

    conn.close()
    return render_template(
        "edit_transaction.html",
        transaction=transaction,
        categories=categories,
        format_currency=format_currency,
    )


@app.route("/transaction/<int:transaction_id>/delete", methods=["POST"])
@login_required
def delete_transaction(transaction_id):
    conn = get_db_connection()
    user_id = session["user_id"]
    conn.execute(
        "DELETE FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, user_id),
    )
    conn.commit()
    conn.close()
    flash("Transaction deleted successfully.", "success")
    return redirect(url_for("transactions"))


@app.route("/reports")
@login_required
def reports():
    conn = get_db_connection()
    user_id = session["user_id"]

    category_breakdown = conn.execute(
        "SELECT c.name AS category, SUM(t.amount) AS total "
        "FROM transactions t "
        "JOIN categories c ON t.category_id = c.id "
        "WHERE t.user_id = ? AND t.type = 'expense' "
        "GROUP BY c.name "
        "ORDER BY total DESC",
        (user_id,),
    ).fetchall()

    totals = conn.execute(
        "SELECT SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) AS income, "
        "SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) AS expense "
        "FROM transactions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()

    income_total = totals["income"] or 0.0
    expense_total = totals["expense"] or 0.0
    balance = income_total - expense_total

    return render_template(
        "reports.html",
        income=format_currency(income_total),
        expense=format_currency(expense_total),
        balance=format_currency(balance),
        breakdown=category_breakdown,
        categories=[row["category"] for row in category_breakdown],
        amounts=[row["total"] for row in category_breakdown],
    )


@app.context_processor
def utility_processor():
    return {"format_currency": format_currency}


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
