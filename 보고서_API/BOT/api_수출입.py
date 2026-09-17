# -*- coding: utf-8 -*-
"""
수출입 동향 보고서 크롤링 봇
pip install openai PyMuPDF selenium webdriver-manager requests beautifulsoup4
"""

import os
import re
import time
import requests
import openai
import zipfile
from xml.etree import ElementTree as ET
from urllib.parse import unquote, urljoin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ════════════════════════════════════════════════════════════════
# config.py에서 설정 import
# ════════════════════════════════════════════════════════════════

try:
    from 보고서_API.BOT.config import TRADE_CONFIG
    SEARCH_TITLE = TRADE_CONFIG['search_title']
    OPENAI_API_KEY = TRADE_CONFIG['openai_api_key']
    MODEL = TRADE_CONFIG['model']
    TEMPERATURE = TRADE_CONFIG['temperature']
    MAX_TOKENS = TRADE_CONFIG['max_tokens']
    TRAINING_PDF_DIR = TRADE_CONFIG['training_dir']
    INPUT_HWPX_DIR = TRADE_CONFIG['input_dir']
    OUTPUT_DIR = TRADE_CONFIG['output_dir']
    BASE_URL = TRADE_CONFIG['base_url']
    MAX_PAGES = TRADE_CONFIG['max_pages']
except ImportError:
    # config.py가 없을 경우 기본값 사용
    SEARCH_TITLE = "2026년 3월 수출입 동향"
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    MODEL = "gpt-4o"
    TEMPERATURE = 0.1
    MAX_TOKENS = 4000
    TRAINING_PDF_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_train"
    INPUT_HWPX_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_test"
    OUTPUT_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_output"
    BASE_URL = "https://www.motir.go.kr"
    MAX_PAGES = 20

LIST_URL = (
    f"{BASE_URL}/kor/article/ATCL3f49a5a8c"
    f"?mno=&pageIndex={{page}}&rowPageC=0&displayAuthor="
    f"&searchCategory=0&schClear=on&startDtD=&endDtD="
    f"&searchCondition=1&searchKeyword=%EC%88%98%EC%B6%9C"
)

client = openai.OpenAI(api_key=OPENAI_API_KEY)


SYSTEM_PROMPT = """당신은 산업통상자원부 수출입 동향 보도자료 원문을 읽고 요약 보고서를 작성하는 전문 분석관입니다.

[형식]
- "(매크로)" 로 시작, 다음 줄에 "- N월 수출은"으로 본문 시작.
- 본문은 줄바꿈 없이 하나의 문단. 문장 사이는 마침표 + 공백.
- 제목·머리말·번호 매기기 금지.
- 원문의 형식을 최대한 그대로 유지한다.

[본문 구성 순서]
① 총괄·수출 개요: 원문의 【총괄】과 【수출】 섹션에 있는 줄 글의 내용과 수치를 빠짐없이 모두 포함한다. 수출액, 수입액, 무역수지, 일평균 수출, 역대 순위, 누적 실적, 연속 증감 횟수 등 해당 섹션의 모든 서술을 누락 없이 반영한다.
② 품목별 동향 (반도체 → 컴퓨터SSD → 무선통신기기 → 자동차 → 바이오헬스 → 선박 → 철강 → 이차전지 → 석유제품·석유화학 → 15대 외 품목)
③ 지역별 동향 (대(對)미국 → 대중국 → 대아세안 → 대EU → 대인도 → 대CIS → 대중남미 → 대일본 → 대중동 → 기타). 원문에 언급된 모든 국가·지역을 누락하지 않고 순서대로 포함한다.

[수치 규칙 — 가장 중요]
- 원문에서 언급된 품목·지역에는 반드시 수출액(억 달러)과 증감률(%)을 함께 쓴다.
- 원문에 괄호가 붙어 있으면(예: "바이오 의약품(11.1억 달러, +54.0%)", "중고차 수출(6.7억 달러, +67.9%)", "농수산식품(10.3억 달러, +7.7%)") 그 괄호를 풀지 말고 형식 그대로 포함한다.
- 세부 품목 괄호 수치(예: "하이브리드차(+23.2%)", "스마트폰(+30.0%)", "CMO 수주")도 반드시 포함한다.
- 연속 증감 횟수("N개월 연속"), 역대 순위("역대 X월 중 최대실적"), 누적 실적("1~N월 누적 X억 달러") 정보가 원문에 있으면 반드시 구체적인 수치와 함께 포함한다.
- 품목별 동향과 지역별 동향도 내용의 지나친 생략을 피하고 자세하게 작성한다.
- 총괄·수출 개요의 줄글에 포함된 수치는 빠짐없이 기록한다.
- 지역별 동향에서도 자세한 수치를 최대한 포함해서 기록한다.
[문체]
- 종결: "~하였음", "~기록하였음", "~보였음", "~증가", "~감소", "~경신" 등.
- 연결어: "한편,", "특히,", "아울러", "다만," 등 자연스럽게 사용.
- 증가: "+X.X%" , 감소: "-X.X%".

[금지]
- 주관적 표현("~것으로 보인다", "~전망이다", "~예상된다") 금지.
- 정책 제언("~할 필요가 있다", "~해야 한다") 금지.
- 원문에 없는 수치 생성·추론 금지.
- 본문 내부 줄바꿈 금지.
- 수치·괄호·국가 누락 금지.
"""


EXAMPLE_REPORTS = {
    "250430_2025년 4월 수출입동향_3보.pdf": """(매크로)
- 4월 수출은 전년 동월 대비 +3.7% 증가한 582.1억 달러로 역대 4월 중 최대 실적을 기록하면서 3개월 연속 증가, 수입은 -2.7% 감소한 533.2억 달러, 무역수지는 +48.8억 달러 흑자를 기록하였음. 4월에는 15대 주력 수출품목 중 7개 품목 수출이 증가함. 최대 수출품목인 반도체 수출은 디램 고정가격이 반등한 가운데 역대 4월 중 최대실적인 117억 달러(+17.2%)를 기록. 무선 통신기기 수출도 스마트폰 수출(+61.1%)을 중심으로 +26.5% 증가한 15억 달러를 기록하면서 3개월 연속 증가함. 바이오헬스 수출은 바이오 의약품 수출(+21.8%)이 큰 폭으로 증가하면서 전체적으로는 14억 달러(+14.6%)를 기록하였음. 철강 수출은 +5.4% 증가한 30억 달러로 4개월 만에 플러스로 전환되었으며, 이차전지 수출은 '23.12월부터 16개월간 지속된 마이너스 흐름을 끊고 +13.7% 증가한 7억 달러를 기록. 선박 수출도 +17.3% 증가한 20억 달러를 기록하면서 2개월 연속 증가. 양대 수출품목인 자동차 수출은 소폭 감소(-3.8%)하였으나 올해 들어 가장 높은 실적인 65억 달러를 기록. 15대 주력 수출품목 외에도 글로벌 K-푸드·K-뷰티 선호도 확대에 따라 농수산식품(+8.6%) 수출은 전 기간 중 역대 최대실적, 화장품(+20.8%) 수출은 4월 중 역대 최대실적을 경신. 대중국 수출은 반도체 수출이 반등한 가운데, 무선통신기기 수출이 증가하면서 전체적으로 +3.9% 증가한 109억 달러를 기록. 대아세안 수출은 반도체, 철강 수출 호조세로 +4.5% 증가한 94억 달러를 기록하였으며, 대EU 수출은 자동차, 바이오헬스 수출이 크게 증가하면서 전 기간 역대 최대실적인 67억 달러(+18.4%)를 달성. 대인도 수출은 반도체, 일반기계, 철강 등 수출이 증가세를 보이며 4월 중 최대 실적인 17억 달러(+8.8%)를 기록. 대중남미 수출은 26억 달러(+3.9%)로 플러스로 전환, 대중동 수출은 17억 달러(+1.6%)로 3개월, 대CIS 수출은 12억 달러(+37.2%)로 2개월 연속 증가. 대미국 수출은 106억 달러로 석유제품·이차전지 등 수출 호조세에도 불구 자동차·일반기계 등 양대 수출품목이 감소하면서 전년 동월대비 -6.8% 감소하였으며, 이에 따라 대미국 흑자 규모도 전년 동월 대비 -9억 달러 감소한 45억 달러를 기록.""",

    "250601_2025년 5월 수출입동향_3보.pdf": """(매크로)
- 5월 수출은 전년 동월 대비 -1.3% 감소한 572.7억 달러, 수입은 -5.3% 감소한 503.3억 달러, 무역수지는 +69.4억 달러 흑자를 기록하였음. 조업일을 고려한 일평균 수출은 전년 동월 대비 소폭 증가(+1.0%)한 26.6억 달러로 올해 들어 가장 높은 수준을 기록하였음. 최대 수출품목인 반도체 수출은 고부가 메모리 제품의 견조한 수요와 고정가격도 상승세로 인해 역대 5월 중 최대실적인 138억 달러(+21.2%)를 기록하였음. 무선통신기기 수출은 스마트폰 수출이 호실적을 보이면서 +3.9% 증가하며, 4개월 연속 증가세를 보임. 컴퓨터SSD 수출은 +2.3% 증가한 11억 달러를 기록하면서 플러스로 전환되었음. 바이오헬스 수출(+4.5%)은 바이오 의약품 수출(+13.7%) 증가세에 힘입어 4개월 연속 증가하였으며, 선박 수출도 +4.3% 증가한 22억 달러를 기록하면서 3개월 연속 증가. 자동차 수출은 전년 동월 대비 -4.4% 감소하였음. 석유 수출은 각각 석유제품(-20.9%), 석유화학(-20.8%)를 기록. 트럼프 행정부 출범 이후 저유가 기조가 이어짐에 따라 양 품목 가격이 급락하면서 수출은 -20% 이상 감소. 한편 15대 주력 수출품목 외 호조를 보이고 있는 농수산식품(+5.5%)·화장품(+9.3%) 수출은 5월 중 역대 최대실적을 경신하였으며, 전기기기 수출도 +0.1% 증가하면서 4개월 연속 증가. 대중국 수출은 최대 수출품목인 반도체와 석유화학 수출이 감소하면서 전체적으로 -8.4% 감소한 104억 달러를 기록. 대미국 수출은 -8.1%감소한 100억 달러로 무선통신기기·석유제품·이차전지 호실적에도 불구, 최대수출품목인 자동차 수출 급감으로 감소세를 유지하였음. 대아세안 수출은 반도체 수출 두 자릿수 증가에도 불구, 석유 수출이 급감하면서 -1.3% 감소한 100억 달러를 기록. 대EU 수출은 자동차, 반도체를 중심으로 +4.0% 증가한 60억 달러를 기록, 3개월 연속 증가하였으며, 대CIS 수출도 +34.7% 증가한 12억 달러를 기록하였음.""",

    "250701_2025년 6월 수출입동향_3보_추가수정.pdf": """(매크로)
- 6월 수출은 전년 동월 대비 4.3% 증가한 598.0억 달러, 수입은 3.3% 증가한 507.2억 달러, 무역수지는 90.8억 달러 흑자를 기록하였음. 조업일수를 고려한 일평균 수출도 6.8% 증가한 28.5억 달러로 역대 6월 중 1위 실적을 경신. 최대 수출품목인 반도체 수출은 사상 최대실적인 149.7억 달러(+11.6%)를 기록하면서 4개월 연속 플러스 흐름을 이어감. 컴퓨터SSD 수출은 15.2% 증가한 13.3억 달러로 2개월 연속 증가. 자동차 수출은 63억 달러로 2.3% 증가하면서 역대 6월 중 최대실적을 기록. 특히, 대미 수출 감소에도 불구하고, 대EU 수출이 전기차를 중심으로 호조세를 보이는 가운데, 중고차 수출(+67.9%)도 크게 증가하면서 역대 최초로 5개월 연속 60억 달러 이상을 기록하였음. 바이오헬스 수출은 바이오 의약품(11.1억 달러, +54.0%)을 중심으로 36.5% 증가한 16.6억 달러로 6월 중 역대 최대실적을 달성. 선박 수출도 63.4% 증가한 25.0억 달러를 기록하면서 4개월 연속 증가. 한편, 석유제품(36.2억 달러, -2.0%)과 석유화학(33.6억 달러, -15.5%) 수출은 제품가격이 연동되는 유가가 약세를 보이면서 감소 흐름을 지속. 15대 주력 품목 외에도 농수산식품(10.3억 달러, +7.7%)·화장품(9.5억 달러, +22.0%) 및 전기기기(15.8억 달러, +14.8%) 수출은 역대 6월 중 최대실적을 기록, 2월부터 5개월 연속 해당 월 기준 1위 실적을 경신. 양대 수출시장인 대미국 수출(112.4억 달러, -0.5%)은 보합세, 대중국 수출(104.2억 달러, -2.7%)은 소폭 감소세 보였음. 대아세안 수출은 반도체·선박·철강제품을 중심으로 2.1% 증가한 97.6억 달러로 1개월 만에 플러스로 전환되었음. 대EU 수출은 자동차·차부품, 선박, 석유제품 수출이 증가하면서 14.7% 증가한 58.0억 달러를 기록, 4개월 연속 플러스를 기록. 한편, 대인도 수출은 2.3% 증가한 15.9억 달러를 기록, 역대 6월 중 최대실적을 기록하였으며, 대CIS 수출은 18.5% 증가한 11.0억 달러로 4개월 연속 증가. 아울러 중남미(+3.3%), 일본(+3.0%), 중동(+14.8%)으로의 수출도 플러스로 전환되었음.""",
}


#  크롤링

def create_driver(download_dir: str = None):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    if download_dir:
        abs_dir = os.path.abspath(download_dir)
        os.makedirs(abs_dir, exist_ok=True)
        prefs = {
            "download.default_directory": abs_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
            "safebrowsing.enabled": True,
        }
        options.add_experimental_option("prefs", prefs)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(5)
    if download_dir:
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": os.path.abspath(download_dir),
        })
    return driver


def navigate_to_article(driver, title: str) -> bool:
    for page in range(1, MAX_PAGES + 1):
        url = LIST_URL.format(page=page)
        print(f"  목록 페이지 {page} 검색 중...")
        driver.get(url)
        time.sleep(3)

        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            try:
                text = link.text.strip()
                if title in text:
                    print(f"  ✅ 게시글 발견: {text}")
                    print(f"  ✅ 클릭하여 상세 페이지 진입...")
                    driver.execute_script("arguments[0].click();", link)
                    time.sleep(3)
                    print(f"     현재 URL: {driver.current_url}")
                    return True
            except:
                continue

    print(f"  ❌ '{title}' 제목의 게시글을 찾지 못했습니다.")
    return False


def extract_filename(text: str) -> str:
    m = re.match(r'^(.+?\.(pdf|hwp|hwpx|xlsx?|docx?|zip))', text.strip(), re.I)
    if m:
        return m.group(1).strip()
    return re.split(r'\s*\[', text)[0].strip()


def wait_for_download(save_dir: str, before: set, expected_name: str, timeout: int = 40) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        current = set(os.listdir(save_dir))
        new_files = current - before
        done = [f for f in new_files if not f.endswith(".crdownload")]
        if done:
            actual = os.path.join(save_dir, done[0])
            expected = os.path.join(save_dir, expected_name)
            if actual != expected:
                try:
                    os.rename(actual, expected)
                    return expected
                except Exception:
                    return actual
            return actual
    return None


def download_all_attachments(driver, save_dir: str) -> list:
    print(f"\n  상세 페이지에서 첨부파일 탐색 중...")
    time.sleep(2)
    os.makedirs(save_dir, exist_ok=True)

    detail_url = driver.current_url

    # ★ 수정: onclick 대신 href에서 /attach/down/ 경로 추출
    # 실제 구조: href="javascript:location.href='/attach/down/...'"
    pdf_link_infos = []
    for link in driver.find_elements(By.TAG_NAME, "a"):
        try:
            text = link.text.strip()
            href = link.get_attribute("href") or ""

            # PDF 텍스트가 있고 href에 /attach/down/ 이 포함된 링크 탐지
            m = re.search(r"/attach/down/[\w/]+", href)
            if re.search(r'\.pdf', text, re.I) and m:
                filename  = extract_filename(text)
                down_path = m.group(0)
                down_url  = BASE_URL + down_path
                pdf_link_infos.append({
                    "filename": filename,
                    "down_url": down_url,
                })
                print(f"  📎 PDF 발견: {filename}")
                print(f"     다운로드 URL: {down_url}")
        except Exception:
            continue

    if not pdf_link_infos:
        print("  ❌ PDF 다운로드 링크를 찾지 못했습니다.")
        return []

    print(f"\n  총 {len(pdf_link_infos)}개 PDF 다운로드 시작")
    downloaded = []

    for info in pdf_link_infos:
        filename = info["filename"]
        down_url = info["down_url"]
        print(f"\n  📥 다운로드 중: {filename}")

        # 상세 페이지 복귀 후 링크 재탐색하여 클릭
        if driver.current_url != detail_url:
            driver.get(detail_url)
            time.sleep(2)

        before = set(os.listdir(save_dir))

        # ★ 수정: href 기준으로 일치하는 링크 요소를 찾아 클릭
        clicked = False
        for link in driver.find_elements(By.TAG_NAME, "a"):
            try:
                link_href = link.get_attribute("href") or ""
                link_text = link.text.strip()
                if down_url.replace(BASE_URL, "") in link_href and re.search(r'\.pdf', link_text, re.I):
                    driver.execute_script("arguments[0].click();", link)
                    clicked = True
                    print(f"     링크 클릭 완료")
                    break
            except Exception:
                continue

        if not clicked:
            print(f"  ❌ 클릭할 링크를 찾지 못함: {filename}")
            continue

        time.sleep(1)

        # 새 탭이 열렸으면 닫고 복귀
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            time.sleep(1)
            driver.close()
            driver.switch_to.window(driver.window_handles[0])

        save_path = wait_for_download(save_dir, before, filename)
        if save_path:
            size = os.path.getsize(save_path)
            with open(save_path, "rb") as f:
                header = f.read(50)
            if size < 50_000 and (b"<!DOCTYPE" in header or b"<html" in header):
                print(f"  ❌ HTML 위장 파일 ({size/1024:.1f} KB) — 삭제")
                os.remove(save_path)
                continue
            print(f"  ✅ 저장 완료: {save_path} ({size/1024:.1f} KB)")
            downloaded.append(save_path)
        else:
            print(f"  ❌ 다운로드 타임아웃: {filename}")

    return downloaded


def crawl_and_get_pdf(title: str, save_dir: str) -> list:
    print(f"\n[크롤링] '{title}'")
    print("-" * 50)

    driver = create_driver(download_dir=save_dir)
    pdf_paths = []
    try:
        if navigate_to_article(driver, title):
            all_files = download_all_attachments(driver, save_dir)

            pdf_files = [f for f in all_files if f.lower().endswith(".pdf")]

            for f in all_files:
                if f in pdf_files:
                    print(f"  📄 PDF 파일 선택: {os.path.basename(f)}")
                else:
                    print(f"  ⏭️ PDF 아님 (건너뜀): {os.path.basename(f)}")

            pdf_paths = pdf_files

    finally:
        driver.quit()
        print("  브라우저 종료")

    return pdf_paths


# 보고서 생성

def extract_text_from_hwpx(hwpx_path: str) -> str:
    text_parts = []
    try:
        with zipfile.ZipFile(hwpx_path, 'r') as z:
            section_files = sorted([
                name for name in z.namelist()
                if re.match(r'Contents/section\d+\.xml', name)
            ])
            if not section_files:
                return ""
            for section_file in section_files:
                with z.open(section_file) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    for elem in root.iter():
                        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        if tag == 't' and elem.text:
                            text_parts.append(elem.text)
    except Exception as e:
        print(f"  ⚠️ hwpx 텍스트 추출 실패: {e}")
        return ""
    return "\n".join(text_parts)


def load_pdf_text(pdf_path: str) -> str:
    try:
        import fitz
    except ImportError:
        raise ImportError("pip install PyMuPDF 필요")
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def generate_report(new_pdf_path: str) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    loaded = 0
    for pdf_filename, report_text in EXAMPLE_REPORTS.items():
        pdf_path = os.path.join(TRAINING_PDF_DIR, pdf_filename)
        if not os.path.exists(pdf_path):
            print(f"  ⚠️ 예시 PDF 없음: {pdf_path}")
            continue
        pdf_text = load_pdf_text(pdf_path)[:8000]
        if not pdf_text:
            continue
        messages.append({
            "role": "user",
            "content": f"다음 수출입 동향 보도자료 원문을 읽고, 동일한 형식의 요약 보고서를 작성하세요.\n\n[원문]\n{pdf_text}"
        })
        messages.append({
            "role": "assistant",
            "content": report_text
        })
        loaded += 1

    print(f"  예시 {loaded}개 로드 완료")

    print(f"  PDF 텍스트 추출 중...")
    pdf_text = load_pdf_text(new_pdf_path)

    if not pdf_text.strip():
        raise ValueError(f"텍스트 추출 실패 또는 내용 없음: {new_pdf_path}")

    print(f"  추출 완료 ({len(pdf_text):,}자)")

    messages.append({
        "role": "user",
        "content": f"다음 수출입 동향 보도자료 원문을 읽고, 동일한 형식의 요약 보고서를 작성하세요.\n\n[원문]\n{pdf_text[:20000]}"
    })

    print(f"  GPT 호출 중 (model={MODEL})...")
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )

    report = response.choices[0].message.content
    usage = response.usage
    print(f"  토큰: input={usage.prompt_tokens:,} / output={usage.completion_tokens:,} / total={usage.total_tokens:,}")
    return report


def main():
    print("=" * 60)
    print("  수출입 동향 보고서 자동 생성 파이프라인")
    print(f"  크롤링 대상: {SEARCH_TITLE}")
    print("=" * 60)

    if OPENAI_API_KEY.startswith("sk-xxx"):
        print("\n⚠️  OPENAI_API_KEY를 설정하세요")
        return None

    print("\n" + "=" * 60)
    print("  [Step 1] PDF 파일 크롤링")
    print("=" * 60)

    os.makedirs(INPUT_HWPX_DIR, exist_ok=True)
    pdf_paths = crawl_and_get_pdf(SEARCH_TITLE, INPUT_HWPX_DIR)

    if not pdf_paths:
        print("\n⚠️ 크롤링된 PDF 파일이 없습니다.")
        existing = [
            os.path.join(INPUT_HWPX_DIR, f)
            for f in os.listdir(INPUT_HWPX_DIR)
            if f.lower().endswith(".pdf")
        ]
        if existing:
            print(f"  → 기존 PDF 파일 {len(existing)}개 발견, 이를 사용합니다.")
            pdf_paths = existing
        else:
            return None

    print("\n" + "=" * 60)
    print("  [Step 2] 보고서 생성")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    final_report = None

    for pdf_path in pdf_paths:
        pdf_name = os.path.basename(pdf_path)
        print(f"\n[처리 중] {pdf_name}")
        print("-" * 40)

        try:
            report = generate_report(pdf_path)
            final_report = report

            output_name = re.sub(r'\.pdf$', '', pdf_name, flags=re.I) + "_보고서.txt"
            output_path = os.path.join(OUTPUT_DIR, output_name)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)

            print(f"\n[생성된 보고서]")
            print(report)
            print(f"\n✅ 저장: {output_path}")

        except Exception as e:
            print(f"❌ 오류: {e}")

    print("\n" + "=" * 60)
    print("  파이프라인 완료")
    print("=" * 60)
    
    return final_report


if __name__ == "__main__":
    main()


#python BOT/api_수출입.py