# services/importer.py — Auto-Import + SEO with Round-Robin batching + lock + sitemap autodetect
# -*- coding: utf-8 -*-
"""
run_all()가 실행되면 순서:
  0) (옵션) AUTO IMPORT: PRODUCT_FEED_URL에서 후보를 불러와 상품 생성
  1) SEO UPDATE: 상품 목록을 가져와 meta title/description, image ALT (옵션: handle) 업데이트
  2) (부가) 사이트맵 핑 전송(자동 주소 감지)

환경변수:
  SHOPIFY_STORE              (예: bj0b8k-kg)   [필수]
  SHOPIFY_ADMIN_TOKEN        (Admin API 토큰)   [필수]
  SHOPIFY_API_VERSION        (기본: 2025-07)
  USER_AGENT                 (기본: shopify-auto-import/1.0)

  AUTO_IMPORT                ("1"이면 임포트 실행)
  PRODUCT_FEED_URL           (임포트용 JSON feed URL)
  MIN_PRICE                  (기본: 2)

  SEO_LIMIT                  (이번 실행에서 처리할 상품 수 상한; 0=무제한)
  SEO_UPDATE_HANDLE          ("1"이면 product handle도 갱신)
  UPDATE_ALL_IMAGES_ALT      ("1"이면 모든 이미지 ALT 갱신; 기본은 첫 이미지 ALT만)

  SEO_CURSOR_PATH            (라운드로빈 커서 저장 파일 경로; 기본: /data/seo_cursor.json → 실패 시 /tmp 폴백)
  SITEMAP_URL                (명시적 sitemap URL; 실패 시 자동 감지 재시도)
  IMPORT_AUTH_TOKEN          (엔드포인트 보호 토큰; main.py에서 사용)

추가 개선:
  - 중복 실행 방지: 간단 락 파일(/tmp/seo.lock)
  - 사이트맵 자동 감지: SITEMAP_URL 없거나 404면 myshopify → 커스텀 도메인 순 재시도
"""

from __future__ import annotations

import os
import re
import time
import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Environment
STORE = os.getenv("SHOPIFY_STORE", "").strip()
TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN", "").strip()
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07").strip()
USER_AGENT = os.getenv("USER_AGENT", "shopify-auto-import/1.0").strip() or "shopify-auto-import/1.0"

# Auto-import flags
AUTO_IMPORT = os.getenv("AUTO_IMPORT", "").strip() == "1"
PRODUCT_FEED_URL = os.getenv("PRODUCT_FEED_URL", "").strip()
try:
    MIN_PRICE = float(os.getenv("MIN_PRICE", "2").strip() or 2)
except Exception:
    MIN_PRICE = 2.0

# SEO flags
try:
    SEO_LIMIT = int(os.getenv("SEO_LIMIT", "10").strip() or 10)  # 기본 10으로 운영
except Exception:
    SEO_LIMIT = 10
SEO_UPDATE_HANDLE = os.getenv("SEO_UPDATE_HANDLE", "0").strip() == "1"
UPDATE_ALL_IMAGES_ALT = os.getenv("UPDATE_ALL_IMAGES_ALT", "0").strip() == "1"

# Round-robin cursor file (영구경로 선호)
_default_cursor = Path("/data/seo_cursor.json")
SEO_CURSOR_PATH = Path(os.getenv("SEO_CURSOR_PATH", str(_default_cursor)))
if not SEO_CURSOR_PATH.parent.exists():
    # Render 퍼시스턴트 디스크가 없거나 권한 없을 때 /tmp로 폴백
    SEO_CURSOR_PATH = Path("/tmp/seo_cursor.json")

SITEMAP_URL_ENV = os.getenv("SITEMAP_URL", "").strip()

if not STORE:
    raise RuntimeError("환경변수 SHOPIFY_STORE 누락 (예: bj0b8k-kg)")

# ─────────────────────────────────────────────────────────────
# HTTP session & helpers
SESSION = requests.Session()
if TOKEN:
    SESSION.headers.update({
        "X-Shopify-Access-Token": TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
else:
    log.warning("[init] SHOPIFY_ADMIN_TOKEN 비어있음 — API 호출 시 401/403 발생 가능")

TIMEOUT = 20
BASE = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}"

def _retry(func, *a, **k) -> requests.Response:
    tries = int(k.pop("tries", 4))
    backoff = float(k.pop("backoff", 1.2))
    last: Optional[requests.Response | Exception] = None
    for i in range(tries):
        try:
            r: requests.Response = func(*a, timeout=TIMEOUT, **k)
            if r.status_code in (200, 201):
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (i + 1))
                last = r
                continue
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(backoff * (i + 1))
            continue
    if isinstance(last, requests.Response):
        return last
    raise RuntimeError("HTTP 요청 재시도 후 실패") from last  # type: ignore[arg-type]

def _get(url: str, **kw) -> requests.Response:
    return _retry(SESSION.get, url, **kw)

def _post(url: str, **kw) -> requests.Response:
    return _retry(SESSION.post, url, **kw)

def _put(url: str, **kw) -> requests.Response:
    return _retry(SESSION.put, url, **kw)

# ─────────────────────────────────────────────────────────────
# 간단 락 (중복 실행 방지)
LOCK_PATH = Path("/tmp/seo.lock")

class RunLock:
    def __enter__(self):
        try:
            if LOCK_PATH.exists():
                # 최근 20분 내 생성된 락이면 실행 스킵
                age = time.time() - LOCK_PATH.stat().st_mtime
                if age < 20 * 60:
                    raise RuntimeError("이미 실행 중으로 판단(락 존재)")
                else:
                    # 오래된 락은 청소
                    LOCK_PATH.unlink(missing_ok=True)
            LOCK_PATH.write_text(str(int(time.time())), encoding="utf-8")
        except Exception as e:
            log.warning("[lock] 락 생성 실패(무시하고 진행): %s", e)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────
# Product listing utilities

def list_all_products() -> List[Dict[str, Any]]:
    """전체 상품을 모두 가져옵니다 (REST, Link 헤더 페이지네이션)."""
    products: List[Dict[str, Any]] = []
    page_info: Optional[str] = None
    while True:
        url = f"{BASE}/products.json?limit=250"
        if page_info:
            url += f"&page_info={page_info}"
        r = _get(url)
        if r.status_code not in (200, 201):
            text = (r.text or "")[:400]
            log.error("[list] %s -> %s %s", url, r.status_code, text)
            break
        batch = r.json().get("products", []) or []
        products.extend(batch)
        link = r.headers.get("Link", "") or ""
        if 'rel="next"' in link:
            m = re.search(r"page_info=([^>;]+)>; rel=\"next\"", link)
            page_info = m.group(1) if m else None
            if not page_info:
                break
        else:
            break
    log.info("[list] products fetched=%d", len(products))
    return products

# ---------- Round-robin support ----------

def _load_cursor() -> Optional[int]:
    try:
        if SEO_CURSOR_PATH.exists():
            data = json.loads(SEO_CURSOR_PATH.read_text(encoding="utf-8"))
            v = int(data.get("since_id") or 0)
            return v if v > 0 else None
    except Exception:
        pass
    return None

def _save_cursor(since_id: Optional[int]) -> None:
    try:
        SEO_CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEO_CURSOR_PATH.write_text(json.dumps({"since_id": since_id or 0}), encoding="utf-8")
    except Exception as e:
        log.warning("[cursor] 저장 실패: %s (path=%s)", e, SEO_CURSOR_PATH)

def list_products_round_robin(limit: int) -> List[Dict[str, Any]]:
    """
    since_id 커서를 사용해 매 실행마다 다른 구간을 순환 처리.
    동작:
      1) 저장된 since_id 이후 상품을 최대 limit개 수집
      2) 부족하면(끝에 도달) 처음부터 이어 받아 limit개 채움
      3) 마지막으로 처리한 상품 id를 커서로 저장
    limit <= 0 이면 전체 목록 반환(list_all_products 사용).
    """
    if limit <= 0:
        return list_all_products()

    batch: List[Dict[str, Any]] = []
    since_id = _load_cursor()
    wrapped = False

    while len(batch) < limit:
        params = {"limit": min(250, limit - len(batch))}
        if since_id:
            params["since_id"] = since_id

        r = _get(f"{BASE}/products.json", params=params)
        if r.status_code not in (200, 201):
            log.error("[list-rr] HTTP %s: %s", r.status_code, (r.text or "")[:300])
            break

        items = r.json().get("products", []) or []
        if not items:
            # 끝까지 갔으면 한 번 랩어라운드
            if wrapped:
                break
            wrapped = True
            since_id = None
            continue

        batch.extend(items)
        since_id = items[-1].get("id")

    _save_cursor(since_id)
    log.info("[list-rr] round-robin fetched=%d (cursor=%s)", len(batch), since_id)
    return batch[:limit]

# ─────────────────────────────────────────────────────────────
# SEO helpers

def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")

def make_seo(product: Dict[str, Any]) -> Dict[str, str]:
    title = (product.get("title") or "").strip()
    handle = (product.get("handle") or "").strip().lower().replace(" ", "-")
    tags = product.get("tags") or ""
    if isinstance(tags, list):
        tags = ", ".join(tags)
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

def update_product_seo(p: Dict[str, Any], seo: Dict[str, str]) -> bool:
    pid = p["id"]
    payload = {"product": {
        "id": pid,
        **({"handle": seo["handle"]} if SEO_UPDATE_HANDLE else {}),
        "metafields_global_title_tag": seo["metafields_global_title_tag"],
        "metafields_global_description_tag": seo["metafields_global_description_tag"],
    }}
    r = _put(f"{BASE}/products/{pid}.json", json=payload)
    ok1 = r.status_code in (200, 201)

    ok2 = True
    images = p.get("images") or []
    if images:
        if UPDATE_ALL_IMAGES_ALT:
            for img in images:
                img_id = img.get("id")
                if not img_id:
                    continue
                r2 = _put(f"{BASE}/products/{pid}/images/{img_id}.json",
                          json={"image": {"id": img_id, "alt": seo["alt_text"]}})
                ok2 = ok2 and (r2.status_code in (200, 201))
        else:
            img_id = images[0].get("id")
            if img_id:
                r2 = _put(f"{BASE}/products/{pid}/images/{img_id}.json",
                          json={"image": {"id": img_id, "alt": seo["alt_text"]}})
                ok2 = r2.status_code in (200, 201)

    return ok1 and ok2

# ─────────────────────────────────────────────────────────────
# AUTO IMPORT (옵션)

ALLOW_CATEGORIES = {
    "phone", "magsafe", "charger", "case", "cable",
    "stand", "holder", "power bank", "powerbank", "pet", "cat", "dog", "wearable"
}

def fetch_feed() -> List[Dict[str, Any]]:
    """Fetch candidate items from PRODUCT_FEED_URL. Expected JSON: list or {"items": [...]}."""
    if not PRODUCT_FEED_URL:
        log.info("[import] PRODUCT_FEED_URL 비어있음 -> 스킵")
        return []
    try:
        r = _get(PRODUCT_FEED_URL)
        if r.status_code not in (200, 201):
            log.error("[import] feed HTTP %s: %s", r.status_code, PRODUCT_FEED_URL)
            return []
        data = r.json()
        if isinstance(data, dict) and "items" in data:
            return data["items"] or []
        if isinstance(data, list):
            return data
        log.warning("[import] 예상외 포맷: dict/list 아님 -> 스킵")
        return []
    except Exception as e:
        log.exception("[import] 피드 로드 실패: %s", e)
        return []

def should_exclude(item: Dict[str, Any]) -> (bool, str):
    """Apply exclusion rules: price floor, category keywords, stock/shipping flags."""
    title = (item.get("title") or "").lower()
    tags = item.get("tags")
    if isinstance(tags, list):
        tags_text = " ".join([str(t) for t in tags])
    else:
        tags_text = str(tags or "")
    tags_text = tags_text.lower()

    try:
        price_val = float(str(item.get("price") or "0").replace("$", "").strip() or 0)
    except ValueError:
        price_val = 0.0
    if price_val < MIN_PRICE:
        return True, f"price<{MIN_PRICE}"

    blob = f"{title} {tags_text}"
    if not any(kw in blob for kw in ALLOW_CATEGORIES):
        return True, "category_not_allowed"

    if str(item.get("in_stock", "true")).lower() == "false":
        return True, "oos"
    if str(item.get("shippable_to_na_eu", "true")).lower() == "false":
        return True, "ship_unavailable"

    return False, ""

def map_to_shopify(item: Dict[str, Any]) -> Dict[str, Any]:
    title = item["title"]
    body_html = item.get("body_html") or item.get("description") or ""
    vendor = item.get("vendor") or "Auto Import"
    product_type = item.get("product_type") or "Dropshipping"
    tags = item.get("tags") or []
    if isinstance(tags, list):
        tags = ", ".join([str(t) for t in tags])

    price = str(item.get("price") or "0")
    sku = item.get("sku") or ""
    status = item.get("status") or "draft"  # safer default

    variant = {
        "price": price,
        "sku": sku,
        "taxable": True,
        "inventory_management": None,
    }

    images = []
    for u in item.get("images", []) or []:
        if u:
            images.append({"src": u})

    return {
        "product": {
            "title": title,
            "body_html": body_html,
            "vendor": vendor,
            "product_type": product_type,
            "tags": tags,
            "status": status,  # 'draft' | 'active'
            "variants": [variant],
            "images": images,
        }
    }

def create_product(payload: Dict[str, Any]) -> requests.Response:
    url = f"{BASE}/products.json"
    return _post(url, json=payload)

def run_auto_import() -> tuple[int, int, int]:
    if not AUTO_IMPORT:
        log.info("[import] AUTO_IMPORT=0 -> 스킵")
        return 0, 0, 0

    items = fetch_feed()
    imported = skipped = errors = 0
    for it in items:
        try:
            ex, reason = should_exclude(it)
            if ex:
                skipped += 1
                log.info("[import] skip: %s (%s)", it.get("title"), reason)
                continue

            payload = map_to_shopify(it)
            r = create_product(payload)
            if r.status_code in (200, 201):
                imported += 1
                pid = (r.json().get("product") or {}).get("id")
                log.info("[import] ok: %s (pid=%s)", it.get("title"), pid)
            else:
                errors += 1
                log.error("[import] fail %s -> %s %s", it.get("title"), r.status_code, (r.text or "")[:300])
        except Exception as e:
            errors += 1
            log.exception("[import] exception %s: %s", it.get("title"), e)

    log.info("[import_summary] imported=%d, skipped=%d, errors=%d", imported, skipped, errors)
    return imported, skipped, errors

# ─────────────────────────────────────────────────────────────
# Sitemap ping (자동 감지 포함)

def _http_head_or_get(url: str) -> int:
    try:
        r = _get(url, allow_redirects=True)
        return r.status_code
    except Exception:
        return 0

def _ping_google(sitemap_url: str) -> int:
    ping = f"https://www.google.com/ping?sitemap={sitemap_url}"
    try:
        r = _get(ping)
        return r.status_code
    except Exception:
        return 0

def resubmit_sitemap() -> None:
    # 1) 우선순위: 환경변수 SITEMAP_URL
    candidates = []
    if SITEMAP_URL_ENV:
        candidates.append(SITEMAP_URL_ENV)

    # 2) myshopify 기본
    candidates.append(f"https://{STORE}.myshopify.com/sitemap.xml")

    # 3) 흔한 커스텀 도메인(운영중 도메인으로 교체)
    # 실제 상점의 도메인이라면 여기 문자열만 교체하세요.
    candidates.append("https://jeffsfavoritepicks.com/sitemap.xml")

    used = None
    for url in candidates:
        code = _http_head_or_get(url)
        if code and 200 <= code < 500:  # 404 포함: 그래도 핑 시도 로그 남김
            used = url
            status = _ping_google(url)
            log.info("[sitemap] Google ping %s (%s)", url, status)
            break

    if not used:
        # 아무 것도 안되면 마지막 후보로라도 로그
        last = candidates[-1] if candidates else "(없음)"
        log.info("[sitemap] 유효 URL 찾지 못함, 마지막 후보 로그만: %s", last)

# ─────────────────────────────────────────────────────────────
# Public entrypoint

def run_all() -> Dict[str, int]:
    """Runs auto-import first (if enabled), then SEO updates, then sitemap ping."""
    # 중복 실행 방지
    with RunLock():
        t0 = time.time()

        # 연결 점검 + 샘플 로그(가독성 유지용)
        try:
            r = _get(f"{BASE}/shop.json")
            if r.status_code in (200, 201):
                shop = r.json().get("shop", {}) or {}
                log.info("[check] 연결 OK: shop=%s, myshopify=%s, api_version=%s",
                         shop.get("name"), shop.get("myshopify_domain"), API_VERSION)
                # 샘플 출력(5개)
                r2 = _get(f"{BASE}/products.json", params={"limit": 5})
                if r2.status_code in (200, 201):
                    prods = r2.json().get("products", []) or []
                    log.info("[shopify] 샘플 상품 5개")
                    for p in prods:
                        log.info(" - %s | %s", p.get("id"), (p.get("title") or "")[:120])
        except Exception:
            pass

        # 0) AUTO IMPORT (optional)
        try:
            imp_i, imp_s, imp_e = run_auto_import()
            if AUTO_IMPORT:
                log.info("[run_all] auto-import result: imported=%d skipped=%d errors=%d", imp_i, imp_s, imp_e)
        except Exception as e:
            log.exception("[run_all] run_auto_import 실패: %s", e)

        # 1) SEO UPDATE
        if SEO_LIMIT and SEO_LIMIT > 0:
            products = list_products_round_robin(SEO_LIMIT)
        else:
            products = list_all_products()

        updated = skipped = errors = 0

        for p in products:
            try:
                status = p.get("status")
                if status not in ("active", "draft"):
                    skipped += 1
                    continue

                seo = make_seo(p)
                if update_product_seo(p, seo):
                    updated += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                log.exception("[seo] failed pid=%s: %s", p.get("id"), e)

            # 너무 빠르면 429 가능성 → 소량 지연
            time.sleep(0.05)

        log.info("[summary] updated_seo=%d, skipped=%d, errors=%d", updated, skipped, errors)

        # 2) SITEMAP PING (자동 감지)
        try:
            resubmit_sitemap()
        except Exception:
            pass

        log.info("[run_all] 완료 (%.1fs)", time.time() - t0)
        return {"updated_seo": updated, "skipped": skipped, "errors": errors}








