# main.py — Unified (Existing features + New endpoints)
# Features:
# - Dashboard & reports
# - Inventory check/sync
# - SEO runner aliases
# - Sitemap: /sitemap-products.xml, /sitemap/ping (GET+POST)
# - SEO rewrite (POST /seo/rewrite)
# - NEW:
#   * GSC CSV low-CTR: /gsc/low-ctr/upload, /gsc/low-ctr/list
#   * Rewrite by handles: /seo/rewrite/by-handles (POST)
#   * FAQ JSON metafield bootstrap: /seo/faq/bootstrap (GET)
#   * FAQ JSON-LD preview: /seo/faq/jsonld?handle=... (GET)
#
# Auth: IMPORT_AUTH_TOKEN (default: jeffshopsecure)
# Shopify: SHOPIFY_STORE, SHOPIFY_API_VERSION (default 2025-07), SHOPIFY_ADMIN_TOKEN

import os, sys, time, json, pathlib, datetime, logging, importlib, re, csv
from threading import Thread
from urllib.parse import quote
from flask import Flask, jsonify, request, Response, render_template_string
import requests

print("[BOOT] importing main.py...")

# ─────────────────────────────────────────────────────────────
# 인증 토큰 (통일: IMPORT_AUTH_TOKEN, 기본값 jeffshopsecure)
# ─────────────────────────────────────────────────────────────
AUTH_TOKEN = os.environ.get("IMPORT_AUTH_TOKEN", "jeffshopsecure")

# ─────────────────────────────────────────────────────────────
# Shopify Admin API 환경변수
# ─────────────────────────────────────────────────────────────
SHOP = os.environ.get("SHOPIFY_STORE", "").strip()                 # ex) bj0b8k-kg
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-07").strip()
ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
TIMEOUT = 20

S = requests.Session()
if ADMIN_TOKEN:
    S.headers.update({
        "X-Shopify-Access-Token": ADMIN_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "shopify-auto-import/1.0",
    })

def _api_get(path, params=None):
    if not SHOP:
        raise RuntimeError("SHOPIFY_STORE env is empty")
    url = f"https://{SHOP}.myshopify.com/admin/api/{API_VERSION}{path}"
    r = S.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def _api_post(path, payload):
    if not SHOP:
        raise RuntimeError("SHOPIFY_STORE env is empty")
    url = f"https://{SHOP}.myshopify.com/admin/api/{API_VERSION}{path}"
    r = S.post(url, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

# ─────────────────────────────────────────────────────────────
# 리포트 저장소
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
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except:
            pass
    return out

def _quickchart_url(labels, values, label="CTR %"):
    cfg = {
        "type": "line",
        "data": {"labels": labels, "datasets": [{"label": label, "data": values}]},
        "options": {"plugins": {"legend": {"display": False}}},
    }
    return f"https://quickchart.io/chart?c={quote(json.dumps(cfg, separators=(',',':')))}"

# ─────────────────────────────────────────────────────────────
# Flask
# ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = Flask(__name__)
print("[BOOT] Flask app instantiated")

def _authorized() -> bool:
    return (
        request.args.get("auth", "") == AUTH_TOKEN
        or request.headers.get("X-Admin-Auth", "") == AUTH_TOKEN
    )

def _unauth():
    return jsonify({"ok": False, "error": "unauthorized"}), 401

# 기본
@app.get("/")
def home():
    return jsonify({"message": "Shopify 자동 등록 서버가 실행 중입니다."})

@app.get("/health")
def health():
    return {"status": "ok"}, 200

@app.route("/keep-alive", methods=["GET", "HEAD"])
def keep_alive():
    if not _authorized():
        return _unauth()
    return jsonify({"status": "alive"}), 200

# ─────────────────────────────────────────────────────────────
# 대시보드(브라우저 점검용)
# ─────────────────────────────────────────────────────────────
DASH_HTML = """
<!doctype html>
<meta charset="utf-8"/>
<title>Jeff Shopify Dashboard</title>
<style>
  body{font-family:system-ui,Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#222}
  h1{margin:0 0 16px}
  .row{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
  button{padding:10px 14px;border:1px solid #ddd;border-radius:10px;cursor:pointer;background:#fff}
  button:hover{background:#f7f7f7}
  textarea, input{width:100%;box-sizing:border-box}
  .card{border:1px solid #eee;border-radius:12px;padding:14px;margin:12px 0}
  .muted{color:#666}
  pre{white-space:pre-wrap;word-break:break-word;background:#fafafa;border:1px solid #eee;border-radius:8px;padding:10px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
</style>
<h1>Jeff’s Favorite Picks – Admin Dashboard</h1>
<p class="muted">이 페이지는 서버 내부 점검용입니다. 주소를 외부에 공유하지 마세요.</p>

<div class="row">
  <button onclick="ping()">1) Shopify Ping</button>
  <button onclick="checkInventory()">2) 재고 현황</button>
  <a href="/tests?auth=" id="testsLink">▶ Test Playground 열기</a>
</div>

<div class="card">
  <h3>3) 동기화 실행 (공급사 재고 → Shopify)</h3>
  <p class="muted">예시 payload: [{"sku":"MAGSAFE-CASE-BLACK","qty":25},{"sku":"USB-C-LED-CABLE","qty":0}]</p>
  <div class="grid">
    <div>
      <textarea id="syncPayload" rows="6">[{"sku":"MAGSAFE-CASE-BLACK","qty":25},{"sku":"USB-C-LED-CABLE","qty":0}]</textarea>
    </div>
    <div>
      <button onclick="sync()">실행</button>
      <p class="muted">응답</p>
      <pre id="syncOut"></pre>
    </div>
  </div>
</div>

<div class="card">
  <h3>결과</h3>
  <pre id="out"></pre>
</div>

<script>
const AUTH = new URLSearchParams(location.search).get("auth") || "";
document.getElementById('testsLink').href = '/tests?auth=' + encodeURIComponent(AUTH);
function show(el, data){ document.getElementById(el).textContent = typeof data==="string" ? data : JSON.stringify(data,null,2); }
async function api(path, opts={}){
  const q = path.includes("?") ? "&" : "?";
  const res = await fetch(path + q + "auth=" + encodeURIComponent(AUTH), opts);
  const txt = await res.text();
  try { return JSON.parse(txt); } catch { return txt; }
}
async function ping(){ const r = await api("/shopify/ping"); show("out", r); }
async function checkInventory(){ const r = await api("/inventory/check"); show("out", r); }
async function sync(){
  let arr = [];
  try { arr = JSON.parse(document.getElementById("syncPayload").value); }
  catch(e){ return show("syncOut", "JSON 파싱 오류: " + e); }
  const r = await api("/inventory/sync", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({items:arr}) });
  show("syncOut", r);
}
</script>
"""
@app.get("/dashboard")
def dashboard():
    if not _authorized():
        return _unauth()
    return render_template_string(DASH_HTML)

# ─────────────────────────────────────────────────────────────
# Admin API 연결 점검
# ─────────────────────────────────────────────────────────────
@app.get("/shopify/ping")
def shopify_ping():
    if not _authorized():
        return _unauth()
    try:
        data = _api_get("/shop.json")
        return jsonify({"ok": True, "shop": data.get("shop", {}).get("name")})
    except Exception as e:
        logging.exception("shopify_ping error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# 리포트
# ─────────────────────────────────────────────────────────────
@app.get("/report/add")
def report_add():
    if not _authorized():
        return _unauth()
    def _num(name, default=0.0):
        try: return float(request.args.get(name, default))
        except: return float(default)
    row = {
        "date": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d"),
        "perf": _num("perf", 0), "acc": _num("acc", 0), "bp": _num("bp", 0), "seo": _num("seo", 0),
        "ctr": _num("ctr", 0), "lcp": _num("lcp", 0), "tbt": _num("tbt", 0),
        "updated": int(_num("updated", 0)), "notes": request.args.get("notes", "")
    }
    _append_row(row)
    return {"ok": True, "saved": row}

@app.get("/report/history")
def report_history():
    if not _authorized():
        return _unauth()
    limit = int(request.args.get("limit", 30))
    return jsonify({"ok": True, "rows": _load_rows(limit=limit)})

@app.get("/report/daily")
def report_daily():
    rows = _load_rows(limit=30)
    today = rows[-1] if rows else {}
    date_str = today.get("date", datetime.date.today().isoformat())
    perf = today.get("perf", 0); acc = today.get("acc", 0); bp = today.get("bp", 0); seo = today.get("seo", 0)
    lcp = today.get("lcp", 0); tbt = today.get("tbt", 0); ctr = today.get("ctr", 0); updated = today.get("updated", 0)
    labels = [r.get("date","") for r in rows[-10:]] or [date_str]
    ctr_vals = [r.get("ctr", 0) for r in rows[-10:]] or [ctr]
    chart_url = _quickchart_url(labels, ctr_vals, label="CTR %")
    html = f"""<!DOCTYPE html><meta charset="utf-8"/><title>Daily SEO Summary</title>
<style>body{{font-family:Arial;max-width:900px;margin:24px auto;color:#333}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #e5e5e5;padding:10px;text-align:left}}</style>
<h2>📅 Daily SEO Summary ({date_str})</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Performance</td><td>{perf:.0f}</td></tr>
<tr><td>Accessibility</td><td>{acc:.0f}</td></tr>
<tr><td>Best Practices</td><td>{bp:.0f}</td></tr>
<tr><td>SEO</td><td>{seo:.0f}</td></tr>
<tr><td>LCP</td><td>{lcp:.2f} s</td></tr>
<tr><td>TBT</td><td>{int(tbt)} ms</td></tr>
<tr><td>CTR</td><td>{ctr:.2f}%</td></tr>
<tr><td>SEO Updates Applied</td><td>{updated}</td></tr>
</table>
<h3>📈 CTR Trend (최근 10일)</h3><img src="{chart_url}" width="600"/>
<p style="color:#777;font-size:12px">Generated {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")}</p>"""
    return Response(html, mimetype="text/html")

# ─────────────────────────────────────────────────────────────
# SEO/임포트 실행부
# ─────────────────────────────────────────────────────────────
from datetime import timezone, timedelta
LAST_RUN_TS = None  # 마지막 실행 시작(UTC)

def _fallback_demo_job():
    logging.info("[fallback] SEO/임포트 작업 시작")
    for s in ["키워드 수집", "메타 생성", "이미지 ALT 점검", "사이트맵 제출"]:
        logging.info("[fallback] %s", s); time.sleep(0.2)
    logging.info("[fallback] SEO/임포트 작업 완료")

def _run_with_kwargs(import_path: str, func_name: str = "run_all", kwargs=None) -> bool:
    kwargs = kwargs or {}
    logging.info("외부 모듈 실행 시도: %s.%s(%s)", import_path, func_name, kwargs)
    try:
        mod = importlib.import_module(import_path)
        fn = getattr(mod, func_name)
        fn(**kwargs)
        return True
    except Exception as e:
        logging.warning("실패: %s.%s (%s)", import_path, func_name, e)
        return False

def run_import_and_seo(kwargs=None):
    global LAST_RUN_TS
    LAST_RUN_TS = datetime.datetime.utcnow().replace(tzinfo=timezone.utc)
    logging.info("SEO 배치 작업 시작")
    if _run_with_kwargs("jobs.importer", "run_all", kwargs): return
    if _run_with_kwargs("services.importer", "run_all", kwargs): return
    _fallback_demo_job()

@app.get("/register")
def register():
    if not _authorized(): return _unauth()
    Thread(target=run_import_and_seo, kwargs={"kwargs": {}}, daemon=True).start()
    return jsonify({"ok": True, "status": "queued"}), 202

@app.get("/run-seo")
def run_seo():
    if not _authorized(): return _unauth()
    Thread(target=run_import_and_seo, kwargs={"kwargs": {}}, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "run_seo"}), 202

# 별칭: /seo/run?dry=1&limit=10
@app.get("/seo/run")
def seo_run_alias():
    if not _authorized(): return _unauth()
    dry_q = (request.args.get("dry") or request.args.get("simulate") or "").lower()
    dry = dry_q in ("1", "true", "yes", "y")
    try:
        limit = int(request.args.get("limit")) if request.args.get("limit") is not None else None
    except Exception:
        limit = None
    kwargs = {}
    if limit is not None: kwargs["limit"] = limit
    if dry: kwargs["dry"] = True
    Thread(target=run_import_and_seo, kwargs={"kwargs": kwargs}, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "seo_run", "args": kwargs}), 202

@app.get("/seo/keywords/run")
def keywords_run():
    if not _authorized(): return _unauth()
    Thread(target=_fallback_demo_job, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "keywords"}), 202

@app.get("/seo/sitemap/resubmit")
def sitemap_resubmit():
    if not _authorized(): return _unauth()
    Thread(target=_fallback_demo_job, daemon=True).start()
    return jsonify({"ok": True, "status": "queued", "job": "sitemap_resubmit"}), 202

# ─────────────────────────────────────────────────────────────
# 재고 점검/동기화
# ─────────────────────────────────────────────────────────────
@app.get("/inventory/check")
def inventory_check():
    if not _authorized(): return _unauth()
    try:
        res = _api_get("/products.json", params={"limit": 250})
    except Exception as e:
        logging.exception("inventory_check products error")
        return jsonify({"ok": False, "error": f"shopify_api: {e}"}), 500

    total, avail, oos = 0, 0, 0
    samples = []
    for p in res.get("products", []):
        total += 1
        any_ok, all_oos = False, True
        for v in p.get("variants", []):
            iq = v.get("inventory_quantity")
            if (isinstance(iq, int) and iq > 0) or (v.get("inventory_policy") == "continue"):
                any_ok, all_oos = True, False; break
        if any_ok: avail += 1
        elif all_oos:
            oos += 1
            if len(samples) < 20:
                samples.append({
                    "title": p.get("title"),
                    "handle": p.get("handle"),
                    "admin_url": f"https://admin.shopify.com/store/{SHOP}/products/{p.get('id')}"
                })

    return jsonify({
        "ok": True, "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "total_products": total, "available_products": avail, "sold_out_products": oos,
        "samples": samples
    })

@app.post("/inventory/sync")
def inventory_sync():
    if not _authorized(): return _unauth()
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    if not items: return jsonify({"ok": False, "error": "empty_items"}), 400

    updated, errors = [], []
    try:
        locs = _api_get("/locations.json").get("locations", [])
        if not locs: return jsonify({"ok": False, "error": "no_location"}), 500
        location_id = locs[0]["id"]
    except Exception as e:
        logging.exception("inventory_sync locations error")
        return jsonify({"ok": False, "error": str(e)}), 500

    for it in items:
        sku = it.get("sku"); qty = int(it.get("qty", 0))
        try:
            vres = _api_get("/variants.json", params={"sku": sku})
            variants = vres.get("variants", [])
            if not variants:
                errors.append({"sku": sku, "error": "variant_not_found"}); continue
            inventory_item_id = variants[0]["inventory_item_id"]
            _api_post("/inventory_levels/set.json", {
                "location_id": location_id,
                "inventory_item_id": inventory_item_id,
                "available": max(qty, 0)
            })
            updated.append({"sku": sku, "qty": qty})
        except Exception as e:
            errors.append({"sku": sku, "error": str(e)})

    return jsonify({"ok": True, "updated": updated, "errors": errors})

# ─────────────────────────────────────────────────────────────
# 최근 업데이트된 상품 조회
# ─────────────────────────────────────────────────────────────
def _iso(dt):
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")

@app.get("/report/recent-products")
def report_recent_products():
    """최근 N분 내에 업데이트된 상품(Shopify updated_at 기반) 목록"""
    if not _authorized(): return _unauth()
    try:
        minutes = int(request.args.get("minutes", 120))
        limit   = int(request.args.get("limit", 50))
    except:
        minutes, limit = 120, 50

    since = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)
    params = { "limit": 250, "updated_at_min": _iso(since) }
    try:
        res = _api_get("/products.json", params=params)
        items = []
        for p in res.get("products", [])[:limit]:
            items.append({
                "id": p.get("id"),
                "title": p.get("title"),
                "handle": p.get("handle"),
                "updated_at": p.get("updated_at"),
                "seo_title": p.get("metafields_global_title_tag"),
                "seo_description": p.get("metafields_global_description_tag"),
                "admin_url": f"https://admin.shopify.com/store/{SHOP}/products/{p.get('id')}"
            })
        return jsonify({"ok": True, "since": _iso(since), "count": len(items), "items": items})
    except Exception as e:
        logging.exception("report_recent_products error")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/report/last-run-products")
def report_last_run_products():
    """마지막 실행 시작 시각 이후로 Shopify가 updated_at을 기록한 상품"""
    if not _authorized(): return _unauth()
    if not LAST_RUN_TS:
        return jsonify({"ok": False, "error": "no_last_run_timestamp"}), 400
    since = LAST_RUN_TS - datetime.timedelta(minutes=2)  # 안전 버퍼
    params = {"limit": 250, "updated_at_min": _iso(since)}
    try:
        res = _api_get("/products.json", params=params)
        items = []
        for p in res.get("products", []):
            items.append({
                "id": p.get("id"),
                "title": p.get("title"),
                "handle": p.get("handle"),
                "updated_at": p.get("updated_at"),
                "seo_title": p.get("metafields_global_title_tag"),
                "seo_description": p.get("metafields_global_description_tag"),
                "admin_url": f"https://admin.shopify.com/store/{SHOP}/products/{p.get('id')}"
            })
        return jsonify({
            "ok": True,
            "last_run_ts": _iso(LAST_RUN_TS),
            "count": len(items),
            "items": items
        })
    except Exception as e:
        logging.exception("report_last_run_products error")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/report/last-updated-products")
def report_last_updated_products():
    """
    services/importer.py 가 기록한 “이번 실행에서 실제로 변경된 상품” 목록 반환.
    파일: /tmp/last_updated_products.json
    """
    if not _authorized(): return _unauth()
    path = pathlib.Path("/tmp/last_updated_products.json")
    if not path.exists():
        return jsonify({"ok": True, "count": 0, "items": []})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return jsonify({"ok": True, **data})
    except Exception as e:
        logging.exception("report_last_updated_products error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Sitemap (products)  — /sitemap-products.xml
# ─────────────────────────────────────────────────────────────
@app.get("/sitemap-products.xml")
def sitemap_products():
    if not _authorized():
        return _unauth()
    try:
        params = {"limit": 200, "fields": "id,handle,updated_at,images,published_at,status"}
        data = _api_get("/products.json", params=params)
        items = []
        for p in data.get("products", []):
            if p.get("status") != "active" or not p.get("published_at"):
                continue
            loc = f"https://{SHOP}.myshopify.com/products/{p['handle']}"
            lastmod = p.get("updated_at", datetime.datetime.utcnow().isoformat() + "Z")
            image_tags = ""
            imgs = p.get("images") or []
            if imgs and imgs[0].get("src"):
                image_tags = f"""
    <image:image>
      <image:loc>{imgs[0]['src']}</image:loc>
      <image:title>{p['handle']}</image:title>
    </image:image>"""
            items.append(f"""
  <url>
    <loc>{loc}</loc>
    <lastmod>{lastmod}</lastmod>{image_tags}
  </url>""")
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
{''.join(items)}
</urlset>"""
        return Response(body, mimetype="application/xml")
    except Exception as e:
        return Response(f"<!-- error: {e} -->", mimetype="application/xml", status=500)

# ─────────────────────────────────────────────────────────────
# Sitemap Ping  — GET/POST /sitemap/ping?auth=...
# ─────────────────────────────────────────────────────────────
@app.route("/sitemap/ping", methods=["GET", "POST"])
def sitemap_ping():
    if not _authorized():
        return _unauth()
    sitemap_url = request.url_root.rstrip("/") + "/sitemap-products.xml"
    ping_url = "https://www.google.com/ping?sitemap=" + quote(sitemap_url, safe="")
    try:
        r = requests.get(ping_url, timeout=TIMEOUT)
        ok = (200 <= r.status_code < 400)
        _append_row({"event": "sitemap_ping", "sitemap": sitemap_url, "google_status": r.status_code, "ok": ok})
        return jsonify({"ok": ok, "sitemap": sitemap_url, "google_status": r.status_code})
    except Exception as e:
        _append_row({"event": "sitemap_ping_error", "error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# SEO Rewrite  — POST /seo/rewrite?limit=10&dry_run=true
# (최근 활성 상품 N개)
# ─────────────────────────────────────────────────────────────
@app.post("/seo/rewrite")
def seo_rewrite():
    if not _authorized():
        return _unauth()
    try:
        limit = int(request.args.get("limit", 10))
        dry = (request.args.get("dry_run") or "").lower() in ("1","true","yes")

        # 최근 활성 제품 가져오기 (필요시 페이지네이션 확장)
        res = _api_get("/products.json", params={"limit": max(10, limit), "fields": "id,title,handle,status,published_at"})
        candidates = [p for p in res.get("products", []) if p.get("status") == "active" and p.get("published_at")]
        products = candidates[:limit]

        changed = []
        for p in products:
            pid = p["id"]
            base = (p.get("title") or "Best Pick").strip()
            title_tag = f"{(base[:40]).rstrip()} | Jeff’s Favorite Picks"
            desc_tag = "Fast shipping, easy returns, quality guaranteed. Grab yours today."

            if dry:
                changed.append({"id": pid, "handle": p.get("handle"), "title": title_tag, "description": desc_tag, "dry_run": True})
                continue

            payload = {"product": {"id": pid, "metafields_global_title_tag": title_tag, "metafields_global_description_tag": desc_tag}}
            _api_post(f"/products/{pid}.json", payload)
            rec = {"event": "seo_rewrite", "product_id": pid, "handle": p.get("handle"), "title": title_tag, "description": desc_tag}
            _append_row(rec)
            changed.append(rec)
        return jsonify({"ok": True, "count": len(changed), "items": changed, "dry_run": dry})
    except Exception as e:
        _append_row({"event": "seo_rewrite_error", "error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# NEW: GSC CSV 업로드 & Low-CTR 추출
# ─────────────────────────────────────────────────────────────
GSC_CSV_PATH = "/tmp/gsc_latest.csv"

def _url_to_handle(url: str):
    try:
        m = re.search(r"/products/([a-z0-9\-]+)/?", url)
        return m.group(1) if m else None
    except:
        return None

@app.post("/gsc/low-ctr/upload")
def gsc_upload():
    if not _authorized():
        return _unauth()
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "no_file"}), 400
    f.save(GSC_CSV_PATH)
    return jsonify({"ok": True, "saved": GSC_CSV_PATH})

@app.get("/gsc/low-ctr/list")
def gsc_list():
    if not _authorized():
        return _unauth()
    max_ctr = float(request.args.get("ctr_max", "1.5"))
    min_impr = int(request.args.get("impr_min", "200"))
    limit = int(request.args.get("limit", "20"))

    if not pathlib.Path(GSC_CSV_PATH).exists():
        return jsonify({"ok": False, "error": "no_csv_uploaded"}), 400

    rows = []
    with open(GSC_CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            page = r.get("Page") or r.get("Page URL") or r.get("page") or ""
            ctr_s = (r.get("CTR") or r.get("Click-through rate") or r.get("ctr") or "").replace("%","").strip()
            imp_s = (r.get("Impressions") or r.get("impressions") or r.get("Impr") or "0").replace(",","").strip()
            try:
                ctr = float(ctr_s)
                imp = int(imp_s)
            except:
                continue
            if ctr <= max_ctr and imp >= min_impr:
                handle = _url_to_handle(page or "")
                if handle:
                    rows.append({"page": page, "handle": handle, "ctr": ctr, "impressions": imp})

    agg = {}
    for r in rows:
        h = r["handle"]
        cur = agg.get(h, {"handle": h, "impressions": 0, "best_ctr": r["ctr"], "page": r["page"]})
        cur["impressions"] += r["impressions"]
        cur["best_ctr"] = min(cur["best_ctr"], r["ctr"])
        cur["page"] = r["page"]
        agg[h] = cur

    out = sorted(agg.values(), key=lambda x: (-x["impressions"], x["best_ctr"]))[:limit]
    return jsonify({"ok": True, "count": len(out), "items": out, "params": {"ctr_max": max_ctr, "impr_min": min_impr, "limit": limit}})

# ─────────────────────────────────────────────────────────────
# NEW: Admin GraphQL helper + 지정 핸들만 리라이트
# ─────────────────────────────────────────────────────────────
def _admin_graphql(query: str, variables=None):
    if not SHOP:
        raise RuntimeError("SHOPIFY_STORE env is empty")
    url = f"https://{SHOP}.myshopify.com/admin/api/{API_VERSION}/graphql.json"
    headers = S.headers.copy()
    headers["Content-Type"] = "application/json"
    r = requests.post(url, json={"query": query, "variables": variables or {}}, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data

def _product_id_by_handle(handle: str):
    q = """
    query($h: String!){
      productByHandle(handle: $h){ id handle title }
    }
    """
    data = _admin_graphql(q, {"h": handle})
    node = (((data or {}).get("data") or {}).get("productByHandle") or None)
    if not node:
        return None
    gid = node["id"]  # gid://shopify/Product/1234567890
    try:
        return int(gid.split("/")[-1])
    except:
        return None

@app.post("/seo/rewrite/by-handles")
def seo_rewrite_by_handles():
    if not _authorized():
        return _unauth()
    body = request.get_json(silent=True) or {}
    handles = body.get("handles") or []
    dry = bool(body.get("dry_run", False))
    if not handles:
        return jsonify({"ok": False, "error": "empty_handles"}), 400

    changed, errors = [], []
    for h in handles:
        pid = _product_id_by_handle(h)
        if not pid:
            errors.append({"handle": h, "error": "id_not_found"}); continue

        base = (h.replace("-", " ").title())[:40]
        title_tag = f"{base} | Jeff’s Favorite Picks"
        desc_tag = "Fast shipping, easy returns, quality guaranteed. Grab yours today."

        if dry:
            changed.append({"id": pid, "handle": h, "title": title_tag, "description": desc_tag, "dry_run": True})
            continue

        try:
            _api_post(f"/products/{pid}.json", {
                "product": {
                    "id": pid,
                    "metafields_global_title_tag": title_tag,
                    "metafields_global_description_tag": desc_tag
                }
            })
            _append_row({"event": "seo_rewrite", "product_id": pid, "handle": h, "title": title_tag})
            changed.append({"id": pid, "handle": h, "ok": True})
        except Exception as e:
            errors.append({"handle": h, "error": str(e)})

    return jsonify({"ok": True, "count": len(changed), "items": changed, "errors": errors, "dry_run": dry})

# ─────────────────────────────────────────────────────────────
# NEW: FAQ JSON 메타필드 부트스트랩 & JSON-LD 미리보기
# (REST로 제품별 메타필드 생성 — 정의 없어도 동작)
# ─────────────────────────────────────────────────────────────
DEFAULT_FAQ = [
    {"question": "배송은 얼마나 걸리나요?", "answer": "보통 2~5영업일 내 도착합니다."},
    {"question": "교환/반품이 가능한가요?", "answer": "수령 후 14일 이내 가능합니다. 간단한 사유와 함께 문의 주세요."},
]

def _get_product_by_handle(handle: str):
    try:
        res = _api_get("/products.json", params={"handle": handle})
        # handle 필터가 REST에 직접 없을 수 있어 전체에서 찾기
        for p in res.get("products", []):
            if p.get("handle") == handle:
                return p
        # 보조: 목록에서 스캔
        res2 = _api_get("/products.json", params={"limit": 250})
        for p in res2.get("products", []):
            if p.get("handle") == handle:
                return p
    except:
        pass
    return None

def _get_faq_metafield(product_id: int):
    # /products/{id}/metafields.json 로드 후 namespace/key 매칭
    try:
        mres = _api_get(f"/products/{product_id}/metafields.json")
        for m in mres.get("metafields", []):
            if m.get("namespace") == "custom" and m.get("key") == "faq_json":
                return m
    except Exception as e:
        logging.warning("get_faq_metafield error for %s: %s", product_id, e)
    return None

def _set_faq_metafield(product_id: int, faq_list):
    # value는 문자열(JSON)로, type은 json
    payload = {
        "metafield": {
            "namespace": "custom",
            "key": "faq_json",
            "type": "json",
            "value": json.dumps(faq_list, ensure_ascii=False)
        }
    }
    try:
        return _api_post(f"/products/{product_id}/metafields.json", payload)
    except Exception as e:
        # 이미 존재하는 경우 업데이트로 재시도
        existing = _get_faq_metafield(product_id)
        if existing:
            mf_id = existing.get("id")
            try:
                return _api_post(f"/metafields/{mf_id}.json", {
                    "metafield": {"id": mf_id, "value": json.dumps(faq_list, ensure_ascii=False)}
                })
            except Exception as e2:
                raise e2
        raise e

@app.get("/seo/faq/bootstrap")
def faq_bootstrap():
    if not _authorized():
        return _unauth()
    dry = (request.args.get("dry_run") or "").lower() in ("1","true","yes")
    limit = int(request.args.get("limit", "20"))
    # 활성 상품 대상
    res = _api_get("/products.json", params={"limit": max(50, limit), "fields": "id,handle,title,status,published_at"})
    targets = [p for p in res.get("products", []) if p.get("status")=="active" and p.get("published_at")][:limit]

    created, skipped, errors = [], [], []
    for p in targets:
        pid = p["id"]; handle = p.get("handle")
        mf = _get_faq_metafield(pid)
        if mf:
            skipped.append({"id": pid, "handle": handle})
            continue
        if dry:
            created.append({"id": pid, "handle": handle, "dry_run": True}); continue
        try:
            _set_faq_metafield(pid, DEFAULT_FAQ)
            created.append({"id": pid, "handle": handle, "ok": True})
        except Exception as e:
            errors.append({"id": pid, "handle": handle, "error": str(e)})

    return jsonify({"ok": True, "created": created, "skipped": skipped, "errors": errors, "dry_run": dry})

@app.get("/seo/faq/jsonld")
def faq_jsonld():
    """제품 handle을 받아 JSON-LD FAQPage 스니펫 생성(메타필드 기반, 없으면 기본)"""
    if not _authorized():
        return _unauth()
    handle = request.args.get("handle", "").strip()
    if not handle:
        return jsonify({"ok": False, "error": "missing_handle"}), 400

    product = _get_product_by_handle(handle)
    if not product:
        return jsonify({"ok": False, "error": "product_not_found"}), 404

    pid = product["id"]
    mf = _get_faq_metafield(pid)
    faq_list = DEFAULT_FAQ
    if mf:
        try:
            val = mf.get("value")
            if isinstance(val, str):
                faq_list = json.loads(val)
            elif isinstance(val, list):
                faq_list = val
        except Exception:
            pass

    items = []
    for qa in faq_list:
        q = qa.get("question") or ""
        a = qa.get("answer") or ""
        items.append({
            "@type": "Question",
            "name": q,
            "acceptedAnswer": {"@type": "Answer", "text": a}
        })

    ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": items
    }
    body = json.dumps(ld, ensure_ascii=False, separators=(",", ":"))
    return Response(body, mimetype="application/ld+json")

# ─────────────────────────────────────────────────────────────
# TEST UI — /tests
# ─────────────────────────────────────────────────────────────
TEST_HTML = """
<!doctype html>
<meta charset="utf-8">
<title>SEO Test Playground</title>
<style>
  body{font-family:system-ui,Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#222}
  input,button{padding:10px;border:1px solid #ddd;border-radius:10px}
  button{cursor:pointer;background:#fff}
  button:hover{background:#f7f7f7}
  .row{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
  pre{white-space:pre-wrap;word-break:break-word;background:#fafafa;border:1px solid #eee;border-radius:8px;padding:10px}
  .card{border:1px solid #eee;border-radius:12px;padding:14px;margin:12px 0}
</style>
<h1>SEO Test Playground</h1>
<p>아래 버튼들은 명령행 <code>curl</code> 예제를 브라우저에서 쉽게 실행할 수 있도록 만든 테스트 도구입니다.</p>
<div class="row">
  <label>Base URL <input id="base" size="50" value="https://shopify-auto-import.onrender.com"></label>
  <label>Auth <input id="auth" size="20" value="jeffshopsecure"></label>
</div>
<div class="card">
  <h3>1) 헬스체크</h3>
  <button onclick="go('/health')">GET /health</button>
  <pre id="out1"></pre>
</div>
<div class="card">
  <h3>2) 사이트맵 생성 확인</h3>
  <button onclick="go('/sitemap-products.xml', 'GET', true)">GET /sitemap-products.xml?auth=...</button>
  <pre id="out2"></pre>
</div>
<div class="card">
  <h3>3) Google 핑</h3>
  <button onclick="go('/sitemap/ping', 'POST', true)">POST /sitemap/ping?auth=...</button>
  <pre id="out3"></pre>
</div>
<div class="card">
  <h3>4) SEO 리라이트 (드라이런)</h3>
  <button onclick="go('/seo/rewrite?limit=5&dry_run=true', 'POST', true)">POST /seo/rewrite?limit=5&dry_run=true&auth=...</button>
  <pre id="out4"></pre>
</div>
<div class="card">
  <h3>5) SEO 리라이트 (실행)</h3>
  <button onclick="go('/seo/rewrite?limit=5', 'POST', true)">POST /seo/rewrite?limit=5&auth=...</button>
  <pre id="out5"></pre>
</div>
<div class="card">
  <h3>6) FAQ 부트스트랩 (드라이런)</h3>
  <button onclick="go('/seo/faq/bootstrap?limit=10&dry_run=true', 'GET', true)">GET /seo/faq/bootstrap?limit=10&dry_run=true&auth=...</button>
  <pre id="out6"></pre>
</div>
<div class="card">
  <h3>7) GSC CSV 업로드 & Low-CTR</h3>
  <input type="file" id="csvFile">
  <button onclick="uploadCSV()">POST /gsc/low-ctr/upload</button>
  <button onclick="go('/gsc/low-ctr/list', 'GET', true)">GET /gsc/low-ctr/list?auth=...</button>
  <pre id="out7"></pre>
</div>
<script>
function el(id){return document.getElementById(id)}
function b(){return (el('base').value||'').replace(/\/$/,'')}
function a(){return el('auth').value||''}
async function go(path, method='GET', needsAuth=false){
  const base=b(); const auth=a();
  let url=base+path;
  if(needsAuth){ url += (url.includes('?')?'&':'?') + 'auth=' + encodeURIComponent(auth); }
  try{
    const res = await fetch(url, {method});
    const txt = await res.text();
    let out = txt;
    try{ out = JSON.stringify(JSON.parse(txt), null, 2); }catch{}
    const map={'/health':'out1','/sitemap-products.xml':'out2','/sitemap/ping':'out3',
               '/seo/rewrite?limit=5&dry_run=true':'out4','/seo/rewrite?limit=5':'out5',
               '/seo/faq/bootstrap':'out6','/gsc/low-ctr/list':'out7'}
    const key = Object.keys(map).find(k=>path.startsWith(k.split('?')[0]));
    el(map[key]||'out1').textContent = out;
  }catch(e){
    alert('요청 실패: '+e);
  }
}

async function uploadCSV(){
  const base=b(); const auth=a();
  const f = el('csvFile').files[0];
  if(!f){ alert('CSV 파일을 선택하세요'); return; }
  const fd = new FormData(); fd.append('file', f);
  const url = base + '/gsc/low-ctr/upload?auth=' + encodeURIComponent(auth);
  const res = await fetch(url, { method: 'POST', body: fd });
  const txt = await res.text();
  try{ el('out7').textContent = JSON.stringify(JSON.parse(txt), null, 2); }
  catch{ el('out7').textContent = txt; }
}
</script>
"""

@app.get("/tests")
def tests_page():
    if not _authorized():
        return _unauth()
    return Response(TEST_HTML, mimetype="text/html")

print("[BOOT] main.py loaded successfully")

# ─────────────────────────────────────────────────────────────
# 실행 (개발 로컬에서만 의미 있음; Render는 gunicorn이 사용)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

