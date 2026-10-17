from flask import (
    Flask, request, redirect, render_template,
    session, jsonify
)
from database import get_connection
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, timedelta
import calendar

app = Flask(__name__)

# Change this to a long random secret before deployment
app.secret_key = "medicare-local-secret-change-before-deployment"


# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("home.html")


# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    message = ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            message = "Please fill in all fields."
        elif len(password) < 8:
            message = "Password must contain at least 8 characters."
        else:
            connection = None
            cursor = None

            try:
                connection = get_connection()
                cursor = connection.cursor()

                password_hash = generate_password_hash(password)

                cursor.execute(
                    """
                    INSERT INTO users (name, email, password_hash)
                    VALUES (%s, %s, %s)
                    """,
                    (name, email, password_hash)
                )
                connection.commit()

                return redirect("/login?registered=1")

            except Exception as error:
                if connection and connection.is_connected():
                    connection.rollback()

                print("Registration error:", error)
                message = "Registration failed. Email may already exist."

            finally:
                if cursor:
                    cursor.close()
                if connection and connection.is_connected():
                    connection.close()

    return render_template("register.html", message=message)


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""

    if request.args.get("registered") == "1":
        message = "Account created successfully. Please log in."

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = None
        cursor = None

        try:
            connection = get_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT user_id, name, email, password_hash
                FROM users
                WHERE email = %s
                """,
                (email,)
            )
            user = cursor.fetchone()

            if user and check_password_hash(
                user["password_hash"], password
            ):
                session.clear()
                session["user_id"] = user["user_id"]
                session["user_name"] = user["name"]
                return redirect("/dashboard")

            message = "Invalid email or password."

        except Exception as error:
            print("Login error:", error)
            message = "Unable to login. Check the database connection."

        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()

    return render_template("login.html", message=message)


# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    medicines = []
    total_medicines = 0
    taken_today = 0
    missed_today = 0
    pending_today = 0

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                m.medicine_id,
                m.medicine_name,
                m.dosage,
                m.frequency,
                m.reminder_time,
                m.start_date,
                m.end_date,
                l.status AS today_status
            FROM medicines AS m
            LEFT JOIN medication_logs AS l
                ON m.medicine_id = l.medicine_id
                AND l.log_date = %s
            WHERE m.user_id = %s
            ORDER BY m.reminder_time
            """,
            (date.today(), session["user_id"])
        )

        medicines = cursor.fetchall()
        total_medicines = len(medicines)

        for medicine in medicines:
            if medicine["today_status"] == "Taken":
                taken_today += 1
            elif medicine["today_status"] == "Missed":
                missed_today += 1
            else:
                pending_today += 1

    except Exception as error:
        print("Dashboard error:", error)

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

    return render_template(
        "dashboard.html",
        name=session.get("user_name", "User"),
        medicines=medicines,
        today=date.today(),
        total_medicines=total_medicines,
        taken_today=taken_today,
        missed_today=missed_today,
        pending_today=pending_today
    )


# ---------------- ADD MEDICINE ----------------
@app.route("/add-medicine", methods=["POST"])
def add_medicine():
    if "user_id" not in session:
        return redirect("/login")

    name = request.form.get("medicine_name", "").strip()
    dosage = request.form.get("dosage", "").strip()
    frequency = request.form.get("frequency", "").strip()
    reminder_time = request.form.get("reminder_time", "").strip()
    start_date = request.form.get("start_date", "")
    end_date = request.form.get("end_date", "")

    if not all([
        name, dosage, frequency, reminder_time,
        start_date, end_date
    ]):
        return redirect("/dashboard?error=missing")

    connection = None
    cursor = None

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        if end < start:
            return redirect("/dashboard?error=dates")

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO medicines
            (user_id, medicine_name, dosage, frequency,
             reminder_time, start_date, end_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session["user_id"], name, dosage, frequency,
                reminder_time, start_date, end_date
            )
        )

        connection.commit()
        return redirect("/dashboard?added=1")

    except Exception as error:
        if connection and connection.is_connected():
            connection.rollback()

        print("Add medicine error:", error)
        return redirect("/dashboard?error=save")

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


# ---------------- DELETE MEDICINE ----------------
@app.route("/delete-medicine/<int:medicine_id>", methods=["POST"])
def delete_medicine(medicine_id):
    if "user_id" not in session:
        return redirect("/login")

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # Users can delete only their own medicines
        cursor.execute(
            """
            DELETE FROM medicines
            WHERE medicine_id = %s AND user_id = %s
            """,
            (medicine_id, session["user_id"])
        )

        connection.commit()

    except Exception as error:
        if connection and connection.is_connected():
            connection.rollback()

        print("Delete medicine error:", error)

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

    return redirect("/dashboard")


# ---------------- MEDICATION TRACKING ----------------
@app.route("/mark-medication/<int:medicine_id>", methods=["POST"])
def mark_medication(medicine_id):
    if "user_id" not in session:
        return redirect("/login")

    status = request.form.get("status", "").strip().title()

    if status not in ("Taken", "Missed"):
        return redirect("/dashboard?error=invalid_status")

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # Verify that this medicine belongs to the logged-in user
        cursor.execute(
            """
            SELECT medicine_id
            FROM medicines
            WHERE medicine_id = %s AND user_id = %s
            """,
            (medicine_id, session["user_id"])
        )

        if not cursor.fetchone():
            return redirect("/dashboard?error=medicine_not_found")

        cursor.execute(
            """
            INSERT INTO medication_logs
                (medicine_id, log_date, status)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                recorded_at = CURRENT_TIMESTAMP
            """,
            (medicine_id, date.today(), status)
        )

        connection.commit()
        return redirect("/dashboard?status_saved=1")

    except Exception as error:
        if connection and connection.is_connected():
            connection.rollback()

        print("Medication tracking error:", error)
        return redirect("/dashboard?error=tracking")

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


# ---------------- MEDICATION HISTORY ----------------
@app.route("/history")
def medication_history():
    if "user_id" not in session:
        return redirect("/login")

    history = []
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                m.medicine_name,
                m.dosage,
                l.log_date,
                l.status,
                l.recorded_at
            FROM medication_logs AS l
            JOIN medicines AS m
                ON m.medicine_id = l.medicine_id
            WHERE m.user_id = %s
            ORDER BY l.log_date DESC, l.recorded_at DESC
            """,
            (session["user_id"],)
        )

        history = cursor.fetchall()

    except Exception as error:
        print("Medication history error:", error)

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

    return render_template("history.html", history=history)


# ---------------- REPORTS ----------------
@app.route("/reports")
def reports():
    if "user_id" not in session:
        return redirect("/login")

    today = date.today()
    week_start = today - timedelta(days=6)
    week_end = today

    selected_month = request.args.get(
        "month", today.strftime("%Y-%m")
    )

    # Validate the selected month
    try:
        year, month = map(int, selected_month.split("-"))

        if not (1 <= month <= 12 and 2000 <= year <= 2100):
            raise ValueError

        month_start = date(year, month, 1)

    except (ValueError, TypeError):
        month_start = date(today.year, today.month, 1)
        selected_month = today.strftime("%Y-%m")

    last_day = calendar.monthrange(
        month_start.year, month_start.month
    )[1]

    month_end = date(
        month_start.year, month_start.month, last_day
    )

    weekly_logs = []
    monthly_logs = []

    weekly_taken = 0
    weekly_missed = 0
    monthly_taken = 0
    monthly_missed = 0

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # Weekly report: last 7 days, including today
        cursor.execute(
            """
            SELECT
                l.log_date,
                l.status,
                m.medicine_name,
                m.dosage,
                l.recorded_at
            FROM medication_logs AS l
            JOIN medicines AS m
                ON m.medicine_id = l.medicine_id
            WHERE m.user_id = %s
              AND l.log_date BETWEEN %s AND %s
            ORDER BY l.log_date DESC, m.medicine_name
            """,
            (session["user_id"], week_start, week_end)
        )

        weekly_logs = cursor.fetchall()

        weekly_taken = sum(
            1 for log in weekly_logs
            if log["status"] == "Taken"
        )
        weekly_missed = sum(
            1 for log in weekly_logs
            if log["status"] == "Missed"
        )

        # Monthly report: selected calendar month
        cursor.execute(
            """
            SELECT
                l.log_date,
                l.status,
                m.medicine_name,
                m.dosage,
                l.recorded_at
            FROM medication_logs AS l
            JOIN medicines AS m
                ON m.medicine_id = l.medicine_id
            WHERE m.user_id = %s
              AND l.log_date BETWEEN %s AND %s
            ORDER BY l.log_date DESC, m.medicine_name
            """,
            (session["user_id"], month_start, month_end)
        )

        monthly_logs = cursor.fetchall()

        monthly_taken = sum(
            1 for log in monthly_logs
            if log["status"] == "Taken"
        )
        monthly_missed = sum(
            1 for log in monthly_logs
            if log["status"] == "Missed"
        )

    except Exception as error:
        print("Reports error:", error)

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

    weekly_recorded = weekly_taken + weekly_missed
    monthly_recorded = monthly_taken + monthly_missed

    weekly_adherence = (
        round(weekly_taken / weekly_recorded * 100)
        if weekly_recorded else 0
    )

    monthly_adherence = (
        round(monthly_taken / monthly_recorded * 100)
        if monthly_recorded else 0
    )

    return render_template(
        "reports.html",
        name=session.get("user_name", "User"),
        today=today,
        week_start=week_start,
        week_end=week_end,
        weekly_logs=weekly_logs,
        weekly_taken=weekly_taken,
        weekly_missed=weekly_missed,
        weekly_recorded=weekly_recorded,
        weekly_adherence=weekly_adherence,
        selected_month=selected_month,
        month_start=month_start,
        month_end=month_end,
        monthly_logs=monthly_logs,
        monthly_taken=monthly_taken,
        monthly_missed=monthly_missed,
        monthly_recorded=monthly_recorded,
        monthly_adherence=monthly_adherence
    )


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ---------------- RUN APPLICATION ----------------
if __name__ == "__main__":
    app.run(debug=True)