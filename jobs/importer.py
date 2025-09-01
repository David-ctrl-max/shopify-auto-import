# jobs/importer.py
# 외부(신규) 모듈 진입점: services.importer 의 실제 구현을 래핑
from __future__ import annotations
import logging

log = logging.getLogger(__name__)

def run_all():
    log.info("[jobs.run_all] 실제 SEO/임포트 작업 시작 (services.importer 위임)")
    try:
        from services.importer import run_all as _run_all
    except ModuleNotFoundError:
        log.exception("[jobs.run_all] services.importer 모듈을 찾을 수 없습니다.")
        return
    except Exception:
        log.exception("[jobs.run_all] services.importer 임포트 중 오류")
        return
    return _run_all()

def run_keywords():
    log.info("[jobs.run_keywords] 별도 키워드 배치 없음 -> run_all 위임")
    try:
        from services.importer import run_all as _run_all
    except ModuleNotFoundError:
        log.exception("[jobs.run_keywords] services.importer 모듈 없음")
        return
    except Exception:
        log.exception("[jobs.run_keywords] services.importer 임포트 중 오류")
        return
    return _run_all()

def resubmit_sitemap():
    log.info("[jobs.resubmit_sitemap] 사이트맵 재제출 (services.importer 위임)")
    try:
        from services.importer import resubmit_sitemap as _resubmit_sitemap
    except ModuleNotFoundError:
        log.exception("[jobs.resubmit_sitemap] services.importer 모듈 없음")
        return
    except Exception:
        log.exception("[jobs.resubmit_sitemap] services.importer 임포트 중 오류")
        return
    return _resubmit_sitemap()






