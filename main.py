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

# 꼭 아래 줄을 추가하세요: Render가 직접 실행할 때 인식이 안 되는 경우 방지용
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
