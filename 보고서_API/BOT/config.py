# -*- coding: utf-8 -*-
"""
BOT 통합 설정 파일
모든 BOT 파일들이 이 설정을 import하여 사용합니다.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

#   베이스 경로


BASE_DIR = Path(__file__).parent.parent  # BOT 폴더의 부모 디렉토리

# 루트 .env(로컬 전용, gitignore) 에서 비밀값 로드
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)


#  공통 디렉토리 (모든 BOT이 공유)

TRAINING_PDF_DIR = BASE_DIR / "pdf_train"
TRAINING_DOCX_DIR = BASE_DIR / "pdf_train"
TRAINING_PPTX_DIR = BASE_DIR / "pdf_train"

INPUT_DIR = BASE_DIR / "pdf_test"          # 범용 input 디렉토리
EMPLOYMENT_INPUT_DIR = BASE_DIR / "employment_test"
OUTPUT_DIR = BASE_DIR / "pdf_output"
EMPLOYMENT_OUTPUT_DIR = BASE_DIR / "employment_output"

# 문자열로도 변환 (경로 호환성)
TRAINING_PDF_DIR_STR = str(TRAINING_PDF_DIR)
TRAINING_DOCX_DIR_STR = str(TRAINING_DOCX_DIR)
TRAINING_PPTX_DIR_STR = str(TRAINING_PPTX_DIR)
INPUT_DIR_STR = str(INPUT_DIR)
EMPLOYMENT_INPUT_DIR_STR = str(EMPLOYMENT_INPUT_DIR)
OUTPUT_DIR_STR = str(OUTPUT_DIR)
EMPLOYMENT_OUTPUT_DIR_STR = str(EMPLOYMENT_OUTPUT_DIR)


#  OpenAI 설정  

# 키는 환경변수/루트 .env 에서만 로드 (하드코딩 금지)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL_DEFAULT = "gpt-4o"


#   BOT별 설정  

# 1. 고용동향 (api_고용동향.py)


EMPLOYMENT_CONFIG = {
    'name': '고용동향',
    'search_title': "2026년 1월 고용동향",  # 수정 가능
    'input_dir': EMPLOYMENT_INPUT_DIR_STR,
    'output_dir': EMPLOYMENT_OUTPUT_DIR_STR,
    'openai_api_key': OPENAI_API_KEY,
    'model': MODEL_DEFAULT,
    'temperature': 0.1,
    'max_tokens': 40000,
    'base_url': "https://mods.go.kr",
    'max_pages': 50,
}

# 2. 글로벌매크로 (api_글로벌매크로.py)


GLOBAL_MACRO_CONFIG = {
    'name': '글로벌매크로',
    'training_dir': TRAINING_PPTX_DIR_STR,
    'output_dir': OUTPUT_DIR_STR,
    'test_file': str(INPUT_DIR / r"C:\\Users\\intern9\\truston_quant_dev\\pdf_test\\[KB증권] 글로벌 시황_202604.pptx"),  # 수정 가능
    'openai_api_key': OPENAI_API_KEY,
    'model': MODEL_DEFAULT,
    'temperature': 0.1,
    'max_tokens': 4000,
    'target_month': "2026년 3월",  # 수정 가능
    'next_month': "2026년 4월",     # 수정 가능
}

# 3. 리뷰 (api_리뷰.py)


REVIEW_CONFIG = {
    'name': '리뷰',
    'training_dir': TRAINING_DOCX_DIR_STR,
    'output_dir': OUTPUT_DIR_STR,
    'test_file': str(INPUT_DIR / r"C:\\Users\\intern9\\truston_quant_dev\\pdf_test\\트러스톤-2026년 4월 주식 전망.docx"),  # 수정 가능
    'openai_api_key': OPENAI_API_KEY,
    'model': MODEL_DEFAULT,
    'temperature': 0.1,
    'max_tokens': 4000,
}


# 4. 산업활동동향 (api_산업활동동향.py)


INDUSTRY_CONFIG = {
    'name': '산업활동동향',
    'search_title': "'26.2월 산업활동동향 및 평가",  # 수정 가능
    'training_dir': TRAINING_PDF_DIR_STR,
    'input_dir': INPUT_DIR_STR,
    'output_dir': OUTPUT_DIR_STR,
    'openai_api_key': OPENAI_API_KEY,
    'model': MODEL_DEFAULT,
    'temperature': 0.1,
    'max_tokens': 4000,
    'base_url': "https://mofe.go.kr",
    'max_pages': 50,
}


# 5. 수출입 (api_수출입.py)


TRADE_CONFIG = {
    'name': '수출입동향',
    'search_title': "2026년 3월 수출입 동향",  # 수정 가능
    'training_dir': TRAINING_PDF_DIR_STR,
    'input_dir': INPUT_DIR_STR,
    'output_dir': OUTPUT_DIR_STR,
    'openai_api_key': OPENAI_API_KEY,
    'model': MODEL_DEFAULT,
    'temperature': 0.1,
    'max_tokens': 4000,
    'base_url': "https://www.motir.go.kr",
    'max_pages': 20,
}

# 6. 통화정책 (api_통화정책.py)


MONETARY_POLICY_CONFIG = {
    'name': '통화정책',
    'search_year': 2026,   # 수정 가능
    'search_month': 3,     # 수정 가능
    'training_dir': TRAINING_PDF_DIR_STR,
    'input_dir': INPUT_DIR_STR,
    'output_dir': OUTPUT_DIR_STR,
    'openai_api_key': OPENAI_API_KEY,
    'model': MODEL_DEFAULT,
    'temperature': 0.1,
    'max_tokens': 4000,
    'bok_list_url': "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?mtgSe=A&menuNo=200755",
}


#   모든 BOT 목록  


all_bots = [
    EMPLOYMENT_CONFIG,
    GLOBAL_MACRO_CONFIG,
    REVIEW_CONFIG,
    INDUSTRY_CONFIG,
    TRADE_CONFIG,
    MONETARY_POLICY_CONFIG,
]


#  디버그 출력


if __name__ == "__main__":
    print("=" * 64)
    print("  BOT 설정 확인")
    print("=" * 64)
    print(f"\n[기본 경로]")
    print(f"  BASE_DIR: {BASE_DIR}")
    print(f"  Training: {TRAINING_PDF_DIR}")
    print(f"  Input:    {INPUT_DIR}")
    print(f"  Output:   {OUTPUT_DIR}")
    
    print(f"\n[BOT 목록]")
    for i, config in enumerate(all_bots, 1):
        print(f"  {i}. {config['name']}")
    
    print("\n✅ 설정 로드 완료")
