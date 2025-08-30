from flask import Flask, jsonify, request
from threading import Thread
import os
import logging
import time

# --- 로깅 설정 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

app = Flask(__name__)

# 홈
@app.route("/")
def home():
    return jsonify({"message": "Shopify 자동 등록 서버가 실행 중입니다."})

# 1) 헬스체크 (인증 없이 200 바로 응답)
@app.get("/health")
def health():
    return {"status": "ok"}, 200

# 공통 인증 함수: 환경변수 IMPORT_AUTH_TOKEN 사용
def _authorized() -> bool:
    expected = os.environ.get("IMPORT_AUTH_TOKEN", "")
    return request.args.get("auth", "") == expected

# 2) 기존 keep-alive (인증 필요)
@app.route("/keep-alive", methods=["GET", "HEAD"])
def keep_alive():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"status": "alive"}), 200


# ─────────────────────────────────────────────────────────────
# 여기서부터 여러분 작업만 연결하면 됩니다.
# ① 실제 작업(run_all 등)이 있으면 그대로 불러쓰고,
# ② 없으면 폴백 더미 작업이 돌아가도록 해 두었습니다.
# ─────────────────────────────────────────────────────────────

def _fallback_demo_job():
    """폴백(데모) 작업: 실제 로직이 없을 때 최소 로그만 남깁니다."""
    logging.info("[fallback] SEO/임포트 작업 시작")
    # TODO: 필요한 경우 실제 로직으로 교체
    # 예: 사이트맵 재생성, 메타태그 재계산, 외부 API 호출 등
    steps = ["키워드 수집", "메타 생성", "이미지 ALT 점검", "사이트맵 제출"]
    for s in steps:
        logging.info("[fallback] %s", s)
        time.sleep(0.2)  # 예시용 짧은 대기 (실제 로직에서는 제거해도 됨)
    logging.info("[fallback] SEO/임포트 작업 완료")

# 실제 작업 함수(여기에 기존 자동 최적화/등록 로직을 호출)
def run_import_and_seo():
    logging.info("SEO 배치 작업 시작")

    # ① 여러분 프로젝트에 실제 모듈/함수가 있는 경우 먼저 시도
    try:
        # 예: 리포지토리에 services/importer.py 파일이 있고, 그 안에 run_all() 함수가 있을 때
        from services.importer import run_all   # ← 실제 경로/함수명으로 바꾸시면 됩니다.
        logging.info("외부 모듈 실행: services.importer.run_all()")
        run_all()
        logging.info("SEO 배치 작업 완료 (외부 모듈)")
        return
    except ModuleNotFoundError:
        logging.warning("services.importer 모듈을 찾을 수 없습니다. 폴백 작업을 실행합니다.")
    except Exception as e:
        logging.exception("외부 모듈 실행 중 오류: %s", e)

    # ② 외부 모듈이 없거나 실패하면 폴백 작업 실행
    try:
        _fallback_demo_job()
        logging.info("SEO 배치 작업 완료 (폴백)")
    except Exception as e:
        logging.exception("폴백 작업 실행 중 오류: %s", e)

# 3) 크론이 호출할 엔드포인트: 즉시 202 반환, 작업은 백그라운드 실행
@app.get("/register")
def register():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=run_import_and_seo, daemon=True).start()
    return jsonify({"ok": True, "status": "queued"}), 202

# Render 로컬 실행 방지(서비스 환경에선 gunicorn이 실행)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
