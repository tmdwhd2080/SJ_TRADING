"""
산업활동동향 보고서 크롤링 봇 (기획재정부)
pip install openai PyMuPDF selenium webdriver-manager requests
"""

import os
import re
import time
import zipfile
import openai
from xml.etree import ElementTree as ET
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ════════════════════════════════════════════════════════════════
# config.py에서 설정 import
# ════════════════════════════════════════════════════════════════

try:
    from config import INDUSTRY_CONFIG
    SEARCH_TITLE = INDUSTRY_CONFIG['search_title']
    OPENAI_API_KEY = INDUSTRY_CONFIG['openai_api_key']
    MODEL = INDUSTRY_CONFIG['model']
    TEMPERATURE = INDUSTRY_CONFIG['temperature']
    MAX_TOKENS = INDUSTRY_CONFIG['max_tokens']
    TRAINING_PDF_DIR = INDUSTRY_CONFIG['training_dir']
    INPUT_DIR = INDUSTRY_CONFIG['input_dir']
    OUTPUT_DIR = INDUSTRY_CONFIG['output_dir']
    BASE_URL = INDUSTRY_CONFIG['base_url']
    MAX_PAGES = INDUSTRY_CONFIG['max_pages']
except ImportError:
    # config.py가 없을 경우 기본값 사용
    SEARCH_TITLE = "'26.2월 산업활동동향 및 평가"
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    MODEL = "gpt-4o"
    TEMPERATURE = 0.1
    MAX_TOKENS = 4000
    TRAINING_PDF_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_train"
    INPUT_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_test"
    OUTPUT_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_output"
    BASE_URL = "https://mofe.go.kr"
    MAX_PAGES = 50

LIST_URL = (
    f"{BASE_URL}/nw/nes/nesdta.do"
    f"?searchBbsId1=MOSFBBS_000000000028&menuNo=4010100&pageIndex={{page}}"
)

client = openai.OpenAI(api_key=OPENAI_API_KEY)


# system prompt

SYSTEM_PROMPT = """당신은 기획재정부 산업활동동향 보도자료 원문을 읽고 간결한 요약 보고서를 작성하는 전문 분석관입니다.

[형식]
- 처음 시작은 "- "를 붙이고 본문 시작.
- 본문은 줄바꿈 없이 하나의 문단. 문장 사이는 마침표 + 공백.
- 제목·머리말·번호 매기기 금지.

[본문 구성 순서 — 아래 6개 항목을 반드시 이 순서대로 모두 포함한다]

① 산업활동동향 (전산업생산 총괄 + 생산 부문)
   - "N월 산업활동동향은 전산업생산(전기비 X%)"으로 시작.
   - 광공업 전기비 수치 및 주요 업종(반도체·자동차 등) 세부 내용 및 구체적 수치 반드시 포함.
   - 서비스업 전기비 구체적 수치 및 주요 업종 증감 내용.
   - 연속 증감 횟수("N개월 연속") 또는 "N개월만에 증가/감소 전환" 정보가 있으면 반드시 포함.
   - "전월 대비"와 이와 관련된 구체적 수치 반드시 포함.
   - '()' 내부에 존재하는 구체적 수치 반드시 포함.

② 소매판매
   - 전기비 수치 및 내구재·준내구재·비내구재 각각의 수치를 반드시 포함.
   - 형식 예: "소매판매는 내구재(X%), 준내구재(X%), 비내구재(X%) ~ 증가/감소/보합(X%)."

③ 설비투자
   - 전기비 수치 및 기계류·운송장비 증감 내용 포함.
   - 형식 예: "설비투자는 기계류(X%)·운송장비(X%) ~ 감소/증가(X%)."

④ 국내기계수주
   - 전년동월대비 수치 및 공공·민간 각각의 수치를 반드시 포함.
   - 형식 예: "국내기계수주는 공공(X%)·민간(X%) ~ 증가/감소(X%)."

⑤ 건설기성
   - 전기비 수치 및 건축·토목 증감 내용 포함.
   - 형식 예: "건설기성은 건축(X%)·토목(X%) ~ 감소/증가(X%)."

⑥ 선행지수
   - 동행지수 순환변동치 및 선행지수 순환변동치의 전월 대비 증감 포함.
   - 형식 예: "동행지수 순환변동치는 X.X(전월비 +X.Xp), 선행지수 순환변동치는 X.X(전월비 +X.Xp)."

[수치 규칙 — 가장 중요]
- 전기비(전월비) 수치를 반드시 괄호 안에 표기: (전기비 X%), (+X%), (-X%) 형식.
- 모든 항목의 세부 항목(내구재·준내구재·비내구재, 공공·민간, 건축·토목 등) 수치는 반드시 모두 포함.
- 동행·선행지수 순환변동치 수치 및 전월 대비 증감(%p)은 반드시 포함.
- 원문에 없는 수치 생성·추론 금지.

[문체]
- 종결: "~감소.", "~증가.", "~전환.", "~지속." 등 간결하게.
- 연결어: "한편,", "특히,", "다만," 등 자연스럽게 사용.
- 증가: "+X%" 또는 "X% 증가". 감소: "-X%".

[금지]
- 원문에 없는 수치 생성·추론 금지.
- 본문 내부 줄바꿈 금지.
- 6개 항목 중 하나라도 누락 금지.
"""

# training set

EXAMPLE_REPORTS = {
    "(보도자료) 4월 산업활동동향_배포.pdf": """
- 4월 산업활동동향은 전산업생산(전기비 -0.8%)은 2개월 연속 큰 폭 증가했던 기저효과로 광공업(-0.9%)과 서비스업(-0.1%) 생산 모두 줄며 3개월만에 감소. 생산 중 광공업은 자동차 관세 부과 영향, 전월 반도체 생산 큰 폭 증가에 따른 기저효과 등으로 감소전환. 서비스업은 도소매업·숙박음식점업 생산이 증가했으나, 주식거래·건축설계 수주 줄며 금융·보험, 전문·과학·기술업 중심 감소. 소매판매는 내구재(-1.4%), 준내구재(-2.0%) 및 비내구재(-0.3%) 판매가 모두 줄면서 감소(-0.9%). 설비투자는 자동차·항공기 등 운송장비 증가에도 반도체제조용기계 등 기계류가 줄며 소폭 감소(-0.4%). 국내기계수주는 공공(-X.X%)·민간(-X.X%) 수주가 모두 줄며 감소(전년동월대비 -X.X%). 건설기성은 토목이 늘었으나, 건축이 줄며 소폭 감소(-0.7%). 동행지수 순환변동치는 98.9(전월비 +0.2p), 선행지수 순환변동치는 100.9(전월비 +0.3p)로 3개월 연속 상승.""",

    "250630 (보도자료) 5월 산업활동동향_배포.pdf": """
- 5월 산업활동동향은 전산업생산(전기비 -0.8%)은 광공업(-2.9%)과 서비스업(-0.1%) 생산이 줄면서 2개월 연속 감소. 생산 중 광공업은 금속·석유정제 증가에도 내수 출하 감소, 3월 큰 폭 증가했던 의약품·반도체 조정 등으로 큰 폭 감소. 서비스업은 금융·보험은 늘었으나, 도소매 및 숙박·음식 줄면서 감소. 소매판매는 내구재(+1.2%), 준내구재(+0.7%) 증가에도 비내구재(-0.7%) 판매가 줄면서 보합(0.0%). 설비투자는 항공기, 선박 등 운송장비 증가에도 반도체제조용기계 등 기계류가 줄며 감소(-4.7%). 국내기계수주는 공공(-X.X%)·민간(-X.X%) 수주가 모두 줄며 감소(전년동월대비 -X.X%). 건설기성은 건축·토목 전월대비 줄며 감소(-3.9%). 동행지수 순환변동치는 98.5(전월비 -0.4p), 선행지수 순환변동치는 100.9(전월비 -0.1p)로 동반 하락.""",

    "(보도자료) 6월 및 2분기 산업활동동향_배포.pdf": """
- 6월 산업활동동향은 전산업생산(전기비 +0.8%)은 광공업(+1.6%) 및 서비스업(+1.8%), 공공행정(+1.5%) 생산이 모두 늘면서 3개월만에 증가. 생산 중 광공업은 전자부품 생산 큰 폭 감소에도 반도체 업황 호조, 자동차 실적 개선 등으로 3개월만에 증가 전환. 서비스업은 도·소매, 금융·보험, 전문·과학·기술 등 늘면서 증가. 소매판매는 내구재(-1.6%)는 감소했으나, 준내구재(+4.1%), 비내구재(+0.3%) 판매가 늘면서 증가(+0.5%). 설비투자는 반도체제조용기계 등 기계류가 늘었으나, 항공기, 선박 등 운송장비가 줄며 감소(-3.7%). 국내기계수주는 공공(-X.X%)·민간(-X.X%) 수주가 모두 줄며 감소(전년동월대비 -X.X%). 건설기성은 토목 감소에도 건축이 크게 늘며 증가 전환(+6.7%). 동행지수 순환변동치는 98.4(전월비 -0.1p), 선행지수 순환변동치는 101.2(전월비 +0.2p)로 선행지수만 상승.""",
}


# 크롤링
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

        for link in driver.find_elements(By.TAG_NAME, "a"):
            try:
                text = link.text.strip()
                if title in text:
                    print(f"  ✅ 게시글 발견: {text}")
                    driver.execute_script("arguments[0].click();", link)
                    time.sleep(3)
                    print(f"     현재 URL: {driver.current_url}")
                    return True
            except Exception:
                continue

    print(f"  ❌ '{title}' 제목의 게시글을 찾지 못했습니다.")
    return False


def extract_filename(text: str) -> str:
    m = re.match(r'^(.+?\.(pdf|hwp|hwpx|xlsx?|docx?|zip))', text.strip(), re.I)
    if m:
        return m.group(1).strip()
    return re.split(r'\s*[\[\(]', text)[0].strip()


def wait_for_download(save_dir: str, before: set, expected_name: str, timeout: int = 60) -> str:
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
    """
    mofe.go.kr 첨부파일 다운로드.
    """
    print(f"\n  상세 페이지에서 첨부파일 탐색 중...")
    time.sleep(2)
    os.makedirs(save_dir, exist_ok=True)

    try:
        toggle = driver.find_element(
            By.CSS_SELECTOR,
            "a.file_list_btn, button.file_list_btn, .attach_file_btn, [class*='file'][class*='btn']"
        )
        driver.execute_script("arguments[0].click();", toggle)
        time.sleep(1)
        print("  📂 첨부파일 영역 펼침")
    except Exception:
        pass  

    file_pairs = []   
    seen_urls = set()

    for link in driver.find_elements(By.TAG_NAME, "a"):
        try:
            text = link.text.strip()
            href = link.get_attribute("href") or ""
            if (re.search(r'\.(hwpx?|pdf)', text, re.I)
                    and re.search(r'FileDown|atchFileId|download', href, re.I)):

                filename = extract_filename(text)
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                file_pairs.append((filename, href))
                print(f"  📎 파일 감지: {filename}")
                print(f"     URL: {href}")

        except Exception:
            continue

    if not file_pairs:
        pending_name = None
        for link in driver.find_elements(By.TAG_NAME, "a"):
            try:
                text = link.text.strip()
                href = link.get_attribute("href") or ""

                if re.search(r'\.(hwpx?|pdf)', text, re.I):
                    pending_name = extract_filename(text)

                elif re.search(r'^다운로드$', text) and pending_name:
                    if href and href not in seen_urls:
                        seen_urls.add(href)
                        file_pairs.append((pending_name, href))
                        print(f"  📎 fallback 파일: {pending_name}")
                        print(f"     URL: {href}")
                    pending_name = None

            except Exception:
                continue


    if not file_pairs:
        print("  ❌ 다운로드 링크를 찾지 못했습니다. 진단 정보:")
        for link in driver.find_elements(By.TAG_NAME, "a"):
            try:
                t = link.text.strip()
                h = link.get_attribute("href") or ""
                if any(x in (t + h).lower() for x in
                       ["hwp", "pdf", "filedown", "atchfileid", "다운", "attach"]):
                    print(f"    text='{t[:60]}' href='{h[:100]}'")
            except Exception:
                pass
        return []

    print(f"\n  총 {len(file_pairs)}개 파일 다운로드 시작")
    downloaded = []

    for filename, down_url in file_pairs:
        print(f"\n  📥 다운로드: {filename}")
        before = set(os.listdir(save_dir))

        driver.get(down_url)
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
            print(f"  ✅ 저장: {save_path} ({size/1024:.1f} KB)")
            downloaded.append(save_path)
        else:
            print(f"  ❌ 타임아웃: {filename}")

    return downloaded


def crawl_and_get_files(title: str, save_dir: str) -> list:
    """크롤링 → 모든 첨부파일 다운로드 → 파일 경로 리스트 반환"""
    print(f"\n[크롤링] '{title}'")
    print("-" * 50)

    driver = create_driver(download_dir=save_dir)
    file_paths = []
    try:
        if navigate_to_article(driver, title):
            all_files = download_all_attachments(driver, save_dir)

            for f in all_files:
                ext = os.path.splitext(f)[1].lower()
                if ext in (".pdf", ".hwpx", ".hwp"):
                    print(f"  📄 선택: {os.path.basename(f)}")
                    file_paths.append(f)
                else:
                    print(f"  ⏭️ 건너뜀 ({ext}): {os.path.basename(f)}")

    finally:
        driver.quit()
        print("  브라우저 종료")

    return file_paths


# 보고서 작성

def extract_text_from_hwpx(hwpx_path: str) -> str:
    """hwpx(ZIP+XML) 파일에서 텍스트 추출"""
    text_parts = []
    try:
        with zipfile.ZipFile(hwpx_path, "r") as z:
            section_files = sorted([
                name for name in z.namelist()
                if re.match(r"Contents/section\d+\.xml", name)
            ])
            if not section_files:
                return ""
            for section_file in section_files:
                with z.open(section_file) as f:
                    root = ET.parse(f).getroot()
                    for elem in root.iter():
                        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if tag == "t" and elem.text:
                            text_parts.append(elem.text)
    except Exception as e:
        print(f"  ⚠️ hwpx 텍스트 추출 실패: {e}")
        return ""
    return "\n".join(text_parts)


def load_file_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            import fitz
        except ImportError:
            raise ImportError("pip install PyMuPDF 필요")
        doc = fitz.open(file_path)
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text
    elif ext in (".hwpx", ".hwp"):
        return extract_text_from_hwpx(file_path)
    else:
        print(f"  ⚠️ 지원하지 않는 형식: {ext}")
        return ""


def generate_report(new_file_path: str) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    #  trainig set 사용 
    loaded = 0
    for pdf_filename, report_text in EXAMPLE_REPORTS.items():
        pdf_path = os.path.join(TRAINING_PDF_DIR, pdf_filename)
        if not os.path.exists(pdf_path):
            print(f"  ⚠️ 예시 파일 없음: {pdf_path}")
            continue
        file_text = load_file_text(pdf_path)[:8000]
        if not file_text.strip():
            continue
        messages.append({
            "role": "user",
            "content": (
                "다음 산업활동동향 보도자료 원문을 읽고 요약 보고서를 작성하세요.\n\n"
                f"[원문]\n{file_text}"
            )
        })
        messages.append({
            "role": "assistant",
            "content": report_text
        })
        loaded += 1

    print(f"  예시 {loaded}개 로드 완료")

    print(f"  파일 텍스트 추출 중: {os.path.basename(new_file_path)}")
    new_text = load_file_text(new_file_path)

    if not new_text.strip():
        raise ValueError(f"텍스트 추출 실패 또는 내용 없음: {new_file_path}")

    print(f"  추출 완료 ({len(new_text):,}자)")

    messages.append({
        "role": "user",
        "content": (
            "다음 산업활동동향 보도자료 원문을 읽고 요약 보고서를 작성하세요.\n\n"
            f"[원문]\n{new_text[:20000]}"
        )
    })

    print(f"  GPT 호출 중 (model={MODEL})...")
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )

    report = response.choices[0].message.content
    usage  = response.usage
    print(f"  토큰: input={usage.prompt_tokens:,} / output={usage.completion_tokens:,} / total={usage.total_tokens:,}")
    return report



def main():
    print("=" * 60)
    print("  산업활동동향 보고서 자동 생성 파이프라인")
    print(f"  크롤링 대상: {SEARCH_TITLE}")
    print("=" * 60)

    print("\n" + "=" * 60)
    print("  [Step 1] 파일 크롤링")
    print("=" * 60)

    os.makedirs(INPUT_DIR, exist_ok=True)
    file_paths = crawl_and_get_files(SEARCH_TITLE, INPUT_DIR)

    if not file_paths:
        print("\n⚠️ 크롤링된 파일이 없습니다.")
        existing = [
            os.path.join(INPUT_DIR, f)
            for f in os.listdir(INPUT_DIR)
            if os.path.splitext(f)[1].lower() in (".pdf", ".hwpx", ".hwp")
        ]
        if existing:
            print(f"  → 기존 파일 {len(existing)}개 발견, 이를 사용합니다.")
            file_paths = existing
        else:
            print("  ❌ 데이터 없음. 종료.")
            return None

    print("\n" + "=" * 60)
    print("  [Step 2] 보고서 생성")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    final_report = None

    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        print(f"\n[처리 중] {file_name}")
        print("-" * 40)

        try:
            report = generate_report(file_path)
            final_report = report

            safe_name = re.sub(r'\.[^.]+$', '', file_name)
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', safe_name)
            output_path = os.path.join(OUTPUT_DIR, f"{safe_name}_보고서.txt")

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

# python BOT/api_산업활동동향.py