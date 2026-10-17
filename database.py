
import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="1234",
        database="medicine_reminder"
    )

if __name__ == "__main__":
    try:
        connection = get_connection()
        print("MySQL Connected Successfully!")
        connection.close()
    except mysql.connector.Error as error:
        print("Connection failed:", error)
