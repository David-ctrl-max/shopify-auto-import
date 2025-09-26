# main.py — Unified Pro (Register + SEO + Keyword-Weighted Optimize + Sitemap + Email + IndexNow) — 2025-09-26
# ------------------------------------------------------------------------------------------------------------
# ✅ What’s included
# - /register (GET/POST)          : real Shopify product creation (images/options/variants/inventory)
# - /seo/optimize                 : rotate N products; keyword-weighted SEO meta (title/desc) with CTA, ALT suggest
# - /run-seo                      : alias to /seo/optimize (cron)
# - /seo/keywords/run             : build keyword map (unigram/bigram), optional CSV save
# - /seo/keywords/cache           : keyword cache status (age/params/counts)
# - /sitemap-products.xml         : product-only sitemap (canonical domain aware)
# - /robots.txt                   : robots with Sitemap lines
# - /bing/ping                    : 410 Gone 안내 (Bing sitemap ping deprecated)
# - /indexnow/submit             : IndexNow 제출 (권장)
# - /gsc/sitemap/submit          : optional Search Console sitemap submit (service account)
# - /report/daily                : EN/KR daily email summary (SendGrid)
# - /health, /__routes, /        : diagnostics
#
# 🔐 Auth:  use ?auth=<IMPORT_AUTH_TOKEN>  (or header X-Auth)
# ------------------------------------------------------------------------------------------------------------
# 🌎 Environment (Render)
# IMPORT_AUTH_TOKEN=jeffshopsecure
# SHOPIFY_STORE=jeffsfavoritepicks                # without .myshopify.com (we add it)
# SHOPIFY_API_VERSION=2025-07
# SHOPIFY_ADMIN_TOKEN=shpat_xxx
# SEO_LIMIT=10
# USE_GRAPHQL=true
# ENABLE_BING_PING=false
# PRIMARY_SITEMAP=https://jeffsfavoritepicks.com/sitemap.xml
# PUBLIC_BASE=https://shopify-auto-import.onrender.com
# CANONICAL_DOMAIN=jeffsfavoritepicks.com
# DRY_RUN=false
# LOG_LEVEL=INFO
#
# # IndexNow
# INDEXNOW_KEY=your-indexnow-key
# INDEXNOW_KEY_URL=https://jeffsfavoritepicks.com/indexnow-key.txt
#
# # Email (optional)
# ENABLE_EMAIL=true
# SENDGRID_API_KEY=SG.xxxxx
# EMAIL_TO=brightoil10@gmail.com,brightoil10@naver.com,brightoil10@kakao.com
# EMAIL_FROM=reports@jeffsfavoritepicks.com
#
# # GSC (optional)
# ENABLE_GSC_SITEMAP_SUBMIT=false
# GSC_SITE_URL=https://jeffsfavoritepicks.com
# GOOGLE_SERVICE_JSON_B64=...   (or)  GOOGLE_SERVICE_JSON_PATH=/app/sa.json
#
# # Keyword Map (NEW)
# KEYWORD_MIN_LEN=3
# KEYWORD_LIMIT=100
# KEYWORD_INCLUDE_BIGRAMS=true
# KEYWORD_SAVE_CSV=false
# KEYWORD_CACHE_TTL_MIN=60
#
# # Keyword Weighting for /seo/optimize (NEW)
# KW_TOP_N_FOR_WEIGHT=30
# TITLE_MAX_LEN=60
# DESC_MAX_LEN=160
# CTA_PHRASE="Grab Yours"
# ------------------------------------------------------------------------------------------------------------

import os, sys, json, time, base64, pathlib, logging, re
from typing import Any, Dict, List, Optional, Tuple
import datetime as dt
from collections import Counter

import requests
from flask import Flask, request, jsonify, Response
from functools import wraps

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("seo-automation")

# Optional file log (best-effort)
try:
    logs_dir = pathlib.Path("logs"); logs_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(logs_dir / "app.log")
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
    log.addHandler(fh)
except Exception as e:
    log.warning(f"File logging disabled: {e}")

# ─────────────────────────────────────────────────────────────
# Env / Config
# ─────────────────────────────────────────────────────────────
def env_bool(key: str, default=False):
    v = os.getenv(key)
    if v is None: return default
    return str(v).lower() in ("1","true","yes","on","y")

def env_str(key: str, default=""):
    return os.getenv(key, default)

def env_int(key: str, default: int) -> int:
    try: return int(os.getenv(key, default))
    except: return default

IMPORT_AUTH_TOKEN = env_str("IMPORT_AUTH_TOKEN", "jeffshopsecure")
SHOPIFY_STORE    = env_str("SHOPIFY_STORE", "").strip()
API_VERSION      = env_str("SHOPIFY_API_VERSION", "2025-07")
ADMIN_TOKEN      = env_str("SHOPIFY_ADMIN_TOKEN", "").strip()
SEO_LIMIT        = env_int("SEO_LIMIT", 10)
USE_GRAPHQL      = env_bool("USE_GRAPHQL", True)
ENABLE_BING_PING = env_bool("ENABLE_BING_PING", False)
PRIMARY_SITEMAP  = env_str("PRIMARY_SITEMAP", "https://jeffsfavoritepicks.com/sitemap.xml").strip()
PUBLIC_BASE      = env_str("PUBLIC_BASE", "").rstrip("/")
CANONICAL_DOMAIN = env_str("CANONICAL_DOMAIN", "").strip()
DRY_RUN          = env_bool("DRY_RUN", False)

# IndexNow
INDEXNOW_KEY     = env_str("INDEXNOW_KEY", "")
INDEXNOW_KEY_URL = env_str("INDEXNOW_KEY_URL", "")

# Email
ENABLE_EMAIL     = env_bool("ENABLE_EMAIL", False)
SENDGRID_API_KEY = env_str("SENDGRID_API_KEY")
EMAIL_TO         = [x.strip() for x in env_str("EMAIL_TO", "").split(',') if x.strip()]
EMAIL_FROM       = env_str("EMAIL_FROM", "reports@jeffsfavoritepicks.com")

# GSC
ENABLE_GSC_SITEMAP_SUBMIT = env_bool("ENABLE_GSC_SITEMAP_SUBMIT", False)
GSC_SITE_URL              = env_str("GSC_SITE_URL", "https://jeffsfavoritepicks.com")
GOOGLE_SERVICE_JSON_B64   = env_str("GOOGLE_SERVICE_JSON_B64")
GOOGLE_SERVICE_JSON_PATH  = env_str("GOOGLE_SERVICE_JSON_PATH")

# Keyword map (NEW)
KEYWORD_MIN_LEN         = env_int("KEYWORD_MIN_LEN", 3)
KEYWORD_LIMIT_DEFAULT   = env_int("KEYWORD_LIMIT", 100)
KEYWORD_INCLUDE_BIGRAMS = env_bool("KEYWORD_INCLUDE_BIGRAMS", True)
KEYWORD_SAVE_CSV        = env_bool("KEYWORD_SAVE_CSV", False)
KEYWORD_CACHE_TTL_MIN   = env_int("KEYWORD_CACHE_TTL_MIN", 60)

# Weighting for optimize (NEW)
KW_TOP_N_FOR_WEIGHT = env_int("KW_TOP_N_FOR_WEIGHT", 30)
TITLE_MAX_LEN       = env_int("TITLE_MAX_LEN", 60)
DESC_MAX_LEN        = env_int("DESC_MAX_LEN", 160)
CTA_PHRASE          = env_str("CTA_PHRASE", "Grab Yours")

# ─────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# Auth & HTTP helpers
# ─────────────────────────────────────────────────────────────
def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.args.get("auth") or request.headers.get("X-Auth")
        if token != IMPORT_AUTH_TOKEN:
            log.warning("Auth failed for %s", request.path)
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper

def retry(max_attempts=3, base_delay=0.6, factor=2.0, allowed=(429, 500, 502, 503, 504)):
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            attempt, delay = 0, base_delay
            while True:
                attempt += 1
                try:
                    return fn(*args, **kwargs)
                except requests.HTTPError as e:
                    status = e.response.status_code if e.response is not None else None
                    log.warning("HTTPError attempt %d (%s): %s", attempt, status, e)
                    if attempt >= max_attempts or status not in allowed: raise
                except Exception as e:
                    log.warning("Error attempt %d: %s", attempt, e)
                    if attempt >= max_attempts: raise
                time.sleep(delay); delay *= factor
        return inner
    return deco

@retry()
def http(method: str, url: str, **kwargs) -> requests.Response:
    r = requests.request(method, url, timeout=30, **kwargs)
    if r.status_code >= 400:
        try: r.raise_for_status()
        finally:
            log.error("HTTP %s %s -> %s %s", method, url, r.status_code, r.text[:500])
    return r

# ─────────────────────────────────────────────────────────────
# Shopify Admin (REST + GraphQL)
# ─────────────────────────────────────────────────────────────
BASE_REST    = f"https://{SHOPIFY_STORE}.myshopify.com/admin/api/{API_VERSION}"
BASE_GRAPHQL = f"https://{SHOPIFY_STORE}.myshopify.com/admin/api/{API_VERSION}/graphql.json"
HEADERS_REST = {"X-Shopify-Access-Token": ADMIN_TOKEN, "Content-Type": "application/json", "Accept":"application/json"}
HEADERS_GQL  = {"X-Shopify-Access-Token": ADMIN_TOKEN, "Content-Type": "application/json", "Accept":"application/json"}

@retry()
def shopify_get_products(limit: int=SEO_LIMIT) -> List[Dict[str,Any]]:
    r = http("GET", f"{BASE_REST}/products.json", headers=HEADERS_REST, params={"limit": min(250, limit)})
    return r.json().get("products", [])

# Paged fetcher for building keyword map (up to many products)
def shopify_get_all_products(max_items: int = 2000) -> List[Dict[str,Any]]:
    out, url, params = [], f"{BASE_REST}/products.json", {"limit": 250}
    while True:
        r = http("GET", url, headers=HEADERS_REST, params=params)
        items = r.json().get("products", [])
        out.extend(items)
        if len(out) >= max_items: break
        link = r.headers.get("Link", "")
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        if not m: break
        url, params = m.group(1), {}  # page_info already embedded
    return out[:max_items]

@retry()
def shopify_update_seo_rest(product_id: int, meta_title: Optional[str], meta_desc: Optional[str]):
    if DRY_RUN:
        log.info("[DRY_RUN] REST SEO update product %s: title=%s desc=%s", product_id, meta_title, meta_desc)
        return {"dry_run": True}
    payload = {"product": {"id": product_id}}
    if meta_title is not None:
        payload["product"]["metafields_global_title_tag"] = meta_title
    if meta_desc is not None:
        payload["product"]["metafields_global_description_tag"] = meta_desc
    r = http("PUT", f"{BASE_REST}/products/{product_id}.json", headers=HEADERS_REST, json=payload)
    return r.json()

@retry()
def shopify_update_seo_graphql(resource_id: str, seo_title: Optional[str], seo_desc: Optional[str]):
    if DRY_RUN:
        log.info("[DRY_RUN] GQL SEO update %s: metaTitle=%s metaDescription=%s", resource_id, seo_title, seo_desc)
        return {"dry_run": True}
    mutation = {
        "query": """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id title handle seo { title description } }
            userErrors { field message }
          }
        }
        """,
        "variables": {
            "input": {
                "id": resource_id,
                "seo": {"title": seo_title, "description": seo_desc}
            }
        }
    }
    r = http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=mutation)
    data = r.json()
    pu = data.get("data", {}).get("productUpdate")
    if not pu:
        log.error("GraphQL productUpdate no data: %s", data)
        return {"ok": False, "error": "no productUpdate data", "raw": data}
    errs = pu.get("userErrors") or []
    if errs:
        log.error("GraphQL productUpdate userErrors: %s", errs)
        return {"ok": False, "errors": errs, "raw": data}
    return {"ok": True, "data": pu}

def product_gid(pid: int) -> str:
    return f"gid://shopify/Product/{pid}"

# ─────────────────────────────────────────────────────────────
# Product Registration (REAL)
# ─────────────────────────────────────────────────────────────
def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9\- ]", "", (title or "").lower()).strip()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or f"prod-{int(time.time())}"

def _normalize_product_payload(p: dict) -> dict:
    title        = p.get("title") or "Untitled Product"
    body_html    = p.get("body_html") or p.get("body") or ""
    vendor       = p.get("vendor") or "Jeff’s Favorite Picks"
    product_type = p.get("product_type") or "General"
    tags         = p.get("tags") or []
    if isinstance(tags, list): tags_str = ",".join([str(t) for t in tags])
    else: tags_str = str(tags)

    handle = p.get("handle") or _slugify(title)[:80]

    images = p.get("images") or []
    images_norm = []
    for img in images:
        if isinstance(img, dict) and img.get("src"): images_norm.append({"src": img["src"]})
        elif isinstance(img, str): images_norm.append({"src": img})

    variants = p.get("variants") or []
    variants_norm = []
    for v in variants:
        vr = {
            "sku": str(v.get("sku") or ""),
            "price": str(v.get("price") or "0"),
            "option1": v.get("option1") or "Default",
            "option2": v.get("option2"),
            "option3": v.get("option3"),
            "inventory_management": "shopify",
        }
        if v.get("inventory_quantity") is not None:
            try: vr["inventory_quantity"] = int(v.get("inventory_quantity"))
            except: vr["inventory_quantity"] = 0
        variants_norm.append(vr)

    options = p.get("options") or []
    options_norm = []
    for opt in options:
        if isinstance(opt, dict) and opt.get("name"):
            options_norm.append({"name": opt["name"], "values": opt.get("values") or []})

    payload = {
        "product": {
            "title": title,
            "body_html": body_html,
            "vendor": vendor,
            "product_type": product_type,
            "tags": tags_str,
            "handle": handle,
            "images": images_norm,
        }
    }
    if options_norm: payload["product"]["options"] = options_norm
    if variants_norm: payload["product"]["variants"] = variants_norm
    return payload

@retry()
def _create_product(payload: dict) -> dict:
    if DRY_RUN:
        log.info("[DRY_RUN] Create product: %s", payload.get("product", {}).get("title"))
        return {"dry_run": True, "id": None}
    r = http("POST", f"{BASE_REST}/products.json", headers=HEADERS_REST, json=payload)
    prod = r.json().get("product", {})
    return {
        "id": prod.get("id"),
        "title": prod.get("title"),
        "handle": prod.get("handle"),
        "admin_url": f"https://admin.shopify.com/store/{SHOPIFY_STORE}/products/{prod.get('id')}" if prod.get("id") else None
    }

@app.route("/register", methods=["GET", "POST"])
@require_auth
def register():
    try:
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            products_input = body.get("products") or []
            if not products_input:
                return jsonify({"ok": False, "error": "empty_products"}), 400
            created, errors = [], []
            for p in products_input:
                try:
                    payload = _normalize_product_payload(p)
                    res = _create_product(payload)
                    created.append(res)
                except Exception as e:
                    log.exception("register create failed")
                    errors.append({"title": p.get("title"), "error": str(e)})
            return jsonify({"ok": True, "created": created, "errors": errors, "count": len(created)})
        # GET → demo create
        demo = {
            "title": "MagSafe Clear Case - iPhone 15",
            "body_html": "<p>Crystal clear anti-yellowing, MagSafe ready.</p>",
            "vendor": "Jeff’s Favorite Picks",
            "product_type": "Phone Case",
            "tags": ["magsafe","iphone","clear"],
            "images": [{"src": "https://picsum.photos/seed/magsafe15/800/800"}],
            "variants": [{"sku": f"MAGSAFE-15-CLR-{int(time.time())}", "price": "19.99", "inventory_quantity": 25, "option1": "Clear"}],
            "options": [{"name": "Color", "values": ["Clear"]}],
        }
        res = _create_product(_normalize_product_payload(demo))
        return jsonify({"ok": True, "created": [res], "demo": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Keyword Map (NEW): tokenize, build, cache
# ─────────────────────────────────────────────────────────────
STOPWORDS = {
    "the","and","for","you","your","with","from","this","that","are","our","has","have","was","were","will","can","all",
    "any","into","more","most","such","other","than","then","them","they","their","there","over","after","before",
    "not","but","about","also","how","what","when","where","which","while","who","whom","why","a","an","in","on","of",
    "to","by","as","at","is","it","be","or","we","i","me","my","mine","yours","its","it’s","it's",
    # product generics
    "new","pcs","pc","set","size","color","colors","style","styles","type","types","model","models","brand",
    "phone","smartphone","case","cases","accessory","accessories","pet","pets","device","devices",
    "for-iphone","iphone","samsung","xiaomi","android","apple","pro","max","ultra","series","gen",
    "magnetic","magsafe","wireless","charger","charging","usb","type-c","cable","cables","adapter","adapters",
    "band","bands","watch","watches","airpods","earbuds",
}

def strip_html(text: str) -> str:
    text = (text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def tokenize(text: str, min_len: int) -> List[str]:
    t = text.lower()
    t = re.sub(r"[_/|]", " ", t)
    return re.findall(r"[a-z0-9\+\-]{%d,}" % max(1, min_len), t)

def filter_stopwords(tokens: List[str], min_len: int) -> List[str]:
    out = []
    for w in tokens:
        if len(w) < min_len: continue
        if w in STOPWORDS: continue
        if re.fullmatch(r"\d[\d\-]*", w): continue
        out.append(w)
    return out

def bigrams(tokens: List[str]) -> List[str]:
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens)-1)]

_kw_cache = {"built_at": None, "params": None, "unigrams": [], "bigrams": [], "scanned": 0}

def _cache_valid(ttl_min: int) -> bool:
    if _kw_cache["built_at"] is None: return False
    return (time.time() - _kw_cache["built_at"]) <= ttl_min * 60

def _build_keyword_map(limit: int, min_len: int, include_bigrams: bool, scope: str="all") -> Dict[str,Any]:
    products = shopify_get_all_products(max_items=2000)
    uni, bi, scanned = Counter(), Counter(), 0
    for p in products:
        scanned += 1
        parts: List[str] = []
        if scope in ("all","titles"):
            parts.append(p.get("title") or "")
            for v in (p.get("variants") or []):
                if v.get("title"): parts.append(v["title"])
                if v.get("sku"):   parts.append(str(v["sku"]))
            for opt in (p.get("options") or []):
                if opt.get("name"): parts.append(opt["name"])
                for val in (opt.get("values") or []): parts.append(val)
        if scope in ("all","descriptions"):
            parts.append(strip_html(p.get("body_html") or ""))
        if scope in ("all","tags"):
            tags = p.get("tags") or []
            if isinstance(tags, list): parts.extend(tags)
            elif isinstance(tags, str): parts.extend([x.strip() for x in tags.split(",") if x.strip()])
        # images alt (REST has 'alt' on image)
        if scope in ("all",):
            for img in (p.get("images") or []):
                alt = (img.get("alt") or "").strip()
                if alt: parts.append(alt)
        text = " ".join([x for x in parts if x])
        toks = filter_stopwords(tokenize(text, min_len), min_len)
        uni.update(toks)
        if include_bigrams:
            bis = [b for b in bigrams(toks) if not any(w in STOPWORDS for w in b.split()) and not re.fullmatch(r"[\d\-\s]+", b)]
            bi.update(bis)
    return {"unigrams": uni.most_common(limit), "bigrams": bi.most_common(limit) if include_bigrams else [], "scanned": scanned}

def _get_keyword_map(limit: int, min_len: int, include_bigrams: bool, scope: str="all", force: bool=False) -> Dict[str,Any]:
    if (not force) and _cache_valid(KEYWORD_CACHE_TTL_MIN):
        return {
            "unigrams": _kw_cache["unigrams"][:limit],
            "bigrams":  _kw_cache["bigrams"][:limit] if include_bigrams else [],
            "scanned":  _kw_cache["scanned"],
            "cached":   True,
            "age_sec":  time.time() - _kw_cache["built_at"],
            "params":   _kw_cache["params"]
        }
    data = _build_keyword_map(limit, min_len, include_bigrams, scope)
    _kw_cache["built_at"] = time.time()
    _kw_cache["params"]   = {"limit": limit, "min_len": min_len, "include_bigrams": include_bigrams, "scope": scope}
    _kw_cache["unigrams"] = data["unigrams"]
    _kw_cache["bigrams"]  = data["bigrams"]
    _kw_cache["scanned"]  = data["scanned"]
    return {**data, "cached": False, "age_sec": 0, "params": _kw_cache["params"]}

# ── Keyword endpoints
@app.get("/seo/keywords/run")
@require_auth
def seo_keywords_run():
    limit   = int(request.args.get("limit", KEYWORD_LIMIT_DEFAULT))
    minlen  = int(request.args.get("min_len", KEYWORD_MIN_LEN))
    include = str(request.args.get("include_bigrams", str(KEYWORD_INCLUDE_BIGRAMS))).lower() in ("1","true","yes","on","y")
    scope   = (request.args.get("scope", "all") or "all").lower()
    savecsv = str(request.args.get("save_csv", str(KEYWORD_SAVE_CSV))).lower() in ("1","true","yes","on","y")
    t0 = time.time()
    data = _get_keyword_map(limit, minlen, include, scope, force=True)
    elapsed = round(time.time()-t0, 3)

    csv_path = None
    if savecsv:
        today = dt.datetime.utcnow().strftime("%Y%m%d")
        csv_path = f"/mnt/data/keyword_map_{today}.csv"
        try:
            import csv
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["keyword","count","type"])
                for k,c in data["unigrams"]: w.writerow([k,c,"unigram"])
                for k,c in (data["bigrams"] or []): w.writerow([k,c,"bigram"])
        except Exception as e:
            csv_path = f"save_failed: {e}"

    return jsonify({
        "ok": True, "elapsed_sec": elapsed, "products_scanned": data["scanned"],
        "params": {"limit":limit,"min_len":minlen,"include_bigrams":include,"scope":scope,"save_csv":savecsv},
        "unigrams": [{"keyword":k,"count":c} for k,c in data["unigrams"]],
        "bigrams":  [{"keyword":k,"count":c} for k,c in (data["bigrams"] or [])],
        "csv_path": csv_path
    })

@app.get("/seo/keywords/cache")
@require_auth
def seo_keywords_cache():
    age = None if _kw_cache["built_at"] is None else round(time.time()-_kw_cache["built_at"], 2)
    return jsonify({
        "ok": True,
        "built_at_epoch": _kw_cache["built_at"],
        "age_sec": age,
        "params": _kw_cache["params"],
        "unigrams_count": len(_kw_cache["unigrams"]),
        "bigrams_count": len(_kw_cache["bigrams"]),
        "products_scanned": _kw_cache["scanned"],
    })

# ─────────────────────────────────────────────────────────────
# SEO routines (keyword-weighted)
# ─────────────────────────────────────────────────────────────
def _ensure_list(v):
    return v if isinstance(v, list) else ([v] if v else [])

def _score_kw(kw: str, title: str, body: str, tags: List[str], boost_set: set) -> float:
    s = 0.0
    kw_re = rf"\b{re.escape(kw)}\b"
    if re.search(kw_re, title): s += 2.0
    if re.search(kw_re, body):  s += 1.0
    if any(kw in (t or "").lower() for t in tags): s += 1.5
    if kw in boost_set: s *= 1.5
    return s

def _compose_title(primary: str, benefit: str, cta: str) -> str:
    title = f"{primary} | {benefit}"
    # try to append CTA if fits
    if len(title) + 3 + len(cta) <= TITLE_MAX_LEN:
        title = f"{title} – {cta}"
    return (title[:TITLE_MAX_LEN]).rstrip(" -|·,")

def _compose_desc(keywords: List[str], base_body: str, cta: str) -> str:
    desc_kw = ", ".join(keywords[:3]) if keywords else ""
    base_desc = (base_body or "")[:120]
    if desc_kw and base_desc:
        desc = f"{desc_kw} — {base_desc}. {cta}."
    elif desc_kw:
        desc = f"{desc_kw}. {cta}."
    elif base_desc:
        desc = f"{base_desc}. {cta}."
    else:
        desc = f"Curated picks for everyday use. {cta}."
    return (desc[:DESC_MAX_LEN]).rstrip(" .,")

def ensure_alt_suggestions(p: Dict[str,Any]) -> List[str]:
    suggestions = []
    imgs = _ensure_list(p.get("images"))
    for i, img in enumerate(imgs):
        alt = (img.get("alt") or "").strip() if isinstance(img, dict) else ""
        if not alt:
            suggestions.append(f"{p.get('title','Product')} — image {i+1}")
    return suggestions

@app.get("/seo/optimize")
@require_auth
def seo_optimize():
    if not ADMIN_TOKEN:
        return jsonify({"ok": False, "error": "missing SHOPIFY_ADMIN_TOKEN"}), 400

    limit        = int(request.args.get("limit") or SEO_LIMIT)
    rotate       = (request.args.get("rotate", "true").lower() != "false")
    force        = str(request.args.get("force","false")).lower() in ("1","true","yes","on","y")
    force_kw     = str(request.args.get("force_keywords","false")).lower() in ("1","true","yes","on","y")
    kw_top_n     = int(request.args.get("kw_top_n", KW_TOP_N_FOR_WEIGHT) or KW_TOP_N_FOR_WEIGHT)

    # 1) keyword map (cached)
    km = _get_keyword_map(limit=max(kw_top_n, KEYWORD_LIMIT_DEFAULT),
                          min_len=KEYWORD_MIN_LEN,
                          include_bigrams=KEYWORD_INCLUDE_BIGRAMS,
                          scope="all",
                          force=force_kw)
    top_unigrams = [k for k,_ in km["unigrams"][:kw_top_n]]
    top_bigrams  = [k for k,_ in (km["bigrams"] or [])[:kw_top_n]]
    boost_set    = set(top_unigrams + top_bigrams)

    # 2) fetch products to update
    prods = shopify_get_products(limit=max(limit, 50))  # buffer
    targets = prods[:limit] if not rotate else prods[:limit]

    changed, errors = [], []
    benefit = "Fast Shipping · Quality Picks"

    for p in targets:
        pid = p.get("id")
        gid = product_gid(pid)
        try:
            title_raw = (p.get("title") or "").lower()
            body_raw  = strip_html(p.get("body_html") or "").lower()
            tags_list = p.get("tags") if isinstance(p.get("tags"), list) else \
                        ([x.strip() for x in (p.get("tags") or "").split(",")] if isinstance(p.get("tags"), str) else [])

            # 3) rank keywords for this product
            scored_bi  = sorted([(kw, _score_kw(kw, title_raw, body_raw, tags_list, boost_set)) for kw in top_bigrams], key=lambda x: x[1], reverse=True)
            scored_uni = sorted([(kw, _score_kw(kw, title_raw, body_raw, tags_list, boost_set)) for kw in top_unigrams], key=lambda x: x[1], reverse=True)

            chosen: List[str] = []
            for kw,sc in scored_bi:
                if sc <= 0: continue
                chosen.append(kw)
                if len(chosen) >= 3: break
            if len(chosen) < 5:
                for kw,sc in scored_uni:
                    if sc <= 0: continue
                    if kw not in chosen:
                        chosen.append(kw)
                        if len(chosen) >= 5: break

            primary = (chosen[0] if chosen else (p.get("title","").split(" ",1)[0] or "Best Picks"))
            meta_title = _compose_title(primary=primary, benefit=benefit, cta=CTA_PHRASE)
            meta_desc  = _compose_desc(keywords=chosen, base_body=strip_html(p.get("body_html") or ""), cta=CTA_PHRASE)

            # Skip if existing SEO is already decent (unless force=1)
            existing_title = p.get("metafields_global_title_tag")
            existing_desc  = p.get("metafields_global_description_tag")
            def ok_len(s, mx): return s and (15 <= len(s.strip()) <= mx)
            if (not force) and ok_len(existing_title, TITLE_MAX_LEN) and ok_len(existing_desc, DESC_MAX_LEN):
                changed.append({"id": pid, "handle": p.get("handle"), "skipped_reason": "existing_seo_ok"})
                continue

            # 4) Update via GraphQL or REST
            if USE_GRAPHQL:
                res = shopify_update_seo_graphql(gid, meta_title, meta_desc)
                if not res.get("ok", True):
                    res = shopify_update_seo_rest(pid, meta_title, meta_desc)
            else:
                res = shopify_update_seo_rest(pid, meta_title, meta_desc)

            changed.append({
                "id": pid,
                "handle": p.get("handle"),
                "metaTitle": meta_title,
                "metaDesc": meta_desc,
                "keywords_used": chosen[:5],
                "altSuggestions": ensure_alt_suggestions(p),
                "result": res
            })
        except Exception as e:
            log.exception("SEO update failed for %s", pid)
            errors.append({"id": pid, "handle": p.get("handle"), "error": str(e)})

    return jsonify({
        "ok": True,
        "action": "seo_optimize",
        "limit": limit,
        "rotate": rotate,
        "keyword_source": {
            "top_unigrams_used": len(top_unigrams),
            "top_bigrams_used": len(top_bigrams),
            "kw_cache_age_sec": None if _kw_cache["built_at"] is None else round(time.time()-_kw_cache["built_at"], 2),
        },
        "changed": changed,
        "errors": errors,
        "count": len(changed)
    })

@app.get("/run-seo")
@require_auth
def run_seo_alias():
    return seo_optimize()

# ─────────────────────────────────────────────────────────────
# Email (SendGrid)
# ─────────────────────────────────────────────────────────────
def send_email(subject: str, html: str, text: Optional[str]=None) -> Dict[str,Any]:
    if not ENABLE_EMAIL:
        log.info("Email disabled; subject=%s", subject)
        return {"ok": False, "reason": "email disabled"}
    if not SENDGRID_API_KEY or not EMAIL_TO:
        log.warning("Missing SENDGRID_API_KEY or EMAIL_TO; email skipped")
        return {"ok": False, "reason": "missing sendgrid or recipients"}
    payload = {
        "personalizations": [{"to": [{"email": e} for e in EMAIL_TO]}],
        "from": {"email": EMAIL_FROM, "name": "Automation"},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text or ""},
            {"type": "text/html",  "value": html}
        ]
    }
    try:
        r = http("POST", "https://api.sendgrid.com/v3/mail/send",
                 headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
                 json=payload)
        return {"ok": r.status_code in (200, 202), "status": r.status_code}
    except Exception as e:
        log.exception("Email send failed")
        return {"ok": False, "error": str(e)}

@app.get("/report/daily")
@require_auth
def report_daily():
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))  # KST
    date_s = now.strftime("%Y-%m-%d, %H:%M KST")
    subject = f"[Daily SEO Auto-Fix] JEFF’s Favorite Picks — {now.strftime('%Y-%m-%d')}"

    en = f"""
    <p>Hi Jeff team,</p>
    <p>Here’s today’s daily Google SEO optimization report for <b>{CANONICAL_DOMAIN or SHOPIFY_STORE}</b> ({date_s}).</p>
    <ul>
      <li>GraphQL: <b>{'ON' if USE_GRAPHQL else 'OFF'}</b></li>
      <li>Email notifications: <b>{'ON' if ENABLE_EMAIL else 'OFF'}</b></li>
      <li>Bing sitemap ping: <b>{'ON' if ENABLE_BING_PING else 'OFF'}</b></li>
      <li>GSC sitemap submit: <b>{'ON' if ENABLE_GSC_SITEMAP_SUBMIT else 'OFF'}</b></li>
    </ul>
    <p>Next actions: keep /run-seo on cron, ensure robots.txt has Sitemap, and manage sitemap in Search Console.</p>
    <p>Best,<br/>Automation</p>
    """

    kr = f"""
    <p>안녕하세요,</p>
    <p><b>{CANONICAL_DOMAIN or SHOPIFY_STORE}</b>의 일일 Google SEO 최적화 리포트입니다 ({date_s}).</p>
    <ul>
      <li>GraphQL 사용: <b>{'예' if USE_GRAPHQL else '아니오'}</b></li>
      <li>이메일 알림: <b>{'켜짐' if ENABLE_EMAIL else '꺼짐'}</b></li>
      <li>Bing 핑: <b>{'켜짐' if ENABLE_BING_PING else '꺼짐'}</b></li>
      <li>GSC 사이트맵 제출: <b>{'켜짐' if ENABLE_GSC_SITEMAP_SUBMIT else '꺼짐'}</b></li>
    </ul>
    <p>다음 조치: 크론으로 /run-seo 유지, robots.txt의 Sitemap 확인, Search Console에서 사이트맵 관리.</p>
    <p>감사합니다.<br/>Automation</p>
    """

    html = f"""
    <div style='font-family:system-ui,Segoe UI,Arial,sans-serif'>
      <h3>Daily SEO Auto-Fix Report</h3>
      {en}
      <hr/>
      {kr}
    </div>
    """
    res = send_email(subject, html, text=("Daily report attached"))
    return jsonify({"ok": True, "emailed": res, "subject": subject})

# ─────────────────────────────────────────────────────────────
# GSC Sitemap submit (optional)
# ─────────────────────────────────────────────────────────────
def gsc_submit_sitemap(sitemap_url: str) -> Dict[str,Any]:
    if not ENABLE_GSC_SITEMAP_SUBMIT:
        return {"ok": False, "reason": "disabled"}
    try:
        from googleapiclient.discovery import build  # type: ignore
        from google.oauth2 import service_account    # type: ignore
    except Exception as e:
        log.warning("GSC libs unavailable: %s", e)
        return {"ok": False, "reason": "google libs unavailable"}
    try:
        creds = None
        if GOOGLE_SERVICE_JSON_B64:
            data = base64.b64decode(GOOGLE_SERVICE_JSON_B64)
            creds = service_account.Credentials.from_service_account_info(json.loads(data))
        elif GOOGLE_SERVICE_JSON_PATH and pathlib.Path(GOOGLE_SERVICE_JSON_PATH).exists():
            creds = service_account.Credentials.from_service_account_file(GOOGLE_SERVICE_JSON_PATH)
        else:
            return {"ok": False, "reason": "missing service account"}
        service = build('searchconsole', 'v1', credentials=creds, cache_discovery=False)
        res = service.sitemaps().submit(siteUrl=GSC_SITE_URL, feedpath=sitemap_url).execute()
        return {"ok": True, "result": res}
    except Exception as e:
        log.exception("GSC submit failed")
        return {"ok": False, "error": str(e)}

@app.get("/gsc/sitemap/submit")
@require_auth
def gsc_submit():
    sitemap = request.args.get("sitemap") or PRIMARY_SITEMAP
    res = gsc_submit_sitemap(sitemap)
    return jsonify(res)

# ─────────────────────────────────────────────────────────────
# Robots, Sitemap, Ping / IndexNow
# ─────────────────────────────────────────────────────────────
def _as_lastmod(iso_str: str) -> str:
    if not iso_str:
        return dt.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"
    try:
        if iso_str.endswith("Z"): return iso_str
        return iso_str.replace("+00:00", "Z")
    except:
        return dt.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"

def _canonical_product_url(handle: str) -> str:
    if CANONICAL_DOMAIN:
        return f"https://{CANONICAL_DOMAIN}/products/{handle}"
    return f"https://{SHOPIFY_STORE}.myshopify.com/products/{handle}"

@app.get("/sitemap-products.xml")
def sitemap_products():
    try:
        r = http("GET", f"{BASE_REST}/products.json", headers=HEADERS_REST,
                 params={"limit": 250, "fields": "id,handle,updated_at,published_at,status,images"})
        data = r.json()
        nodes = []
        for p in data.get("products", []):
            if p.get("status") != "active" or not p.get("published_at"): continue
            loc = _canonical_product_url(p["handle"])
            lastmod = _as_lastmod(p.get("updated_at") or p.get("published_at"))
            image_tag = ""
            imgs = p.get("images") or []
            if imgs and imgs[0].get("src"):
                image_tag = f"\n    <image:image><image:loc>{imgs[0]['src']}</image:loc></image:image>"
            nodes.append(f"\n  <url>\n    <loc>{loc}</loc>\n    <lastmod>{lastmod}</lastmod>{image_tag}\n  </url>")
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
                '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
                f'{"".join(nodes)}\n'
                '</urlset>')
        return Response(body, mimetype="application/xml")
    except Exception as e:
        return Response(f"<!-- sitemap error: {e} -->", mimetype="application/xml", status=500)

@app.get("/robots.txt")
def robots():
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {PRIMARY_SITEMAP}" if PRIMARY_SITEMAP else "",
        f"Sitemap: {PUBLIC_BASE}/sitemap-products.xml" if PUBLIC_BASE else "Sitemap: /sitemap-products.xml",
    ]
    return Response("\n".join([l for l in lines if l]) + "\n", mimetype="text/plain")

@app.get("/bing/ping")
@require_auth
def bing_ping():
    # Bing sitemap ping은 공식적으로 410 Gone (deprecated)
    return jsonify({
        "ok": False,
        "reason": "bing sitemap ping deprecated (HTTP 410)",
        "action": "use /indexnow/submit instead"
    }), 410

@app.post("/indexnow/submit")
@require_auth
def indexnow_submit():
    """
    Body(JSON):
    {
      "urls": ["https://jeffsfavoritepicks.com/products/...", "..."],  # 선택
      "use_sitemap": true                                             # 선택: sitemap도 함께 제출
    }
    """
    key = INDEXNOW_KEY
    key_url = INDEXNOW_KEY_URL
    if not key or not key_url:
        return jsonify({"ok": False, "error": "missing INDEXNOW_KEY / INDEXNOW_KEY_URL"}), 400

    data = request.get_json(silent=True) or {}
    urls = data.get("urls") or []
    if data.get("use_sitemap") and PRIMARY_SITEMAP:
        urls.append(PRIMARY_SITEMAP)
    if not urls:
        return jsonify({"ok": False, "error": "no urls"}), 400

    payload = {
        "host": CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com",
        "key": key,
        "keyLocation": key_url,
        "urlList": urls
    }
    r = http("POST", "https://api.indexnow.org/indexnow",
             json=payload, headers={"Content-Type": "application/json"})
    return jsonify({"ok": 200 <= r.status_code < 300, "status": r.status_code, "response": r.text[:500]})

# ─────────────────────────────────────────────────────────────
# Misc convenience endpoints
# ─────────────────────────────────────────────────────────────
@app.get("/")
def root():
    base = request.host_url
    return jsonify({
        "ok": True,
        "service": "unified-pro",
        "health": f"{base}health",
        "routes": f"{base}__routes?auth=***",
        "run_seo": f"{base}run-seo?auth=***&limit=10&rotate=true",
        "register_demo": f"{base}register?auth=***",
    })

@app.get("/__routes")
@require_auth
def list_routes():
    routes = []
    for r in app.url_map.iter_rules():
        routes.append({"rule": str(r), "endpoint": r.endpoint, "methods": sorted(list(r.methods))})
    return jsonify({"count": len(routes), "routes": routes})

@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "store": SHOPIFY_STORE,
        "v": API_VERSION,
        "use_graphql": USE_GRAPHQL,
        "email_enabled": ENABLE_EMAIL,
        "bing_ping": ENABLE_BING_PING,
        "gsc_sitemap_submit": ENABLE_GSC_SITEMAP_SUBMIT,
        "ts": dt.datetime.utcnow().isoformat()+"Z"
    })

# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    log.info("Starting server on :%s", port)
    app.run(host="0.0.0.0", port=port)

