from flask import Flask, jsonify, request
from threading import Thread
import os
import logging
import time

# 경로/동적 임포트 유틸
import sys, pathlib, importlib, importlib.util

# --- 로깅 설정 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# --- 프로젝트 루트를 임포트 경로에 추가 ---
ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def _try_import_and_run(module_name: str) -> bool:
    """module_name.run_all()을 찾아 실행. 성공 시 True, 실패/미존재 시 False."""
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            logging.warning("%s 모듈 스펙을 찾을 수 없습니다.", module_name)
            return False

        mod = importlib.import_module(module_name)
        func = getattr(mod, "run_all", None)
        if func is None:
            logging.warning("%s 안에 run_all()이 없습니다.", module_name)
            return False

        logging.info("외부 모듈 실행: %s.run_all()", module_name)
        func()
        logging.info("SEO 배치 작업 완료 (%s)", module_name)
        return True

    except Exception as e:
        logging.exception("%s 실행 중 오류: %s", module_name, e)
        return False


def run_import_and_seo():
    logging.info("SEO 배치 작업 시작")

    # 디버그: 현재 작업 디렉토리/엔트리/sys.path 일부를 로깅
    try:
        entries = sorted(p.name for p in ROOT.iterdir())
        logging.info("[debug] CWD=%s", ROOT)
        logging.info("[debug] 엔트리=%s", entries)
        logging.info("[debug] sys.path[0:5]=%s", sys.path[:5])
    except Exception as e:
        logging.warning("[debug] 경로 로깅 실패: %s", e)

    # ① 신규 경로 우선: jobs.importer.run_all()
    if _try_import_and_run("jobs.importer"):
        return

    logging.warning("jobs.importer 모듈을 찾을 수 없습니다. (구경로 시도)")

    # ② 구(호환) 경로: services.importer.run_all()
    if _try_import_and_run("services.importer"):
        return

    logging.warning("services.importer 모듈도 없습니다. 폴백 작업을 실행합니다.")

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


