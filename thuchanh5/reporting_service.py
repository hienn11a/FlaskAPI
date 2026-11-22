
from flask import Flask, request, jsonify
import requests

from database import get_db_connection, create_tables

app = Flask(__name__)

# =====================================
# CAU HINH CAC SERVICE
# =====================================

AUTH_VERIFY_URL = "http://127.0.0.1:5000/auth"
PRODUCT_SERVICE_URL = "http://127.0.0.1:5001"
ORDER_SERVICE_URL = "http://127.0.0.1:5002"


# =====================================
# 1. XAC THUC TOKEN
# =====================================

def get_token():
    return request.headers.get("Authorization", "").strip()


def check_token():
    token = get_token()

    if not token:
        return False

    try:
        response = requests.get(
            AUTH_VERIFY_URL,
            headers={"Authorization": token},
            timeout=5
        )

        return response.status_code == 200

    except requests.RequestException:
        return False


def service_headers():
    token = get_token()

    return {
        "Authorization": token
    }


# =====================================
# 2. LAY DU LIEU TU PRODUCT SERVICE
# =====================================

def get_product(product_id):
    try:
        response = requests.get(
            PRODUCT_SERVICE_URL + "/products/" + str(product_id),
            headers=service_headers(),
            timeout=5
        )

        if response.status_code != 200:
            return None, "Khong tim thay san pham"

        data = response.json()

        if isinstance(data, dict) and isinstance(data.get("product"), dict):
            data = data["product"]

        if not isinstance(data, dict):
            return None, "Du lieu san pham khong hop le"

        return data, None

    except (requests.RequestException, ValueError):
        return None, "Khong ket noi duoc Product Service"


def get_all_products():
    try:
        response = requests.get(
            PRODUCT_SERVICE_URL + "/products",
            headers=service_headers(),
            timeout=5
        )

        if response.status_code != 200:
            return None, "Khong lay duoc danh sach san pham"

        data = response.json()

        if isinstance(data, dict) and isinstance(data.get("products"), list):
            data = data["products"]

        if not isinstance(data, list):
            return None, "Du lieu danh sach san pham khong hop le"

        return data, None

    except (requests.RequestException, ValueError):
        return None, "Khong ket noi duoc Product Service"


# =====================================
# 3. LAY DU LIEU TU ORDER SERVICE
# =====================================

def get_order(order_id):
    try:
        response = requests.get(
            ORDER_SERVICE_URL + "/orders/" + str(order_id),
            headers=service_headers(),
            timeout=5
        )

        if response.status_code != 200:
            return None, "Khong tim thay don hang"

        data = response.json()

        if not isinstance(data, dict):
            return None, "Du lieu don hang khong hop le"

        return data, None

    except (requests.RequestException, ValueError):
        return None, "Khong ket noi duoc Order Service"


def get_all_orders():
    try:
        response = requests.get(
            ORDER_SERVICE_URL + "/orders",
            headers=service_headers(),
            timeout=5
        )

        if response.status_code != 200:
            return None, "Khong lay duoc danh sach don hang"

        data = response.json()

        if not isinstance(data, list):
            return None, "Du lieu danh sach don hang khong hop le"

        return data, None

    except (requests.RequestException, ValueError):
        return None, "Khong ket noi duoc Order Service"


# =====================================
# 4. TINH TOAN BAO CAO DON HANG
# =====================================

def calculate_order_report(order):
    items = order.get("items", [])

    if not isinstance(items, list):
        return None, "Danh sach san pham trong don hang khong hop le"

    total_revenue = 0
    total_cost = 0
    product_data = []

    for item in items:
        try:
            product_id = int(item["product_id"])
            quantity = int(item["quantity"])
            unit_price = float(item["unit_price"])
        except (KeyError, TypeError, ValueError):
            return None, "Thong tin mat hang trong don hang khong hop le"

        if quantity <= 0:
            return None, "So luong san pham khong hop le"

        product, error = get_product(product_id)

        if error:
            return None, error

        try:
            unit_cost = float(product["cost"])
        except (KeyError, TypeError, ValueError):
            return None, (
                "San pham ID " + str(product_id) +
                " chua co truong cost hop le trong Product Service"
            )

        revenue = quantity * unit_price
        cost = quantity * unit_cost
        profit = revenue - cost

        total_revenue += revenue
        total_cost += cost

        product_data.append({
            "product_id": product_id,
            "total_sold": quantity,
            "revenue": revenue,
            "cost": cost,
            "profit": profit
        })

    return {
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "total_profit": total_revenue - total_cost,
        "products": product_data
    }, None


# =====================================
# 5. TAO BAO CAO DON HANG
# =====================================

def create_order_report(order_id):
    order, error = get_order(order_id)

    if error:
        return None, error

    if order.get("status") != "completed":
        return None, "Chi tao bao cao cho don hang completed"

    result, error = calculate_order_report(order)

    if error:
        return None, error

    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO orders_reports
            (order_id, total_revenue, total_cost, total_profit)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                total_revenue = excluded.total_revenue,
                total_cost = excluded.total_cost,
                total_profit = excluded.total_profit
        """, (
            order_id,
            result["total_revenue"],
            result["total_cost"],
            result["total_profit"]
        ))

        report = conn.execute(
            "SELECT id FROM orders_reports WHERE order_id = ?",
            (order_id,)
        ).fetchone()

        report_id = report["id"]

        # Cap nhat cac bao cao san pham thuoc don hang
        conn.execute(
            "DELETE FROM product_reports WHERE order_report_id = ?",
            (report_id,)
        )

        for item in result["products"]:
            conn.execute("""
                INSERT INTO product_reports
                (order_report_id, product_id, total_sold,
                 revenue, cost, profit)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                report_id,
                item["product_id"],
                item["total_sold"],
                item["revenue"],
                item["cost"],
                item["profit"]
            ))

        conn.commit()

        result["id"] = report_id
        result["order_id"] = order_id

        return result, None

    except Exception as error:
        conn.rollback()
        app.logger.exception("Loi tao bao cao don hang")
        return None, str(error)

    finally:
        conn.close()


# =====================================
# 6. TAO BAO CAO SAN PHAM
# =====================================

def create_product_report(product_id):
    product, error = get_product(product_id)

    if error:
        return None, error

    try:
        stock_quantity = int(product.get("quantity", product.get("stock", 0)))
    except (TypeError, ValueError):
        return None, "So luong ton kho khong hop le"

    orders, error = get_all_orders()

    if error:
        return None, error

    total_sold = 0
    revenue = 0
    total_cost = 0

    for order_info in orders:
        if order_info.get("status") != "completed":
            continue

        order_id = order_info.get("id")

        if order_id is None:
            continue

        order, error = get_order(order_id)

        if error:
            return None, error

        for item in order.get("items", []):
            if int(item.get("product_id", 0)) != int(product_id):
                continue

            try:
                quantity = int(item["quantity"])
                unit_price = float(item["unit_price"])
                unit_cost = float(product["cost"])
            except (KeyError, TypeError, ValueError):
                return None, "Thieu thong tin gia ban hoac gia von"

            total_sold += quantity
            revenue += quantity * unit_price
            total_cost += quantity * unit_cost

    profit = revenue - total_cost

    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        # Tao bao cao tong hop cho san pham.
        # order_report_id = 0 duoc dung cho bao cao tong hop.
        cursor.execute("""
            INSERT INTO orders_reports
            (order_id, total_revenue, total_cost, total_profit)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                total_revenue = excluded.total_revenue,
                total_cost = excluded.total_cost,
                total_profit = excluded.total_profit
        """, (
            -int(product_id),
            revenue,
            total_cost,
            profit
        ))

        report = conn.execute(
            "SELECT id FROM orders_reports WHERE order_id = ?",
            (-int(product_id),)
        ).fetchone()

        report_id = report["id"]

        cursor.execute("""
            INSERT INTO product_reports
            (order_report_id, product_id, total_sold,
             revenue, cost, profit)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_report_id, product_id) DO UPDATE SET
                total_sold = excluded.total_sold,
                revenue = excluded.revenue,
                cost = excluded.cost,
                profit = excluded.profit
        """, (
            report_id,
            product_id,
            total_sold,
            revenue,
            total_cost,
            profit
        ))

        product_report = conn.execute("""
            SELECT * FROM product_reports
            WHERE order_report_id = ? AND product_id = ?
        """, (report_id, product_id)).fetchone()

        conn.commit()

        result = dict(product_report)
        result["stock_quantity"] = stock_quantity
        result["product_name"] = product.get("name")

        return result, None

    except Exception as error:
        conn.rollback()
        app.logger.exception("Loi tao bao cao san pham")
        return None, str(error)

    finally:
        conn.close()


# =====================================
# 7. TRANG CHU
# =====================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Reporting Service dang hoat dong",
        "port": 5003,
        "endpoints": [
            "GET /reports/products",
            "GET /reports/products/<id>",
            "GET /reports/orders",
            "GET /reports/orders/<id>",
            "POST /reports/products",
            "POST /reports/orders",
            "DELETE /reports/products/<id>",
            "DELETE /reports/orders/<id>"
        ]
    }), 200


# =====================================
# 8. GET DANH SACH BAO CAO SAN PHAM
# =====================================

@app.route("/reports/products", methods=["GET"])
def get_product_reports():
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        reports = conn.execute("""
            SELECT * FROM product_reports
            ORDER BY id DESC
        """).fetchall()

        result = []

        for report in reports:
            item = dict(report)

            product, error = get_product(item["product_id"])

            if not error:
                item["stock_quantity"] = product.get(
                    "quantity",
                    product.get("stock", 0)
                )
                item["product_name"] = product.get("name")

            result.append(item)

        return jsonify(result), 200

    finally:
        conn.close()


# =====================================
# 9. GET BAO CAO SAN PHAM THEO ID
# =====================================

@app.route("/reports/products/<int:product_id>", methods=["GET"])
def get_product_report(product_id):
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        report = conn.execute("""
            SELECT * FROM product_reports
            WHERE product_id = ?
            ORDER BY id DESC
        """, (product_id,)).fetchall()

        if not report:
            return jsonify({
                "message": "Khong tim thay bao cao san pham"
            }), 404

        result = [dict(item) for item in report]

        product, error = get_product(product_id)

        if not error:
            for item in result:
                item["stock_quantity"] = product.get(
                    "quantity",
                    product.get("stock", 0)
                )
                item["product_name"] = product.get("name")

        return jsonify(result), 200

    finally:
        conn.close()


# =====================================
# 10. GET DANH SACH BAO CAO DON HANG
# =====================================

@app.route("/reports/orders", methods=["GET"])
def get_order_reports():
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        reports = conn.execute("""
            SELECT * FROM orders_reports
            WHERE order_id > 0
            ORDER BY id DESC
        """).fetchall()

        return jsonify([dict(item) for item in reports]), 200

    finally:
        conn.close()


# =====================================
# 11. GET BAO CAO DON HANG THEO ID
# =====================================

@app.route("/reports/orders/<int:order_id>", methods=["GET"])
def get_order_report(order_id):
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        report = conn.execute("""
            SELECT * FROM orders_reports
            WHERE order_id = ?
        """, (order_id,)).fetchone()

        if report is None:
            return jsonify({
                "message": "Khong tim thay bao cao don hang"
            }), 404

        result = dict(report)

        products = conn.execute("""
            SELECT * FROM product_reports
            WHERE order_report_id = ?
        """, (result["id"],)).fetchall()

        result["products"] = [dict(item) for item in products]

        return jsonify(result), 200

    finally:
        conn.close()


# =====================================
# 12. POST TAO BAO CAO SAN PHAM
# =====================================

@app.route("/reports/products", methods=["POST"])
def post_product_report():
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"message": "Du lieu JSON khong hop le"}), 400

    try:
        product_id = int(data.get("product_id"))
    except (TypeError, ValueError):
        return jsonify({"message": "product_id khong hop le"}), 400

    if product_id <= 0:
        return jsonify({"message": "product_id phai lon hon 0"}), 400

    result, error = create_product_report(product_id)

    if error:
        return jsonify({"message": error}), 400

    return jsonify({
        "message": "Tao bao cao san pham thanh cong",
        "report": result
    }), 201


# =====================================
# 13. POST TAO BAO CAO DON HANG
# =====================================

@app.route("/reports/orders", methods=["POST"])
def post_order_report():
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"message": "Du lieu JSON khong hop le"}), 400

    try:
        order_id = int(data.get("order_id"))
    except (TypeError, ValueError):
        return jsonify({"message": "order_id khong hop le"}), 400

    if order_id <= 0:
        return jsonify({"message": "order_id phai lon hon 0"}), 400

    result, error = create_order_report(order_id)

    if error:
        return jsonify({"message": error}), 400

    return jsonify({
        "message": "Tao bao cao don hang thanh cong",
        "report": result
    }), 201


# =====================================
# 14. DELETE BAO CAO SAN PHAM
# =====================================

@app.route("/reports/products/<int:product_id>", methods=["DELETE"])
def delete_product_report(product_id):
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        cursor = conn.execute("""
            DELETE FROM product_reports
            WHERE product_id = ?
        """, (product_id,))

        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({
                "message": "Khong tim thay bao cao san pham"
            }), 404

        return jsonify({
            "message": "Xoa bao cao san pham thanh cong"
        }), 200

    finally:
        conn.close()


# =====================================
# 15. DELETE BAO CAO DON HANG
# =====================================

@app.route("/reports/orders/<int:order_id>", methods=["DELETE"])
def delete_order_report(order_id):
    if not check_token():
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()

    try:
        cursor = conn.execute("""
            DELETE FROM orders_reports
            WHERE order_id = ?
        """, (order_id,))

        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({
                "message": "Khong tim thay bao cao don hang"
            }), 404

        return jsonify({
            "message": "Xoa bao cao don hang thanh cong"
        }), 200

    finally:
        conn.close()


# =====================================
# KHOI DONG SERVICE
# =====================================

if __name__ == "__main__":
    create_tables()

    print("Reporting Service dang chay tai http://127.0.0.1:5003")

    app.run(
        host="127.0.0.1",
        port=5003,
        debug=True
    )
