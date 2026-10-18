from flask import Flask, request, jsonify
import sqlite3
import requests
from datetime import datetime

app = Flask(__name__)

PORT = 5001
DATABASE = "product_database.db"
AUTH_SERVICE_URL = "http://127.0.0.1:5000/auth"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        price DECIMAL(10, 2) NOT NULL,
        quantity INTEGER NOT NULL,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL
    )
    """)

    conn.commit()
    conn.close()


def check_token():
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        return False, "Thieu token"

    if not auth_header.startswith("Bearer "):
        return False, "Token khong dung dinh dang"

    token = auth_header.replace("Bearer ", "", 1).strip()

    if not token:
        return False, "Thieu token"

    try:
        response = requests.get(
            AUTH_SERVICE_URL,
            headers={
                "Authorization": "Bearer " + token
            },
            timeout=5
        )

        if response.status_code == 200:
            return True, None

        return False, "Token khong hop le"

    except requests.exceptions.RequestException:
        return False, "Khong ket noi duoc Auth Service"


def product_to_dict(product):
    return {
        "id": product["id"],
        "name": product["name"],
        "description": product["description"],
        "price": float(product["price"]),
        "quantity": product["quantity"],
        "created_at": product["created_at"],
        "updated_at": product["updated_at"]
    }


@app.route("/products", methods=["GET"])
def get_products():
    ok, message = check_token()

    if not ok:
        return jsonify({
            "message": message
        }), 401

    conn = get_db()

    products = conn.execute(
        "SELECT * FROM products ORDER BY id"
    ).fetchall()

    conn.close()

    result = []

    for product in products:
        result.append(product_to_dict(product))

    return jsonify(result), 200


@app.route("/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    ok, message = check_token()

    if not ok:
        return jsonify({
            "message": message
        }), 401

    conn = get_db()

    product = conn.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    conn.close()

    if product is None:
        return jsonify({
            "message": "Khong tim thay san pham"
        }), 404

    return jsonify(product_to_dict(product)), 200


@app.route("/products", methods=["POST"])
def create_product():
    ok, message = check_token()

    if not ok:
        return jsonify({
            "message": message
        }), 401

    data = request.get_json()

    if not data:
        return jsonify({
            "message": "Du lieu JSON khong hop le"
        }), 400

    name = data.get("name")
    description = data.get("description", "")
    price = data.get("price")
    quantity = data.get("quantity")

    if not name or price is None or quantity is None:
        return jsonify({
            "message": "Thieu thong tin san pham"
        }), 400

    try:
        price = float(price)
        quantity = int(quantity)
    except (ValueError, TypeError):
        return jsonify({
            "message": "price phai la so va quantity phai la so nguyen"
        }), 400

    if price < 0 or quantity < 0:
        return jsonify({
            "message": "Gia va so luong khong duoc am"
        }), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()

    cursor = conn.execute("""
        INSERT INTO products
        (name, description, price, quantity, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        name,
        description,
        price,
        quantity,
        now,
        now
    ))

    conn.commit()

    product_id = cursor.lastrowid

    product = conn.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    conn.close()

    return jsonify(product_to_dict(product)), 201


@app.route("/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    ok, message = check_token()

    if not ok:
        return jsonify({
            "message": message
        }), 401

    data = request.get_json()

    if not data:
        return jsonify({
            "message": "Du lieu JSON khong hop le"
        }), 400

    conn = get_db()

    old_product = conn.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if old_product is None:
        conn.close()

        return jsonify({
            "message": "Khong tim thay san pham"
        }), 404

    name = data.get("name", old_product["name"])
    description = data.get("description", old_product["description"])
    price = data.get("price", old_product["price"])
    quantity = data.get("quantity", old_product["quantity"])

    try:
        price = float(price)
        quantity = int(quantity)
    except (ValueError, TypeError):
        conn.close()

        return jsonify({
            "message": "price phai la so va quantity phai la so nguyen"
        }), 400

    if price < 0 or quantity < 0:
        conn.close()

        return jsonify({
            "message": "Gia va so luong khong duoc am"
        }), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        UPDATE products
        SET name = ?,
            description = ?,
            price = ?,
            quantity = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        name,
        description,
        price,
        quantity,
        now,
        product_id
    ))

    conn.commit()

    product = conn.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    conn.close()

    return jsonify(product_to_dict(product)), 200


@app.route("/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    ok, message = check_token()

    if not ok:
        return jsonify({
            "message": message
        }), 401

    conn = get_db()

    product = conn.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if product is None:
        conn.close()

        return jsonify({
            "message": "Khong tim thay san pham"
        }), 404

    conn.execute(
        "DELETE FROM products WHERE id = ?",
        (product_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Xoa san pham thanh cong"
    }), 200


if __name__ == "__main__":
    init_database()
    app.run(
        host="127.0.0.1",
        port=PORT,
        debug=True
    )