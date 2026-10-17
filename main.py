
import hashlib
import secrets
import threading
import time
from datetime import datetime

import mysql.connector
from plyer import notification

from database import get_connection


# ---------- PASSWORD SECURITY ----------

def hash_password(password):
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        100000
    ).hex()
    return salt + "$" + hashed


def verify_password(password, stored_hash):
    try:
        salt, original_hash = stored_hash.split("$", 1)
        new_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            100000
        ).hex()
        return secrets.compare_digest(new_hash, original_hash)
    except (ValueError, AttributeError):
        return False


# ---------- DATABASE HELPER ----------

def run_query(query, values=None, fetch=False):
    connection = get_connection()
    cursor = None

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, values or ())

        if fetch:
            return cursor.fetchall()

        connection.commit()
        return True

    except mysql.connector.Error as error:
        print("Database error:", error)
        return None

    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


# ---------- USER AUTHENTICATION ----------

def register():
    print("\n--- USER REGISTRATION ---")
    name = input("Enter name: ").strip()
    email = input("Enter email: ").strip().lower()
    password = input("Create password: ")

    if not name or not email or not password:
        print("All fields are required.")
        return

    result = run_query(
        "SELECT user_id FROM users WHERE email = %s",
        (email,),
        fetch=True
    )

    if result is None:
        return

    if result:
        print("Email already registered.")
        return

    success = run_query(
        "INSERT INTO users (name, email, password_hash) "
        "VALUES (%s, %s, %s)",
        (name, email, hash_password(password))
    )

    if success:
        print("Registration successful!")


def login():
    print("\n--- USER LOGIN ---")
    email = input("Enter email: ").strip().lower()
    password = input("Enter password: ")

    users = run_query(
        "SELECT * FROM users WHERE email = %s",
        (email,),
        fetch=True
    )

    if users and verify_password(
        password, users[0]["password_hash"]
    ):
        print("Login successful! Welcome", users[0]["name"])
        return users[0]["user_id"]

    if users is not None:
        print("Invalid email or password.")

    return None


# ---------- MEDICINE MANAGEMENT ----------

def add_medicine(user_id):
    print("\n--- ADD MEDICINE ---")
    name = input("Medicine name: ").strip()
    dosage = input("Dosage (example: 1 tablet): ").strip()
    frequency = input("Frequency (example: Daily): ").strip()
    reminder = input("Reminder time (HH:MM, 24-hour): ").strip()
    start_date = input("Start date (YYYY-MM-DD): ").strip()
    end_date = input("End date (YYYY-MM-DD): ").strip()

    try:
        datetime.strptime(reminder, "%H:%M")
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        if end < start:
            print("End date must not be before start date.")
            return

    except ValueError:
        print("Invalid time or date format.")
        return

    if not all([name, dosage, frequency]):
        print("All fields are required.")
        return

    success = run_query(
        """
        INSERT INTO medicines
        (user_id, medicine_name, dosage, frequency,
         reminder_time, start_date, end_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            user_id, name, dosage, frequency,
            reminder + ":00", start_date, end_date
        )
    )

    if success:
        print("Medicine added successfully!")


def view_medicines(user_id):
    medicines = run_query(
        """
        SELECT medicine_id, medicine_name, dosage, frequency,
               reminder_time, start_date, end_date
        FROM medicines
        WHERE user_id = %s
        ORDER BY reminder_time
        """,
        (user_id,),
        fetch=True
    )

    print("\n--- YOUR MEDICINES ---")

    if medicines:
        for med in medicines:
            print(
                f"ID: {med['medicine_id']} | "
                f"Name: {med['medicine_name']} | "
                f"Dosage: {med['dosage']} | "
                f"Frequency: {med['frequency']} | "
                f"Time: {med['reminder_time']} | "
                f"From: {med['start_date']} "
                f"To: {med['end_date']}"
            )
    elif medicines == []:
        print("No medicines added yet.")


# ---------- REMINDER MANAGEMENT ----------

def reminder_worker(user_id, stop_event):
    notified = set()

    while not stop_event.is_set():
        now = datetime.now()
        today = now.date()
        current_time = now.strftime("%H:%M:00")

        medicines = run_query(
            """
            SELECT medicine_id, medicine_name, dosage
            FROM medicines
            WHERE user_id = %s
              AND reminder_time = %s
              AND start_date <= %s
              AND end_date >= %s
            """,
            (user_id, current_time, today, today),
            fetch=True
        )

        if medicines:
            for med in medicines:
                key = (today, med["medicine_id"])

                if key not in notified:
                    try:
                        notification.notify(
                            title="Medicine Reminder",
                            message=(
                                f"Time to take {med['medicine_name']} "
                                f"({med['dosage']})"
                            ),
                            timeout=10
                        )
                        print(
                            "\nReminder:",
                            med["medicine_name"],
                            "-",
                            med["dosage"]
                        )
                    except Exception:
                        print(
                            "\nReminder:",
                            med["medicine_name"],
                            "-",
                            med["dosage"]
                        )

                    notified.add(key)

        stop_event.wait(15)


# ---------- MEDICATION TRACKING ----------

def mark_medicine(user_id):
    view_medicines(user_id)

    try:
        medicine_id = int(input("Enter medicine ID: "))
    except ValueError:
        print("Enter a valid numeric ID.")
        return

    medicines = run_query(
        "SELECT medicine_id FROM medicines "
        "WHERE medicine_id = %s AND user_id = %s",
        (medicine_id, user_id),
        fetch=True
    )

    if not medicines:
        print("Medicine not found for this account.")
        return

    status = input("Enter status (Taken/Missed): ").strip().title()

    if status not in ("Taken", "Missed"):
        print("Status must be Taken or Missed.")
        return

    success = run_query(
        """
        INSERT INTO medication_logs
            (medicine_id, log_date, status)
        VALUES (%s, CURDATE(), %s)
        ON DUPLICATE KEY UPDATE
            status = %s,
            recorded_at = CURRENT_TIMESTAMP
        """,
        (medicine_id, status, status)
    )

    if success:
        print("Medication status saved:", status)


def view_history(user_id):
    history = run_query(
        """
        SELECT m.medicine_name, l.log_date,
               l.status, l.recorded_at
        FROM medication_logs l
        JOIN medicines m ON m.medicine_id = l.medicine_id
        WHERE m.user_id = %s
        ORDER BY l.log_date DESC, l.recorded_at DESC
        """,
        (user_id,),
        fetch=True
    )

    print("\n--- MEDICATION HISTORY ---")

    if history:
        for row in history:
            print(
                row["log_date"], "|",
                row["medicine_name"], "|",
                row["status"], "|",
                row["recorded_at"]
            )
    elif history == []:
        print("No medication history available.")


# ---------- DASHBOARD & REPORTS ----------

def dashboard(user_id):
    medicines = run_query(
        "SELECT COUNT(*) AS total FROM medicines "
        "WHERE user_id = %s",
        (user_id,),
        fetch=True
    )

    taken = run_query(
        """
        SELECT COUNT(*) AS total
        FROM medication_logs l
        JOIN medicines m ON m.medicine_id = l.medicine_id
        WHERE m.user_id = %s
          AND l.log_date = CURDATE()
          AND l.status = 'Taken'
        """,
        (user_id,),
        fetch=True
    )

    missed = run_query(
        """
        SELECT COUNT(*) AS total
        FROM medication_logs l
        JOIN medicines m ON m.medicine_id = l.medicine_id
        WHERE m.user_id = %s
          AND l.log_date = CURDATE()
          AND l.status = 'Missed'
        """,
        (user_id,),
        fetch=True
    )

    if medicines is not None and taken is not None and missed is not None:
        print("\n--- DASHBOARD ---")
        print("Total medicines:", medicines[0]["total"])
        print("Taken today:", taken[0]["total"])
        print("Missed today:", missed[0]["total"])


def reports(user_id):
    rows = run_query(
        """
        SELECT m.medicine_name,
               SUM(l.status = 'Taken') AS taken_count,
               SUM(l.status = 'Missed') AS missed_count
        FROM medicines m
        LEFT JOIN medication_logs l
          ON m.medicine_id = l.medicine_id
        WHERE m.user_id = %s
        GROUP BY m.medicine_id, m.medicine_name
        ORDER BY m.medicine_name
        """,
        (user_id,),
        fetch=True
    )

    print("\n--- MEDICATION REPORT ---")

    if rows:
        for row in rows:
            print(
                row["medicine_name"],
                "| Taken:", row["taken_count"] or 0,
                "| Missed:", row["missed_count"] or 0
            )
    elif rows == []:
        print("No report data available.")


# ---------- MAIN APPLICATION ----------

def user_menu(user_id):
    stop_event = threading.Event()

    reminder_thread = threading.Thread(
        target=reminder_worker,
        args=(user_id, stop_event),
        daemon=True
    )
    reminder_thread.start()

    try:
        while True:
            print("\n====== MEDICINE REMINDER SYSTEM ======")
            print("1. Add Medicine")
            print("2. View Medicines")
            print("3. Mark Taken / Missed")
            print("4. View Medication History")
            print("5. Dashboard")
            print("6. Reports")
            print("7. Logout")

            choice = input("Enter your choice: ").strip()

            if choice == "1":
                add_medicine(user_id)
            elif choice == "2":
                view_medicines(user_id)
            elif choice == "3":
                mark_medicine(user_id)
            elif choice == "4":
                view_history(user_id)
            elif choice == "5":
                dashboard(user_id)
            elif choice == "6":
                reports(user_id)
            elif choice == "7":
                print("Logged out successfully.")
                break
            else:
                print("Invalid choice. Select 1 to 7.")

    finally:
        stop_event.set()


def main():
    while True:
        print("\n====== WELCOME ======")
        print("1. Register")
        print("2. Login")
        print("3. Exit")

        choice = input("Enter your choice: ").strip()

        if choice == "1":
            register()
        elif choice == "2":
            user_id = login()
            if user_id is not None:
                user_menu(user_id)
        elif choice == "3":
            print("Thank you for using Medicine Reminder System!")
            break
        else:
            print("Invalid choice. Select 1, 2 or 3.")


if __name__ == "__main__":
    main()
    
