# main.py — Unified (Existing features + New endpoints)
# Features:
# - Dashboard & reports
# - Inventory check/sync
# - SEO runner aliases
# - NEW: /sitemap-products.xml, /sitemap/ping (GET+POST), /seo/rewrite (GET+POST)
# - NEW: FAQ JSON-LD bootstrap/apply/preview
#
# Auth: IMPORT_AUTH_TOKEN (default: jeffshopsecure)
# Shopify: SHOPIFY_STORE, SHOPIFY_API_VERSION (default 2025-07), SHOPIFY_ADMIN_TOKEN

import os, sys, time, json, pathlib, datetime, logging, importlib
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

def _api_put(path, payload):
    if not SHOP:
        raise RuntimeError("SHOPIFY_STORE env is empty")
    url = f"https://{SHOP}.myshopify.com/admin/api/{API_VERSION}{path}"
    r = S.put(url, json=payload, timeout=TIMEOUT)
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
    from urllib.parse import quote as _q
    cfg = {
        "type": "line",
        "data": {"labels": labels, "datasets": [{"label": label, "data": values}]},
        "options": {"plugins": {"legend": {"display": False}}},
    }
    return f"https://quickchart.io/chart?c={_q(json.dumps(cfg, separators=(',',':')))}"

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
# NEW ①: 사이드카 사이트맵 (products)  — /sitemap-products.xml
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
# NEW ②: 사이트맵 Ping  — GET/POST /sitemap/ping?auth=...
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
# NEW ③: SEO Rewrite  — GET/POST /seo/rewrite?limit=10&dry_run=true
# ─────────────────────────────────────────────────────────────
@app.route("/seo/rewrite", methods=["GET", "POST"])
def seo_rewrite():
    if not _authorized():
        return _unauth()
    try:
        # GET에서도 사용 가능하도록 query에서 읽음
        limit = int(request.args.get("limit", 10))
        dry = (request.args.get("dry_run") or "").lower() in ("1","true","yes")

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
            _api_put(f"/products/{pid}.json", payload)
            rec = {"event": "seo_rewrite", "product_id": pid, "handle": p.get("handle"), "title": title_tag, "description": desc_tag}
            _append_row(rec)
            changed.append(rec)
        return jsonify({"ok": True, "count": len(changed), "items": changed, "dry_run": dry})
    except Exception as e:
        _append_row({"event": "seo_rewrite_error", "error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# NEW ④: FAQ JSON-LD 지원
#   - 메타필드 정의 생성(custom.faq_json)
#   - 제품에 FAQ JSON upsert
#   - 미리보기
# ─────────────────────────────────────────────────────────────
FAQ_NAMESPACE = "custom"
FAQ_KEY = "faq_json"
FAQ_TYPE = "json"  # Shopify metafield type

def _ensure_faq_definition():
    """custom.faq_json 메타필드 정의가 없으면 생성"""
    try:
        q = {"namespace": FAQ_NAMESPACE, "key": FAQ_KEY, "owner_types[]": "product"}
        exists = _api_get("/metafield_definitions.json", params=q).get("metafield_definitions", [])
        if exists:
            return {"ok": True, "created": False, "definition": exists[0]}
        payload = {
            "metafield_definition": {
                "name": "Product FAQ JSON",
                "namespace": FAQ_NAMESPACE,
                "key": FAQ_KEY,
                "type": FAQ_TYPE,
                "description": "Google FAQPage markup(JSON-LD) source for the product",
                "owner_types": ["product"]
            }
        }
        created = _api_post("/metafield_definitions.json", payload).get("metafield_definition")
        return {"ok": True, "created": True, "definition": created}
    except Exception as e:
        logging.exception("ensure_faq_definition error")
        return {"ok": False, "error": str(e)}

def _product_map(limit=250):
    """handle -> {id, handle, title} 매핑"""
    res = _api_get("/products.json", params={"limit": limit, "fields": "id,handle,title,status,published_at"})
    out = {}
    for p in res.get("products", []):
        out[p.get("handle")] = {"id": p.get("id"), "handle": p.get("handle"), "title": p.get("title")}
    return out

def _qa_list_to_jsonld(qas):
    """[['Q','A'], ...] -> JSON-LD dict"""
    main_entity = [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q,a in qas]
    return {
        "@context":"https://schema.org",
        "@type":"FAQPage",
        "mainEntity": main_entity
    }

def _upsert_product_faq(product_id: int, qas, dry=False):
    """제품 메타필드 upsert. dry=True면 API 호출 없이 preview만 반환"""
    value_obj = _qa_list_to_jsonld(qas)
    if dry:
        return {"dry_run": True, "value": value_obj}
    try:
        payload = {
            "metafield": {
                "namespace": FAQ_NAMESPACE,
                "key": FAQ_KEY,
                "type": FAQ_TYPE,
                "value": value_obj
            }
        }
        created = _api_post(f"/products/{product_id}/metafields.json", payload).get("metafield")
        return {"dry_run": False, "metafield": created}
    except Exception as e:
        return {"error": str(e)}

@app.route("/seo/faq/bootstrap", methods=["GET", "POST"])
def faq_bootstrap():
    if not _authorized(): return _unauth()
    out = _ensure_faq_definition()
    if out.get("ok"):
        return jsonify({"ok": True, "created": out.get("created", False), "definition": out.get("definition")})
    return jsonify({"ok": False, "error": out.get("error","unknown")}), 500

@app.route("/seo/faq/apply", methods=["GET", "POST"])
def faq_apply():
    """
    POST body 예시:
    {
      "dry_run": true,
      "default_when_empty": true,
      "items": [
        {"handle":"aluminum-desktop-phone-holder-gravity-electric-stand",
         "qas":[["각도 조절이 가능한가요?","네, 자유로운 각도/높이 조절이 가능합니다."]]}
      ]
    }
    GET로 호출 시엔 샘플 드라이런으로 동작
    """
    if not _authorized(): return _unauth()

    # GET이면 샘플 드라이런
    body = request.get_json(silent=True) or {}
    if request.method == "GET":
        body = {
            "dry_run": True,
            "default_when_empty": True,
            "items": body.get("items") or []
        }

    dry = bool(body.get("dry_run"))
    default_when_empty = bool(body.get("default_when_empty"))
    items = body.get("items") or []

    # 정의 보장
    ensure = _ensure_faq_definition()
    if not ensure.get("ok"):
        return jsonify({"ok": False, "error": ensure.get("error","faq_definition_failed")}), 500

    # 제품 맵
    pmap = _product_map(limit=250)

    results, errors = [], []
    # items가 비어있고 default_when_empty면 최근 active 제품 일부에 기본 Q/A 적용
    if not items and default_when_empty:
        # 기본 Q/A
        default_qas = [
            ["배송은 얼마나 걸리나요?", "결제 후 평균 1~3영업일 내 출고되며, 지역에 따라 상이할 수 있습니다."],
            ["반품/교환이 가능한가요?", "상품 수령 후 7일 이내 미사용/훼손없음 조건에서 가능합니다."],
            ["A/S는 어떻게 받나요?", "구매내역과 함께 고객센터로 문의 주시면 안내드립니다."]
        ]
        # 앞쪽 5개 정도만 대상
        targets = list(pmap.values())[:5]
        for t in targets:
            r = _upsert_product_faq(t["id"], default_qas, dry=dry)
            if "error" in r: errors.append({"handle": t["handle"], "error": r["error"]})
            else:
                results.append({"handle": t["handle"], "product_id": t["id"], **r})
        return jsonify({"ok": True, "count": len(results), "items": results, "errors": errors, "dry_run": dry})

    # 명시 items 처리
    for it in items:
        handle = it.get("handle")
        qas = it.get("qas") or []
        if not handle or not qas:
            errors.append({"handle": handle, "error": "invalid_item"}); continue
        prod = pmap.get(handle)
        if not prod:
            errors.append({"handle": handle, "error": "product_not_found"}); continue
        r = _upsert_product_faq(prod["id"], qas, dry=dry)
        if "error" in r: errors.append({"handle": handle, "error": r["error"]})
        else:
            results.append({"handle": handle, "product_id": prod["id"], **r})

    return jsonify({"ok": True, "count": len(results), "items": results, "errors": errors, "dry_run": dry})

@app.get("/seo/faq/preview")
def faq_preview():
    """handle 로 저장된 faq_json을 JSON-LD 스니펫으로 렌더"""
    if not _authorized(): return _unauth()
    handle = request.args.get("handle", "").strip()
    if not handle:
        return jsonify({"ok": False, "error": "missing_handle"}), 400
    # product id 찾기
    pmap = _product_map(limit=250)
    prod = pmap.get(handle)
    if not prod:
        return jsonify({"ok": False, "error": "product_not_found"}), 404

    # 메타필드 조회
    try:
        metas = _api_get(f"/products/{prod['id']}/metafields.json",
                         params={"namespace": FAQ_NAMESPACE, "key": FAQ_KEY}).get("metafields", [])
        target = None
        for m in metas:
            if m.get("namespace")==FAQ_NAMESPACE and m.get("key")==FAQ_KEY:
                target = m; break
        if not target:
            return jsonify({"ok": False, "error": "faq_metafield_not_set"}), 404
        val = target.get("value")
        if isinstance(val, str):
            try: val = json.loads(val)
            except: pass
        jsonld = json.dumps(val, ensure_ascii=False, separators=(',',':'))
        html = f'<!doctype html><meta charset="utf-8"><title>FAQ JSON-LD Preview</title>' \
               f'<pre>{json.dumps(val, ensure_ascii=False, indent=2)}</pre>' \
               f'<h3>Embed snippet</h3>' \
               f'<pre>&lt;script type="application/ld+json"&gt;{jsonld}&lt;/script&gt;</pre>'
        return Response(html, mimetype="text/html")
    except Exception as e:
        logging.exception("faq_preview error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# TEST UI — /tests (buttons that mirror your curl examples)
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
  <h3>6) FAQ Bootstrap</h3>
  <button onclick="go('/seo/faq/bootstrap', 'POST', true)">POST /seo/faq/bootstrap?auth=...</button>
  <pre id="out6"></pre>
</div>
<div class="card">
  <h3>7) FAQ Apply (샘플 드라이런)</h3>
  <button onclick="go('/seo/faq/apply', 'GET', true)">GET /seo/faq/apply?auth=... (dry)</button>
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
    const map={'/health':'out1','/sitemap-products.xml':'out2','/sitemap/ping':'out3','/seo/rewrite?limit=5&dry_run=true':'out4','/seo/rewrite?limit=5':'out5','/seo/faq/bootstrap':'out6','/seo/faq/apply':'out7'}
    const key = Object.keys(map).find(k=>path.startsWith(k.split('?')[0]));
    el(map[key]||'out1').textContent = out;
  }catch(e){
    alert('요청 실패: '+e);
  }
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
