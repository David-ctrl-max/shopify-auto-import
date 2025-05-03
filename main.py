from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"message": "Shopify 자동 등록 서버가 실행 중입니다."})

@app.route("/keep-alive", methods=["GET"])
def keep_alive():
    auth = request.args.get("auth")
    if auth != "jeffshopsecure":
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"status": "alive"}), 200

# Render에서 수동 실행 시 방지
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
