# services/importer.py — full replacement (auto-import + SEO update)
# -*- coding: utf-8 -*-
"""
This module performs two things when run_all() is called:
  1) Optional AUTO IMPORT: fetch candidate items from PRODUCT_FEED_URL and create Shopify products
  2) SEO UPDATE: iterate existing products and update meta title/description and image ALT

Environment variables used:
  SHOPIFY_STORE           (e.g., bj0b8k-kg)
  SHOPIFY_ADMIN_TOKEN     (Admin API token)
  SHOPIFY_API_VERSION     (default: 2025-07)
  USER_AGENT              (optional; default: shopify-auto-import/1.0)

  AUTO_IMPORT             ("1" to enable)
  PRODUCT_FEED_URL        (JSON feed URL returning list or {"items": []})
  MIN_PRICE               (default: 2)

  SEO_LIMIT               (optional; limit number of products updated; 0=unlimited)
  SEO_UPDATE_HANDLE       ("1" to also update product handle; default: 0)
  UPDATE_ALL_IMAGES_ALT   ("1" to update ALT on all images; default: 0)
"""

import os
import re
import time
import logging
import requests

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Environment
STORE = os.getenv("SHOPIFY_STORE", "").strip()  # e.g., bj0b8k-kg
TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN", "").strip()
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-07").strip()
USER_AGENT = os.getenv("USER_AGENT", "shopify-auto-import/1.0").strip() or "shopify-auto-import/1.0"

# Auto-import flags
AUTO_IMPORT = os.getenv("AUTO_IMPORT", "").strip() == "1"
PRODUCT_FEED_URL = os.getenv("PRODUCT_FEED_URL", "").strip()
MIN_PRICE = float(os.getenv("MIN_PRICE", "2").strip() or 2)

# SEO flags
SEO_LIMIT = int(os.getenv("SEO_LIMIT", "0").strip() or 0)  # 0 = unlimited
SEO_UPDATE_HANDLE = os.getenv("SEO_UPDATE_HANDLE", "0").strip() == "1"
UPDATE_ALL_IMAGES_ALT = os.getenv("UPDATE_ALL_IMAGES_ALT", "0").strip() == "1"

if not STORE:
    # Raise early to avoid confusing 404s later
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


def _retry(func, *a, **k):
    """Retry helper for transient errors and 429."""
    tries = k.pop("tries", 4)
    backoff = k.pop("backoff", 1.2)
    last = None
    for i in range(tries):
        try:
            r = func(*a, timeout=TIMEOUT, **k)
            if r.status_code in (200, 201):
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (i + 1))
                last = r
                continue
            # Non-retriable
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(backoff * (i + 1))
            continue
    if isinstance(last, requests.Response):
        return last
    raise RuntimeError("HTTP 요청 재시도 후 실패") from last


def _get(url, **kw):
    return _retry(SESSION.get, url, **kw)


def _post(url, **kw):
    return _retry(SESSION.post, url, **kw)


def _put(url, **kw):
    return _retry(SESSION.put, url, **kw)


# ─────────────────────────────────────────────────────────────
# Product listing (REST, cursor pagination via Link header)

def list_all_products():
    products, page_info = [], None
    while True:
        url = f"{BASE}/products.json?limit=250"
        if page_info:
            url += f"&page_info={page_info}"
        r = _get(url)
        if r.status_code not in (200, 201):
            text = (r.text or "")[:400]
            log.error("[list] %s -> %s %s", url, r.status_code, text)
            break
        batch = r.json().get("products", [])
        products.extend(batch)
        link = r.headers.get("Link", "")
        if 'rel="next"' in link:
            m = re.search(r"page_info=([^>;]+)>; rel=\"next\"", link)
            page_info = m.group(1) if m else None
            if not page_info:
                break
        else:
            break
    log.info("[list] products fetched=%d", len(products))
    return products


# ─────────────────────────────────────────────────────────────
# SEO helpers

def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def make_seo(product):
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


def update_product_seo(p, seo):
    pid = p["id"]
    payload = {"product": {
        "id": pid,
        # Handle update is optional (off by default to avoid URL changes)
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
# AUTO IMPORT

ALLOW_CATEGORIES = {
    "phone", "magsafe", "charger", "case", "cable",
    "stand", "holder", "power bank", "powerbank", "pet", "cat", "dog", "wearable"
}


def fetch_feed():
    """Fetch candidate items from PRODUCT_FEED_URL.
    Expected JSON: list or {"items": [...]}.
    """
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


def should_exclude(item):
    """Apply exclusion rules: price floor, category keywords, stock/shipping flags."""
    title = (item.get("title") or "").lower()
    tags = item.get("tags")
    if isinstance(tags, list):
        tags_text = " ".join([str(t) for t in tags])
    else:
        tags_text = str(tags or "")
    tags_text = tags_text.lower()

    # price
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


def map_to_shopify(item):
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


def create_product(payload):
    url = f"{BASE}/products.json"
    return _post(url, json=payload)


def run_auto_import():
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
# Public entrypoint

def run_all():
    """Runs auto-import first (if enabled), then SEO updates for all products."""
    t0 = time.time()
    log.info("[run_all] 시작: auto-import -> SEO")

    # 0) AUTO IMPORT (optional)
    try:
        imp_i, imp_s, imp_e = run_auto_import()
        if AUTO_IMPORT:
            log.info("[run_all] auto-import result: imported=%d skipped=%d errors=%d", imp_i, imp_s, imp_e)
    except Exception as e:
        log.exception("[run_all] run_auto_import 실패: %s", e)

    # 1) SEO UPDATE for all products
    products = list_all_products()
    updated = skipped = errors = 0

    for idx, p in enumerate(products):
        if SEO_LIMIT and idx >= SEO_LIMIT:
            break
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

    log.info("[summary] updated_seo=%d, skipped=%d, errors=%d", updated, skipped, errors)
    log.info("[run_all] 완료 (%.1fs)", time.time() - t0)
    return {
        "updated_seo": updated,
        "skipped": skipped,
        "errors": errors,
    }







