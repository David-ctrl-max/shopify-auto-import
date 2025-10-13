# main.py — Unified Pro + GSC Trend Boost (2025-10-13)
# =================================================================================================
# Feature set (요약)
# - /register (Demo/Batch) : 실등록 + 자동 body_html + ALT + TitleCase
# - /seo/keywords/run|cache : 사이트 전반 키워드 맵(uni/bigram) + intent 태깅
# - /seo/optimize | /run-seo : 키워드 가중치 + 의도/시즌어 + 내부링크 주입 + (NEW) GSC 트렌드 부스팅
# - /seo/trends/gsc : GSC 트렌드 원본 확인
# - /blog/auto-post : 리뷰/비교 글 자동 발행 + 내부링크 + 공유 스니펫
# - /sitemap-index.xml | /sitemap-products.xml | /robots.txt
# - /indexnow/submit | /gsc/sitemap/submit(베스트 에포트 핑)
# - /report/daily : Orphan 의심 + WebP 비율 리포트(이메일 옵션)
# - /health/shopify, /__routes, /health, /
# =================================================================================================

import os, sys, json, time, base64, pathlib, logging, re, random, hashlib, datetime as dt
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

import requests
from flask import Flask, request, jsonify, Response
from functools import wraps
from jinja2 import Template

# ---- (선택) GSC용 라이브러리 ----
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("seo-automation")

try:
    pathlib.Path("logs").mkdir(exist_ok=True)
    fh = logging.FileHandler("logs/app.log")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    log.addHandler(fh)
except Exception as e:
    log.warning("File logging disabled: %s", e)

# ─────────────────────────────────────────────────────────────
# Env helpers
# ─────────────────────────────────────────────────────────────
def env_bool(k, d=False): 
    v=os.getenv(k); 
    return d if v is None else str(v).lower() in ("1","true","yes","on","y")
def env_str(k, d=""): return os.getenv(k, d)
def env_int(k, d): 
    try: return int(os.getenv(k, d))
    except: return d

# ─────────────────────────────────────────────────────────────
# GSC service JSON materialization (always-on)
# ─────────────────────────────────────────────────────────────
def ensure_gsc_json():
    b64 = (os.getenv("GOOGLE_SERVICE_JSON_B64") or "").strip()
    target = os.getenv("GOOGLE_SERVICE_JSON_PATH", "/opt/render/project/src/gsc-service.json")
    if not b64:
        log.info("[GSC] GOOGLE_SERVICE_JSON_B64 not set"); return
    p = pathlib.Path(target); p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.stat().st_size > 1024:
        log.info("[GSC] JSON already present at %s", target); return
    pad=len(b64)%4
    if pad: b64+="="*(4-pad)
    data=base64.b64decode(b64); p.write_bytes(data)
    sha1=hashlib.sha1(data).hexdigest()[:8]
    try: email=json.loads(data).get("client_email","unknown")
    except: email="unknown"
    log.info("[GSC] JSON written → %s (sha1=%s, client_email=%s)", target, sha1, email)

ensure_gsc_json()

# ─────────────────────────────────────────────────────────────
# Core config
# ─────────────────────────────────────────────────────────────
IMPORT_AUTH_TOKEN   = env_str("IMPORT_AUTH_TOKEN", "jeffshopsecure")

SHOPIFY_STORE       = env_str("SHOPIFY_STORE", "").strip()
API_VERSION         = env_str("SHOPIFY_API_VERSION", "2025-07")
ADMIN_TOKEN         = env_str("SHOPIFY_ADMIN_TOKEN", "").strip()

SEO_LIMIT           = env_int("SEO_LIMIT", 10)
USE_GRAPHQL         = env_bool("USE_GRAPHQL", True)

PRIMARY_SITEMAP     = env_str("PRIMARY_SITEMAP", "https://jeffsfavoritepicks.com/sitemap.xml").strip()
PUBLIC_BASE         = env_str("PUBLIC_BASE", "").rstrip("/")
CANONICAL_DOMAIN    = env_str("CANONICAL_DOMAIN", "").strip()

DRY_RUN             = env_bool("DRY_RUN", False)
IP_ALLOWLIST        = [x.strip() for x in env_str("IP_ALLOWLIST","").split(",") if x.strip()]

# IndexNow
INDEXNOW_KEY        = env_str("INDEXNOW_KEY", "")
INDEXNOW_KEY_URL    = env_str("INDEXNOW_KEY_URL", "")

# Email
ENABLE_EMAIL        = env_bool("ENABLE_EMAIL", False)
SENDGRID_API_KEY    = env_str("SENDGRID_API_KEY")
EMAIL_TO            = [x.strip() for x in env_str("EMAIL_TO","").split(",") if x.strip()]
EMAIL_FROM          = env_str("EMAIL_FROM","reports@jeffsfavoritepicks.com")

# GSC
ENABLE_GSC_SITEMAP_SUBMIT = env_bool("ENABLE_GSC_SITEMAP_SUBMIT", False)
GSC_SITE_URL        = env_str("GSC_SITE_URL", "https://jeffsfavoritepicks.com")
GOOGLE_SERVICE_JSON_PATH = env_str("GOOGLE_SERVICE_JSON_PATH", "/opt/render/project/src/gsc-service.json")

# 🔹 NEW: GSC Trend envs
SEO_TREND_FROM_GSC      = env_bool("SEO_TREND_FROM_GSC", True)
SEO_TREND_LOOKBACK_DAYS = env_int("SEO_TREND_LOOKBACK_DAYS", 28)
SEO_TREND_TOP_N         = env_int("SEO_TREND_TOP_N", 50)
SEO_TREND_MIN_IMPRESSIONS = env_int("SEO_TREND_MIN_IMPRESSIONS", 30)
SEO_TREND_BLACKLIST     = [x.strip().lower() for x in env_str("SEO_TREND_BLACKLIST","").split(",") if x.strip()]

# Keyword map config
KEYWORD_MIN_LEN         = env_int("KEYWORD_MIN_LEN", 3)
KEYWORD_LIMIT_DEFAULT   = env_int("KEYWORD_LIMIT", 100)
KEYWORD_INCLUDE_BIGRAMS = env_bool("KEYWORD_INCLUDE_BIGRAMS", True)
KEYWORD_SAVE_CSV        = env_bool("KEYWORD_SAVE_CSV", False)
KEYWORD_CACHE_TTL_MIN   = env_int("KEYWORD_CACHE_TTL_MIN", 60)

# Weighting
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

# Intent/Report
INTENT_CLASSIFY        = env_bool("INTENT_CLASSIFY", True)
ORPHAN_LINK_MIN        = env_int("ORPHAN_LINK_MIN", 1)
SPEED_WEBP_THRESHOLD   = float(env_str("SPEED_WEBP_THRESHOLD", "0.6"))
SEASONAL_WORDS         = [w.strip() for w in env_str("SEASONAL_WORDS","2025 New, Free Shipping, Limited Stock").split(",") if w.strip()]

# Limits
MAX_PRODUCTS_SCAN   = int(os.getenv("MAX_PRODUCTS_SCAN", "6000"))
MAX_ENDPOINT_LIMIT  = int(os.getenv("MAX_ENDPOINT_LIMIT", "250"))
def clamp(n, lo, hi):
    try: n=int(n)
    except: n=lo
    return max(lo, min(hi, n))

# ─────────────────────────────────────────────────────────────
# Flask app / auth
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)

def require_auth(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        token_qs = request.args.get("auth")
        bearer = (request.headers.get("Authorization") or "").strip()
        token_hdr = request.headers.get("X-Auth")
        token = None
        if bearer.lower().startswith("bearer "):
            token = bearer.split(" ",1)[1].strip()
        token = token or token_hdr or token_qs
        if IP_ALLOWLIST:
            remote = request.headers.get("X-Forwarded-For", request.remote_addr or "")
            ip = remote.split(",")[0].strip()
            if ip not in IP_ALLOWLIST:
                return jsonify({"ok":False,"error":"forbidden_ip"}), 403
        if token != IMPORT_AUTH_TOKEN:
            return jsonify({"ok":False,"error":"unauthorized"}), 401
        return fn(*a, **kw)
    return wrapper

def retry(max_attempts=3, base_delay=0.6, factor=2.0, allowed=(429,500,502,503,504)):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            delay=base_delay
            for i in range(1, max_attempts+1):
                try: return fn(*a, **kw)
                except requests.HTTPError as e:
                    st=e.response.status_code if e.response is not None else None
                    if i>=max_attempts or st not in allowed: raise
                except Exception:
                    if i>=max_attempts: raise
                time.sleep(delay); delay*=factor
        return inner
    return deco

@retry()
def http(method, url, **kw):
    r=requests.request(method, url, timeout=30, **kw)
    if r.status_code>=400:
        log.error("HTTP %s %s -> %s", method, url, r.status_code)
        r.raise_for_status()
    return r

# ─────────────────────────────────────────────────────────────
# Shopify Admin (REST/GQL)
# ─────────────────────────────────────────────────────────────
BASE_REST    = f"https://{SHOPIFY_STORE}.myshopify.com/admin/api/{API_VERSION}"
BASE_GRAPHQL = f"https://{SHOPIFY_STORE}.myshopify.com/admin/api/{API_VERSION}/graphql.json"
HEADERS_REST = {"X-Shopify-Access-Token": ADMIN_TOKEN, "Content-Type":"application/json","Accept":"application/json"}
HEADERS_GQL  = {"X-Shopify-Access-Token": ADMIN_TOKEN, "Content-Type":"application/json","Accept":"application/json"}

@retry()
def shopify_get_products(limit=SEO_LIMIT):
    r=http("GET", f"{BASE_REST}/products.json", headers=HEADERS_REST, params={"limit":min(250,int(limit))})
    return r.json().get("products", [])

def _gql_products_page(after=None, page_size=250)->dict:
    q={
        "query":"""
        query($first:Int!, $after:String){
          products(first:$first, after:$after, sortKey:UPDATED_AT){
            edges{ cursor node{
              id handle title updatedAt publishedAt
              tags descriptionHtml
              images(first:10){edges{node{url altText}}}
              options{name values}
              variants(first:50){edges{node{title sku price}}}
            }}
            pageInfo{hasNextPage endCursor}
          }
        }""",
        "variables":{"first":min(250,page_size),"after":after}
    }
    r=http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=q)
    return r.json()["data"]["products"]

def _edge_to_restish(n:dict)->dict:
    imgs=[{"src":e["node"]["url"],"alt":e["node"]["altText"] or ""} for e in (n.get("images",{}).get("edges") or [])]
    vars=[{"title":v["node"]["title"],"sku":v["node"]["sku"],"price":v["node"]["price"]} for v in (n.get("variants",{}).get("edges") or [])]
    return {
        "id": int(n["id"].split("/")[-1]),
        "title": n.get("title"), "handle": n.get("handle"),
        "updated_at": n.get("updatedAt"), "published_at": n.get("publishedAt"),
        "body_html": n.get("descriptionHtml") or "", "tags": n.get("tags") or [],
        "images": imgs, "variants": vars, "options": n.get("options") or []
    }

def shopify_get_all_products(max_items=2000)->List[dict]:
    items, after, fetched = [], None, 0
    while True:
        data=_gql_products_page(after=after, page_size=250)
        for e in data["edges"]:
            items.append(_edge_to_restish(e["node"]))
            fetched+=1
            if fetched>=min(MAX_PRODUCTS_SCAN,max_items): return items
        if not data["pageInfo"]["hasNextPage"]: break
        after=data["pageInfo"]["endCursor"]
    return items

@retry()
def shopify_update_seo_rest(pid:int, meta_title:Optional[str], meta_desc:Optional[str], body_html:Optional[str]=None):
    if DRY_RUN: return {"dry_run":True}
    payload={"product":{"id":pid}}
    if meta_title is not None: payload["product"]["metafields_global_title_tag"]=meta_title
    if meta_desc  is not None: payload["product"]["metafields_global_description_tag"]=meta_desc
    if body_html is not None:  payload["product"]["body_html"]=body_html
    r=http("PUT", f"{BASE_REST}/products/{pid}.json", headers=HEADERS_REST, json=payload)
    return r.json()

@retry()
def shopify_update_seo_graphql(gid:str, seo_title:Optional[str], seo_desc:Optional[str], body_html:Optional[str]=None):
    if DRY_RUN: return {"dry_run":True}
    m={"query":"""
        mutation productUpdate($input: ProductInput!){
          productUpdate(input:$input){
            product{ id title descriptionHtml seo{title description} }
            userErrors{ field message }
          }
        }""",
       "variables":{"input":{
           "id":gid,
           **({"seo":{"title":seo_title,"description":seo_desc}} if (seo_title or seo_desc) else {}),
           **({"descriptionHtml":body_html} if body_html is not None else {})
       }}}
    r=http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=m)
    data=r.json().get("data",{}).get("productUpdate")
    errs=(data or {}).get("userErrors") or []
    if not data or errs: return {"ok":False,"errors":errs or ["no productUpdate data"]}
    return {"ok":True,"data":data}

def product_gid(pid:int)->str: return f"gid://shopify/Product/{pid}"

# ─────────────────────────────────────────────────────────────
# Utils (tokenize/intent/template)
# ─────────────────────────────────────────────────────────────
STOPWORDS={"the","and","for","you","your","with","from","this","that","are","our","has","have","was","were","will","can","all",
"any","into","more","most","such","other","than","then","them","they","their","there","over","after","before","not","but",
"about","also","how","what","when","where","which","while","who","whom","why","a","an","in","on","of","to","by","as","at",
"is","it","be","or","we","i","me","my","mine","yours","its","it’s","it's","new","pcs","pc","set","size","color","colors",
"style","styles","type","types","model","models","brand","phone","smartphone","case","cases","accessory","accessories",
"pet","pets","device","devices","for-iphone","iphone","samsung","xiaomi","android","apple","pro","max","ultra","series",
"gen","magnetic","magsafe","wireless","charger","charging","usb","type-c","cable","cables","adapter","adapters","band",
"bands","watch","watches","airpods","earbuds"}

INTENT_LEX={
 "informational":["how","what","guide","tips","tutorial","review","size guide","faq","benefits","pros","cons"],
 "commercial":["best","top","compare","vs","versus","brands","recommend","recommendation","deal","discount"],
 "transactional":["buy","price","coupon","free shipping","order","checkout","shop","sale"]
}

def classify_intent_from_text(text:str)->str:
    if not INTENT_CLASSIFY: return "unknown"
    t=(text or "").lower(); score={"informational":0,"commercial":0,"transactional":0}
    for intent, keys in INTENT_LEX.items():
        for k in keys:
            if re.search(rf"\b{re.escape(k)}\b", t): score[intent]+=1
    intent=max(score, key=score.get)
    return intent if score[intent]>0 else "unknown"

def strip_html(s:str)->str:
    s=re.sub(r"<[^>]+>"," ", s or ""); return re.sub(r"\s+"," ", s).strip()

def title_case(s:str)->str:
    if not s: return s
    words=re.split(r"(\s+|-|/)", str(s))
    def tc(w): 
        if not w or re.fullmatch(r"\W+", w): return w
        return w[0].upper()+w[1:].lower() if w.lower() not in {"for","and","or","to","of","a","an","the","in","on","at","by"} else w.lower()
    return "".join(tc(w) for w in words)

def tokenize(text:str, min_len:int)->List[str]:
    t=text.lower(); t=re.sub(r"[_/|]"," ", t)
    return re.findall(r"[a-z0-9\+\-]{%d,}"%max(1,min_len), t)

def filter_stopwords(tokens:List[str], min_len:int)->List[str]:
    out=[]
    for w in tokens:
        if len(w)<min_len: continue
        if w in STOPWORDS: continue
        if re.fullmatch(r"\d[\d\-]*", w): continue
        out.append(w)
    return out

def bigrams(tokens:List[str])->List[str]:
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens)-1)]

# ---- Body template ----
_PDP_TMPL = Template("""
<div class='pdp-copy'>
  <h2>{{ title }}</h2>
  <p><strong>{{ vendor }}</strong> — {{ benefit_en }} / {{ benefit_kr }}</p>
  <p>{{ story }}</p>
  {% if bullets %}<h3>Key Features</h3><ul>{% for b in bullets %}<li>{{ b }}</li>{% endfor %}</ul>{% endif %}
  <h3>Pros & Cons</h3>
  <p><strong>Pros:</strong> Durable, easy to use, modern look.<br><strong>Cons:</strong> Check device/size/color before ordering.</p>
  {% if specs %}<h3>Specs</h3><table role="table" class="pdp-specs">{% for k,v in specs %}<tr><th>{{ k }}</th><td>{{ v }}</td></tr>{% endfor %}</table>{% endif %}
  <p>Differentiators: Better grip, scratch-resistant finish, and wide compatibility.</p>
  <p><em>Tip:</em> Add to cart now — limited stock! <strong>{{ cta }}</strong>.</p>
  {% if has_gallery %}<p class="pdp-note">See product images above for color and style references.</p>{% endif %}
</div>
""".strip())

def best_keywords_from_product(p:dict, top_n:int=8)->List[str]:
    parts=[p.get("title") or "", strip_html(p.get("body_html") or "")]
    tags=p.get("tags")
    if isinstance(tags,list): parts.extend(tags)
    elif isinstance(tags,str): parts.extend([x.strip() for x in tags.split(",") if x.strip()])
    for opt in (p.get("options") or []):
        if isinstance(opt,dict):
            if opt.get("name"): parts.append(opt["name"])
            for v in (opt.get("values") or []): parts.append(v)
    for v in (p.get("variants") or []):
        if isinstance(v,dict):
            if v.get("title"): parts.append(v["title"])
            if v.get("sku"): parts.append(str(v["sku"]))
    toks=filter_stopwords(tokenize(" ".join(parts), KEYWORD_MIN_LEN), KEYWORD_MIN_LEN)
    uni=Counter(toks)
    return [k for k,_ in uni.most_common(top_n)]

def make_feature_list_from_keywords(kws:List[str])->List[str]:
    feats=[kw.replace("-"," ").title() for kw in kws][:8]
    base=["Lightweight","Durable Materials","Easy to Use","Fits Most Devices","Gift-Ready Packaging"]
    for b in base:
        if len(feats)>=8: break
        if b.lower() not in " ".join(feats).lower(): feats.append(b)
    return feats[:8]

def build_text_body_html(p:dict)->str:
    title=p.get("title") or "Product"
    vendor=p.get("vendor") or BRAND_NAME
    kws=best_keywords_from_product(p, top_n=10)
    bullets=make_feature_list_from_keywords(kws)
    specs=[]
    for opt in (p.get("options") or []):
        if isinstance(opt,dict) and opt.get("name") and opt.get("values"):
            name=title_case(opt["name"]) if NORMALIZE_TITLECASE else opt["name"]
            vals=", ".join([title_case(v) if NORMALIZE_TITLECASE else v for v in opt["values"]])
            specs.append((name, vals))
    return _PDP_TMPL.render(
        title=title, vendor=vendor, benefit_en=BENEFIT_LINE_EN, benefit_kr=BENEFIT_LINE_KR,
        story=f"{title} solves daily hassles with reliable build and clean design — ideal for commuting, travel, or gifting.",
        bullets=bullets, specs=specs, cta=CTA_PHRASE, has_gallery=bool(p.get("images") or [])
    )

def should_generate_body(existing:Optional[str])->bool:
    if BODY_FORCE_OVERWRITE: return True
    return len(strip_html(existing or "")) < BODY_MIN_CHARS

def ensure_titlecase_in_product(p:dict)->dict:
    if not NORMALIZE_TITLECASE: return p
    for opt in (p.get("options") or []):
        if isinstance(opt,dict):
            if opt.get("name"): opt["name"]=title_case(opt["name"])
            if isinstance(opt.get("values"),list): opt["values"]=[title_case(v) for v in opt["values"]]
    tags=p.get("tags")
    if isinstance(tags,list): p["tags"]=[title_case(t) for t in tags]
    elif isinstance(tags,str): p["tags"]=",".join([title_case(x.strip()) for x in tags.split(",") if x.strip()])
    return p

def inject_auto_alt_to_images(p:dict)->dict:
    if not ALT_AUTO_GENERATE: return p
    title=p.get("title") or "Product"
    imgs=p.get("images") or []; new=[]
    for i,img in enumerate(imgs):
        if isinstance(img,str): new.append({"src":img,"alt":f"{title} — image {i+1}"})
        elif isinstance(img,dict):
            if not (img.get("alt") or "").strip(): img["alt"]=f"{title} — image {i+1}"
            new.append(img)
    p["images"]=new; return p

# ─────────────────────────────────────────────────────────────
# Product Registration (demo or batch)
# ─────────────────────────────────────────────────────────────
def _slugify(title:str)->str:
    slug=re.sub(r"[^a-z0-9\- ]","",(title or "").lower()).strip()
    slug=re.sub(r"\s+","-",slug); slug=re.sub(r"-{2,}","-",slug).strip("-")
    return slug or f"prod-{int(time.time())}"

def _normalize_product_payload(p:dict)->dict:
    p=ensure_titlecase_in_product(p); p=inject_auto_alt_to_images(p)
    title=p.get("title") or "Untitled Product"
    body=p.get("body_html") or p.get("body") or ""
    if should_generate_body(body):
        try:
            body=build_text_body_html({"title":title,"vendor":p.get("vendor") or BRAND_NAME,
                                       "options":p.get("options") or [],"variants":p.get("variants") or [],
                                       "images":p.get("images") or [],"tags":p.get("tags")})
        except Exception:
            body=f"<p>{title} — {BENEFIT_LINE_EN} / {BENEFIT_LINE_KR}. {CTA_PHRASE}.</p>"
    tags=p.get("tags") or []
    tags_str=",".join([str(t) for t in tags]) if isinstance(tags,list) else str(tags)
    handle=p.get("handle") or _slugify(title)[:80]
    images=[]
    for img in (p.get("images") or []):
        if isinstance(img,dict) and img.get("src"):
            images.append({"src":img["src"], **({"alt":img["alt"]} if img.get("alt") else {})})
        elif isinstance(img,str):
            images.append({"src":img})
    variants=[]
    for v in (p.get("variants") or []):
        vr={"sku":str(v.get("sku") or ""), "price":str(v.get("price") or "0"),
            "option1":v.get("option1") or "Default", "option2":v.get("option2"), "option3":v.get("option3"),
            "inventory_management":"shopify"}
        if v.get("inventory_quantity") is not None:
            try: vr["inventory_quantity"]=int(v.get("inventory_quantity"))
            except: vr["inventory_quantity"]=0
        variants.append(vr)
    options=[]
    for opt in (p.get("options") or []):
        if isinstance(opt,dict) and opt.get("name"):
            options.append({"name":opt["name"], "values":opt.get("values") or []})
    payload={"product":{
        "title":title, "body_html":body, "vendor":p.get("vendor") or BRAND_NAME,
        "product_type":p.get("product_type") or "General", "tags":tags_str, "handle":handle, "images":images
    }}
    if options: payload["product"]["options"]=options
    if variants: payload["product"]["variants"]=variants
    return payload

@retry()
def _create_product(payload:dict)->dict:
    if DRY_RUN: return {"dry_run":True, "id":None}
    r=http("POST", f"{BASE_REST}/products.json", headers=HEADERS_REST, json=payload)
    prod=r.json().get("product",{})
    return {"id":prod.get("id"), "title":prod.get("title"), "handle":prod.get("handle"),
            "admin_url": f"https://admin.shopify.com/store/{SHOPIFY_STORE}/products/{prod.get('id')}" if prod.get("id") else None}

@app.route("/register", methods=["GET","POST"])
@require_auth
def register():
    try:
        if request.method=="POST":
            body=request.get_json(silent=True) or {}
            products_input=body.get("products") or []
            if not products_input: return jsonify({"ok":False,"error":"empty_products"}), 400
            created, errors=[], []
            for p in products_input:
                try: created.append(_create_product(_normalize_product_payload(p)))
                except Exception as e:
                    log.exception("create failed"); errors.append({"title":p.get("title"),"error":str(e)})
            return jsonify({"ok":True,"created":created,"errors":errors,"count":len(created)})
        # GET demo
        demo={"title":"MagSafe Clear Case - iPhone 15","body_html":"","vendor":BRAND_NAME,"product_type":"Phone Case",
              "tags":["MagSafe","iPhone","Clear"],"images":[{"src":"https://picsum.photos/seed/magsafe15/800/800"}],
              "variants":[{"sku":f"MAGSAFE-15-CLR-{int(time.time())}","price":"19.99","inventory_quantity":25,"option1":"Clear"}],
              "options":[{"name":"Color","values":["Clear"]}]}
        res=_create_product(_normalize_product_payload(demo))
        return jsonify({"ok":True,"created":[res],"demo":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Keyword Map (cached) + Intent
# ─────────────────────────────────────────────────────────────
_kw_cache={"built_at":None,"params":None,"unigrams":[],"bigrams":[],"scanned":0}

def _cache_valid(ttl_min:int)->bool:
    return _kw_cache["built_at"] is not None and (time.time()-_kw_cache["built_at"])<=ttl_min*60

def _build_keyword_map(limit:int, min_len:int, include_bigrams:bool, scope:str="all")->Dict[str,Any]:
    products=shopify_get_all_products(max_items=2000)
    uni, bi, scanned=Counter(), Counter(), 0
    for p in products:
        scanned+=1
        parts=[]
        if scope in ("all","titles"):
            parts.append(p.get("title") or "")
            for v in (p.get("variants") or []):
                if isinstance(v,dict):
                    if v.get("title"): parts.append(v["title"])
                    if v.get("sku"):   parts.append(str(v["sku"]))
            for opt in (p.get("options") or []):
                if isinstance(opt,dict):
                    if opt.get("name"): parts.append(opt["name"])
                    for val in (opt.get("values") or []): parts.append(val)
        if scope in ("all","descriptions"):
            parts.append(strip_html(p.get("body_html") or ""))
        if scope in ("all","tags"):
            tags=p.get("tags") or []
            if isinstance(tags,list): parts.extend(tags)
            elif isinstance(tags,str): parts.extend([x.strip() for x in tags.split(",") if x.strip()])
        if scope in ("all",):
            for img in (p.get("images") or []):
                if isinstance(img,dict):
                    alt=(img.get("alt") or "").strip()
                    if alt: parts.append(alt)
        text=" ".join([x for x in parts if x])
        toks=filter_stopwords(tokenize(text, min_len), min_len)
        uni.update(toks)
        if include_bigrams:
            bis=[b for b in bigrams(toks) if not any(w in STOPWORDS for w in b.split()) and not re.fullmatch(r"[\d\-\s]+", b)]
            bi.update(bis)
    uni_top=uni.most_common(limit)
    bi_top =bi.most_common(limit) if include_bigrams else []
    def tag(kw:str)->str: return classify_intent_from_text(kw)
    return {"unigrams":[(k,c,tag(k)) for k,c in uni_top],
            "bigrams":[(k,c,tag(k)) for k,c in bi_top],
            "scanned":scanned}

def _get_keyword_map(limit:int, min_len:int, include_bigrams:bool, scope:str="all", force:bool=False)->Dict[str,Any]:
    if (not force) and _cache_valid(KEYWORD_CACHE_TTL_MIN):
        return {"unigrams":_kw_cache["unigrams"][:limit],
                "bigrams": _kw_cache["bigrams"][:limit] if include_bigrams else [],
                "scanned": _kw_cache["scanned"], "cached":True,
                "age_sec": time.time()-_kw_cache["built_at"], "params":_kw_cache["params"]}
    data=_build_keyword_map(limit, min_len, include_bigrams, scope)
    _kw_cache.update({"built_at":time.time(),"params":{"limit":limit,"min_len":min_len,"include_bigrams":include_bigrams,"scope":scope},
                      "unigrams":data["unigrams"],"bigrams":data["bigrams"],"scanned":data["scanned"]})
    return {**data,"cached":False,"age_sec":0,"params":_kw_cache["params"]}

@app.get("/seo/keywords/run")
@require_auth
def seo_keywords_run():
    limit  = clamp(int(request.args.get("limit", KEYWORD_LIMIT_DEFAULT)), 10, 2000)
    minlen = clamp(int(request.args.get("min_len", KEYWORD_MIN_LEN)), 2, 10)
    include=str(request.args.get("include_bigrams", str(KEYWORD_INCLUDE_BIGRAMS))).lower() in ("1","true","yes","on","y")
    scope  =(request.args.get("scope","all") or "all").lower()
    savecsv=str(request.args.get("save_csv", str(KEYWORD_SAVE_CSV))).lower() in ("1","true","yes","on","y")
    t0=time.time()
    data=_get_keyword_map(limit, minlen, include, scope, force=True)
    elapsed=round(time.time()-t0,3)
    csv_path=None
    if savecsv:
        today=dt.datetime.utcnow().strftime("%Y%m%d"); csv_path=f"/mnt/data/keyword_map_{today}.csv"
        try:
            import csv
            with open(csv_path,"w",newline="",encoding="utf-8") as f:
                w=csv.writer(f); w.writerow(["keyword","count","type","intent"])
                for k,c,i in data["unigrams"]: w.writerow([k,c,"unigram",i])
                for k,c,i in (data["bigrams"] or []): w.writerow([k,c,"bigram",i])
        except Exception as e:
            csv_path=f"save_failed: {e}"
    return jsonify({
        "ok":True, "elapsed_sec":elapsed, "products_scanned":data["scanned"],
        "params":{"limit":limit,"min_len":minlen,"include_bigrams":include,"scope":scope,"save_csv":savecsv},
        "unigrams":[{"keyword":k,"count":c,"intent":i} for k,c,i in data["unigrams"]],
        "bigrams":[{"keyword":k,"count":c,"intent":i} for k,c,i in (data["bigrams"] or [])],
        "csv_path":csv_path
    })

@app.get("/seo/keywords/cache")
@require_auth
def seo_keywords_cache():
    age=None if _kw_cache["built_at"] is None else round(time.time()-_kw_cache["built_at"],2)
    return jsonify({"ok":True,"built_at_epoch":_kw_cache["built_at"],"age_sec":age,"params":_kw_cache["params"],
                    "unigrams_count":len(_kw_cache["unigrams"]),"bigrams_count":len(_kw_cache["bigrams"]),
                    "products_scanned":_kw_cache["scanned"]})

# ─────────────────────────────────────────────────────────────
# NEW: GSC Trend fetcher + endpoint
# ─────────────────────────────────────────────────────────────
def _gsc_service():
    creds=service_account.Credentials.from_service_account_file(GOOGLE_SERVICE_JSON_PATH, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return build("searchconsole","v1", credentials=creds, cache_discovery=False)

def fetch_gsc_trends() -> List[Dict[str,Any]]:
    """Return list of {query, clicks, impressions, ctr, position} filtered & sorted by impressions desc."""
    if not SEO_TREND_FROM_GSC:
        return []
    try:
        svc=_gsc_service()
        end=(dt.datetime.utcnow()-dt.timedelta(days=2)).date()  # 약간의 지연 버퍼
        start=end - dt.timedelta(days=max(7, SEO_TREND_LOOKBACK_DAYS))
        body={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions":["query"],
            "rowLimit": SEO_TREND_TOP_N,
        }
        res=svc.searchanalytics().query(siteUrl=GSC_SITE_URL, body=body).execute()
        rows=res.get("rows", [])
        out=[]
        for r in rows:
            q=(r.get("keys",[None])[0] or "").strip()
            if not q: continue
            ql=q.lower()
            if SEO_TREND_BLACKLIST and any(b in ql for b in SEO_TREND_BLACKLIST): continue
            imp=int(r.get("impressions",0))
            if imp < SEO_TREND_MIN_IMPRESSIONS: continue
            clicks=int(r.get("clicks",0)); ctr=float(r.get("ctr",0)); pos=float(r.get("position",0))
            out.append({"query":q, "clicks":clicks, "impressions":imp, "ctr":ctr, "position":pos})
        out.sort(key=lambda x: (-x["impressions"], -x["clicks"]))
        return out[:SEO_TREND_TOP_N]
    except Exception as e:
        log.exception("fetch_gsc_trends failed")
        return []

@app.get("/seo/trends/gsc")
@require_auth
def seo_trends_gsc():
    data=fetch_gsc_trends()
    return jsonify({"ok":True,"count":len(data),"site":GSC_SITE_URL,"lookback_days":SEO_TREND_LOOKBACK_DAYS,
                    "min_impressions":SEO_TREND_MIN_IMPRESSIONS,"blacklist":SEO_TREND_BLACKLIST,"rows":data})

# ─────────────────────────────────────────────────────────────
# Internal links helpers
# ─────────────────────────────────────────────────────────────
def _extract_tokens_for_match(p:dict)->set:
    parts=[p.get("title") or "", strip_html(p.get("body_html") or "")]
    tags=p.get("tags") or []
    if isinstance(tags,list): parts.extend(tags)
    elif isinstance(tags,str): parts.extend([x.strip() for x in tags.split(",") if x.strip()])
    toks=set(filter_stopwords(tokenize(" ".join(parts), KEYWORD_MIN_LEN), KEYWORD_MIN_LEN))
    return toks

def find_related_products(target:dict, candidates:List[dict], k:int)->List[dict]:
    tgt=_extract_tokens_for_match(target); scored=[]
    for c in candidates:
        if c.get("id")==target.get("id"): continue
        cset=_extract_tokens_for_match(c); score=len(tgt & cset)
        if score>0: scored.append((score,c))
    scored.sort(key=lambda x:x[0], reverse=True)
    return [c for _,c in scored[:max(0,k)]]

def inject_related_links_bottom(body_html:str, related:List[dict])->str:
    if not related or RELATED_SECTION_MARKER in (body_html or ""): return body_html
    lis=[f'<li><a href="/products/{rp.get("handle")}">{rp.get("title") or "View product"}</a></li>' for rp in related]
    block="\n".join([RELATED_SECTION_MARKER,"<h3>Related Picks</h3>","<ul>",*lis,"</ul>"])
    return (body_html or "") + "\n\n" + block

def inject_related_links_top(html:str, related:List[dict])->str:
    if not related or RELATED_TOP_MARKER in (html or ""): return html
    picks=[f'<a href="/products/{rp.get("handle")}">{rp.get("title") or "View product"}</a>' for rp in related[:2]]
    block=RELATED_TOP_MARKER + f'\n<p>Quick Picks: {" · ".join(picks)}</p>\n'
    if "</p>" in (html or ""): return re.sub(r"(</p>)", r"\1\n"+block, html, count=1)
    return block + (html or "")

def count_internal_links(body_html:str)->int:
    return 0 if not body_html else len(re.findall(r'href="/products/[^"]+"', body_html))

# ─────────────────────────────────────────────────────────────
# SEO Optimize (+ GSC trend boost)
# ─────────────────────────────────────────────────────────────
def _ensure_list(v): return v if isinstance(v,list) else ([v] if v else [])

def _score_kw(kw:str, title:str, body:str, tags:List[str], boost_set:set)->float:
    s=0.0; kw_re=rf"\b{re.escape(kw)}\b"
    if re.search(kw_re, title): s+=2.0
    if re.search(kw_re, body):  s+=1.0
    if any(kw in (t or "").lower() for t in tags): s+=1.5
    if kw in boost_set: s*=1.5
    if " " in kw: s*=1.25
    if len(kw)>=14: s*=1.1
    return s

def _compose_title(primary:str, benefit:str, cta:str)->str:
    seasonal=""
    for w in SEASONAL_WORDS:
        if len(primary)+len(" | ")+len(benefit)+len(" – ")+len(cta)+len(" · ")+len(w)<=TITLE_MAX_LEN:
            seasonal=f" · {w}"; break
    title=f"{primary} | {benefit}{seasonal}"
    if len(title)+3+len(cta)<=TITLE_MAX_LEN: title=f"{title} – {cta}"
    return (title[:TITLE_MAX_LEN]).rstrip(" -|·,")

def _compose_desc(keywords:List[str], base_body:str, cta:str)->str:
    desc_kw=", ".join(keywords[:3]) if keywords else ""
    base_desc=(base_body or "")[:120]
    if desc_kw and base_desc: desc=f"{desc_kw} — {base_desc}. {cta}."
    elif desc_kw: desc=f"{desc_kw}. {cta}."
    elif base_desc: desc=f"{base_desc}. {cta}."
    else: desc=f"Curated picks for everyday use. {cta}."
    return (desc[:DESC_MAX_LEN]).rstrip(" .,")

def ensure_alt_suggestions(p:dict)->List[str]:
    out=[]; imgs=_ensure_list(p.get("images"))
    for i,img in enumerate(imgs):
        alt=(img.get("alt") or "").strip() if isinstance(img,dict) else ""
        if not alt: out.append(f"{p.get('title','Product')} — image {i+1}")
    return out

@app.get("/seo/optimize")
@require_auth
def seo_optimize():
    if not ADMIN_TOKEN: return jsonify({"ok":False,"error":"missing SHOPIFY_ADMIN_TOKEN"}), 400

    limit      = clamp(int(request.args.get("limit", SEO_LIMIT)), 1, MAX_ENDPOINT_LIMIT)
    rotate     = (request.args.get("rotate","true").lower()!="false")
    force      = str(request.args.get("force","false")).lower() in ("1","true","yes","on","y")
    force_kw   = str(request.args.get("force_keywords","false")).lower() in ("1","true","yes","on","y")
    kw_top_n   = clamp(int(request.args.get("kw_top_n", KW_TOP_N_FOR_WEIGHT)), 5, 200)
    inject_rel = str(request.args.get("related_links", str(ALLOW_BODY_LINK_INJECTION))).lower() in ("1","true","yes","on","y")

    # 1) 기본 키워드 맵
    km=_get_keyword_map(limit=max(kw_top_n, KEYWORD_LIMIT_DEFAULT),
                        min_len=KEYWORD_MIN_LEN,
                        include_bigrams=KEYWORD_INCLUDE_BIGRAMS,
                        scope="all", force=force_kw)
    top_unigrams=[k for k,_,_ in km["unigrams"][:kw_top_n]]
    top_bigrams =[k for k,_,_ in (km["bigrams"] or [])[:kw_top_n]]
    boost_set=set(top_unigrams+top_bigrams)

    # 2) GSC 트렌드 병합(부스팅 전용)
    trend_keywords=[]
    if SEO_TREND_FROM_GSC:
        rows=fetch_gsc_trends()
        trend_keywords=[r["query"].lower() for r in rows]
        boost_set |= set(trend_keywords)

    prods=shopify_get_products(limit=max(limit,50))
    targets=prods[:limit] if not rotate else prods[:limit]
    all_candidates=shopify_get_all_products(max_items=600) if inject_rel else []

    changed, errors=[], []
    default_benefit="Fast Shipping · Quality Picks"

    for p in targets:
        pid=p.get("id"); gid=product_gid(pid)
        try:
            title_raw=p.get("title") or ""
            body_html=p.get("body_html") or ""
            body_raw=strip_html(body_html)
            tags_list=p.get("tags") if isinstance(p.get("tags"),list) else \
                      ([x.strip() for x in (p.get("tags") or "").split(",")] if isinstance(p.get("tags"),str) else [])

            # intent
            intent=classify_intent_from_text(" ".join([title_raw, body_raw, " ".join(tags_list)]))

            # 스코어링
            title_l=title_raw.lower(); body_l=body_raw.lower()
            scored_bi =sorted([(kw,_score_kw(kw,title_l,body_l,tags_list,boost_set)) for kw in top_bigrams], key=lambda x:x[1], reverse=True)
            scored_uni=sorted([(kw,_score_kw(kw,title_l,body_l,tags_list,boost_set)) for kw in top_unigrams], key=lambda x:x[1], reverse=True)

            chosen=[]
            for kw,sc in scored_bi:
                if sc<=0: continue
                chosen.append(kw)
                if len(chosen)>=3: break
            if len(chosen)<5:
                for kw,sc in scored_uni:
                    if sc<=0: continue
                    if kw not in chosen:
                        chosen.append(kw)
                        if len(chosen)>=5: break
            # 트렌드 키워드를 살짝 섞기(있다면 1~2개 우선 삽입)
            for tk in trend_keywords[:2]:
                if tk not in chosen: chosen.insert(0, tk)

            primary = chosen[0] if chosen else (p.get("title","").split(" ",1)[0] or "Best Picks")
            benefit = {
                "informational":"Quick Tips · Honest Reviews",
                "commercial":"Top Picks · Expert Compare",
                "transactional": default_benefit,
                "unknown": default_benefit
            }.get(intent, default_benefit)

            meta_title=_compose_title(primary, benefit, CTA_PHRASE)
            meta_desc =_compose_desc(chosen, body_raw, CTA_PHRASE)

            existing_title=p.get("metafields_global_title_tag")
            existing_desc =p.get("metafields_global_description_tag")
            def ok_len(s,mx): return s and (15<=len(s.strip())<=mx)

            # 내부링크 주입
            new_body=None; updated_html=body_html
            if inject_rel and RELATED_LINKS_MAX>0:
                rel=find_related_products(p, all_candidates, RELATED_LINKS_MAX)
                if rel:
                    if RELATED_TOP_MARKER not in updated_html:
                        updated_html=inject_related_links_top(updated_html, rel)
                    if RELATED_SECTION_MARKER not in updated_html:
                        updated_html=inject_related_links_bottom(updated_html, rel)
                    if updated_html!=body_html: new_body=updated_html

            if (not force) and ok_len(existing_title,TITLE_MAX_LEN) and ok_len(existing_desc,DESC_MAX_LEN) and (new_body is None):
                changed.append({"id":pid,"handle":p.get("handle"),"skipped_reason":"existing_seo_ok","intent":intent})
                continue

            if USE_GRAPHQL:
                res=shopify_update_seo_graphql(gid, meta_title, meta_desc, body_html=new_body)
                if not res.get("ok", True):
                    res=shopify_update_seo_rest(pid, meta_title, meta_desc, body_html=new_body)
            else:
                res=shopify_update_seo_rest(pid, meta_title, meta_desc, body_html=new_body)

            changed.append({
                "id":pid,"handle":p.get("handle"),
                "metaTitle":meta_title,"metaDesc":meta_desc,
                "keywords_used":chosen[:5],"intent":intent,
                "altSuggestions":ensure_alt_suggestions(p),
                "body_updated": bool(new_body is not None),
                "internal_link_count": count_internal_links(new_body if new_body is not None else body_html),
                "result":res
            })
        except Exception as e:
            log.exception("SEO update failed for %s", pid)
            errors.append({"id":pid,"handle":p.get("handle"),"error":str(e)})

    return jsonify({
        "ok":True,"action":"seo_optimize","limit":limit,"rotate":rotate,
        "keyword_source":{
            "top_unigrams_used":len(top_unigrams),"top_bigrams_used":len(top_bigrams),
            "kw_cache_age_sec": None if _kw_cache["built_at"] is None else round(time.time()-_kw_cache["built_at"],2),
            "trend_keywords_used": len(trend_keywords) if SEO_TREND_FROM_GSC else 0
        },
        "changed":changed,"errors":errors,"count":len(changed)
    })

@app.get("/run-seo")
@require_auth
def run_seo_alias(): return seo_optimize()

# ─────────────────────────────────────────────────────────────
# Blog Auto-Post (요약: 동일 로직 / 축약 표기)
# ─────────────────────────────────────────────────────────────
def _get_blog_id_by_handle(handle:str)->Optional[str]:
    q={"query":"query($h:String!){ blogByHandle(handle:$h){ id title handle }}","variables":{"h":handle}}
    try:
        r=http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=q)
        b=(r.json().get("data",{}).get("blogByHandle") or {})
        return b.get("id")
    except Exception:
        return None

def _article_create(blog_id:str, title:str, html:str, tags:List[str])->Dict[str,Any]:
    if DRY_RUN: return {"dry_run":True}
    m={"query":"""
        mutation articleCreate($input:ArticleInput!){
          articleCreate(input:$input){ article{ id handle onlineStoreUrl title } userErrors{ field message } }
        }""","variables":{"input":{"title":title,"contentHtml":html,"blogId":blog_id,"tags":tags}}}
    r=http("POST", BASE_GRAPHQL, headers=HEADERS_GQL, json=m)
    data=r.json().get("data",{}).get("articleCreate"); errs=(data or {}).get("userErrors") or []
    return {"ok": not bool(errs), "article": (data or {}).get("article"), "errors":errs}

def _blog_template(topic:str, products:List[dict], post_type:str, keywords:List[str])->Tuple[str,str]:
    n=len(products)
    title = f"{products[0]['title']} vs {products[1]['title']} — Which {topic} is Best?" if post_type=="compare" and n>=2 \
            else f"Top {n} {topic} in 2025 — Reviews & Buying Guide"
    intro=f"<p>Looking for the best {topic}? Here’s our curated list with pros & cons.</p>"
    body=[f"<h2>{title}</h2>", intro]
    link_count=0
    for i,p in enumerate(products,1):
        purl=f"/products/{p['handle']}"
        body+=[f"<h3>{i}. {p['title']}</h3>",
               "<strong>Pros:</strong> Stylish, durable, easy to use.<br><strong>Cons:</strong> Check sizes/colors before you buy.",
               f"<p><a href='{purl}'>Check {p['title']} &rarr;</a></p>"]
        link_count+=1
    while link_count<3 and products:
        p=random.choice(products); body.append(f"<p><a href='/products/{p['handle']}'>Explore {p['title']} &rarr;</a></p>"); link_count+=1
    outro="<p>All items are curated by Jeff’s Favorite Picks. Limited stock — grab yours today!</p>"
    kw=f"<p>Popular keywords: {', '.join(keywords[:5])}</p>" if keywords else ""
    return title, "\n".join(body+[outro, kw])

def _share_snippets(title:str, url:str, products:List[dict])->Dict[str,str]:
    picks=", ".join([p.get("title","") for p in products[:3] if p.get("title")])
    return {
        "pinterest": f"{title}\n{picks}\n{url}\n#phone #accessories #shopping #review",
        "medium":    f"{title}\n\nWe compared: {picks}.\nRead more: {url}",
        "reddit":    f"[Review] {title} — picks: {picks}\n{url}",
        "quora":     f"{title}: What to consider when buying? See our breakdown → {url}"
    }

@app.post("/blog/auto-post")
@require_auth
def blog_auto_post():
    if not BLOG_AUTO_POST: return jsonify({"ok":False,"error":"BLOG_AUTO_POST disabled"}), 400
    body=request.get_json(silent=True) or {}
    topic=body.get("topic") or BLOG_DEFAULT_TOPIC
    post_type=(body.get("type") or BLOG_POST_TYPE or "review").lower()
    pick_n=int(body.get("pick_n") or 5); tags=body.get("tags") or [topic,"auto","review" if post_type=="review" else "compare"]
    allp=shopify_get_all_products(max_items=500); 
    if not allp: return jsonify({"ok":False,"error":"no products"}), 400
    random.shuffle(allp); picks=allp[:pick_n] if len(allp)>=pick_n else allp
    km=_get_keyword_map(limit=KEYWORD_LIMIT_DEFAULT, min_len=KEYWORD_MIN_LEN, include_bigrams=KEYWORD_INCLUDE_BIGRAMS, scope="all", force=False)
    top_kw=[k for k,_,_ in km["unigrams"][:10]]
    title, html=_blog_template(topic, picks, post_type, top_kw)
    blog_id=_get_blog_id_by_handle(BLOG_HANDLE)
    if not blog_id: return jsonify({"ok":False,"error":f"blog handle '{BLOG_HANDLE}' not found"}), 400
    created=_article_create(blog_id, title, html, tags)
    if not created.get("ok"): return jsonify({"ok":False,"error":"article_create_failed","details":created}), 500
    article=created["article"]; a_url=article.get("onlineStoreUrl") or f"/blogs/{BLOG_HANDLE}/{article.get('handle')}"
    return jsonify({"ok":True,"article":{"id":article.get("id"),"title":article.get("title"),"handle":article.get("handle"),"url":a_url},
                    "snippets":_share_snippets(title, a_url, picks), "picks_count":len(picks),"topic":topic,"type":post_type})

# ─────────────────────────────────────────────────────────────
# Sitemap / Robots
# ─────────────────────────────────────────────────────────────
def _abs_product_url(handle:str)->str:
    host=CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com"
    return f"https://{host}/products/{handle}"

def _xml_escape(s:str)->str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&apos;")

def _to_rfc3339_utc(ts:Optional[str])->str:
    if not ts: return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        d=dt.datetime.fromisoformat(ts.replace("Z","+00:00"))
        if d.tzinfo is not None: d=d.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return d.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

@app.get("/sitemap-index.xml")
def sitemap_index():
    host=CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com"
    now=dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    items=[f"<sitemap><loc>{_xml_escape(PRIMARY_SITEMAP or f'https://{host}/sitemap.xml')}</loc><lastmod>{now}</lastmod></sitemap>"]
    if PUBLIC_BASE:
        items.append(f"<sitemap><loc>{_xml_escape(PUBLIC_BASE+'/sitemap-products.xml')}</loc><lastmod>{now}</lastmod></sitemap>")
    body="\n".join(['<?xml version="1.0" encoding="UTF-8"?>','<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',*items,'</sitemapindex>'])
    return Response(body, mimetype="application/xml")

@app.get("/sitemap-products.xml")
def sitemap_products():
    try:
        prods=shopify_get_all_products(max_items=5000); urls=[]
        for p in prods:
            h=p.get("handle"); if not h: continue
            loc=_abs_product_url(h); lastmod=_to_rfc3339_utc(p.get("updated_at") or p.get("published_at"))
            imgs=p.get("images") or []; img_xml=[]
            for im in imgs[:6]:
                src=im.get("src") if isinstance(im,dict) else (str(im) if im else "")
                if src: img_xml.append(f"<image:image><image:loc>{_xml_escape(src)}</image:loc></image:image>")
            urls.append(f"<url><loc>{_xml_escape(loc)}</loc><lastmod>{lastmod}</lastmod><changefreq>weekly</changefreq><priority>0.7</priority>{''.join(img_xml)}</url>")
        body="\n".join(['<?xml version="1.0" encoding="UTF-8"?>',
                        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
                        *urls,"</urlset>"])
        return Response(body, mimetype="application/xml")
    except Exception as e:
        log.exception("sitemap-products failed")
        return jsonify({"ok":False,"error":str(e)}), 500

@app.get("/robots.txt")
def robots_txt():
    host=CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com"
    lines=["User-agent: *","Allow: /","",f"Sitemap: https://{host}/sitemap.xml"]
    if PUBLIC_BASE:
        lines.append(f"Sitemap: {PUBLIC_BASE}/sitemap-products.xml")
        lines.append(f"Sitemap: {PUBLIC_BASE}/sitemap-index.xml")
    return Response("\n".join(lines)+"\n", mimetype="text/plain")

# ─────────────────────────────────────────────────────────────
# IndexNow + (fallback) GSC ping
# ─────────────────────────────────────────────────────────────
@app.get("/bing/ping")
def bing_ping(): return Response("Bing sitemap ping is deprecated.\n", status=410, mimetype="text/plain")

def _indexnow_submit(urls:List[str])->Dict[str,Any]:
    if not INDEXNOW_KEY: return {"ok":False,"error":"missing INDEXNOW_KEY"}
    payload={"host": CANONICAL_DOMAIN or f"{SHOPIFY_STORE}.myshopify.com","key":INDEXNOW_KEY,"keyLocation":INDEXNOW_KEY_URL or "","urlList":urls[:1000]}
    try:
        r=http("POST","https://api.indexnow.org/indexnow", json=payload, headers={"Content-Type":"application/json"})
        return {"ok": r.status_code in (200,202), "status":r.status_code, "text": r.text[:500]}
    except Exception as e:
        log.exception("IndexNow submit failed"); return {"ok":False,"error":str(e)}

@app.post("/indexnow/submit")
@require_auth
def indexnow_submit():
    body=request.get_json(silent=True) or {}; urls=body.get("urls") or []
    if not urls:
        prods=shopify_get_products(limit=250); urls=[_abs_product_url(p["handle"]) for p in prods if p.get("handle")]
    if not INDEXNOW_KEY or not (INDEXNOW_KEY_URL or "").startswith("http"):
        log.warning("IndexNow not fully configured")
    res=_indexnow_submit(urls); return jsonify({"ok":res.get("ok",False),"result":res,"count":len(urls)}), (200 if res.get("ok") else 500)

@app.post("/gsc/sitemap/submit")
@require_auth
def gsc_sitemap_submit():
    sitemap_url=(request.get_json(silent=True) or {}).get("sitemap_url") or PRIMARY_SITEMAP
    try:
        r=http("GET","https://www.google.com/ping", params={"sitemap":sitemap_url})
        ok=r.status_code in (200,202)
        return jsonify({"ok":ok,"status":r.status_code,"used_fallback_ping":True,"sitemap_url":sitemap_url}), (200 if ok else 500)
    except Exception as e:
        return jsonify({"ok":False,"error":str(e),"sitemap_url":sitemap_url}), 500

# ─────────────────────────────────────────────────────────────
# Daily Report (orphans + WebP)
# ─────────────────────────────────────────────────────────────
def _image_webp_ratio(p:dict)->float:
    imgs=p.get("images") or []; 
    if not imgs: return 0.0
    total=sum(1 for _ in imgs); webp=sum(1 for im in imgs if ".webp" in ((im.get("src") if isinstance(im,dict) else str(im)) or "").lower())
    return (webp/total) if total>0 else 0.0

def _report_html(s:Dict[str,Any])->str:
    lines=["<div style='font-family:system-ui,Segoe UI,Arial'>",
           "<h2>Daily SEO Report / 일일 SEO 점검 리포트</h2>",
           f"<p>Generated (UTC): {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}</p>",
           "<h3>Summary / 요약</h3>",
           "<ul>",
           f"<li>Products scanned: {s['scanned']}</li>",
           f"<li>Orphan suspects: {len(s['orphans'])}</li>",
           f"<li>Avg WebP ratio: {s['avg_webp_ratio']:.2f}</li>",
           f"<li>Below WebP threshold (&gt;{int(SPEED_WEBP_THRESHOLD*100)}% target): {len(s['below_threshold'])}</li>",
           "</ul>"]
    if s["orphans"]:
        lines+=["<h3>Orphaned-Page Suspects (내부 링크 부족)</h3>","<ol>"]
        for o in s["orphans"][:50]:
            lines.append(f"<li><a href='{_abs_product_url(o['handle'])}'>{o['title']}</a> — internal links: {o['internal_links']}</li>")
        lines.append("</ol>")
    else: lines.append("<p>No orphan suspects. 🎉</p>")
    if s["below_threshold"]:
        lines+=["<h3>WebP Ratio Below Threshold (이미지 WebP 비율 낮음)</h3>","<ol>"]
        for b in s["below_threshold"][:50]:
            lines.append(f"<li><a href='{_abs_product_url(b['handle'])}'>{b['title']}</a> — WebP: {int(round(b['webp_ratio']*100))}%</li>")
        lines.append("</ol>")
    else: lines.append("<p>All products meet WebP ratio target. ✅</p>")
    lines+=["<h3>Tips</h3>","<ul>",
            "<li>Add 2–3 internal links (Related Picks) into low-link product pages.</li>",
            "<li>Convert gallery images to WebP for faster LCP and better INP.</li>",
            "<li>Keep meta title & description within length limits; include CTA.</li>",
            "</ul>","</div>"]
    return "\n".join(lines)

def send_email(subject:str, html_content:str, to:Optional[List[str]]=None)->Dict[str,Any]:
    if not ENABLE_EMAIL: return {"ok":False,"error":"email_disabled"}
    if not SENDGRID_API_KEY: return {"ok":False,"error":"missing SENDGRID_API_KEY"}
    to_list=[t for t in (to or EMAIL_TO) if t]; 
    if not to_list: return {"ok":False,"error":"empty_email_to"}
    payload={"personalizations":[{"to":[{"email":x} for x in to_list]}],
             "from":{"email":EMAIL_FROM},"subject":subject,"content":[{"type":"text/html","value":html_content}]}
    try:
        r=http("POST","https://api.sendgrid.com/v3/mail/send",
               headers={"Authorization":f"Bearer {SENDGRID_API_KEY}","Content-Type":"application/json"}, json=payload)
        return {"ok": r.status_code in (200,202), "status":r.status_code}
    except Exception as e:
        log.exception("send_email failed"); return {"ok":False,"error":str(e)}

@app.get("/report/daily")
@require_auth
def daily_report():
    try:
        prods=shopify_get_all_products(max_items=1000); scanned=len(prods)
        orphans, below, ratios=[], [], []
        for p in prods:
            il=count_internal_links(p.get("body_html") or ""); 
            if il<ORPHAN_LINK_MIN: orphans.append({"id":p.get("id"),"handle":p.get("handle"),"title":p.get("title"),"internal_links":il})
            wr=_image_webp_ratio(p); ratios.append(wr)
            if wr<SPEED_WEBP_THRESHOLD: below.append({"id":p.get("id"),"handle":p.get("handle"),"title":p.get("title"),"webp_ratio":wr})
        orphans.sort(key=lambda x:x["internal_links"]); below.sort(key=lambda x:x["webp_ratio"])
        summary={"scanned":scanned,"orphans":orphans,"below_threshold":below,"avg_webp_ratio": (sum(ratios)/len(ratios) if ratios else 0.0)}
        html=_report_html(summary); email_status=send_email("Daily SEO Report — Orphans & WebP / 일일 SEO 리포트", html)
        return jsonify({"ok":True,"summary":summary,"email":email_status})
    except Exception as e:
        log.exception("daily_report failed"); return jsonify({"ok":False,"error":str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Shopify 연결 진단
# ─────────────────────────────────────────────────────────────
@app.get("/health/shopify")
def health_shopify():
    admin_auth=os.getenv("ADMIN_AUTH") or IMPORT_AUTH_TOKEN
    if admin_auth:
        qs=request.args.get("auth"); bearer=(request.headers.get("Authorization") or "").strip(); xauth=request.headers.get("X-Auth")
        token_hdr=bearer.split(" ",1)[1].strip() if bearer.lower().startswith("bearer ") else None
        if (qs or xauth or token_hdr) != admin_auth: return jsonify({"ok":False,"error":"unauthorized"}), 401
    store=os.getenv("SHOPIFY_STORE_DOMAIN") or ((os.getenv("SHOPIFY_STORE") or "").strip()+".myshopify.com")
    store=store.replace("https://","").replace("http://","").strip("/")
    token=os.getenv("SHOPIFY_API_TOKEN") or os.getenv("SHOPIFY_ADMIN_TOKEN")
    api_v=os.getenv("SHOPIFY_API_VERSION") or os.getenv("API_VERSION") or "2025-07"
    if not store or not token:
        return jsonify({"ok":False,"error":"missing_env","need":{"SHOPIFY_STORE_DOMAIN":bool(store),"SHOPIFY_API_TOKEN":bool(token),"SHOPIFY_API_VERSION":api_v}}), 500
    base=f"https://{store}/admin/api/{api_v}"
    try:
        r=http("GET", f"{base}/shop.json", headers={"X-Shopify-Access-Token":token,"Accept":"application/json"})
        try: body=r.json()
        except: body=(r.text or "")[:500]
        return jsonify({"ok":r.ok,"status":r.status_code,"endpoint":f"{base}/shop.json","domain":store,"api_version":api_v,"body":body}), (200 if r.ok else r.status_code)
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)}), 500

# ─────────────────────────────────────────────────────────────
# Diagnostics & root
# ─────────────────────────────────────────────────────────────
@app.get("/__routes")
def list_routes():
    rules=[{"endpoint":r.endpoint,"methods":sorted([m for m in r.methods if m in {"GET","POST","PUT","DELETE","PATCH"}]),"rule":str(r)}
           for r in app.url_map.iter_rules() if r.endpoint!="static"]
    rules.sort(key=lambda x:x["rule"]); return jsonify({"ok":True,"routes":rules})

@app.get("/health")
def health(): return jsonify({"ok":True,"time_utc":dt.datetime.utcnow().isoformat()+"Z"})

@app.get("/")
def root():
    return jsonify({"ok":True,"name":"Unified Pro + GSC Trend Boost","version":"2025-10-13",
                    "public_base":PUBLIC_BASE,"store":SHOPIFY_STORE,"canonical_domain":CANONICAL_DOMAIN,
                    "endpoints":[r.rule for r in app.url_map.iter_rules() if r.endpoint!="static"]})

# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
if __name__=="__main__":
    port=int(os.getenv("PORT","8000"))
    app.run(host="0.0.0.0", port=port)


