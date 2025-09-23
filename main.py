# main.py — Unified Pro (Full, with Real Product Registration)
#
# REQUIRED ENV:
#   IMPORT_AUTH_TOKEN                  (default: jeffshopsecure)
#   SHOPIFY_STORE                      (e.g. bj0b8k-kg)
#   SHOPIFY_API_VERSION                (default: 2025-07)
#   SHOPIFY_ADMIN_TOKEN                (Admin API access token)
#
# OPTIONAL ENV:
#   SEO_LIMIT=10
#   USE_GRAPHQL=true
#   ENABLE_BING_PING=true
#   PRIMARY_SITEMAP=https://jeffsfavoritepicks.com/sitemap.xml
#   PUBLIC_BASE=https://shopify-auto-import.onrender.com
#   CANONICAL_DOMAIN=jeffsfavoritepicks.com
#
# ENDPOINTS:
#   GET  /                     → ok
#   GET  /health               → status
#   GET  /__routes?auth=...    → registered routes
#   POST /register?auth=...    → create products from JSON payload
#   GET  /register?auth=...    → create 1 sample product (quick test)
#   GET  /seo/optimize?auth=...&limit=10&rotate=true
#   GET  /sitemap-products.xml
#   GET  /robots.txt
#   GET  or POST /sitemap/ping?auth=...
#
#  Register payload example (POST /register?auth=...):
#  {
#    "products": [
#      {
#        "title": "MagSafe Clear Case - iPhone 15",
#        "body_html": "<p>Crystal clear anti-yellowing, MagSafe ready.</p>",
#        "vendor": "Jeff’s Picks",
#        "product_type": "Phone Case",
#        "tags": ["magsafe", "iphone", "clear"],
#        "handle": "magsafe-clear-case-iphone-15",
#        "images": [{"src": "https://example.com/img1.jpg"}, {"src": "https://example.com/img2.jpg"}],
#        "variants": [
#          {"sku": "MAGSAFE-15-CLR", "price": "19.99", "inventory_quantity": 30, "option1": "Clear"}
#        ],
#        "options": [{"name":"Color","values":["Clear"]}]
#      }
#    ]
#  }
#
#  Notes:
#   • If images[].src is an external URL, Shopify will fetch it.
#   • If you want to set inventory, variants[].inventory_quantity is supported; we set “inventory_management”: "shopify".
#   • If handle omitted, Shopify will auto-generate from title.

import os, json, datetime, logging, re, time
from flask import Flask, jsonify, request, Response
import requests

print("[BOOT] importing main.py…")

# ─────────────────────────────────────────────────────────────
# ENV / CONFIG
# ─────────────────────────────────────────────────────────────
AUTH_TOKEN          = os.getenv("IMPORT_AUTH_TOKEN", "jeffshopsecure").strip()
SHOP                = os.getenv("SHOPIFY_STORE", "").strip()
API_VERSION         = os.getenv("SHOPIFY_API_VERSION", "2025-07").strip()
ADMIN_TOKEN         = os.getenv("SHOPIFY_ADMIN_TOKEN", "").strip()
SEO_LIMIT           = int(os.getenv("SEO_LIMIT", "10") or 10)
USE_GRAPHQL         = os.getenv("USE_GRAPHQL", "true").lower() == "true"
ENABLE_BING_PING    = os.getenv("ENABLE_BING_PING", "true").lower() == "true"
PRIMARY_SITEMAP     = os.getenv("PRIMARY_SITEMAP", "https://jeffsfavoritepicks.com/sitemap.xml").strip()
PUBLIC_BASE         = os.getenv("PUBLIC_BASE", "").rstrip("/")
CANONICAL_DOMAIN    = os.getenv("CANONICAL_DOMAIN", "").strip()
TIMEOUT             = 25

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
log = logging.getLogger("unified-pro")

# ─────────────────────────────────────────────────────────────
# HTTP / Shopify helpers
# ─────────────────────────────────────────────────────────────
S = requests.Session()
if ADMIN_TOKEN:
    S.headers.update({
        "X-Shopify-Access-Token": ADMIN_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "unified-pro/1.0",
    })

def _api_url(path: str) -> str:
    if not SHOP:
        raise RuntimeError("SHOPIFY_STORE env is empty")
    return f"https://{SHOP}.myshopify.com/admin/api/{API_VERSION}{path}"

def _api_get(path: str, params=None):
    r = S.get(_api_url(path), params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def _api_post(path: str, payload: dict):
    r = S.post(_api_url(path), json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def _api_put(path: str, payload: dict):
    r = S.put(_api_url(path), json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def _admin_graphql(query: str, variables=None):
    url = f"https://{SHOP}.myshopify.com/admin/api/{API_VERSION}/graphql.json"
    headers = S.headers.copy()
    headers["Content-Type"] = "application/json"
    r = requests.post(url, json={"query": query, "variables": variables or {}}, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data

# ─────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────
def _authorized() -> bool:
    return request.args.get("auth", "") == AUTH_TOKEN or request.headers.get("X-Admin-Auth", "") == AUTH_TOKEN

def _unauth():
    return jsonify({"ok": False, "error": "unauthorized"}), 401

# ─────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.get("/")
def root():
    return jsonify({"ok": True, "service": "unified-pro"})

@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "shop": SHOP,
        "api_version": API_VERSION,
        "use_graphql": USE_GRAPHQL,
        "ts": datetime.datetime.utcnow().isoformat() + "Z"
    })

# ─────────────────────────────────────────────────────────────
# Debug: list routes
# ─────────────────────────────────────────────────────────────
@app.get("/__routes")
def list_routes():
    if not _authorized(): return _unauth()
    routes = []
    for r in app.url_map.iter_rules():
        routes.append({"rule": str(r), "endpoint": r.endpoint, "methods": sorted(list(r.methods))})
    return jsonify({"count": len(routes), "routes": routes})

# ─────────────────────────────────────────────────────────────
# Product Registration (REAL)
# ─────────────────────────────────────────────────────────────
def _normalize_product_payload(p: dict) -> dict:
    """Map incoming JSON to Shopify product create schema."""
    title       = p.get("title") or "Untitled Product"
    body_html   = p.get("body_html") or p.get("body") or ""
    vendor      = p.get("vendor") or "Jeff’s Favorite Picks"
    product_type= p.get("product_type") or "General"
    tags        = p.get("tags") or []
    if isinstance(tags, list):
        tags_str = ",".join([str(t) for t in tags])
    else:
        tags_str = str(tags)

    # Handle
    handle = p.get("handle")
    if not handle:
        # generate from title
        slug = re.sub(r"[^a-z0-9\- ]", "", title.lower()).strip()
        slug = re.sub(r"\s+", "-", slug)
        slug = re.sub(r"-{2,}", "-", slug).strip("-") or f"prod-{int(time.time())}"
        handle = slug[:80]

    # Images (Shopify will fetch external URLs)
    images = p.get("images") or []
    images_norm = []
    for img in images:
        if isinstance(img, dict) and img.get("src"):
            images_norm.append({"src": img["src"]})
        elif isinstance(img, str):
            images_norm.append({"src": img})
    # Variants
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
            try:
                vr["inventory_quantity"] = int(v.get("inventory_quantity"))
            except:
                vr["inventory_quantity"] = 0
        variants_norm.append(vr)

    # Options (e.g. Color/Size)
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
    if options_norm:
        payload["product"]["options"] = options_norm
    if variants_norm:
        payload["product"]["variants"] = variants_norm
    return payload

def _create_product(product_payload: dict) -> dict:
    """Call Shopify Create Product."""
    res = _api_post("/products.json", product_payload)
    prod = (res or {}).get("product", {})
    return {
        "id": prod.get("id"),
        "title": prod.get("title"),
        "handle": prod.get("handle"),
        "admin_url": f"https://admin.shopify.com/store/{SHOP}/products/{prod.get('id')}" if prod.get("id") else None
    }

@app.post("/register")
@app.get("/register")
def register():
    if not _authorized(): return _unauth()
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
                    errors.append({"input": p.get("title") or p.get("handle"), "error": str(e)})
            return jsonify({"ok": True, "created": created, "errors": errors, "count": len(created)})

        # GET → create one demo product (quick smoke test)
        demo = {
            "title": "MagSafe Clear Case - iPhone 15",
            "body_html": "<p>Crystal clear anti-yellowing, MagSafe ready.</p>",
            "vendor": "Jeff’s Favorite Picks",
            "product_type": "Phone Case",
            "tags": ["magsafe", "iphone", "clear"],
            "images": [{"src": "https://picsum.photos/seed/magsafe15/800/800"}],
            "variants": [{"sku": f"MAGSAFE-15-CLR-{int(time.time())}", "price": "19.99", "inventory_quantity": 25, "option1": "Clear"}],
            "options": [{"name": "Color", "values": ["Clear"]}],
        }
        payload = _normalize_product_payload(demo)
        res = _create_product(payload)
        return jsonify({"ok": True, "created": [res], "demo": True})

    except Exception as e:
        log.exception("register failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────
# SEO Optimize (rotate N products: SEO title/desc + ALT fill)
# ─────────────────────────────────────────────────────────────
def _choose_kw(title: str) -> str:
    t = (title or "").lower()
    if any(x in t for x in ["dog", "cat", "pet"]): return "pet accessories"
    if "charger" in t: return "fast wireless charger"
    if "case" in t: return "magsafe iphone case"
    return "best value picks"

def _cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n-1].rstrip() + "…"

def _seo_for_product(p: dict):
    base = p.get("title") or "Best Pick"
    kw = _choose_kw(base)
    title = _cut(f"{base} | {kw} – Jeff’s Favorite Picks", 70)
    desc  = _cut(f"{kw} for {base}. Durable build, quick shipping. Grab yours today.", 160)
    return title, desc

def _update_product_seo_rest(pid: int, title: str, desc: str):
    return _api_put(f"/products/{pid}.json", {
        "product": {
            "id": pid,
            "metafields_global_title_tag": title,
            "metafields_global_description_tag": desc
        }
    })

def _update_alt_if_empty(pid: int, images: list, product_title: str, kw: str):
    if not images: return
    updates = []
    for img in images:
        if (img.get("alt") or "").strip(): continue
        if not img.get("id"): continue
        updates.append({"id": img["id"], "alt": f"{product_title} – {kw}"})
    if updates:
        _api_put(f"/products/{pid}.json", {"product": {"id": pid, "images": updates}})

@app.get("/seo/optimize")
def seo_optimize():
    if not _authorized(): return _unauth()
    limit = int(request.args.get("limit", SEO_LIMIT))
    rotate = request.args.get("rotate", "true").lower() == "true"
    # naive fetch (no cursor persisted to keep code compact)
    res = _api_get("/products.json", params={"limit": min(250, limit)})
    products = res.get("products", [])

    results = []
    for p in products[:limit]:
        try:
            pid = p["id"]
            title, desc = _seo_for_product(p)
            _update_product_seo_rest(pid, title, desc)
            kw = _choose_kw(p.get("title") or "")
            _update_alt_if_empty(pid, p.get("images") or [], p.get("title") or "", kw)
            results.append({"product_id": pid, "handle": p.get("handle"), "seo_title": title})
        except Exception as e:
            results.append({"product_id": p.get("id"), "error": str(e)})
    return jsonify({"ok": True, "count": len(results), "results": results, "rotate": rotate})

# ─────────────────────────────────────────────────────────────
# Sitemap (products) + Robots + Ping
# ─────────────────────────────────────────────────────────────
def _as_lastmod(iso_str: str) -> str:
    if not iso_str: return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    try:
        # normalize to Z
        if iso_str.endswith("Z"): return iso_str
        return iso_str.replace("+00:00", "Z")
    except:
        return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def _canonical_product_url(handle: str) -> str:
    if CANONICAL_DOMAIN:
        return f"https://{CANONICAL_DOMAIN}/products/{handle}"
    return f"https://{SHOP}.myshopify.com/products/{handle}"

@app.get("/sitemap-products.xml")
def sitemap_products():
    try:
        data = _api_get("/products.json", params={"limit": 250, "fields": "id,handle,updated_at,published_at,status,images"})
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
        f"Sitemap: {PUBLIC_BASE}/sitemap-products.xml" if PUBLIC_BASE else "Sitemap: /sitemap-products.xml"
    ]
    body = "\n".join([l for l in lines if l]) + "\n"
    return Response(body, mimetype="text/plain")

@app.route("/sitemap/ping", methods=["GET", "POST"])
def sitemap_ping():
    if not _authorized(): return _unauth()
    target = (request.args.get("sitemap") or PRIMARY_SITEMAP).strip()
    out = {"ok": True, "sitemap": target, "note": "google ping deprecated; bing only"}
    if ENABLE_BING_PING and target:
        try:
            r = requests.get("https://www.bing.com/ping", params={"siteMap": target},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            out["bing_status"] = r.status_code
            out["bing_ok"] = 200 <= r.status_code < 400
        except Exception as e:
            out["bing_ok"] = False
            out["bing_error"] = str(e)[:200]
    return jsonify(out)

# ─────────────────────────────────────────────────────────────
print("[BOOT] main.py loaded successfully")
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

