"""테스트 전역 설정.

⚠️ 실거래 DB 보호: 엔진을 생성/사용하는 테스트가 persistence 모듈을 통해
backend/data/trading.db(실거래 DB)에 쓰는 것을 막는다. 모든 테스트는 per-test
임시 DB 로 격리된다. (2026-06-08 회귀 사고 방지 — pytest 가 실DB 를 오염시킨 건)
"""

import pytest

import app.trading.persistence as persistence


@pytest.fixture(autouse=True)
def isolate_trading_db(monkeypatch, tmp_path):
    """persistence.DB_PATH 를 per-test 임시 파일로 치환 → 실거래 DB 절대 미접촉."""
    test_db = tmp_path / "test_trading.db"
    monkeypatch.setattr(persistence, "DB_PATH", test_db)
    yield
