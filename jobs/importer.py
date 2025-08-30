# jobs/importer.py
import os, time, logging, requests

# ─────────────────────────────────────────────────────────────
# 환경변수
STORE = os.environ.get("SHOPIFY_STORE", "").strip()               # 예: bj0b8k-kg
TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()         # Admin API Access Token
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-07").strip()
SITEMAP_URL = os.environ.get("SITEMAP_URL", "").strip()

# ─────────────────────────────────────────────────────────────
# HTTP 세션
SESSION = requests.Session()
if TOKEN:
    SESSION.headers.update({
        "X-Shopify-Access-Token": TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "shopify-auto-import/1.0"
    })

TIMEOUT = 20

def _api_base():
    if not STORE:
        raise RuntimeError("환경변수 SHOPIFY_STORE 누락 (예: bj0b8k-kg)")
    return f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}"

def _request(method, path, *, params=None, json=None):
    base = _api_base()
    url = f"{base}/{path.lstrip('/')}"
    last_err = None
    for attempt in range(5):
        try:
            r = SESSION.request(method, url, params=params, json=json, timeout=TIMEOUT)
            if r.status_code == 429:  # 레이트리밋
                time.sleep(0.6); continue
            r.raise_for_status()
            try:
                return r.json()
            except ValueError:
                return {"_raw": r.text}
        except requests.HTTPError as e:
            body = ""
            try: body = r.text[:500]
            except: pass
            status = getattr(e.response, "status_code", "N/A")
            if status == 404:
                logging.error("Shopify 404 (경로/스토어/버전 확인 필요): %s :: %s", url, body)
            elif status == 401:
                logging.error("Shopify 401 (토큰 없음/잘못됨): %s :: %s", url, body)
            elif status == 403:
                logging.error("Shopify 403 (스코프 부족? read_products 등): %s :: %s", url, body)
            else:
                logging.error("Shopify 요청 실패(%s): %s :: %s", status, url, body)
            last_err = e
            break   # 4xx는 즉시 중단
        except requests.RequestException as e:
            last_err = e
            time.sleep(0.4); continue
    raise RuntimeError(f"Shopify 요청 실패: {url}") from last_err

def _shopify_get(path, params=None):
    return _request("GET", path, params=params)

# ─────────────────────────────────────────────────────────────
# 진단/유틸
def _connectivity_check():
    logging.info("[check] /shop.json 호출로 연결 점검")
    data = _shopify_get("shop.json")
    shop = data.get("shop", {}) or {}
    logging.info("[check] 연결 OK: shop=%s, myshopify=%s, api_version=%s",
                 shop.get("name"), shop.get("myshopify_domain"), API_VERSION)

def _fetch_sample_products(n=5):
    data = _shopify_get("products.json", {"limit": n})
    items = data.get("products", [])
    logging.info("[shopify] 샘플 상품 %d개", len(items))
    for p in items:
        logging.info(" - %s | %s", p.get("id"), p.get("title"))
    return items

def _ping_sitemap():
    if not SITEMAP_URL:
        logging.info("[sitemap] SITEMAP_URL 없음 → 건너뜀"); return
    try:
        r = requests.get("https://www.google.com/ping",
                         params={"sitemap": SITEMAP_URL}, timeout=TIMEOUT)
        logging.info("[sitemap] Google ping %s (%d)", SITEMAP_URL, r.status_code)
    except requests.RequestException as e:
        logging.warning("[sitemap] ping 실패: %s", e)

# ─────────────────────────────────────────────────────────────
# 메인 플로우
def run_all():
    t0 = time.time()
    logging.info("[run_all] 실제 SEO/임포트 작업 시작")

    # 1) 연결/권한 점검 + 2) 샘플 조회 + 3) 사이트맵 핑
    _connectivity_check()
    _fetch_sample_products(5)
    _ping_sitemap()

    # 4) 실제 SEO 자동화 실행 (services.importer.run_all)
    from services.importer import run_all as seo_run_all
    seo_run_all()  # 메타 타이틀/디스크립션/ALT 업데이트

    logging.info("[run_all] 완료 (%.1fs)", time.time() - t0)

def run():
    missing = []
    if not STORE: missing.append("SHOPIFY_STORE")
    if not TOKEN: missing.append("SHOPIFY_ADMIN_TOKEN")
    if missing:
        logging.error("[run] 필수 환경변수 누락: %s", ", ".join(missing)); return
    try:
        run_all()
    except Exception as e:
        logging.exception("[run] 작업 실패: %s", e)





