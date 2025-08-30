# jobs/importer.py
"""
Render에서 main.py가 동적으로 불러 호출하는 임포트/SEO 작업 모듈.
- 필수 ENV: SHOPIFY_STORE, SHOPIFY_ADMIN_TOKEN
- 선택 ENV: SHOPIFY_API_VERSION(기본 2024-04), SITEMAP_URL
"""

import os
import time
import logging
from typing import Any, Dict, Optional

import requests

# -----------------------------
# 환경 변수
# -----------------------------
STORE: str = os.environ.get("SHOPIFY_STORE", "").strip()
TOKEN: str = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
API_VERSION: str = os.environ.get("SHOPIFY_API_VERSION", "2024-04").strip()
SITEMAP_URL: str = os.environ.get("SITEMAP_URL", "").strip()

# -----------------------------
# HTTP 세션 & 상수
# -----------------------------
SESSION = requests.Session()
if TOKEN:
    SESSION.headers.update(
        {
            "X-Shopify-Access-Token": TOKEN,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
TIMEOUT = 20  # seconds
MAX_RETRY = 3


def _base_url() -> str:
    if not STORE:
        raise RuntimeError("환경변수 SHOPIFY_STORE 가 설정되지 않았습니다.")
    return f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/"


# -----------------------------
# Shopify 요청 유틸
# -----------------------------
def _request(
    method: str, path: str, *, params: Optional[Dict[str, Any]] = None, json: Any = None
) -> Dict[str, Any]:
    """429(레이트리밋) 처리 포함 공통 요청 함수"""
    if not TOKEN:
        raise RuntimeError("환경변수 SHOPIFY_ADMIN_TOKEN 이 설정되지 않았습니다.")

    url = _base_url() + path.lstrip("/")

    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = SESSION.request(
                method, url, params=params, json=json, timeout=TIMEOUT
            )
        except requests.RequestException as e:
            # 네트워크 오류는 재시도
            if attempt < MAX_RETRY:
                time.sleep(0.7 * attempt)
                continue
            raise RuntimeError(f"Shopify 요청 실패(네트워크): {e}") from e

        # 레이트 리밋
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 0.7
            time.sleep(delay)
            continue

        # 그 외 상태코드 처리
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            # 4xx/5xx는 재시도 가치가 낮지만 5xx는 한 번 더 시도
            if 500 <= r.status_code < 600 and attempt < MAX_RETRY:
                time.sleep(0.7 * attempt)
                continue
            # 에러 본문 로깅 보조
            body = r.text[:500]
            raise RuntimeError(
                f"Shopify 요청 실패({r.status_code}): {url} :: {body}"
            ) from e

        # 정상
        return r.json() if r.content else {}

    raise RuntimeError(f"Shopify 요청 반복 실패: {url}")


def _shopify_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _request("GET", path, params=params)


def _shopify_post(path: str, payload: Any) -> Dict[str, Any]:
    return _request("POST", path, json=payload)


def _shopify_put(path: str, payload: Any) -> Dict[str, Any]:
    return _request("PUT", path, json=payload)


# -----------------------------
# 작업 로직 (샘플)
# -----------------------------
def _fetch_sample_products(n: int = 5):
    """연결/토큰 확인 겸 샘플 상품 조회"""
    data = _shopify_get("products.json", {"limit": n})
    items = data.get("products", []) or []
    logging.info("[shopify] 샘플 상품 %d개", len(items))
    for p in items:
        logging.info(" - %s | %s", p.get("id"), p.get("title"))
    return items


def _ping_sitemap():
    """사이트맵 핑(Google + 선택적 Bing)"""
    if not SITEMAP_URL:
        logging.info("[sitemap] SITEMAP_URL 없음, 건너뜀")
        return
    try:
        g = requests.get(
            "https://www.google.com/ping", params={"sitemap": SITEMAP_URL}, timeout=TIMEOUT
        )
        logging.info("[sitemap] Google ping %s (%d)", SITEMAP_URL, g.status_code)
    except requests.RequestException as e:
        logging.warning("[sitemap] Google ping 실패: %s", e)

    # Bing은 선택
    try:
        b = requests.get(
            "https://www.bing.com/ping", params={"siteMap": SITEMAP_URL}, timeout=TIMEOUT
        )
        logging.info("[sitemap] Bing ping %s (%d)", SITEMAP_URL, b.status_code)
    except requests.RequestException as e:
        logging.warning("[sitemap] Bing ping 실패: %s", e)


def run_all():
    """여기에 실제 임포트/SEO 배치 단계들을 연결하세요."""
    t0 = time.time()
    logging.info("[run_all] 실제 SEO/임포트 작업 시작")

    # 0) 연결 점검
    _fetch_sample_products(5)

    # 1) TODO: 상품 생성/수정 예시
    # new_payload = {"product": {"title": "새 상품", "body_html": "<strong>설명</strong>"}}
    # created = _shopify_post("products.json", new_payload)
    # logging.info("[shopify] 상품 생성 완료 id=%s", created.get("product", {}).get("id"))

    # 2) TODO: 메타필드/메타태그 갱신, 이미지 ALT 보정 등 구현

    # 3) 사이트맵 핑(선택)
    _ping_sitemap()

    logging.info("[run_all] 완료 (%.1fs)", time.time() - t0)


# -----------------------------
# 외부에서 호출하는 진입점
# -----------------------------
def run():
    """
    main.py에서 import하여 호출하는 함수.
    환경변수 누락 시 에러 로그만 남기고 폴백을 가능하게 함.
    """
    missing = []
    if not STORE:
        missing.append("SHOPIFY_STORE")
    if not TOKEN:
        missing.append("SHOPIFY_ADMIN_TOKEN")

    if missing:
        logging.error("[run] 필수 환경변수 누락: %s", ", ".join(missing))
        return

    try:
        run_all()
    except Exception as e:
        logging.exception("[run] 작업 실패: %s", e)

