# jobs/importer.py
import os, time, logging, requests

# ── 환경변수 ─────────────────────────────────────────────────────────────
STORE       = os.environ.get("SHOPIFY_STORE", "").strip()
TOKEN       = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-07").strip()
SITEMAP_URL = os.environ.get("SITEMAP_URL", "").strip()

# ── HTTP 세션 ────────────────────────────────────────────────────────────
SESSION = requests.Session()
if TOKEN:
    SESSION.headers.update({
        "X-Shopify-Access-Token": TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "shopify-auto-import/1.0"
    })
TIMEOUT = 20

# ── 유틸 ─────────────────────────────────────────────────────────────────
def _base_url(path: str) -> str:
    return f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/{path.lstrip('/')}"

def _request(method: str, path: str, params=None, json=None):
    if not STORE or not TOKEN:
        raise RuntimeError("SHOPIFY_STORE 또는 SHOPIFY_ADMIN_TOKEN 누락")

    url = _base_url(path)
    backoff = 0.5
    for attempt in range(5):
        try:
            r = SESSION.request(method, url, params=params, json=json, timeout=TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff)
                backoff = min(backoff * 1.8, 5.0)
                continue
            r.raise_for_status()
            if r.text and r.headers.get("Content-Type","").startswith("application/json"):
                return r.json()
            return {}
        except requests.RequestException as e:
            if attempt < 4:
                time.sleep(backoff)
                backoff = min(backoff * 1.8, 5.0)
                continue
            body = getattr(e, "response", None).text if getattr(e, "response", None) else ""
            status = getattr(e, "response", None).status_code if getattr(e, "response", None) else "N/A"
            raise RuntimeError(f"Shopify 요청 실패({status}): {url} :: {body}") from e

def _shopify_get(path: str, params=None):
    return _request("GET", path, params=params)

# ── 작업 루틴 ────────────────────────────────────────────────────────────
def _fetch_sample_products(n=5):
    data = _shopify_get("products.json", {"limit": n})
    items = data.get("products", []) if isinstance(data, dict) else []
    logging.info("[shopify] 샘플 상품 %d개", len(items))
    for p in items:
        logging.info(" - %s | %s", p.get("id"), p.get("title"))
    return items

def _ping_sitemap():
    if not SITEMAP_URL:
        logging.info("[sitemap] SITEMAP_URL 없음, 건너뜀")
        return
    try:
        r = requests.get("https://www.google.com/ping", params={"sitemap": SITEMAP_URL}, timeout=TIMEOUT)
        logging.info("[sitemap] Google ping %s (%d)", SITEMAP_URL, r.status_code)
    except requests.RequestException as e:
        logging.warning("[sitemap] ping 실패: %s", e)

def run_all():
    t0 = time.time()
    logging.info("[run_all] 실제 SEO/임포트 작업 시작")
    _fetch_sample_products(5)
    _ping_sitemap()
    # TODO: 상품 생성/수정, SEO 메타 갱신, 이미지 ALT 채우기 등
    logging.info("[run_all] 완료 (%.1fs)", time.time() - t0)

def run():
    """main.py에서 호출할 수 있는 진입점(옵션)"""
    try:
        run_all()
    except Exception as e:
        logging.exception("[run] 작업 실패: %s", e)


