# services/importer.py
import os, time, logging, requests
log = logging.getLogger(__name__)

STORE = os.getenv("SHOPIFY_STORE", "bj0b8k-kg").strip()
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07").strip()
TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN", "").strip()

SESSION = requests.Session()
SESSION.headers.update({
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "shopify-auto-import/1.0"
})
BASE = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}"

def _get(url, **kw):    return SESSION.get(url, timeout=20, **kw)
def _put(url, json):    return SESSION.put(url, json=json, timeout=20)
def _retry(func, *a, **k):
    for i in range(4):
        r = func(*a, **k)
        if r.status_code in (200, 201): return r
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(1.2*(i+1)); continue
        return r
    return r

def list_all_products():
    # 최대 250씩 페이지네이션
    products, page_info = [], None
    while True:
        url = f"{BASE}/products.json?limit=250"
        if page_info: url += f"&page_info={page_info}"
        r = _retry(_get, url)
        r.raise_for_status()
        data = r.json().get("products", [])
        products.extend(data)
        # Link 헤더로 다음 페이지 판별
        link = r.headers.get("Link","")
        if 'rel="next"' in link:
            # page_info 추출
            import re
            m = re.search(r'page_info=([^>;]+)>; rel="next"', link)
            page_info = m.group(1) if m else None
            if not page_info: break
        else:
            break
    return products

def make_seo(product):
    title = product.get("title","").strip()
    handle = product.get("handle","").strip().lower().replace(" ", "-")
    # 키워드 예시(간단 버전): 제품 카테고리/태그 기반
    tags = product.get("tags","")
    main_kw = (tags.split(",")[0] or title).strip()
    # 60자 내 타이틀, 160자 내 디스크립션
    meta_title = f"{title} | Jeff’s Favorite Picks"
    if len(meta_title) > 60: meta_title = (meta_title[:57] + "…")
    meta_desc  = f"Shop {title}. {main_kw} for US/EU/CA. Fast shipping. Grab yours."
    if len(meta_desc) > 160: meta_desc = (meta_desc[:157] + "…")
    # ALT(첫 이미지 기준)
    alt = f"{title} – {main_kw}"
    return {
        "handle": handle,
        "metafields_global_title_tag": meta_title,
        "metafields_global_description_tag": meta_desc,
        "alt_text": alt
    }

def update_product_seo(p, seo):
    pid = p["id"]
    payload = {"product": {
        "id": pid,
        "handle": seo["handle"],
        "metafields_global_title_tag": seo["metafields_global_title_tag"],
        "metafields_global_description_tag": seo["metafields_global_description_tag"],
    }}
    r = _retry(_put, f"{BASE}/products/{pid}.json", json=payload)
    ok1 = r.status_code in (200,201)

    ok2 = True
    # 첫 이미지 ALT 업데이트
    if p.get("images"):
        img_id = p["images"][0]["id"]
        r2 = _retry(_put, f"{BASE}/products/{pid}/images/{img_id}.json",
                    json={"image":{"id": img_id, "alt": seo["alt_text"]}})
        ok2 = r2.status_code in (200,201)
    return ok1 and ok2

def run_all():
    # 기존 체크/샘플/사이트맵 호출 이후에 이 블록을 추가
    products = list_all_products()
    updated = skipped = errors = 0
    for p in products:
        try:
            seo = make_seo(p)

            # 예시 스킵 규칙: 비공개 상품/아카이브 제외
            if p.get("status") not in ("active", "draft"):
                skipped += 1; continue

            if update_product_seo(p, seo):
                updated += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1
            log.exception(f"[seo] failed pid={p.get('id')}: {e}")

    log.info(f"[summary] updated_seo={updated}, skipped={skipped}, errors={errors}")






