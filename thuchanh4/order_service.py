
from flask import Flask, request, jsonify
import requests
from database import get_db_connection, create_tables

app = Flask(__name__)

# Cau hinh cac service
PRODUCT_SERVICE_URL = "http://127.0.0.1:5001"
AUTH_SERVICE_URL = "http://127.0.0.1:5000"
AUTH_VERIFY_URL = AUTH_SERVICE_URL + "/auth"

ALLOWED_ORDER_STATUS = ["pending", "completed", "cancelled"]


# =====================================
# 1. KIEM TRA TOKEN
# =====================================

def get_authorization_header():
    return request.headers.get("Authorization", "").strip()


def check_token():
    token = get_authorization_header()

    if not token:
        return False

    try:
        response = requests.get(
            AUTH_VERIFY_URL,
            headers={"Authorization": token},
            timeout=5
        )

        return response.status_code == 200

    except requests.RequestException as error:
        app.logger.error("Loi xac thuc token: %s", error)
        return False


# =====================================
# 2. LAY SAN PHAM TU PRODUCT SERVICE
# =====================================

def get_product(product_id):
    token = get_authorization_header()

    headers = {}
    if token:
        headers["Authorization"] = token

    try:
        response = requests.get(
            PRODUCT_SERVICE_URL + "/products/" + str(product_id),
            headers=headers,
            timeout=5
        )

        if response.status_code != 200:
            app.logger.error(
                "Product Service loi: HTTP %s - %s",
                response.status_code,
                response.text
            )

            return None, "Khong tim thay san pham"

        data = response.json()

        if isinstance(data, dict) and isinstance(data.get("product"), dict):
            data = data["product"]

        if not isinstance(data, dict):
            return None, "Du lieu san pham khong hop le"

        return data, None

    except (requests.RequestException, ValueError) as error:
        app.logger.error("Loi ket noi Product Service: %s", error)
        return None, "Khong ket noi duoc Product Service"


# =====================================
# 3. KIEM TRA TON KHO VA TINH TIEN
# =====================================

def validate_product(product_id, quantity):

    product, error = get_product(product_id)

    if error:
        return None, error

    stock = product.get("quantity", product.get("stock"))
    price = product.get("price", product.get("unit_price"))
    product_name = product.get("name", product.get("product_name"))

    try:
        stock = int(stock)
        price = float(price)
        quantity = int(quantity)

    except (TypeError, ValueError):
        return None, "Thong tin san pham khong hop le"

    if stock < quantity:
        return None, "So luong san pham trong kho khong du"

    if not product_name:
        return None, "San pham chua co ten"

    return {
        "product_id": int(product_id),
        "product_name": product_name,
        "quantity": quantity,
        "unit_price": price,
        "total_price": price * quantity
    }, None


# =====================================
# 4. CAP NHAT TONG TIEN DON HANG
# =====================================

def update_order_total(conn, order_id):

    conn.execute(
        """
        UPDATE orders
        SET total_amount = COALESCE(
            (SELECT SUM(total_price)
             FROM order_items
             WHERE order_id = ?), 0
        ),
        updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (order_id, order_id)
    )


@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "message": "Order Service dang hoat dong",
        "endpoints": ["/orders", "/order_items"]
    }), 200


# =====================================
# 5. LAY DANH SACH DON HANG
# GET /orders
# =====================================

@app.route("/orders", methods=["GET"])
def get_orders():

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        orders = conn.execute(
            "SELECT * FROM orders ORDER BY id DESC"
        ).fetchall()

        return jsonify([dict(order) for order in orders]), 200

    finally:
        conn.close()


# =====================================
# 6. XEM CHI TIET DON HANG
# GET /orders/id
# =====================================

@app.route("/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

        if order is None:
            return jsonify({"message": "Khong tim thay don hang"}), 404

        items = conn.execute(
            "SELECT * FROM order_items WHERE order_id = ?",
            (order_id,)
        ).fetchall()

        result = dict(order)
        result["items"] = [dict(item) for item in items]

        return jsonify(result), 200

    finally:
        conn.close()


# =====================================
# 7. TAO DON HANG
# POST /orders
# =====================================

@app.route("/orders", methods=["POST"])
def create_order():

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"message": "Du lieu JSON khong hop le"}), 400

    customer_name = data.get("customer_name")
    customer_email = data.get("customer_email")
    items = data.get("items")

    if not customer_name or not customer_email:
        return jsonify({
            "message": "Vui long nhap ten va email khach hang"
        }), 400

    if not isinstance(items, list) or len(items) == 0:
        return jsonify({
            "message": "Items phai la danh sach co san pham"
        }), 400

    quantities = {}

    for item in items:

        if not isinstance(item, dict):
            return jsonify({"message": "Du lieu item khong hop le"}), 400

        try:
            product_id = int(item.get("product_id"))
            quantity = int(item.get("quantity"))

        except (TypeError, ValueError):
            return jsonify({"message": "product_id va quantity khong hop le"}), 400

        if product_id <= 0 or quantity <= 0:
            return jsonify({"message": "ID va so luong phai lon hon 0"}), 400

        quantities[product_id] = quantities.get(product_id, 0) + quantity

    validated_items = []

    for product_id, quantity in quantities.items():

        product, error = validate_product(product_id, quantity)

        if error:
            return jsonify({
                "message": error,
                "product_id": product_id
            }), 400

        validated_items.append(product)

    total_amount = sum(
        item["total_price"] for item in validated_items
    )

    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO orders
            (customer_name, customer_email, total_amount, status)
            VALUES (?, ?, ?, ?)
            """,
            (customer_name, customer_email, total_amount, "pending")
        )

        order_id = cursor.lastrowid

        for item in validated_items:

            cursor.execute(
                """
                INSERT INTO order_items
                (order_id, product_id, product_name,
                 quantity, unit_price, total_price)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    item["product_id"],
                    item["product_name"],
                    item["quantity"],
                    item["unit_price"],
                    item["total_price"]
                )
            )

        conn.commit()

        return jsonify({
            "message": "Tao don hang thanh cong",
            "order_id": order_id,
            "total_amount": total_amount,
            "status": "pending"
        }), 201

    except Exception as error:
        conn.rollback()
        app.logger.exception("Loi tao don hang")

        return jsonify({"message": str(error)}), 500

    finally:
        conn.close()


# =====================================
# 8. CAP NHAT TRANG THAI DON HANG
# PUT /orders/id
# =====================================

@app.route("/orders/<int:order_id>", methods=["PUT"])
def update_order(order_id):

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        return jsonify({"message": "Vui long nhap status"}), 400

    status = data["status"].strip().lower()

    if status not in ALLOWED_ORDER_STATUS:
        return jsonify({
            "message": "Status phai la pending, completed hoac cancelled"
        }), 400

    conn = get_db_connection()

    try:
        cursor = conn.execute(
            """
            UPDATE orders
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, order_id)
        )

        if cursor.rowcount == 0:
            return jsonify({"message": "Khong tim thay don hang"}), 404

        conn.commit()

        return jsonify({
            "message": "Cap nhat trang thai thanh cong",
            "status": status
        }), 200

    except Exception as error:
        conn.rollback()
        return jsonify({"message": str(error)}), 500

    finally:
        conn.close()


# =====================================
# 9. XOA DON HANG
# DELETE /orders/id
# =====================================

@app.route("/orders/<int:order_id>", methods=["DELETE"])
def delete_order(order_id):

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        order = conn.execute(
            "SELECT id FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

        if order is None:
            return jsonify({"message": "Khong tim thay don hang"}), 404

        conn.execute(
            "DELETE FROM order_items WHERE order_id = ?",
            (order_id,)
        )

        conn.execute(
            "DELETE FROM orders WHERE id = ?",
            (order_id,)
        )

        conn.commit()

        return jsonify({"message": "Xoa don hang thanh cong"}), 200

    except Exception as error:
        conn.rollback()
        return jsonify({"message": str(error)}), 500

    finally:
        conn.close()


# =====================================
# 10. LAY DANH SACH CHI TIET DON HANG
# GET /order_items
# =====================================

@app.route("/order_items", methods=["GET"])
def get_order_items():

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        items = conn.execute(
            "SELECT * FROM order_items ORDER BY id DESC"
        ).fetchall()

        return jsonify([dict(item) for item in items]), 200

    finally:
        conn.close()


# =====================================
# 11. XEM CHI TIET MOT MAT HANG
# GET /order_items/id
# =====================================

@app.route("/order_items/<int:item_id>", methods=["GET"])
def get_order_item(item_id):

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        item = conn.execute(
            "SELECT * FROM order_items WHERE id = ?",
            (item_id,)
        ).fetchone()

        if item is None:
            return jsonify({"message": "Khong tim thay mat hang"}), 404

        return jsonify(dict(item)), 200

    finally:
        conn.close()


# =====================================
# 12. THEM MAT HANG VAO DON
# POST /order_items
# =====================================

@app.route("/order_items", methods=["POST"])
def create_order_item():

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"message": "Du lieu JSON khong hop le"}), 400

    try:
        order_id = int(data.get("order_id"))
        product_id = int(data.get("product_id"))
        quantity = int(data.get("quantity"))

    except (TypeError, ValueError):
        return jsonify({"message": "Du lieu ID va quantity khong hop le"}), 400

    if order_id <= 0 or product_id <= 0 or quantity <= 0:
        return jsonify({"message": "ID va quantity phai lon hon 0"}), 400

    conn = get_db_connection()

    try:
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

        if order is None:
            return jsonify({"message": "Khong tim thay don hang"}), 404

        if order["status"] != "pending":
            return jsonify({
                "message": "Chi duoc them mat hang vao don pending"
            }), 400

        product, error = validate_product(product_id, quantity)

        if error:
            return jsonify({"message": error}), 400

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO order_items
            (order_id, product_id, product_name,
             quantity, unit_price, total_price)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                product_id,
                product["product_name"],
                quantity,
                product["unit_price"],
                product["total_price"]
            )
        )

        item_id = cursor.lastrowid

        update_order_total(conn, order_id)
        conn.commit()

        return jsonify({
            "message": "Them mat hang thanh cong",
            "item_id": item_id
        }), 201

    except Exception as error:
        conn.rollback()
        return jsonify({"message": str(error)}), 500

    finally:
        conn.close()


# =====================================
# 13. CAP NHAT MAT HANG
# PUT /order_items/id
# =====================================

@app.route("/order_items/<int:item_id>", methods=["PUT"])
def update_order_item(item_id):

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"message": "Du lieu JSON khong hop le"}), 400

    try:
        quantity = int(data.get("quantity"))

    except (TypeError, ValueError):
        return jsonify({"message": "quantity phai la so nguyen"}), 400

    if quantity <= 0:
        return jsonify({"message": "quantity phai lon hon 0"}), 400

    conn = get_db_connection()

    try:
        item = conn.execute(
            "SELECT * FROM order_items WHERE id = ?",
            (item_id,)
        ).fetchone()

        if item is None:
            return jsonify({"message": "Khong tim thay mat hang"}), 404

        order = conn.execute(
            "SELECT status FROM orders WHERE id = ?",
            (item["order_id"],)
        ).fetchone()

        if order is None or order["status"] != "pending":
            return jsonify({
                "message": "Chi duoc sua mat hang trong don pending"
            }), 400

        product, error = get_product(item["product_id"])

        if error:
            return jsonify({"message": error}), 400

        stock = product.get("quantity", product.get("stock"))

        try:
            stock = int(stock)

        except (TypeError, ValueError):
            return jsonify({
                "message": "Product Service khong tra ve quantity hop le"
            }), 400

        if quantity > stock:
            return jsonify({
                "message": "So luong san pham trong kho khong du"
            }), 400

        new_total = quantity * float(item["unit_price"])

        conn.execute(
            """
            UPDATE order_items
            SET quantity = ?, total_price = ?
            WHERE id = ?
            """,
            (quantity, new_total, item_id)
        )

        update_order_total(conn, item["order_id"])
        conn.commit()

        return jsonify({
            "message": "Cap nhat mat hang thanh cong",
            "quantity": quantity,
            "total_price": new_total
        }), 200

    except Exception as error:
        conn.rollback()
        return jsonify({"message": str(error)}), 500

    finally:
        conn.close()


# =====================================
# 14. XOA MAT HANG
# DELETE /order_items/id
# =====================================

@app.route("/order_items/<int:item_id>", methods=["DELETE"])
def delete_order_item(item_id):

    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        item = conn.execute(
            "SELECT * FROM order_items WHERE id = ?",
            (item_id,)
        ).fetchone()

        if item is None:
            return jsonify({"message": "Khong tim thay mat hang"}), 404

        order = conn.execute(
            "SELECT status FROM orders WHERE id = ?",
            (item["order_id"],)
        ).fetchone()

        if order is None or order["status"] != "pending":
            return jsonify({
                "message": "Chi duoc xoa mat hang trong don pending"
            }), 400

        conn.execute(
            "DELETE FROM order_items WHERE id = ?",
            (item_id,)
        )

        update_order_total(conn, item["order_id"])
        conn.commit()

        return jsonify({
            "message": "Xoa mat hang thanh cong"
        }), 200

    except Exception as error:
        conn.rollback()
        return jsonify({"message": str(error)}), 500

    finally:
        conn.close()


# =====================================
# 15. CHAY ORDER SERVICE
# =====================================

if __name__ == "__main__":
    create_tables()

    print("Order Service dang chay tai http://127.0.0.1:5002")

    app.run(
        host="127.0.0.1",
        port=5002,
        debug=True
    )
