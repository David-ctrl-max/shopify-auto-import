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
# 외부 배치 작업 연결부 (없으면 폴백 더미 작업 수행)
# ─────────────────────────────────────────────────────────────

def _fallback_demo_job():
    """폴백(데모) 작업: 실제 로직이 없을 때 최소 로그만 남깁니다."""
    logging.info("[fallback] SEO/임포트 작업 시작")
    steps = ["키워드 수집", "메타 생성", "이미지 ALT 점검", "사이트맵 제출"]
    for s in steps:
        logging.info("[fallback] %s", s)
        time.sleep(0.2)  # 데모용 대기
    logging.info("[fallback] SEO/임포트 작업 완료")

def run_import_and_seo():
    logging.info("SEO 배치 작업 시작")

    # ① 신규 경로: jobs.importer.run_all()
    try:
        from jobs.importer import run_all as external_run_all
        logging.info("외부 모듈 실행: jobs.importer.run_all()")
        external_run_all()
        logging.info("SEO 배치 작업 완료 (외부 모듈: jobs)")
        return
    except ModuleNotFoundError:
        logging.warning("jobs.importer 모듈을 찾을 수 없습니다. (구경로 시도)")
    except Exception as e:
        logging.exception("jobs.importer.run_all 실행 중 오류: %s", e)

    # ② 구(호환) 경로: services.importer.run_all()
    try:
        from services.importer import run_all as external_run_all
        logging.info("외부 모듈 실행: services.importer.run_all()")
        external_run_all()
        logging.info("SEO 배치 작업 완료 (외부 모듈: services)")
        return
    except ModuleNotFoundError:
        logging.warning("services.importer 모듈도 없습니다. 폴백 작업을 실행합니다.")
    except Exception as e:
        logging.exception("services.importer.run_all 실행 중 오류: %s", e)

    # ③ 외부 모듈이 없거나 실패하면 폴백 작업 실행
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

