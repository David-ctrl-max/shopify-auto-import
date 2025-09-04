# services/importer.py — Auto-Import + SEO with Round-Robin batching + lock + sitemap autodetect + daily report + no-change skip + last-updated dump
# -*- coding: utf-8 -*-
"""
run_all() 실행 순서:
  0) (옵션) AUTO IMPORT
  1) SEO UPDATE (필요할 때만 PUT; 드라이 모드 지원)
  2) 사이트맵 핑
  3) /report/add 로 데일리 리포트 기록
  4) 이번 실행에서 실제 업데이트(또는 드라이 모드의 “업데이트 필요”)된 상품을 /tmp/last_updated_products.json 에 저장

환경변수:
  SHOPIFY_STORE, SHOPIFY_ADMIN_TOKEN, SHOPIFY_API_VERSION, USER_AGENT
  AUTO_IMPORT, PRODUCT_FEED_URL, MIN_PRICE
  SEO_LIMIT, SEO_UPDATE_HANDLE, UPDATE_ALL_IMAGES_ALT
  SEO_CURSOR_PATH, SITEMAP_URL
  IMPORT_AUTH_TOKEN, PUBLIC_BASE_URL
  OVERWRITE_ALWAYS
"""

from __future__ import annotations
import os, re, time, json, logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import requests

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Env
STORE = os.getenv("SHOPIFY_STORE", "").strip()
TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN", "").strip()
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07").strip()
USER_AGENT = os.getenv("USER_AGENT", "shopify-auto-import/1.0").strip() or "shopify-auto-import/1.0"

AUTO_IMPORT = os.getenv("AUTO_IMPORT", "").strip() == "1"
PRODUCT_FEED_URL = os.getenv("PRODUCT_FEED_URL", "").strip()
try:
    MIN_PRICE = float(os.getenv("MIN_PRICE", "2").strip() or 2)
except Exception:
    MIN_PRICE = 2.0

try:
    SEO_LIMIT = int(os.getenv("SEO_LIMIT", "10").strip() or 10)
except Exception:
    SEO_LIMIT = 10
SEO_UPDATE_HANDLE = os.getenv("SEO_UPDATE_HANDLE", "0").strip() == "1"
UPDATE_ALL_IMAGES_ALT = os.getenv("UPDATE_ALL_IMAGES_ALT", "0").strip() == "1"
OVERWRITE_ALWAYS = os.getenv("OVERWRITE_ALWAYS", "0").strip() == "1"

_default_cursor = Path("/data/seo_cursor.json")
SEO_CURSOR_PATH = Path(os.getenv("SEO_CURSOR_PATH", str(_default_cursor)))
if not SEO_CURSOR_PATH.parent.exists():
    SEO_CURSOR_PATH = Path("/tmp/seo_cursor.json")

SITEMAP_URL_ENV = os.getenv("SITEMAP_URL", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://shopify-auto-import.onrender.com").strip()
IMPORT_AUTH_TOKEN = os.getenv("IMPORT_AUTH_TOKEN", os.getenv("AUTH_TOKEN", "jeffshopsecure")).strip()

if not STORE:
    raise RuntimeError("환경변수 SHOPIFY_STORE 누락 (예: bj0b8k-kg)")

# ─────────────────────────────────────────────────────────────
# HTTP
SESSION = requests.Session()
if TOKEN:
    SESSION.headers.update({
        "X-Shopify-Access-Token": TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
else:
    log.warning("[init] SHOPIFY_ADMIN_TOKEN 비어있음 — API 호출 시 401/403 가능")

TIMEOUT = 20
BASE = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}"

def _retry(func, *a, **k) -> requests.Response:
    tries = int(k.pop("tries", 4)); backoff = float(k.pop("backoff", 1.2))
    last: Optional[requests.Response | Exception] = None
    for i in range(tries):
        try:
            r: requests.Response = func(*a, timeout=TIMEOUT, **k)
            if r.status_code in (200, 201): return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (i+1)); last = r; continue
            return r
        except requests.RequestException as e:
            last = e; time.sleep(backoff * (i+1)); continue
    if isinstance(last, requests.Response): return last
    raise RuntimeError("HTTP 요청 재시도 후 실패") from last  # type: ignore[arg-type]

def _get(url: str, **kw) -> requests.Response: return _retry(SESSION.get, url, **kw)
def _post(url: str, **kw) -> requests.Response: return _retry(SESSION.post, url, **kw)
def _put(url: str, **kw) -> requests.Response: return _retry(SESSION.put, url, **kw)

# ─────────────────────────────────────────────────────────────
# Lock
LOCK_PATH = Path("/tmp/seo.lock")
class RunLock:
    def __enter__(self):
        try:
            if LOCK_PATH.exists():
                age = time.time() - LOCK_PATH.stat().st_mtime
                if age < 20*60: raise RuntimeError("이미 실행 중으로 판단(락 존재)")
                else: LOCK_PATH.unlink(missing_ok=True)
            LOCK_PATH.write_text(str(int(time.time())), encoding="utf-8")
        except Exception as e:
            log.warning("[lock] 락 생성 실패(무시): %s", e)
        return self
    def __exit__(self, a,b,c):
        try: LOCK_PATH.unlink(missing_ok=True)
        except Exception: pass

# ─────────────────────────────────────────────────────────────
# List helpers
def list_all_products() -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []; page_info: Optional[str] = None
    while True:
        url = f"{BASE}/products.json?limit=250"
        if page_info: url += f"&page_info={page_info}"
        r = _get(url)
        if r.status_code not in (200, 201):
            log.error("[list] %s -> %s %s", url, r.status_code, (r.text or "")[:400]); break
        batch = r.json().get("products", []) or []; products.extend(batch)
        link = r.headers.get("Link", "") or ""
        if 'rel="next"' in link:
            m = re.search(r"page_info=([^>;]+)>; rel=\"next\"", link); page_info = m.group(1) if m else None
            if not page_info: break
        else: break
    log.info("[list] products fetched=%d", len(products)); return products

def _load_cursor() -> Optional[int]:
    try:
        if SEO_CURSOR_PATH.exists():
            data = json.loads(SEO_CURSOR_PATH.read_text(encoding="utf-8"))
            v = int(data.get("since_id") or 0); return v if v>0 else None
    except Exception: pass
    return None

def _save_cursor(since_id: Optional[int]) -> None:
    try:
        SEO_CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEO_CURSOR_PATH.write_text(json.dumps({"since_id": since_id or 0}), encoding="utf-8")
    except Exception as e:
        log.warning("[cursor] 저장 실패: %s (path=%s)", e, SEO_CURSOR_PATH)

def list_products_round_robin(limit: int) -> List[Dict[str, Any]]:
    if limit <= 0: return list_all_products()
    batch: List[Dict[str, Any]] = []; since_id = _load_cursor(); wrapped = False
    while len(batch) < limit:
        params = {"limit": min(250, limit-len(batch))}
        if since_id: params["since_id"] = since_id
        r = _get(f"{BASE}/products.json", params=params)
        if r.status_code not in (200, 201):
            log.error("[list-rr] HTTP %s: %s", r.status_code, (r.text or "")[:300]); break
        items = r.json().get("products", []) or []
        if not items:
            if wrapped: break
            wrapped = True; since_id = None; continue
        batch.extend(items); since_id = items[-1].get("id")
    _save_cursor(since_id)
    log.info("[list-rr] round-robin fetched=%d (cursor=%s)", len(batch), since_id)
    return batch[:limit]

# ─────────────────────────────────────────────────────────────
# SEO helpers
def _truncate(s: str, n: int) -> str:
    s = s or ""; return s if len(s) <= n else (s[: max(0, n-1)] + "…")

def make_seo(product: Dict[str, Any]) -> Dict[str, str]:
    title = (product.get("title") or "").strip()
    handle = (product.get("handle") or "").strip().lower().replace(" ", "-")
    tags = product.get("tags") or ""
    if isinstance(tags, list): tags = ", ".join(tags)
    main_kw = (str(tags).split(",")[0] or title).strip()
    meta_title = _truncate(f"{title} | Jeff’s Favorite Picks", 60)
    meta_desc = _truncate(f"Shop {title}. {main_kw} for US/EU/CA. Fast shipping. Grab yours.", 160)
    alt = f"{title} – {main_kw}"
    return {
        "handle": handle,
        "metafields_global_title_tag": meta_title,
        "metafields_global_description_tag": meta_desc,
        "alt_text": alt,
    }

def needs_update(product: Dict[str, Any], seo: Dict[str, str]) -> Tuple[bool, str]:
    cur_title = (product.get("metafields_global_title_tag") or "").strip()
    cur_desc  = (product.get("metafields_global_description_tag") or "").strip()
    new_title = seo["metafields_global_title_tag"].strip()
    new_desc  = seo["metafields_global_description_tag"].strip()
    if cur_title != new_title: return True, "title_diff"
    if cur_desc != new_desc:   return True, "desc_diff"
    if SEO_UPDATE_HANDLE:
        cur_handle = (product.get("handle") or "").strip()
        if cur_handle != (seo["handle"] or "").strip(): return True, "handle_diff"
    imgs = product.get("images") or []
    new_alt = seo["alt_text"].strip()
    if not imgs: return False, "nochange"
    if UPDATE_ALL_IMAGES_ALT:
        for img in imgs:
            if (img.get("alt") or "").strip() != new_alt: return True, "alt_diff_all"
        return False, "nochange"
    else:
        first = imgs[0]
        if (first.get("alt") or "").strip() != new_alt: return True, "alt_diff_first"
        return False, "nochange"

def update_product_seo(p: Dict[str, Any], seo: Dict[str, str]) -> Tuple[bool, str]:
    if not OVERWRITE_ALWAYS:
        need, why = needs_update(p, seo)
        if not need: return False, "nochange"
    else:
        why = "force"
    pid = p["id"]
    r = _put(f"{BASE}/products/{pid}.json", json={"product": {
        "id": pid,
        **({"handle": seo["handle"]} if SEO_UPDATE_HANDLE else {}),
        "metafields_global_title_tag": seo["metafields_global_title_tag"],
        "metafields_global_description_tag": seo["metafields_global_description_tag"],
    }})
    ok1 = r.status_code in (200, 201)
    ok2 = True
    images = p.get("images") or []
    if images:
        if UPDATE_ALL_IMAGES_ALT:
            for img in images:
                img_id = img.get("id")
                if not img_id: continue
                r2 = _put(f"{BASE}/products/{pid}/images/{img_id}.json",
                          json={"image": {"id": img_id, "alt": seo["alt_text"]}})
                ok2 = ok2 and (r2.status_code in (200, 201))
        else:
            img_id = images[0].get("id")
            if img_id:
                r2 = _put(f"{BASE}/products/{pid}/images/{img_id}.json",
                          json={"image": {"id": img_id, "alt": seo["alt_text"]}})
                ok2 = ok2 and (r2.status_code in (200, 201))
    return (ok1 and ok2), why

# ─────────────────────────────────────────────────────────────
# AUTO IMPORT (옵션) — (생략 없이 동일)
ALLOW_CATEGORIES = {
    "phone","magsafe","charger","case","cable","stand","holder",
    "power bank","powerbank","pet","cat","dog","wearable"
}

def fetch_feed() -> List[Dict[str, Any]]:
    if not PRODUCT_FEED_URL:
        log.info("[import] PRODUCT_FEED_URL 비어있음 -> 스킵"); return []
    try:
        r = _get(PRODUCT_FEED_URL)
        if r.status_code not in (200, 201):
            log.error("[import] feed HTTP %s: %s", r.status_code, PRODUCT_FEED_URL); return []
        data = r.json()
        if isinstance(data, dict) and "items" in data: return data["items"] or []
        if isinstance(data, list): return data
        log.warning("[import] 예상외 포맷: dict/list 아님 -> 스킵"); return []
    except Exception as e:
        log.exception("[import] 피드 로드 실패: %s", e); return []

def should_exclude(item: Dict[str, Any]) -> (bool, str):
    title = (item.get("title") or "").lower()
    tags  = item.get("tags"); tags_text = " ".join(tags) if isinstance(tags, list) else str(tags or ""); tags_text = tags_text.lower()
    try: price_val = float(str(item.get("price") or "0").replace("$","").strip() or 0)
    except ValueError: price_val = 0.0
    if price_val < MIN_PRICE: return True, f"price<{MIN_PRICE}"
    blob = f"{title} {tags_text}"
    if not any(kw in blob for kw in ALLOW_CATEGORIES): return True, "category_not_allowed"
    if str(item.get("in_stock","true")).lower()=="false": return True, "oos"
    if str(item.get("shippable_to_na_eu","true")).lower()=="false": return True, "ship_unavailable"
    return False, ""

def map_to_shopify(item: Dict[str, Any]) -> Dict[str, Any]:
    title = item["title"]; body_html = item.get("body_html") or item.get("description") or ""
    vendor = item.get("vendor") or "Auto Import"; product_type = item.get("product_type") or "Dropshipping"
    tags = item.get("tags") or []; tags = ", ".join([str(t) for t in tags]) if isinstance(tags, list) else tags
    price = str(item.get("price") or "0"); sku = item.get("sku") or ""; status = item.get("status") or "draft"
    variant = {"price": price, "sku": sku, "taxable": True, "inventory_management": None}
    images = [{"src": u} for u in (item.get("images", []) or []) if u]
    return {"product": {"title": title,"body_html": body_html,"vendor": vendor,"product_type": product_type,
                        "tags": tags,"status": status,"variants": [variant],"images": images}}

def create_product(payload: Dict[str, Any]) -> requests.Response:
    return _post(f"{BASE}/products.json", json=payload)

def run_auto_import() -> tuple[int,int,int]:
    if not AUTO_IMPORT:
        log.info("[import] AUTO_IMPORT=0 -> 스킵"); return 0,0,0
    items = fetch_feed(); imported=skipped=errors=0
    for it in items:
        try:
            ex, reason = should_exclude(it)
            if ex: skipped += 1; log.info("[import] skip: %s (%s)", it.get("title"), reason); continue
            r = create_product(map_to_shopify(it))
            if r.status_code in (200, 201):
                imported += 1; pid = (r.json().get("product") or {}).get("id")
                log.info("[import] ok: %s (pid=%s)", it.get("title"), pid)
            else:
                errors += 1; log.error("[import] fail %s -> %s %s", it.get("title"), r.status_code, (r.text or "")[:300])
        except Exception as e:
            errors += 1; log.exception("[import] exception %s: %s", it.get("title"), e)
    log.info("[import_summary] imported=%d, skipped=%d, errors=%d", imported, skipped, errors)
    return imported, skipped, errors

# ─────────────────────────────────────────────────────────────
# Sitemap
def _http_head_or_get(url: str) -> int:
    try: return _get(url, allow_redirects=True).status_code
    except Exception: return 0

def _ping_google(sitemap_url: str) -> int:
    try: return _get(f"https://www.google.com/ping?sitemap={sitemap_url}").status_code
    except Exception: return 0

def resubmit_sitemap() -> None:
    candidates = []
    if SITEMAP_URL_ENV: candidates.append(SITEMAP_URL_ENV)
    candidates.append(f"https://{STORE}.myshopify.com/sitemap.xml")
    candidates.append("https://jeffsfavoritepicks.com/sitemap.xml")
    used = None
    for url in candidates:
        code = _http_head_or_get(url)
        if code and 200 <= code < 500:
            used = url; status = _ping_google(url); log.info("[sitemap] Google ping %s (%s)", url, status); break
    if not used:
        last = candidates[-1] if candidates else "(없음)"
        log.info("[sitemap] 유효 URL 찾지 못함, 마지막 후보 로그만: %s", last)

# ─────────────────────────────────────────────────────────────
# Report helper
def _submit_daily_report(updated:int, dry:bool, limit:int,
                         perf=0, acc=0, bp=0, seo=0, lcp=0.0, tbt=0, ctr=0.0, notes=""):
    try:
        params = {"auth": IMPORT_AUTH_TOKEN,"perf": perf,"acc": acc,"bp": bp,"seo": seo,
                  "lcp": lcp,"tbt": tbt,"ctr": ctr,"updated": updated,
                  "notes": notes or f"dry={dry}, limit={limit}"}
        requests.get(f"{PUBLIC_BASE_URL}/report/add", params=params, timeout=8)
    except Exception as e:
        log.warning("[report] submit failed: %s", e)

def _save_last_updated_dump(items: List[Dict[str, Any]], dry: bool, limit: int):
    """이번 실행에서 실제 업데이트(또는 드라이 모드의 '업데이트 필요')된 상품을 파일로 저장"""
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry": bool(dry),
        "limit": int(limit),
        "count": len(items),
        "items": items,
    }
    path = Path("/tmp/last_updated_products.json")
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.warning("[dump] save failed: %s", e)

# ─────────────────────────────────────────────────────────────
# Public entrypoint
def run_all(*args, **kwargs) -> Dict[str, int]:
    dry: bool = bool(kwargs.get("dry", False))
    limit_kw = kwargs.get("limit", None)
    try: limit: int = int(limit_kw) if limit_kw is not None else SEO_LIMIT
    except Exception: limit = SEO_LIMIT

    with RunLock():
        t0 = time.time()

        # 연결 점검 + 샘플
        try:
            r = _get(f"{BASE}/shop.json")
            if r.status_code in (200, 201):
                shop = r.json().get("shop", {}) or {}
                log.info("[check] 연결 OK: shop=%s, myshopify=%s, api_version=%s",
                         shop.get("name"), shop.get("myshopify_domain"), API_VERSION)
                r2 = _get(f"{BASE}/products.json", params={"limit": 5})
                if r2.status_code in (200, 201):
                    prods = r2.json().get("products", []) or []
                    log.info("[shopify] 샘플 상품 5개")
                    for p in prods:
                        log.info(" - %s | %s", p.get("id"), (p.get("title") or "")[:120])
        except Exception:
            pass

        # 0) Auto import
        try:
            imp_i, imp_s, imp_e = run_auto_import()
            if AUTO_IMPORT:
                log.info("[run_all] auto-import result: imported=%d skipped=%d errors=%d", imp_i, imp_s, imp_e)
        except Exception as e:
            log.exception("[run_all] run_auto_import 실패: %s", e)

        # 1) SEO UPDATE
        products = list_products_round_robin(limit) if (limit and limit > 0) else list_all_products()
        updated = skipped = errors = 0
        skipped_nochange = 0
        updated_items: List[Dict[str, Any]] = []

        for p in products:
            try:
                status = p.get("status")
                if status not in ("active", "draft"):
                    skipped += 1; continue

                seo = make_seo(p)

                if dry:
                    need, why = (True, "force") if OVERWRITE_ALWAYS else needs_update(p, seo)
                    if need:
                        updated += 1
                        updated_items.append({
                            "id": p.get("id"),
                            "title": p.get("title"),
                            "handle": p.get("handle"),
                            "reason": why,
                            "admin_url": f"https://admin.shopify.com/store/{STORE}/products/{p.get('id')}",
                        })
                        log.info("[seo] (dry) would update pid=%s (%s)", p.get("id"), why)
                    else:
                        skipped_nochange += 1
                        log.info("[seo] (dry) skip pid=%s (nochange)", p.get("id"))
                    continue

                did, reason = update_product_seo(p, seo)
                if did:
                    updated += 1
                    updated_items.append({
                        "id": p.get("id"),
                        "title": p.get("title"),
                        "handle": p.get("handle"),
                        "reason": reason,
                        "admin_url": f"https://admin.shopify.com/store/{STORE}/products/{p.get('id')}",
                    })
                    log.info("[seo] updated pid=%s (%s)", p.get("id"), reason)
                else:
                    if reason == "nochange": skipped_nochange += 1
                    else: errors += 1
                    log.info("[seo] skip pid=%s (%s)", p.get("id"), reason)

            except Exception as e:
                errors += 1
                log.exception("[seo] failed pid=%s: %s", p.get("id"), e)

            time.sleep(0.05)  # rate limit 보호

        log.info("[summary] updated_seo=%d, skipped=%d, skipped_nochange=%d, errors=%d",
                 updated, skipped, skipped_nochange, errors)

        # 2) Sitemap
        try: resubmit_sitemap()
        except Exception: pass

        # 3) Daily report
        _submit_daily_report(updated=updated, dry=dry, limit=limit)

        # 4) 이번 실행 변경 목록 저장
        _save_last_updated_dump(updated_items, dry=dry, limit=limit)

        log.info("[run_all] 완료 (%.1fs)", time.time() - t0)
        return {"updated_seo": updated, "skipped": skipped + skipped_nochange, "errors": errors}











