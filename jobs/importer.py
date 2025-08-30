# jobs/importer.py
import os, time, logging, requests

STORE = os.environ.get("SHOPIFY_STORE","").strip()
TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN","").strip()
API_VERSION = os.environ.get("SHOPIFY_API_VERSION","2024-04").strip()
SITEMAP_URL = os.environ.get("SITEMAP_URL","").strip()

SESSION = requests.Session()
SESSION.headers.update({"X-Shopify-Access-Token": TOKEN, "Content-Type":"application/json"})
TIMEOUT = 20

def _shopify(path, params=None):
    url = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/{path.lstrip('/')}"
    for _ in range(3):
        r = SESSION.get(url, params=params, timeout=TIMEOUT)
        if r.status_code == 429:
            time.sleep(0.6); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Shopify 요청 실패: {url}")

def _fetch_sample_products(n=5):
    data = _shopify("products.json", {"limit": n})
    items = data.get("products", [])
    logging.info("[shopify] 샘플 상품 %d개", len(items))
    for p in items:
        logging.info(" - %s | %s", p.get("id"), p.get("title"))
    return items

def _ping_sitemap():
    if not SITEMAP_URL:
        logging.info("[sitemap] SITEMAP_URL 없음, 건너뜀")
        return
    try:
        r = requests.get("https://www.google.com/ping",
                         params={"sitemap": SITEMAP_URL}, timeout=TIMEOUT)
        logging.info("[sitemap] Google ping %s (%d)", SITEMAP_URL, r.status_code)
    except requests.RequestException as e:
        logging.warning("[sitemap] ping 실패: %s", e)

def run_all():
    t0 = time.time()
    logging.info("[run_all] 실제 SEO/임포트 작업 시작")
    _fetch_sample_products(5)   # 연결/토큰 확인 겸
    _ping_sitemap()             # 사이트맵 핑(선택)
    # TODO: 여기서부터 상품 생성/수정, SEO 메타 갱신, 이미지 ALT 채우기 등 구현
    logging.info("[run_all] 완료 (%.1fs)", time.time() - t0)
