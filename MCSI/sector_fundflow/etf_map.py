# -*- coding: utf-8 -*-
"""
GICS 11개 섹터 → 한국 시장 대표 섹터 ETF 매핑
==============================================

선정 기준:
  1) KODEX(삼성자산운용) 우선
  2) KODEX 에 해당 섹터가 없으면 TIGER(미래에셋) 등으로 대체
  3) 가급적 코스피200 섹터 지수를 추종하는 상품 선택 (유동성·대표성)

GICS Sector              | ETF 종목명                        | 종목코드
-------------------------|-----------------------------------|--------
Energy                   | KODEX 에너지화학                   | 117460
Materials                | KODEX 철강                         | 117680
Industrials              | TIGER 200 산업재                   | 227550
Consumer Discretionary   | KODEX 경기소비재                   | 266390
Consumer Staples         | KODEX 필수소비재                   | 266410
Health Care              | KODEX 헬스케어                     | 266420
Financials               | TIGER 200 금융                     | 139270
Information Technology   | TIGER 200 IT                       | 139260
Communication Services   | TIGER 200 커뮤니케이션서비스        | 315270
Utilities                | KODEX 에너지화학                   | 117460  ← 국내 순수 유틸리티 ETF 부재, 별도 참고
Real Estate              | KODEX 한국부동산리츠인프라          | 476800

※ Utilities: 한국 시장에 순수 유틸리티 섹터 ETF가 없음.
   대안으로 HANARO 전력설비투자 등이 있으나 상장 이력이 짧아,
   여기서는 에너지화학으로 대체 매핑하되, 별도 유틸리티 프록시를 남겨둠.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class SectorETF:
    """GICS 섹터 하나에 대응하는 한국 ETF 정보."""
    gics_sector: str          # 영문 GICS 섹터명
    gics_sector_kr: str       # 한글 섹터명
    etf_name: str             # ETF 종목명
    ticker: str               # 6자리 종목코드
    brand: str                # ETF 브랜드 (KODEX, TIGER 등)
    note: str = ""            # 비고


# ── 매핑 테이블 ──────────────────────────────────────────────
SECTOR_ETF_MAP: List[SectorETF] = [
    SectorETF("Energy",                   "에너지",       "KODEX 에너지화학",              "117460", "KODEX"),
    SectorETF("Materials",                "소재",         "KODEX 철강",                    "117680", "KODEX"),
    SectorETF("Industrials",              "산업재",       "TIGER 200 산업재",              "227550", "TIGER"),
    SectorETF("Consumer Discretionary",   "경기소비재",   "KODEX 경기소비재",              "266390", "KODEX"),
    SectorETF("Consumer Staples",         "필수소비재",   "KODEX 필수소비재",              "266410", "KODEX"),
    SectorETF("Health Care",              "헬스케어",     "KODEX 헬스케어",                "266420", "KODEX"),
    SectorETF("Financials",               "금융",         "TIGER 200 금융",                "139270", "TIGER"),
    SectorETF("Information Technology",   "IT",           "TIGER 200 IT",                  "139260", "TIGER"),
    SectorETF("Communication Services",   "커뮤니케이션", "TIGER 200 커뮤니케이션서비스",  "315270", "TIGER"),
    SectorETF("Utilities",               "유틸리티",     "KODEX 에너지화학",              "117460", "KODEX",
     "순수 유틸리티 ETF 부재 → 에너지화학 대체"),
    SectorETF("Real Estate",              "부동산",       "KODEX 한국부동산리츠인프라",    "476800", "KODEX"),
]


def tickers() -> List[str]:
    """고유 종목코드 목록 (중복 제거)."""
    seen: set[str] = set()
    out: List[str] = []
    for s in SECTOR_ETF_MAP:
        if s.ticker not in seen:
            seen.add(s.ticker)
            out.append(s.ticker)
    return out


def ticker_name_map() -> Dict[str, str]:
    """종목코드 → ETF 이름 딕셔너리 (중복 시 먼저 등장한 것 우선)."""
    m: Dict[str, str] = {}
    for s in SECTOR_ETF_MAP:
        m.setdefault(s.ticker, s.etf_name)
    return m


def ticker_sector_map() -> Dict[str, str]:
    """종목코드 → GICS 섹터(영문) 딕셔너리."""
    m: Dict[str, str] = {}
    for s in SECTOR_ETF_MAP:
        m.setdefault(s.ticker, s.gics_sector)
    return m
