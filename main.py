# main.py
from flask import Flask, jsonify, request
from threading import Thread
import os
import sys
import logging
import time
from pathlib import Path
import importlib

# --- 로깅 설정 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# Python 경로/파일 진단: 루트 강제 추가 + 상태 로그
# ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent  # repo 루트(= main.py가 있는 디렉터리)
CWD  = Path.cwd()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.info("[debug] CWD=%s", CWD)
logging.info("[debug] ROOT=%s", ROOT)
try:
    logging.info("[debug] ROOT 목록=%s", sorted(os.listdir(ROOT)))
except Exception as e:
    logging.warning("[debug] ROOT 목록 조회 실패: %s", e)

jobs_init   = ROOT / "jobs" / "__init__.py"
jobs_imp    = ROOT / "jobs" / "importer.py"
serv_init   = ROOT / "services" / "__init__.py"
serv_imp    = ROOT / "services" / "importer.py"

logging.info("[debug] jobs/__init__.py 존재=%s (%s)", jobs_init.exists(), jobs_init)
logging.info("[debug] jobs/importer.py 존재=%s (%s)", jobs_imp.exists(),  jobs_imp)
logging.info("[debug] services/__init__.py 존재=%s (%s)", serv_init.exists(), serv_init)
logging.info("[debug] services/importer.py 존재=%s (%s)", serv_imp.exists(), serv_imp)
logging.info("[debug] sys.path[0..4]=%s", sys.path[:5])

# ─────────────────────────────────────────────────────────────
# 기본 라우트
# ─────────────────────────────────────────────────────────────
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

def _run_with(import_path: str, func_name: str = "run_all") -> bool:
    """
    import_path.func_name 을 호출. 성공 시 True, 실패 시 False 반환.
    실패 원인을 로그에 자세히 남김.
    """
    logging.info("외부 모듈 실행 시도: %s.%s()", import_path, func_name)
    try:
        mod = importlib.import_module(import_path)
    except ModuleNotFoundError as e:
        logging.warning("%s 모듈을 찾을 수 없습니다. (e.name=%s, msg=%s)", import_path, getattr(e, "name", None), e)
        return False
    except Exception as e:
        logging.exception("%s 임포트 중 오류: %s", import_path, e)
        return False

    try:
        fn = getattr(mod, func_name)
    except AttributeError:
        logging.warning("%s 안에 %s 가 없습니다.", import_path, func_name)
        return False

    try:
        fn()
        logging.info("외부 모듈 실행 완료: %s.%s()", import_path, func_name)
        return True
    except Exception as e:
        logging.exception("%s.%s 실행 중 오류: %s", import_path, func_name, e)
        return False

def run_import_and_seo():
    """
    SEO/임포트 전체 배치 실행 진입점
    - 우선순위: jobs.importer.run_all -> services.importer.run_all -> fallback
    """
    logging.info("SEO 배치 작업 시작")

    # ① 신규 경로: jobs.importer.run_all()
    if _run_with("jobs.importer", "run_all"):
        logging.info("SEO 배치 작업 완료 (외부 모듈: jobs)")
        return

    # ② 구(호환) 경로: services.importer.run_all()
    if _run_with("services.importer", "run_all"):
        logging.info("SEO 배치 작업 완료 (외부 모듈: services)")
        return

    # ③ 외부 모듈이 없거나 실패하면 폴백 작업 실행
    _fallback_demo_job()
    logging.info("SEO 배치 작업 완료 (폴백)")

# 3) 크론이 호출할 엔드포인트: 즉시 202 반환, 작업은 백그라운드 실행
@app.get("/register")
def register():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=run_import_and_seo, daemon=True).start()
    return jsonify({"ok": True, "status": "queued"}), 202

# 추가 라우트: SEO 전체 실행 (/run-seo)
@app.get("/run-seo")
def run_seo():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=run_import_and_seo, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "run_seo"}), 202

# 키워드 수집 더미 (구조 유지용)
def _run_keywords_job():
    if _run_with("jobs.importer", "run_keywords"):
        return True
    if _run_with("services.importer", "run_keywords"):
        return True
    _fallback_demo_job()
    return True

@app.get("/seo/keywords/run")
def keywords_run():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=_run_keywords_job, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "keywords"}), 202

# 사이트맵 재등록 더미 (구조 유지용)
def _resubmit_sitemap_job():
    if _run_with("jobs.importer", "resubmit_sitemap"):
        return True
    if _run_with("services.importer", "resubmit_sitemap"):
        return True
    url = os.environ.get("SITEMAP_URL", "")
    logging.info("[fallback] resubmit_sitemap: SITEMAP_URL=%s", url or "(미지정)")
    _fallback_demo_job()
    return True

@app.get("/seo/sitemap/resubmit")
def sitemap_resubmit():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=_resubmit_sitemap_job, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "sitemap_resubmit"}), 202

# Render 로컬 실행 방지(서비스 환경에선 gunicorn이 실행)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))






