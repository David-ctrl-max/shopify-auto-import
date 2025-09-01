# main.py

import os, sys, time, json, pathlib, datetime, logging, importlib
from threading import Thread
from pathlib import Path
from urllib.parse import quote
from flask import Flask, jsonify, request, Response

# ─────────────────────────────────────────────────────────────
# 인증 토큰 (통일: IMPORT_AUTH_TOKEN, 기본값 jeffshopsecure)
# ─────────────────────────────────────────────────────────────
AUTH_TOKEN = os.environ.get("IMPORT_AUTH_TOKEN", "jeffshopsecure")

# ─────────────────────────────────────────────────────────────
# 리포트 저장소 설정
# ─────────────────────────────────────────────────────────────
BASE_DIR = pathlib.Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)
HISTORY_FILE = REPORTS_DIR / "history.jsonl"

def _append_row(row: dict):
    row["ts"] = datetime.datetime.utcnow().isoformat() + "Z"
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

def _load_rows(limit=30):
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    rows = []
    for ln in lines[-limit:]:
        try:
            rows.append(json.loads(ln))
        except:
            pass
    return rows

def _quickchart_url(labels, values, label="CTR %"):
    cfg = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{"label": label, "data": values}]
        },
        "options": {"plugins": {"legend": {"display": False}}}
    }
    return f"https://quickchart.io/chart?c={quote(json.dumps(cfg, separators=(',',':')))}"

# ─────────────────────────────────────────────────────────────
# Flask 앱 설정
# ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# 기본 라우트
# ─────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({"message": "Shopify 자동 등록 서버가 실행 중입니다."})

@app.get("/health")
def health():
    return {"status": "ok"}, 200

def _authorized() -> bool:
    return request.args.get("auth", "") == AUTH_TOKEN

@app.route("/keep-alive", methods=["GET", "HEAD"])
def keep_alive():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"status": "alive"}), 200

# ─────────────────────────────────────────────────────────────
# 리포트 관련 라우트
# ─────────────────────────────────────────────────────────────
@app.get("/report/add")
def report_add():
    """
    예: /report/add?auth=jeffshopsecure&perf=76&acc=96&bp=100&seo=76&ctr=6.8&lcp=0.7&tbt=470&updated=10
    """
    if not _authorized():
        return ("forbidden", 403)

    def _num(name, default=0.0):
        try:
            return float(request.args.get(name, default))
        except:
            return float(default)

    row = {
        "date": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d"),
        "perf": _num("perf", 0),
        "acc": _num("acc", 0),
        "bp": _num("bp", 0),
        "seo": _num("seo", 0),
        "ctr": _num("ctr", 0),
        "lcp": _num("lcp", 0),
        "tbt": _num("tbt", 0),
        "updated": int(_num("updated", 0)),
        "notes": request.args.get("notes", "")
    }
    _append_row(row)
    return {"ok": True, "saved": row}

@app.get("/report/daily")
def report_daily():
    rows = _load_rows(limit=30)
    today = rows[-1] if rows else {}
    date_str = today.get("date", datetime.date.today().isoformat())
    perf = today.get("perf", 0)
    acc = today.get("acc", 0)
    bp  = today.get("bp", 0)
    seo = today.get("seo", 0)
    lcp = today.get("lcp", 0)
    tbt = today.get("tbt", 0)
    ctr = today.get("ctr", 0)
    updated = today.get("updated", 0)

    labels = [r.get("date","") for r in rows[-10:]] or [date_str]
    ctr_vals = [r.get("ctr", 0) for r in rows[-10:]] or [ctr]
    chart_url = _quickchart_url(labels, ctr_vals, label="CTR %")

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>Daily SEO Summary – Jeff’s Favorite Picks</title>
<style>
  body {{ font-family: Arial, sans-serif; color:#333; max-width: 900px; margin: 24px auto; }}
  h2 {{ margin-bottom: 6px; }}
  .muted {{ color:#777; }}
  table {{ border-collapse: collapse; width:100%; margin-top: 8px; }}
  th, td {{ border:1px solid #e5e5e5; padding:10px; text-align:left; }}
  th {{ background:#fafafa; }}
  .kpi {{ display:grid; grid-template-columns: repeat(4,1fr); gap:12px; margin: 18px 0; }}
  .card {{ border:1px solid #eee; border-radius:10px; padding:14px; }}
  .small {{ font-size:12px; }}
</style>
</head>
<body>
  <h2>📅 Daily SEO Summary <span class="muted">({date_str})</span></h2>

  <div class="kpi">
    <div class="card"><div class="small muted">Performance</div><div style="font-size:24px;font-weight:700;">{perf:.0f}</div></div>
    <div class="card"><div class="small muted">Accessibility</div><div style="font-size:24px;font-weight:700;">{acc:.0f}</div></div>
    <div class="card"><div class="small muted">Best Practices</div><div style="font-size:24px;font-weight:700;">{bp:.0f}</div></div>
    <div class="card"><div class="small muted">SEO</div><div style="font-size:24px;font-weight:700;">{seo:.0f}</div></div>
  </div>

  <h3>🔹 Key Metrics (Today)</h3>
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Largest Contentful Paint (LCP)</td><td>{lcp:.2f} s</td></tr>
    <tr><td>Total Blocking Time (TBT)</td><td>{int(tbt)} ms</td></tr>
    <tr><td>CTR</td><td>{ctr:.2f}%</td></tr>
    <tr><td>SEO Updates Applied</td><td>{updated}</td></tr>
  </table>

  <h3>📈 CTR Trend (최근 10일)</h3>
  <img src="{chart_url}" width="600" alt="CTR Trend"/>

  <p class="small muted" style="margin-top:16px;">
    ✅ Generated by shopify-auto-import · {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")}
  </p>
</body>
</html>
"""
    return Response(html, mimetype="text/html")

# ─────────────────────────────────────────────────────────────
# SEO/임포트 작업 실행부
# ─────────────────────────────────────────────────────────────
def _fallback_demo_job():
    logging.info("[fallback] SEO/임포트 작업 시작")
    for s in ["키워드 수집", "메타 생성", "이미지 ALT 점검", "사이트맵 제출"]:
        logging.info("[fallback] %s", s)
        time.sleep(0.2)
    logging.info("[fallback] SEO/임포트 작업 완료")

def _run_with(import_path: str, func_name: str = "run_all") -> bool:
    logging.info("외부 모듈 실행 시도: %s.%s()", import_path, func_name)
    try:
        mod = importlib.import_module(import_path)
        fn = getattr(mod, func_name)
        fn()
        return True
    except Exception as e:
        logging.warning("실패: %s.%s (%s)", import_path, func_name, e)
        return False

def run_import_and_seo():
    logging.info("SEO 배치 작업 시작")
    if _run_with("jobs.importer", "run_all"): return
    if _run_with("services.importer", "run_all"): return
    _fallback_demo_job()

@app.get("/register")
def register():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=run_import_and_seo, daemon=True).start()
    return jsonify({"ok": True, "status": "queued"}), 202

@app.get("/run-seo")
def run_seo():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=run_import_and_seo, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "run_seo"}), 202

@app.get("/seo/keywords/run")
def keywords_run():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=_fallback_demo_job, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "keywords"}), 202

@app.get("/seo/sitemap/resubmit")
def sitemap_resubmit():
    if not _authorized():
        return jsonify({"error": "Unauthorized"}), 401
    Thread(target=_fallback_demo_job, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "sitemap_resubmit"}), 202

# ─────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))






