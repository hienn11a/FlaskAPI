from flask import Flask, request, jsonify
import sqlite3
import jwt
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)

SECRET_KEY = "my_secret_key"

def init_database():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS User (
        IdUser INTEGER PRIMARY KEY AUTOINCREMENT,
        UserName VARCHAR(255) NOT NULL UNIQUE,
        Password VARCHAR(255) NOT NULL,
        Token VARCHAR(255)
    )
    """)

    cursor.execute("""
    SELECT * FROM User WHERE UserName = ?
    """, ("admin",))

    user = cursor.fetchone()

    if user is None:
        cursor.execute("""
        INSERT INTO User (UserName, Password, Token)
        VALUES (?, ?, ?)
        """, ("admin", "e10adc3949ba59abbe56e057f20f883e", ""))

    cursor.execute("""
    UPDATE User
    SET Password = ?
    WHERE UserName = ?
    """, ("e10adc3949ba59abbe56e057f20f883e", "admin"))
    
    conn.commit()
    conn.close()

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):

        token = None

        if "Authorization" in request.headers:
            auth_header = request.headers["Authorization"]

            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]

        if token is None:
            return jsonify({
                "message": "Thieu token"
            }), 401

        try:
            data = jwt.decode(
                token,
                SECRET_KEY,
                algorithms=["HS256"]
            )

            user_name = data["userName"]

        except jwt.ExpiredSignatureError:
            return jsonify({
                "message": "Token da het han"
            }), 401

        except jwt.InvalidTokenError:
            return jsonify({
                "message": "Token khong hop le"
            }), 401

        return f(user_name, *args, **kwargs)

    return decorated

@app.route("/", methods=["POST"])
def login():

    data = request.get_json()

    if not data:
        return jsonify({
            "message": "Du lieu JSON khong hop le"
        }), 400

    user_name = data.get("userName")
    password = data.get("password")

    if not user_name or not password:
        return jsonify({
            "message": "Thieu userName hoac password"
        }), 400

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM User
    WHERE UserName = ? AND Password = ?
    """, (user_name, password))

    user = cursor.fetchone()

    if user is None:
        conn.close()

        return jsonify({
            "message": "Sai tai khoan hoac mat khau"
        }), 401

    payload = {
        "userName": user_name,
        "exp": datetime.utcnow() + timedelta(minutes=30)
    }

    token = jwt.encode(
        payload,
        SECRET_KEY,
        algorithm="HS256"
    )

    cursor.execute("""
    UPDATE User
    SET Token = ?
    WHERE UserName = ?
    """, (token, user_name))

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Dang nhap thanh cong",
        "token": token
    }), 200

@app.route("/auth", methods=["GET"])
@token_required
def auth(user_name):

    return jsonify({
        "message": "Token hop le",
        "userName": user_name
    }), 200

@app.route("/hello", methods=["GET"])
@token_required
def hello(user_name):

    return jsonify({
        "message": "Hello World"
    }), 200


if __name__ == "__main__":
    init_database()
    app.run(debug=True)