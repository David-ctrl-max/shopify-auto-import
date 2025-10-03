# main.py — Unified Pro (Register + Auto Body HTML + SEO + Keyword-Weighted Optimize + Sitemap + Email + IndexNow + Blog Auto-Post + Intent + Orphan/Speed Report + Share Snippets)
# =========================================================================================================
# ✅ What’s included (2025-10-02 + quick-win patches)
# - /register (GET/POST)          : real Shopify product creation (images/options/variants/inventory)
#   ↳ Auto body_html(text-first), ALT auto, TitleCase normalize, Story/Pros&Cons/Differentiators
# - /seo/optimize                 : keyword-weighted SEO meta (title/desc) + Long-tail bias + Intent aware
#   ↳ Related Picks internal links injection (idempotent, top+bottom) + seasonal/click phrases
# - /run-seo                      : alias to /seo/optimize (cron)
# - /seo/keywords/run             : build keyword map (unigram/bigram), + intent tags per keyword
# - /seo/keywords/cache           : keyword cache status
# - /blog/auto-post               : review/compare article generator + min 3 internal links + share snippets
# - /sitemap-index.xml            : sitemap index (host main + this service’s product sitemap)
# - /sitemap-products.xml         : product-only sitemap (canonical domain aware, real lastmod, image:image)
# - /robots.txt                   : robots with Sitemap lines (+ sitemap-index)
# - /bing/ping                    : 410 Gone 안내 (Bing sitemap ping deprecated)
# - /indexnow/submit              : IndexNow 제출 (guard 포함)
# - /gsc/sitemap/submit           : optional Search Console sitemap submit (fallback ping)
# - /report/daily                 : EN/KR daily email; orphaned-page suspects + speed(WebP/LazyLoad) checks
# - /health, /__routes, /         : diagnostics
#
# 🔐 Auth: Authorization: Bearer <IMPORT_AUTH_TOKEN> (또는 ?auth= / X-Auth), (옵션) IP_ALLOWLIST
# =========================================================================================================
# 🌎 Environment (Render)
# IMPORT_AUTH_TOKEN=jeffshopsecure
# SHOPIFY_STORE=jeffsfavoritepicks
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
# IP_ALLOWLIST=                 # (optional) "1.2.3.4,5.6.7.8"
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
# GOOGLE_SERVICE_JSON_B64=...
# GOOGLE_SERVICE_JSON_PATH=/app/sa.json
#
# # Keyword Map
# KEYWORD_MIN_LEN=3
# KEYWORD_LIMIT=100
# KEYWORD_INCLUDE_BIGRAMS=true
# KEYWORD_SAVE_CSV=false
# KEYWORD_CACHE_TTL_MIN=60
#
# # Keyword Weighting for /seo/optimize
# KW_TOP_N_FOR_WEIGHT=30
# TITLE_MAX_LEN=60
# DESC_MAX_LEN=160
# CTA_PHRASE="Grab Yours"
#
# # Auto body generator
# BODY_MIN_CHARS=120
# BODY_FORCE_OVERWRITE=false
# BODY_INCLUDE_GALLERY=true
# NORMALIZE_TITLECASE=true
# ALT_AUTO_GENERATE=true
# BRAND_NAME="Jeff’s Favorite Picks"
# BENEFIT_LINE_EN="Fast Shipping · Quality Picks"
# BENEFIT_LINE_KR="빠른 배송 · 엄선된 픽"
#
# # Internal links injection
# ALLOW_BODY_LINK_INJECTION=true
# RELATED_LINKS_MAX=3
# RELATED_SECTION_MARKER="<!--related-picks-->"
# RELATED_TOP_MARKER="<!--related-picks-top-->"   # NEW
#
# # Blog auto post
# BLOG_AUTO_POST=true
# BLOG_HANDLE=news
# BLOG_DEFAULT_TOPIC="Phone Accessories"
# BLOG_POST_TYPE=review  # review|compare
#
# # Intent/Report tuning
# INTENT_CLASSIFY=true
# ORPHAN_LINK_MIN=1
# SPEED_WEBP_THRESHOLD=0.6
# SEASONAL_WORDS="2025 New, Free Shipping, Limited Stock"
# =========================================================================================================

import os, sys, json, time, base64, pathlib, logging, re, random
from typing import Any, Dict, List, Optional, Tuple
import datetime as dt
from collections import Counter

import requests
from flask import Flask, request, jsonify, Response
from functools import wraps
from jinja2 import Template

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

try:
    logs_dir = pathlib.Path("logs"); logs_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(logs_dir / "app.log")
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
    log.addHandler(fh)
except Exception as e:
    log.warning("File logging disabled: %s", e)

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
IP_ALLOWLIST     = [x.strip() for x in env_str("IP_ALLOWLIST","").split(",") if x.strip()]

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

# Keyword map
KEYWORD_MIN_LEN         = env_int("KEYWORD_MIN_LEN", 3)
KEYWORD_LIMIT_DEFAULT   = env_int("KEYWORD_LIMIT", 100)
KEYWORD_INCLUDE_BIGRAMS = env_bool("KEYWORD_INCLUDE_BIGRAMS", True)
KEYWORD_SAVE_CSV        = env_bool("KEYWORD_SAVE_CSV", False)
KEYWORD_CACHE_TTL_MIN   = env_int("KEYWORD_CACHE_TTL_MIN", 60)

# Weighting for optimize
KW_TOP_N_FOR_WEIGHT = env_int("KW_TOP_N_FOR_WEIGHT", 30)
TITLE_MAX_LEN       = env_int("TITLE_MAX_LEN", 60)
DESC_MAX_LEN        = env_int("DESC_MAX_LEN", 160)
CTA_PHRASE          = env_str("CTA_PHRASE", "Grab Yours")

# Auto body generator
BODY_MIN_CHARS         = env_int("BODY_MIN_CHARS", 120)
BODY_FORCE_OVERWRITE   = env_bool("BODY_FORCE_OVERWRITE", False)
BODY_INCLUDE_GALLERY   = env_bool("BODY_INCLUDE_GALLERY", True)
NORMALIZE_TITLECASE    = env_bool("NORMALIZE_TITLECASE", True)
ALT_AUTO_GENERATE      = env_bool("ALT_AUTO_GENERATE", True)
BRAND_NAME             = env_str("BRAND_NAME", "Jeff’s Favorite Picks")
BENEFIT_LINE_EN        = env_str("BENEFIT_LINE_EN", "Fast Shipping · Quality Picks")
BENEFIT_LINE_KR        = env_str("BENEFIT_LINE_KR", "빠른 배송 · 엄선된 픽")

# Internal links
ALLOW_BODY_LINK_INJECTION = env_bool("ALLOW_BODY_LINK_INJECTION", True)
RELATED_LINKS_MAX         = env_int("RELATED_LINKS_MAX", 3)
RELATED_SECTION_MARKER    = env_str("RELATED_SECTION_MARKER", "<!--related-picks-->")
RELATED_TOP_MARKER        = env_str("RELATED_TOP_MARKER", "<!--related-picks-top-->")

# Blog auto post
BLOG_AUTO_POST      = env_bool("BLOG_AUTO_POST", True)
BLOG_HANDLE         = env_str("BLOG_HANDLE", "news")
BLOG_DEFAULT_TOPIC  = env_str("BLOG_DEFAULT_TOPIC", "Phone Accessories")
BLOG_POST_TYPE      = env_str("BLOG_POST_TYPE", "review")

# Intent/Report tuning
INTENT_CLASSIFY        = env_bool("INTENT_CLASSIFY", True)
ORPHAN_LINK_MIN        = env_int("ORPHAN_LINK_MIN", 1)
SPEED_WEBP_THRESHOLD   = float(env_str("SPEED_WEBP_THRESHOLD", "0.6"))
SEASONAL_WORDS         = [w.strip() for w in env_str("SEASONAL_WORDS","2025 New, Free Shipping, Limited Stock").split(",") if w.strip()]

# --- PATCH START: config validation & safety ---
REQUIRED_ENVS = {
    "SHOPIFY_STORE": SHOPIFY_STORE,
    "SHOPIFY_ADMIN_TOKEN": ADMIN_TOKEN,
    "SHOPIFY_API_VERSION": API_VERSION,
}
_missing = [k for k,v in REQUIRED_ENVS.items() if not v]
if _missing:
    log.error("Missing required env(s): %s", ", ".join(_missing))
    # raise SystemExit(f"Missing required env(s): {', '.join(_missing)}")

MAX_PRODUCTS_SCAN = int(os.getenv("MAX_PRODUCTS_SCAN", "6000"))
MAX_ENDPOINT_LIMIT = int(os.getenv("MAX_ENDPOINT_LIMIT", "250"))
def clamp(n, lo, hi):
    try: n = int(n)
    except: n = lo
    return max(lo, min(hi, n))  # --- PATCH FIX: clamp
# --- PATCH END ---

# ─────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# Auth & HTTP helpers
# ─────────────────────────────────────────────────────────────
# --- PATCH START: stronger auth (Bearer + IP allowlist) ---
def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token_qs = request.args.get("auth")
        bearer = (request.headers.get("Authorization") or "").strip()
        token_hdr = request.headers.get("X-Auth")
        token = None
        if bearer.lower().startswith("bearer "):
            token = bearer.split(" ",1)[1].strip()
        token = token or token_hdr or token_qs

        if IP_ALLOWLIST:
            remote = request.headers.get("X-Forwarded-For", request.remote_addr or "")
            client_ip = remote.split(",")[0].strip()
            if client_ip not in IP_ALLOWLIST:
                log.warning("IP not allowed: %s", client_ip)
                return jsonify({"ok": False, "error": "forbidden_ip"}), 403

        if token != IMPORT_AUTH_TOKEN:
            log.warning("Auth failed for %s", request.path)
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper
# --- PATCH END ---

# --- PATCH START: retry/http hardening ---
def retry(max_attempts=3, base_delay=0.6, factor=2.0, allowed=(429, 500, 502, 503, 504)):
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, max_attempts+1):
                try:
                    return fn(*args, **kwargs)
                except requests.HTTPError as e:
                    status = e.response.status_code if e.response is not None else None
                    body = (e.response.text[:300] if e.response is not None else "")
                    log.warning("HTTPError %s/%s status=%s body=%s", attempt, max_attempts, status, body)
                    if attempt >= max_attempts or status not in allowed:
                        raise
                except Exception as e:
                    log.warning("Error %s/%s: %s", attempt, max_attempts, e)
                    if attempt >= max_attempts:
                        raise
                time.sleep(delay)
                delay *= factor
        return inner
    return deco

@retry()
def http(method: str, url: str, **kwargs) -> requests.Response:
    r = requests.request(method, url, timeout=30, **kwargs)
    if r.status_code >= 400:
        log.error("HTTP %s %s -> %s", method, url, r.status_code)
        r.raise_for_status()
    return r
# --- PATCH END ---

# ─────────────────────────────────────────────────────────────
# Shopify Admin (REST + GraphQL)
# ─────────────────────────────────────────────────────────────
BASE_REST    = f"https://{SHOPIFY_STORE}.myshopify.com/admin/api/{API_VERSION}"
BASE_GRAPHQL = f"https://{SHOPIFY_STORE}.myshopify.com/admin/api/{API_VERSION}/graphql.json"
HEADERS_REST = {"X-Shopify-Access-Token": ADMIN_TOKEN, "Content-Type": "application/json", "Accept":"application/json"}
HEADERS_GQL  = {"X-Shopify-Access-Token": ADMIN_TOKEN, "Content-Type": "application/json", "Accept":"application/json"}

@retry()
def shopify_get_products(limit: int=SEO_LIMIT) -> List[Dict[str,Any]]:
    r = http("GET", f"{BASE_REST}/products.json", headers=HEADERS_REST, params={"limit": min(250, int(limit))})
    return r.json().get("products", [])

# --- PATCH START: GraphQL pagination for all products ---
def _gql_products_page(after_cursor: Optional[str]=None, page_size: int=250) -> dict:
    q = {
        "query": """
        query($first:Int!, $after:String) {
          products(first:$first, after:$after, sortKey:UPDATED_AT) {
            edges {
              cursor
              node {
                id handle title updatedAt publishedAt
                tags
                descriptionHtml
                images(first:10) { edges { node { url altText } } }
                options { name values }
                variants(first:50) { edges { node { title sku price } } }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """,
        "variables": {"first": min(250, page_size), "after": after_cursor}
    }
    r = http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=q)
    return r.json()["data"]["products"]

def _edge_to_restish(pnode: dict) -> dict:
    imgs = [{"src": e["node"]["url"], "alt": e["node"]["altText"] or ""} for e in (pnode.get("images",{}).get("edges") or [])]
    vars = [{"title": v["node"]["title"], "sku": v["node"]["sku"], "price": v["node"]["price"]} for v in (pnode.get("variants",{}).get("edges") or [])]
    return {
        "id": int(pnode["id"].split("/")[-1]),
        "title": pnode.get("title"),
        "handle": pnode.get("handle"),
        "updated_at": pnode.get("updatedAt"),
        "published_at": pnode.get("publishedAt"),
        "body_html": pnode.get("descriptionHtml") or "",
        "tags": pnode.get("tags") or [],
        "images": imgs,
        "variants": vars,
        "options": pnode.get("options") or [],
    }

def shopify_get_all_products(max_items: int = 2000) -> List[Dict[str,Any]]:
    items, after, fetched = [], None, 0
    while True:
        data = _gql_products_page(after_cursor=after, page_size=250)
        edges = data["edges"]
        for e in edges:
            items.append(_edge_to_restish(e["node"]))
            fetched += 1
            if fetched >= min(MAX_PRODUCTS_SCAN, max_items):
                return items
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]
    return items
# --- PATCH END ---

@retry()
def shopify_update_seo_rest(product_id: int, meta_title: Optional[str], meta_desc: Optional[str], body_html: Optional[str]=None):
    if DRY_RUN:
        log.info("[DRY_RUN] REST SEO update product %s: title=%s desc=%s body?%s", product_id, meta_title, meta_desc, bool(body_html))
        return {"dry_run": True}
    payload = {"product": {"id": product_id}}
    if meta_title is not None:
        payload["product"]["metafields_global_title_tag"] = meta_title
    if meta_desc is not None:
        payload["product"]["metafields_global_description_tag"] = meta_desc
    if body_html is not None:
        payload["product"]["body_html"] = body_html
    r = http("PUT", f"{BASE_REST}/products/{product_id}.json", headers=HEADERS_REST, json=payload)
    return r.json()

@retry()
def shopify_update_seo_graphql(resource_id: str, seo_title: Optional[str], seo_desc: Optional[str], body_html: Optional[str]=None):
    if DRY_RUN:
        log.info("[DRY_RUN] GQL SEO update %s: metaTitle=%s metaDescription=%s body?%s", resource_id, seo_title, seo_desc, bool(body_html))
        return {"dry_run": True}
    mutation = {
        "query": """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id title descriptionHtml seo { title description } }
            userErrors { field message }
          }
        }
        """,
        "variables": {
            "input": {
                "id": resource_id,
                **({"seo": {"title": seo_title, "description": seo_desc}} if (seo_title or seo_desc) else {}),
                **({"descriptionHtml": body_html} if body_html is not None else {})
            }
        }
    }
    r = http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=mutation)
    data = r.json()
    pu = data.get("data", {}).get("productUpdate")
    errs = (pu or {}).get("userErrors") or []
    if not pu or errs:
        log.error("GraphQL productUpdate issue: %s", errs or data)
        return {"ok": False, "errors": errs or ["no productUpdate data"], "raw": data}
    return {"ok": True, "data": pu}

def product_gid(pid: int) -> str:
    return f"gid://shopify/Product/{pid}"

# ─────────────────────────────────────────────────────────────
# Utils (body_html / keywords / intent)
# ─────────────────────────────────────────────────────────────
STOPWORDS = {
    "the","and","for","you","your","with","from","this","that","are","our","has","have","was","were","will","can","all",
    "any","into","more","most","such","other","than","then","them","they","their","there","over","after","before",
    "not","but","about","also","how","what","when","where","which","while","who","whom","why","a","an","in","on","of",
    "to","by","as","at","is","it","be","or","we","i","me","my","mine","yours","its","it’s","it's",
    "new","pcs","pc","set","size","color","colors","style","styles","type","types","model","models","brand",
    "phone","smartphone","case","cases","accessory","accessories","pet","pets","device","devices",
    "for-iphone","iphone","samsung","xiaomi","android","apple","pro","max","ultra","series","gen",
    "magnetic","magsafe","wireless","charger","charging","usb","type-c","cable","cables","adapter","adapters",
    "band","bands","watch","watches","airpods","earbuds",
}

INTENT_LEX = {
    "informational": ["how", "what", "guide", "tips", "tutorial", "review", "size guide", "faq", "benefits", "pros", "cons"],
    "commercial":    ["best", "top", "compare", "vs", "versus", "brands", "recommend", "recommendation", "deal", "discount"],
    "transactional": ["buy", "price", "coupon", "free shipping", "order", "checkout", "shop", "sale"]
}

# --- PATCH START: intent classification via word-boundary regex ---
def classify_intent_from_text(text: str) -> str:
    if not INTENT_CLASSIFY: return "unknown"
    t = (text or "").lower()
    score = {"informational":0, "commercial":0, "transactional":0}
    for intent, keys in INTENT_LEX.items():
        for k in keys:
            if re.search(rf"\b{re.escape(k.lower())}\b", t):
                score[intent] += 1
    intent = max(score, key=score.get)
    return intent if score[intent] > 0 else "unknown"
# --- PATCH END ---

def strip_html(text: str) -> str:
    text = (text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def title_case(s: str) -> str:
    if not s: return s
    words = re.split(r"(\s+|-|/)", str(s))
    def tc(w: str) -> str:
        if not w or re.fullmatch(r"\W+", w): return w
        if w.lower() in {"for","and","or","to","of","a","an","the","in","on","at","by"}:
            return w.lower()
        return w[0].upper() + w[1:].lower()
    return "".join(tc(w) for w in words)

def ensure_titlecase_in_product(p: dict):
    if not NORMALIZE_TITLECASE: return p
    opts = p.get("options") or []
    for opt in opts:
        if isinstance(opt, dict):
            if opt.get("name"): opt["name"] = title_case(opt["name"])
            if isinstance(opt.get("values"), list):
                opt["values"] = [title_case(v) for v in opt["values"]]
    tags = p.get("tags")
    if isinstance(tags, list):
        p["tags"] = [title_case(t) for t in tags]
    elif isinstance(tags, str):
        p["tags"] = ",".join([title_case(x.strip()) for x in tags.split(",") if x.strip()])
    return p

def inject_auto_alt_to_images(p: dict):
    if not ALT_AUTO_GENERATE: return p
    title = p.get("title") or "Product"
    imgs = p.get("images") or []
    new = []
    for i, img in enumerate(imgs):
        if isinstance(img, str):
            new.append({"src": img, "alt": f"{title} — image {i+1}"})
        elif isinstance(img, dict):
            if not (img.get("alt") or "").strip():
                img["alt"] = f"{title} — image {i+1}"
            new.append(img)
    p["images"] = new
    return p

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

def best_keywords_from_product(p: dict, top_n: int = 8) -> List[str]:
    parts: List[str] = []
    parts.append(p.get("title") or "")
    parts.append(strip_html(p.get("body_html") or ""))
    tags = p.get("tags")
    if isinstance(tags, list): parts.extend(tags)
    elif isinstance(tags, str): parts.extend([x.strip() for x in tags.split(",") if x.strip()])
    for opt in (p.get("options") or []):
        if isinstance(opt, dict):
            if opt.get("name"): parts.append(opt["name"])
            for v in (opt.get("values") or []): parts.append(v)
    for v in (p.get("variants") or []):
        if isinstance(v, dict):
            if v.get("title"): parts.append(v["title"])
            if v.get("sku"):   parts.append(str(v["sku"]))
    tokens = filter_stopwords(tokenize(" ".join(parts), KEYWORD_MIN_LEN), KEYWORD_MIN_LEN)
    uni = Counter(tokens)
    key_list = [k for k,_ in uni.most_common(top_n)]
    return key_list

def make_feature_list_from_keywords(kws: List[str]) -> List[str]:
    feats = []
    for kw in kws:
        feats.append(kw.replace("-", " ").title())
    base = ["Lightweight", "Durable Materials", "Easy to Use", "Fits Most Devices", "Gift-Ready Packaging"]
    for b in base:
        if len(feats) >= 8: break
        if b.lower() not in " ".join(feats).lower():
            feats.append(b)
    return feats[:8]

# --- PATCH START: Jinja2 template for body_html ---
_PDP_TMPL = Template("""
<div class='pdp-copy'>
  <h2>{{ title }}</h2>
  <p><strong>{{ vendor }}</strong> — {{ benefit_en }} / {{ benefit_kr }}</p>
  <p>{{ story }}</p>

  {% if bullets %}
  <h3>Key Features</h3>
  <ul>
    {% for b in bullets %}<li>{{ b }}</li>{% endfor %}
  </ul>
  {% endif %}

  <h3>Pros & Cons</h3>
  <p><strong>Pros:</strong> Durable, easy to use, modern look.<br><strong>Cons:</strong> Check device/size/color before ordering.</p>

  {% if specs %}
  <h3>Specs</h3>
  <table role="table" class="pdp-specs">
  {% for k,v in specs %}<tr><th>{{ k }}</th><td>{{ v }}</td></tr>{% endfor %}
  </table>
  {% endif %}

  <p>Differentiators: {{ differentiators }}</p>
  <p><em>Tip:</em> Add to cart now — limited stock! <strong>{{ cta }}</strong>.</p>
  {% if has_gallery %}<p class="pdp-note">See product images above for color and style references.</p>{% endif %}
</div>
""".strip())

def build_text_body_html(p: dict) -> str:
    title = p.get("title") or "Product"
    vendor = p.get("vendor") or BRAND_NAME
    kws = best_keywords_from_product(p, top_n=10)
    bullets = make_feature_list_from_keywords(kws)
    specs: List[Tuple[str,str]] = []
    for opt in (p.get("options") or []):
        if isinstance(opt, dict) and opt.get("name") and opt.get("values"):
            name = title_case(opt["name"]) if NORMALIZE_TITLECASE else opt["name"]
            vals = ", ".join([title_case(v) if NORMALIZE_TITLECASE else v for v in opt["values"]])
            specs.append((name, vals))
    html = _PDP_TMPL.render(
        title=title,
        vendor=vendor,
        benefit_en=BENEFIT_LINE_EN,
        benefit_kr=BENEFIT_LINE_KR,
        story=f"{title} solves daily hassles with reliable build and clean design — ideal for commuting, travel, or gifting.",
        bullets=bullets,
        specs=specs,
        differentiators="Better grip, scratch-resistant finish, and easy compatibility with popular models.",
        cta=CTA_PHRASE,
        has_gallery=bool(p.get("images") or [])
    )
    return html
# --- PATCH END ---

def should_generate_body(existing: Optional[str]) -> bool:
    if BODY_FORCE_OVERWRITE:
        return True
    clean = strip_html(existing or "")
    return len(clean) < BODY_MIN_CHARS

# ─────────────────────────────────────────────────────────────
# Product Registration (REAL)
# ─────────────────────────────────────────────────────────────
def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9\- ]", "", (title or "").lower()).strip()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or f"prod-{int(time.time())}"

def _normalize_product_payload(p: dict) -> dict:
    p = ensure_titlecase_in_product(p)
    p = inject_auto_alt_to_images(p)

    title        = p.get("title") or "Untitled Product"
    body_html_in = p.get("body_html") or p.get("body") or ""
    if should_generate_body(body_html_in):
        try:
            body_html_in = build_text_body_html({"title": title,
                                                 "vendor": p.get("vendor") or BRAND_NAME,
                                                 "options": p.get("options") or [],
                                                 "variants": p.get("variants") or [],
                                                 "images": p.get("images") or [],
                                                 "tags": p.get("tags")})
        except Exception as e:
            log.warning("Auto body_html build failed, fallback to minimal: %s", e)
            body_html_in = f"<p>{title} — {BENEFIT_LINE_EN} / {BENEFIT_LINE_KR}. {CTA_PHRASE}.</p>"

    vendor       = p.get("vendor") or BRAND_NAME
    product_type = p.get("product_type") or "General"
    tags         = p.get("tags") or []
    if isinstance(tags, list): tags_str = ",".join([str(t) for t in tags])
    else: tags_str = str(tags)

    handle = p.get("handle") or _slugify(title)[:80]

    images = p.get("images") or []
    images_norm = []
    for img in images:
        if isinstance(img, dict) and img.get("src"):
            images_norm.append({"src": img["src"], **({"alt": img["alt"]} if img.get("alt") else {})})
        elif isinstance(img, str):
            images_norm.append({"src": img})

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
            "body_html": body_html_in,
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
        demo = {
            "title": "MagSafe Clear Case - iPhone 15",
            "body_html": "",
            "vendor": BRAND_NAME,
            "product_type": "Phone Case",
            "tags": ["MagSafe","iPhone","Clear"],
            "images": [{"src": "https://picsum.photos/seed/magsafe15/800/800"}],
            "variants": [{"sku": f"MAGSAFE-15-CLR-{int(time.time())}", "price": "19.99", "inventory_quantity": 25, "option1": "Clear"}],
            "options": [{"name": "Color", "values": ["Clear"]}],
        }
        res = _create_product(_normalize_product_payload(demo))
        return jsonify({"ok": True, "created": [res], "demo": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Keyword Map (cached) + Intent tags
# ─────────────────────────────────────────────────────────────
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
                if isinstance(v, dict):
                    if v.get("title"): parts.append(v["title"])
                    if v.get("sku"):   parts.append(str(v["sku"]))
            for opt in (p.get("options") or []):
                if isinstance(opt, dict):
                    if opt.get("name"): parts.append(opt["name"])
                    for val in (opt.get("values") or []): parts.append(val)
        if scope in ("all","descriptions"):
            parts.append(strip_html(p.get("body_html") or ""))
        if scope in ("all","tags"):
            tags = p.get("tags") or []
            if isinstance(tags, list): parts.extend(tags)
            elif isinstance(tags, str): parts.extend([x.strip() for x in tags.split(",") if x.strip()])
        if scope in ("all",):
            for img in (p.get("images") or []):
                if isinstance(img, dict):
                    alt = (img.get("alt") or "").strip()
                    if alt: parts.append(alt)
        text = " ".join([x for x in parts if x])
        toks = filter_stopwords(tokenize(text, min_len), min_len)
        uni.update(toks)
        if include_bigrams:
            bis = [b for b in bigrams(toks) if not any(w in STOPWORDS for w in b.split()) and not re.fullmatch(r"[\d\-\s]+", b)]
            bi.update(bis)
    uni_top = uni.most_common(limit)
    bi_top  = bi.most_common(limit) if include_bigrams else []
    def tag_intent(kw:str)->str:
        return classify_intent_from_text(kw)
    uni_tagged = [(k,c,tag_intent(k)) for k,c in uni_top]
    bi_tagged  = [(k,c,tag_intent(k)) for k,c in bi_top]
    return {"unigrams": uni_tagged, "bigrams": bi_tagged, "scanned": scanned}

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

@app.get("/seo/keywords/run")
@require_auth
def seo_keywords_run():
    limit   = int(request.args.get("limit", KEYWORD_LIMIT_DEFAULT))
    minlen  = int(request.args.get("min_len", KEYWORD_MIN_LEN))
    include = str(request.args.get("include_bigrams", str(KEYWORD_INCLUDE_BIGRAMS))).lower() in ("1","true","yes","on","y")
    scope   = (request.args.get("scope", "all") or "all").lower()
    savecsv = str(request.args.get("save_csv", str(KEYWORD_SAVE_CSV))).lower() in ("1","true","yes","on","y")

    # --- PATCH: param validation ---
    limit  = clamp(limit, 10, 2000)
    minlen = clamp(minlen, 2, 10)

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
                w = csv.writer(f); w.writerow(["keyword","count","type","intent"])
                for k,c,i in data["unigrams"]: w.writerow([k,c,"unigram",i])
                for k,c,i in (data["bigrams"] or []): w.writerow([k,c,"bigram",i])
        except Exception as e:
            csv_path = f"save_failed: {e}"

    return jsonify({
        "ok": True, "elapsed_sec": elapsed, "products_scanned": data["scanned"],
        "params": {"limit":limit,"min_len":minlen,"include_bigrams":include,"scope":scope,"save_csv":savecsv},
        "unigrams": [{"keyword":k,"count":c,"intent":i} for k,c,i in data["unigrams"]],
        "bigrams":  [{"keyword":k,"count":c,"intent":i} for k,c,i in (data["bigrams"] or [])],
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
# Internal links (Related Picks)
# ─────────────────────────────────────────────────────────────
def _extract_tokens_for_match(p: dict) -> set:
    parts = [p.get("title") or "", strip_html(p.get("body_html") or "")]
    tags = p.get("tags") or []
    if isinstance(tags, list): parts.extend(tags)
    elif isinstance(tags, str): parts.extend([x.strip() for x in tags.split(",") if x.strip()])
    toks = set(filter_stopwords(tokenize(" ".join(parts), KEYWORD_MIN_LEN), KEYWORD_MIN_LEN))
    return toks

def find_related_products(target: dict, candidates: List[dict], k: int) -> List[dict]:
    tgt = _extract_tokens_for_match(target)
    scored = []
    for c in candidates:
        if c.get("id") == target.get("id"): continue
        cset = _extract_tokens_for_match(c)
        score = len(tgt & cset)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _,c in scored[:max(0,k)]]

def inject_related_links_bottom(body_html: str, related: List[dict]) -> str:
    if not related: return body_html
    if RELATED_SECTION_MARKER in (body_html or ""):  # idempotent
        return body_html
    lis = []
    for rp in related:
        url = f"/products/{rp.get('handle')}"
        title = rp.get("title") or "View product"
        lis.append(f'<li><a href="{url}">{title}</a></li>')
    block = "\n".join([
        RELATED_SECTION_MARKER,
        "<h3>Related Picks</h3>",
        "<ul>",
        *lis,
        "</ul>"
    ])
    return (body_html or "") + "\n\n" + block

def inject_related_links_top(html: str, related: List[dict]) -> str:
    if not related or RELATED_TOP_MARKER in (html or ""):
        return html
    picks = []
    for rp in related[:2]:
        url = f"/products/{rp.get('handle')}"
        title = rp.get("title") or "View product"
        picks.append(f'<a href="{url}">{title}</a>')
    block = RELATED_TOP_MARKER + f'\n<p>Quick Picks: {" · ".join(picks)}</p>\n'
    if "</p>" in (html or ""):
        return re.sub(r"(</p>)", r"\1\n" + block, html, count=1)
    return block + (html or "")

def count_internal_links(body_html: str) -> int:
    if not body_html: return 0
    return len(re.findall(r'href="/products/[^"]+"', body_html))

# ─────────────────────────────────────────────────────────────
# SEO routines (keyword-weighted + intent + seasonal)
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
    if " " in kw: s *= 1.25
    if len(kw) >= 14: s *= 1.1
    return s

def _compose_title(primary: str, benefit: str, cta: str) -> str:
    seasonal = ""
    for w in SEASONAL_WORDS:
        if len(primary) + len(" | ") + len(benefit) + len(" – ") + len(cta) + len(" · ") + len(w) <= TITLE_MAX_LEN:
            seasonal = f" · {w}"
            break
    title = f"{primary} | {benefit}{seasonal}"
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

    limit        = request.args.get("limit", SEO_LIMIT)
    rotate       = (request.args.get("rotate", "true").lower() != "false")
    force        = str(request.args.get("force","false")).lower() in ("1","true","yes","on","y")
    force_kw     = str(request.args.get("force_keywords","false")).lower() in ("1","true","yes","on","y")
    kw_top_n     = request.args.get("kw_top_n", KW_TOP_N_FOR_WEIGHT)
    inject_rel   = str(request.args.get("related_links", str(ALLOW_BODY_LINK_INJECTION))).lower() in ("1","true","yes","on","y")

    # --- PATCH: clamps ---
    limit   = clamp(limit, 1, MAX_ENDPOINT_LIMIT)
    kw_top_n = clamp(kw_top_n, 5, 200)

    km = _get_keyword_map(limit=max(kw_top_n, KEYWORD_LIMIT_DEFAULT),
                          min_len=KEYWORD_MIN_LEN,
                          include_bigrams=KEYWORD_INCLUDE_BIGRAMS,
                          scope="all",
                          force=force_kw)
    top_unigrams = [k for k,_,_ in km["unigrams"][:kw_top_n]]
    top_bigrams  = [k for k,_,_ in (km["bigrams"] or [])[:kw_top_n]]
    boost_set    = set(top_unigrams + top_bigrams)

    prods = shopify_get_products(limit=max(limit, 50))
    targets = prods[:limit] if not rotate else prods[:limit]
    all_candidates = shopify_get_all_products(max_items=600) if inject_rel else []

    changed, errors = [], []
    benefit = "Fast Shipping · Quality Picks"

    for p in targets:
        pid = p.get("id")
        gid = product_gid(pid)
        try:
            title_raw = (p.get("title") or "")
            body_current_html = p.get("body_html") or ""
            body_raw  = strip_html(body_current_html)
            tags_list = p.get("tags") if isinstance(p.get("tags"), list) else \
                        ([x.strip() for x in (p.get("tags") or "").split(",")] if isinstance(p.get("tags"), str) else [])

            intent_input = " ".join([title_raw, body_raw, " ".join(tags_list)])
            intent = classify_intent_from_text(intent_input)

            title_l = title_raw.lower(); body_l = body_raw.lower()
            scored_bi  = sorted([(kw, _score_kw(kw, title_l, body_l, tags_list, boost_set)) for kw in top_bigrams], key=lambda x: x[1], reverse=True)
            scored_uni = sorted([(kw, _score_kw(kw, title_l, body_l, tags_list, boost_set)) for kw in top_unigrams], key=lambda x: x[1], reverse=True)

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

            benefit_intent = {
                "informational": "Quick Tips · Honest Reviews",
                "commercial":    "Top Picks · Expert Compare",
                "transactional": benefit,
                "unknown":       benefit
            }.get(intent, benefit)

            meta_title = _compose_title(primary=primary, benefit=benefit_intent, cta=CTA_PHRASE)
            meta_desc  = _compose_desc(keywords=chosen, base_body=body_raw, cta=CTA_PHRASE)

            existing_title = p.get("metafields_global_title_tag")
            existing_desc  = p.get("metafields_global_description_tag")
            def ok_len(s, mx): return s and (15 <= len(s.strip()) <= mx)

            new_body = None
            updated_html = body_current_html
            if inject_rel and RELATED_LINKS_MAX > 0:
                rel = find_related_products(p, all_candidates, RELATED_LINKS_MAX)
                if rel:
                    if RELATED_TOP_MARKER not in updated_html:
                        updated_html = inject_related_links_top(updated_html, rel)
                    if RELATED_SECTION_MARKER not in updated_html:
                        updated_html = inject_related_links_bottom(updated_html, rel)
                    if updated_html != body_current_html:
                        new_body = updated_html

            if (not force) and ok_len(existing_title, TITLE_MAX_LEN) and ok_len(existing_desc, DESC_MAX_LEN) and (new_body is None):
                changed.append({"id": pid, "handle": p.get("handle"), "skipped_reason": "existing_seo_ok", "intent": intent})
                continue

            if USE_GRAPHQL:
                res = shopify_update_seo_graphql(gid, meta_title, meta_desc, body_html=new_body)
                if not res.get("ok", True):
                    res = shopify_update_seo_rest(pid, meta_title, meta_desc, body_html=new_body)
            else:
                res = shopify_update_seo_rest(pid, meta_title, meta_desc, body_html=new_body)

            changed.append({
                "id": pid,
                "handle": p.get("handle"),
                "metaTitle": meta_title,
                "metaDesc": meta_desc,
                "keywords_used": chosen[:5],
                "intent": intent,
                "altSuggestions": ensure_alt_suggestions(p),
                "body_updated": bool(new_body is not None),
                "internal_link_count": count_internal_links(new_body if new_body is not None else body_current_html),
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
# Blog Auto-Post (review / compare) + share snippets
# ─────────────────────────────────────────────────────────────
def _get_blog_id_by_handle(handle: str) -> Optional[str]:
    q = {
        "query": """
        query($handle: String!) {
          blogByHandle(handle: $handle) { id title handle }
        }
        """,
        "variables": {"handle": handle}
    }
    try:
        r = http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=q)
        data = r.json().get("data", {})
        b = (data.get("blogByHandle") or {})
        return b.get("id")
    except Exception as e:
        log.exception("blogByHandle failed: %s", e)
        return None

def _article_create(blog_id: str, title: str, html: str, tags: List[str]) -> Dict[str,Any]:
    if DRY_RUN:
        log.info("[DRY_RUN] Article create: %s", title)
        return {"dry_run": True}
    m = {
        "query": """
        mutation articleCreate($input: ArticleInput!) {
          articleCreate(input: $input) {
            article { id handle onlineStoreUrl title }
            userErrors { field message }
          }
        }
        """,
        "variables": {"input": {"title": title, "contentHtml": html, "blogId": blog_id, "tags": tags}}
    }
    r = http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=m)
    data = r.json().get("data", {}).get("articleCreate")
    errs = (data or {}).get("userErrors") or []
    if errs:
        return {"ok": False, "errors": errs}
    return {"ok": True, "article": (data or {}).get("article")}

def _blog_template(topic: str, products: List[dict], post_type: str, keywords: List[str]) -> Tuple[str,str]:
    n = len(products)
    if post_type == "compare" and n >= 2:
        title = f"{products[0]['title']} vs {products[1]['title']} — Which {topic} is Best?"
    else:
        title = f"Top {n} {topic} in 2025 — Reviews & Buying Guide"

    intro = f"<p>Looking for the best {topic}? Here’s our curated list with pros & cons, based on real features and compatibility.</p>"
    body = [f"<h2>{title}</h2>", intro]

    link_count = 0
    for i, p in enumerate(products, 1):
        purl = f"/products/{p['handle']}"
        body.append(f"<h3>{i}. {p['title']}</h3>")
        body.append(f"<strong>Pros:</strong> Stylish, durable, easy to use.<br><strong>Cons:</strong> Check sizes/colors before you buy.")
        body.append(f"<p><a href='{purl}'>Check {p['title']} &rarr;</a></p>")
        link_count += 1
    while link_count < 3 and products:
        p = random.choice(products)
        purl = f"/products/{p['handle']}"
        body.append(f"<p><a href='{purl}'>Explore {p['title']} &rarr;</a></p>")
        link_count += 1

    outro = "<p>All items are curated by Jeff’s Favorite Picks. Limited stock — grab yours today!</p>"
    kw = f"<p>Popular keywords: {', '.join(keywords[:5])}</p>" if keywords else ""
    html = "\n".join(body + [outro, kw])
    return title, html

def _share_snippets(article_title: str, article_url: str, products: List[dict]) -> Dict[str,str]:
    picks = ", ".join([p.get("title","") for p in products[:3] if p.get("title")])
    return {
        "pinterest": f"{article_title}\n{picks}\n{article_url}\n#phone #accessories #shopping #review",
        "medium":    f"{article_title}\n\nWe compared: {picks}.\nRead more: {article_url}",
        "reddit":    f"[Review] {article_title} — picks: {picks}\n{article_url}",
        "quora":     f"{article_title}: What to consider when buying? See our breakdown → {article_url}"
    }

@app.post("/blog/auto-post")
@require_auth
def blog_auto_post():
    if not BLOG_AUTO_POST:
        return jsonify({"ok": False, "error": "BLOG_AUTO_POST disabled"}), 400

    body = request.get_json(silent=True) or {}
    topic = body.get("topic") or BLOG_DEFAULT_TOPIC
    post_type = (body.get("type") or BLOG_POST_TYPE or "review").lower()
    pick_n = int(body.get("pick_n") or 5)
    tags   = body.get("tags") or [topic, "auto", "review" if post_type=="review" else "compare"]

    allp = shopify_get_all_products(max_items=500)
    if not allp: return jsonify({"ok": False, "error": "no products"}), 400
    random.shuffle(allp)

    picks = allp[:pick_n] if len(allp) >= pick_n else allp
    if not picks:
        return jsonify({"ok": False, "error": "no picks"}), 400

    km = _get_keyword_map(limit=KEYWORD_LIMIT_DEFAULT,
                          min_len=KEYWORD_MIN_LEN,
                          include_bigrams=KEYWORD_INCLUDE_BIGRAMS,
                          scope="all",
                          force=False)
    top_kw = [k for k,_,_ in km["unigrams"][:10]]

    title, html = _blog_template(topic, picks, post_type, top_kw)

    blog_id = _get_blog_id_by_handle(BLOG_HANDLE)
    if not blog_id:
        return jsonify({"ok": False, "error": f"blog handle '{BLOG_HANDLE}' not found"}), 400

    created = _article_create(blog_id, title, html, tags)
    if not created.get("ok"):
        return jsonify({"ok": False, "error": "article_create_failed", "details": created}), 500

    article = created["article"]
    a_url = article.get("onlineStoreUrl") or f"/blogs/{BLOG_HANDLE}/{article.get('handle')}"
    snippets = _share_snippets(title, a_url, picks)

    return jsonify({
        "ok": True,
        "article": {
            "id": article.get("id"),
            "title": article.get("title"),
            "handle": article.get("handle"),
            "url": a_url
        },
        "snippets": snippets,
        "picks_count": len(picks),
        "topic": topic,
        "type": post_type
    })

# ─────────────────────────────────────────────────────────────
# Sitemap (index + products) + Robots
# ─────────────────────────────────────────────────────────────
def _abs_product_url(handle: str) -> str:
    host = CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com"
    return f"https://{host}/products/{handle}"

def _xml_escape(s: str) -> str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&apos;")

def _to_rfc3339_utc(ts: Optional[str]) -> str:
    if not ts:
        return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        d = dt.datetime.fromisoformat(ts.replace("Z","+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return d.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

@app.get("/sitemap-index.xml")
def sitemap_index():
    host = CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com"
    now = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    items = [
        f"<sitemap><loc>{_xml_escape(PRIMARY_SITEMAP or f'https://{host}/sitemap.xml')}</loc><lastmod>{now}</lastmod></sitemap>",
    ]
    if PUBLIC_BASE:
        items.append(f"<sitemap><loc>{_xml_escape(PUBLIC_BASE + '/sitemap-products.xml')}</loc><lastmod>{now}</lastmod></sitemap>")
    body = "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        *items,
        '</sitemapindex>'
    ])
    return Response(body, mimetype="application/xml")

@app.get("/sitemap-products.xml")
def sitemap_products():
    try:
        prods = shopify_get_all_products(max_items=5000)
        urls = []
        for p in prods:
            handle = p.get("handle")
            if not handle: continue
            loc = _abs_product_url(handle)
            lastmod = _to_rfc3339_utc(p.get("updated_at") or p.get("published_at"))
            imgs = p.get("images") or []
            img_xml = []
            for im in imgs[:6]:
                src = im.get("src") if isinstance(im, dict) else (str(im) if im else "")
                if src:
                    img_xml.append(f"<image:image><image:loc>{_xml_escape(src)}</image:loc></image:image>")

            urls.append(
                f"<url><loc>{_xml_escape(loc)}</loc><lastmod>{lastmod}</lastmod>"
                f"<changefreq>weekly</changefreq><priority>0.7</priority>{''.join(img_xml)}</url>"
            )

        body = "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
            *urls,
            "</urlset>"
        ])
        return Response(body, mimetype="application/xml")
    except Exception as e:
        log.exception("sitemap-products failed")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/robots.txt")
def robots_txt():
    host = CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com"
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        f"Sitemap: https://{host}/sitemap.xml",
    ]
    if PUBLIC_BASE:
        lines.append(f"Sitemap: {PUBLIC_BASE}/sitemap-products.xml")
        lines.append(f"Sitemap: {PUBLIC_BASE}/sitemap-index.xml")
    return Response("\n".join(lines) + "\n", mimetype="text/plain")

# ─────────────────────────────────────────────────────────────
# Bing ping (deprecated) + IndexNow submit + (Fallback) Google ping
# ─────────────────────────────────────────────────────────────
@app.get("/bing/ping")
def bing_ping():
    return Response("Bing sitemap ping is deprecated.\n", status=410, mimetype="text/plain")

def _indexnow_submit(urls: List[str]) -> Dict[str, Any]:
    if not INDEXNOW_KEY:
        return {"ok": False, "error": "missing INDEXNOW_KEY"}
    payload = {
        "host": CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com",
        "key": INDEXNOW_KEY,
        "keyLocation": INDEXNOW_KEY_URL or "",
        "urlList": urls[:1000],
    }
    try:
        r = http("POST", "https://api.indexnow.org/indexnow", json=payload, headers={"Content-Type":"application/json"})
        return {"ok": r.status_code in (200,202), "status": r.status_code, "text": r.text[:500]}
    except Exception as e:
        log.exception("IndexNow submit failed")
        return {"ok": False, "error": str(e)}

@app.post("/indexnow/submit")
@require_auth
def indexnow_submit():
    body = request.get_json(silent=True) or {}
    urls = body.get("urls") or []
    if not urls:
        prods = shopify_get_products(limit=250)
        urls = [_abs_product_url(p["handle"]) for p in prods if p.get("handle")]

    # --- PATCH: guard warn if misconfigured
    if not INDEXNOW_KEY or not (INDEXNOW_KEY_URL or "").startswith("http"):
        log.warning("IndexNow is not fully configured (INDEXNOW_KEY/INDEXNOW_KEY_URL).")

    res = _indexnow_submit(urls)
    return jsonify({"ok": res.get("ok", False), "result": res, "count": len(urls)}), (200 if res.get("ok") else 500)

@app.post("/gsc/sitemap/submit")
@require_auth
def gsc_sitemap_submit():
    """
    NOTE:
    - Google deprecated public ping endpoints. Proper submission requires OAuth user credentials
      to call Search Console API (sitemaps.submit). As a fallback, we attempt legacy ping which
      may be ignored by Google. This endpoint is best-effort only.
    """
    body = request.get_json(silent=True) or {}
    sitemap_url = body.get("sitemap_url") or PRIMARY_SITEMAP
    try:
        r = http("GET", "https://www.google.com/ping", params={"sitemap": sitemap_url})
        ok = r.status_code in (200, 202)
        return jsonify({"ok": ok, "status": r.status_code, "used_fallback_ping": True, "sitemap_url": sitemap_url}), (200 if ok else 500)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "sitemap_url": sitemap_url}), 500

# ─────────────────────────────────────────────────────────────
# Email helper (SendGrid) + GSC service JSON materialize
# ─────────────────────────────────────────────────────────────
def send_email(subject: str, html_content: str, to: Optional[List[str]] = None) -> Dict[str, Any]:
    if not ENABLE_EMAIL:
        return {"ok": False, "error": "email_disabled"}
    if not SENDGRID_API_KEY:
        return {"ok": False, "error": "missing SENDGRID_API_KEY"}
    to_list = [t for t in (to or EMAIL_TO) if t]
    if not to_list:
        return {"ok": False, "error": "empty_email_to"}

    payload = {
        "personalizations": [{"to": [{"email": x} for x in to_list]}],
        "from": {"email": EMAIL_FROM},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_content}],
    }
    try:
        r = http("POST", "https://api.sendgrid.com/v3/mail/send",
                 headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type":"application/json"},
                 json=payload)
        ok = r.status_code in (200, 202)
        return {"ok": ok, "status": r.status_code}
    except Exception as e:
        log.exception("send_email failed")
        return {"ok": False, "error": str(e)}

# --- PATCH START: decode Google service account JSON (if enabled) ---
def _ensure_service_json():
    if ENABLE_GSC_SITEMAP_SUBMIT and GOOGLE_SERVICE_JSON_B64 and GOOGLE_SERVICE_JSON_PATH:
        try:
            if not os.path.exists(GOOGLE_SERVICE_JSON_PATH):
                data = base64.b64decode(GOOGLE_SERVICE_JSON_B64.encode("utf-8"))
                pathlib.Path(GOOGLE_SERVICE_JSON_PATH).write_bytes(data)
                log.info("Service account JSON written to %s", GOOGLE_SERVICE_JSON_PATH)
        except Exception as e:
            log.exception("Failed to materialize service JSON: %s", e)
_ensure_service_json()
# --- PATCH END ---

# ─────────────────────────────────────────────────────────────
# Daily Report: orphan suspects + speed(WebP) checks + summary
# ─────────────────────────────────────────────────────────────
def _image_webp_ratio(p: dict) -> float:
    imgs = p.get("images") or []
    if not imgs: return 0.0
    total, webp = 0, 0
    for im in imgs:
        src = (im.get("src") if isinstance(im, dict) else str(im)) or ""
        if not src: continue
        total += 1
        if ".webp" in src.lower(): webp += 1
    return (webp / total) if total > 0 else 0.0

def _orphan_suspect(p: dict) -> bool:
    return count_internal_links(p.get("body_html") or "") < ORPHAN_LINK_MIN

def _report_html(summary: Dict[str, Any]) -> str:
    lines = []
    lines.append("<div style='font-family:system-ui,Segoe UI,Arial'>")
    lines.append("<h2>Daily SEO Report / 일일 SEO 점검 리포트</h2>")
    lines.append(f"<p>Generated (UTC): {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}</p>")
    lines.append("<h3>Summary / 요약</h3>")
    lines.append("<ul>")
    lines.append(f"<li>Products scanned: {summary['scanned']}</li>")
    lines.append(f"<li>Orphan suspects: {len(summary['orphans'])}</li>")
    lines.append(f"<li>Avg WebP ratio: {summary['avg_webp_ratio']:.2f}</li>")
    lines.append(f"<li>Below WebP threshold (&gt;{int(SPEED_WEBP_THRESHOLD*100)}% target): {len(summary['below_threshold'])}</li>")
    lines.append("</ul>")

    if summary["orphans"]:
        lines.append("<h3>Orphaned-Page Suspects (내부 링크 부족)</h3>")
        lines.append("<ol>")
        for o in summary["orphans"][:50]:
            url = _abs_product_url(o['handle'])
            lines.append(f"<li><a href='{url}'>{o['title']}</a> — internal links: {o['internal_links']}</li>")
        lines.append("</ol>")
    else:
        lines.append("<p>No orphan suspects. 🎉</p>")

    if summary["below_threshold"]:
        lines.append("<h3>WebP Ratio Below Threshold (이미지 WebP 비율 낮음)</h3>")
        lines.append("<ol>")
        for b in summary["below_threshold"][:50]:
            url = _abs_product_url(b['handle'])
            pct = int(round(b['webp_ratio']*100))
            lines.append(f"<li><a href='{url}'>{b['title']}</a> — WebP: {pct}%</li>")
        lines.append("</ol>")
    else:
        lines.append("<p>All products meet WebP ratio target. ✅</p>")

    lines.append("<h3>Tips</h3>")
    lines.append("<ul>")
    lines.append("<li>Add 2–3 internal links (Related Picks) into low-link product pages.</li>")
    lines.append("<li>Convert gallery images to WebP for faster LCP and better INP.</li>")
    lines.append("<li>Keep meta title & description within length limits; include CTA.</li>")
    lines.append("</ul>")
    lines.append("</div>")
    return "\n".join(lines)

@app.get("/report/daily")
@require_auth
def daily_report():
    try:
        prods = shopify_get_all_products(max_items=1000)
        scanned = len(prods)

        orphans, below = [], []
        webp_ratios = []

        for p in prods:
            il = count_internal_links(p.get("body_html") or "")
            if il < ORPHAN_LINK_MIN:
                orphans.append({"id": p.get("id"), "handle": p.get("handle"), "title": p.get("title"), "internal_links": il})
            wr = _image_webp_ratio(p)
            webp_ratios.append(wr)
            if wr < SPEED_WEBP_THRESHOLD:
                below.append({"id": p.get("id"), "handle": p.get("handle"), "title": p.get("title"), "webp_ratio": wr})

        # --- PATCH: sorted lists for better readability
        orphans.sort(key=lambda x: x["internal_links"])
        below.sort(key=lambda x: x["webp_ratio"])

        avg_webp = sum(webp_ratios)/len(webp_ratios) if webp_ratios else 0.0
        summary = {
            "scanned": scanned,
            "orphans": orphans,
            "below_threshold": below,
            "avg_webp_ratio": avg_webp,
            "webp_threshold": SPEED_WEBP_THRESHOLD
        }
        html = _report_html(summary)

        email_status = send_email(
            subject="Daily SEO Report — Orphans & WebP / 일일 SEO 리포트",
            html_content=html
        )

        return jsonify({"ok": True, "summary": summary, "email": email_status})
    except Exception as e:
        log.exception("daily_report failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Diagnostics
# ─────────────────────────────────────────────────────────────
@app.get("/__routes")
def list_routes():
    rules = []
    for r in app.url_map.iter_rules():
        if r.endpoint == 'static': continue
        rules.append({
            "endpoint": r.endpoint,
            "methods": sorted([m for m in r.methods if m in {"GET","POST","PUT","DELETE","PATCH"}]),
            "rule": str(r)
        })
    rules.sort(key=lambda x: x["rule"])
    return jsonify({"ok": True, "routes": rules})

@app.get("/health")
def health():
    return jsonify({"ok": True, "time_utc": dt.datetime.utcnow().isoformat() + "Z"})

@app.get("/")
def root():
    return jsonify({
        "ok": True,
        "name": "Unified Pro (Register + SEO + Keywords + Blog + Sitemap + Email + IndexNow + Reports)",
        "version": "2025-10-02+quick-patches",
        "public_base": PUBLIC_BASE,
        "store": SHOPIFY_STORE,
        "canonical_domain": CANONICAL_DOMAIN,
        "endpoints": [r.rule for r in app.url_map.iter_rules() if r.endpoint != "static"]
    })

# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)



