from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"message": "Shopify 자동 등록 서버가 실행 중입니다."})

@app.route("/keep-alive/")
def keep_alive():
    auth = request.args.get("auth")
    if auth != "jeffshopsecure":
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"status": "alive"}), 200
