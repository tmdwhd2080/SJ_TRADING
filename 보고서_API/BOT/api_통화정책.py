"""
한국은행 통화정책방향 결정문 크롤링 & 보고서 생성 봇
pip install openai PyMuPDF selenium webdriver-manager
"""

import os
import re
import time
import openai
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager

# ════════════════════════════════════════════════════════════════
# config.py에서 설정 import
# ════════════════════════════════════════════════════════════════

try:
    from 보고서_API.BOT.config import MONETARY_POLICY_CONFIG
    SEARCH_YEAR = MONETARY_POLICY_CONFIG['search_year']
    SEARCH_MONTH = MONETARY_POLICY_CONFIG['search_month']
    OPENAI_API_KEY = MONETARY_POLICY_CONFIG['openai_api_key']
    MODEL = MONETARY_POLICY_CONFIG['model']
    TEMPERATURE = MONETARY_POLICY_CONFIG['temperature']
    MAX_TOKENS = MONETARY_POLICY_CONFIG['max_tokens']
    TRAINING_PDF_DIR = MONETARY_POLICY_CONFIG['training_dir']
    INPUT_PDF_DIR = MONETARY_POLICY_CONFIG['input_dir']
    OUTPUT_DIR = MONETARY_POLICY_CONFIG['output_dir']
    BOK_LIST_URL = MONETARY_POLICY_CONFIG['bok_list_url']
except ImportError:
    # config.py가 없을 경우 기본값 사용
    SEARCH_YEAR = 2026
    SEARCH_MONTH = 3
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    MODEL = "gpt-4o"
    TEMPERATURE = 0.1
    MAX_TOKENS = 4000
    TRAINING_PDF_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_train"
    INPUT_PDF_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_test"
    OUTPUT_DIR = r"C:\Users\intern9\truston_quant_dev\pdf_output"
    BOK_LIST_URL = (
        "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do"
        "?mtgSe=A&menuNo=200755"
    )

client = openai.OpenAI(api_key=OPENAI_API_KEY)


# 시스템 프롬프트
SYSTEM_PROMPT = """당신은 한국은행 금융통화위원회 통화정책방향 결정문을 읽고 요약 보고서를 작성하는 전문 분석관입니다.

[형식]
- "- "로 시작하는 하나의 문단.
- 본문은 줄바꿈 없이 하나의 문단. 문장 사이는 마침표 + 공백.
- 제목·머리말·번호 매기기 금지.

[본문 구성 순서]
1. 기준금리 결정 사항: 인하·인상·유지 여부, 변경 폭(%p), 새 금리 수준(%)
2. 결정 배경(아래 하위 요소의 내용과 구체적 수치를 반드시 포함하여 작성) 
    1) 성장·물가 전망
    2) 국내 경제 
    3)대내외 여건 
3. 금융안정 관련 언급: 가계부채, 환율, 금융 및 외환 시장과 관련된 내용 및 수치 반드시 포함
4. 향후 통화정책 방향

[수치 규칙]
- 기준금리(%), 변동폭(%p), 성장률 전망치(%) 등 원문의 모든 수치 포함
- 원문에 없는 수치 생성·추론 금지

[문체]
- 종결: "~하였음", "~밝힘", "~판단하였음" 등
- 본문 내부 줄바꿈 금지
"""

# training set
EXAMPLE_REPORTS = {

    "국문보도자료(2505).pdf": (
        "- 금융통화위원회는 다음 통화정책방향 결정시까지 한국은행 기준금리를 2.75%에서 2.50%로 "
        "0.25%p 하향 조정하여 통화정책을 운용하기로 하였음. 물가상승률이 안정적인 흐름을 이어가는 "
        "가운데 금년 중 성장률이 크게 낮아질 것으로 전망되며 향후 성장경로의 불확실성도 높은 상황. "
        "금융안정 측면에서는 금융완화 기조 지속에 따른 가계부채 증가세 확대 가능성과 외환시장의 "
        "높은 변동성에 유의할 필요가 있다고 밝힘."
    ),

    "국문보도자료(2507).pdf": (
        "- 금융통화위원회는 다음 통화정책방향 결정시까지 한국은행 기준금리를 현재의 2.50% 수준에서 "
        "유지하여 통화정책을 운용하기로 하였음. 물가상승률이 안정적 흐름을 이어가는 가운데 당분간 "
        "낮은 성장세가 이어질 것으로 예상되며 무역협상 등과 관련한 불확실성이 큰 상황. "
        "금융안정 측면에서는 수도권 주택시장 및 가계부채 리스크가 증대된 만큼 거시건전성정책의 "
        "효과를 점검하는 한편, 외환시장의 변동성 확대 가능성에도 계속 유의할 필요가 있다고 밝힘."
    ),

    "국문보도자료(2508).pdf": (
        "- 금융통화위원회는 다음 통화정책방향 결정시까지 한국은행 기준금리를 현재의 2.50% 수준에서 "
        "유지하여 통화정책을 운용하기로 하였음. 물가상승률이 안정적인 흐름을 이어가는 가운데 "
        "성장세가 다소 개선되었지만 미 관세정책의 영향 등으로 향후 성장경로의 불확실성은 높은 상황. "
        "금융안정 측면에서는 수도권 주택가격 상승세와 가계부채 증가세가 둔화되었지만 추세적으로 "
        "안정될지를 좀 더 점검하는 한편 환율 변동성의 확대 가능성에도 계속 유의할 필요가 있다고 밝힘."
    ),

    "국문보도자료(2510).pdf": (
        "- 금융통화위원회는 다음 통화정책방향 결정시까지 한국은행 기준금리를 현재의 2.50% 수준에서 "
        "유지하여 통화정책을 운용하기로 하였음. 물가가 안정적인 흐름을 지속하는 가운데 성장은 "
        "개선세를 이어가고 있지만 무역협상, 반도체 경기 전망 등과 관련한 불확실성이 확대. "
        "금융안정 측면에서는 정부의 추가 부동산 대책의 효과를 점검하는 한편, 높은 환율 변동성의 "
        "영향에도 유의할 필요가 있다고 밝힘."
    ),
}


# 크롤링
def create_driver(download_dir: str):
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
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": abs_dir,
    })
    return driver


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()


def cell_full_text(cell) -> str:
    """textContent로 CSS 숨김 요소 포함 전체 텍스트 반환"""
    return normalize(cell.get_attribute("textContent") or "")


def wait_for_download(save_dir: str, before: set, timeout: int = 60) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        current = set(os.listdir(save_dir))
        done = [f for f in (current - before) if not f.endswith(".crdownload")]
        if done:
            return os.path.join(save_dir, sorted(done)[0])
    return None

# pdf 다운로드
def crawl_bok_decision(year: int, month: int, save_dir: str) -> list:

    yymm = f"{str(year)[-2:]}{month:02d}"          # 예: 2025년 10월 → "2510"
    target_filename = f"국문보도자료({yymm}).pdf"
    target_re = re.compile(re.escape(target_filename), re.I)

    print(f"\n[크롤링] {year}년 {month}월  (탐색 파일명: {target_filename})")
    print("-" * 50)

    os.makedirs(save_dir, exist_ok=True)
    driver = create_driver(save_dir)
    pdf_paths = []

    try:
        
        print(f"  URL: {BOK_LIST_URL}")
        driver.get(BOK_LIST_URL)
        time.sleep(4)

        # 연도 선택 및 이동 버튼 클릭
        
        try:
            sel = Select(driver.find_element(By.CSS_SELECTOR, "select"))
            sel.select_by_value(str(year))
            print(f"  연도 {year} 선택 완료, 이동 버튼 클릭...")
            move_btn = None
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                if "이동" in (btn.text or ""):
                    move_btn = btn
                    break
            if move_btn is None:
                for el in driver.find_elements(By.CSS_SELECTOR,
                                               "input[type=submit], input[type=button], a"):
                    if "이동" in (el.get_attribute("value") or el.text or ""):
                        move_btn = el
                        break

            if move_btn:
                driver.execute_script("arguments[0].click();", move_btn)
                print(f"  이동 버튼 클릭 완료")
            else:
                print(f"  ⚠️ 이동 버튼 미발견 → URL pYear 파라미터로 직접 접근")
                driver.get(f"{BOK_LIST_URL}&pYear={year}")

            time.sleep(4)

        except Exception as e:
            print(f"  ⚠️ 연도 선택 실패: {e}")
            driver.get(f"{BOK_LIST_URL}&pYear={year}")
            time.sleep(4)

        # 파일명 패턴으로 결정문 셀 찾기 
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        print(f"  총 {len(rows)}개 행에서 '{target_filename}' 탐색 중...")

        target_cell = None
        for row_idx, row in enumerate(rows):
            cells = row.find_elements(By.TAG_NAME, "td")
            for col_idx, cell in enumerate(cells):
                text = cell_full_text(cell)
                if target_re.search(text):
                    print(f"  ✅ 발견! row={row_idx}, col={col_idx}")
                    print(f"     셀 내용: {text[:100]}")
                    target_cell = cell
                    break
            if target_cell:
                break

        if target_cell is None:
            print(f"\n  ❌ {year}년 {month}월 결정문이 존재하지 않습니다.")
            return []

        pdf_links = []
        for link in target_cell.find_elements(By.TAG_NAME, "a"):
            href    = (link.get_attribute("href") or "").strip()
            onclick = (link.get_attribute("onclick") or "").strip()
            title   = (link.get_attribute("title") or "").strip()
            text    = cell_full_text(link)

            combined = f"{href} {title} {text}"
            if target_re.search(combined):
                skip = {"", "#", "javascript:void(0)", "javascript:;"}
                entry = {"title": target_filename, "href": href,
                         "onclick": onclick, "element": link}
                if href not in skip or onclick:
                    pdf_links.append(entry)
                    print(f"  📎 PDF 링크: href={href[:60]}  title={title}")
        if not pdf_links:
            print("  ⚠️ PDF 링크 미발견 → 셀 내 첫 번째 <a> 클릭 시도")
            icons = target_cell.find_elements(By.TAG_NAME, "a")
            if icons:
                pdf_links = [{"title": target_filename, "href": "",
                              "onclick": "", "element": icons[0]}]

        if not pdf_links:
            print(f"  ❌ 다운로드 링크를 찾지 못했습니다.")
            return []

        print(f"  다운로드 대상: {len(pdf_links)}개")

        for item in pdf_links:
            print(f"\n  📥 다운로드: {item['title']}")
            before = set(os.listdir(save_dir))

            try:
                if item["href"] and item["href"] not in (
                    "", "#", "javascript:void(0)", "javascript:;"
                ):
                    driver.get(item["href"])
                else:
                    driver.execute_script("arguments[0].click();", item["element"])
                time.sleep(2)

                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    time.sleep(1)
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                save_path = wait_for_download(save_dir, before, timeout=60)
                if not save_path:
                    print("  ❌ 다운로드 타임아웃")
                    continue

                size = os.path.getsize(save_path)
                with open(save_path, "rb") as f:
                    header = f.read(50)
                if size < 50_000 and (b"<!DOCTYPE" in header or b"<html" in header):
                    print(f"  ❌ HTML 위장 파일 ({size/1024:.1f} KB) — 삭제")
                    os.remove(save_path)
                    continue

                if not save_path.lower().endswith(".pdf"):
                    new_path = save_path + ".pdf"
                    os.rename(save_path, new_path)
                    save_path = new_path

                print(f"  ✅ 저장: {save_path} ({size/1024:.1f} KB)")
                pdf_paths.append(save_path)

            except Exception as e:
                print(f"  ❌ 오류: {e}")

    finally:
        driver.quit()
        print("\n  브라우저 종료")

    return pdf_paths


# 보고서 작성

def load_pdf_text(pdf_path: str) -> str:
    try:
        import fitz
    except ImportError:
        raise ImportError("pip install PyMuPDF 필요")
    doc = fitz.open(pdf_path)
    text = "".join(page.get_text() for page in doc)
    doc.close()
    return text


def generate_report(new_pdf_path: str) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    loaded = 0
    for pdf_filename, report_text in EXAMPLE_REPORTS.items():
        pdf_path = os.path.join(TRAINING_PDF_DIR, pdf_filename)
        if not os.path.exists(pdf_path):
            print(f"  ⚠️ 예시 PDF 없음 (건너뜀): {pdf_filename}")
            continue
        pdf_text = load_pdf_text(pdf_path)
        if not pdf_text.strip():
            continue
        messages.append({
            "role": "user",
            "content": (
                "다음 한국은행 통화정책방향 결정문 원문을 읽고 "
                "동일한 형식의 요약 보고서를 작성하세요.\n\n"
                f"[원문]\n{pdf_text[:8000]}"
            )
        })
        messages.append({"role": "assistant", "content": report_text})
        loaded += 1

    print(f"  Few-shot 예시 {loaded}개 로드 완료")

    print(f"  PDF 텍스트 추출 중: {os.path.basename(new_pdf_path)}")
    pdf_text = load_pdf_text(new_pdf_path)
    if not pdf_text.strip():
        raise ValueError(f"텍스트 추출 실패: {new_pdf_path}")
    print(f"  추출 완료 ({len(pdf_text):,}자)")

    messages.append({
        "role": "user",
        "content": (
            "다음 한국은행 통화정책방향 결정문 원문을 읽고 "
            "동일한 형식의 요약 보고서를 작성하세요.\n\n"
            f"[원문]\n{pdf_text[:20000]}"
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
    print(
        f"  토큰: input={usage.prompt_tokens:,} / "
        f"output={usage.completion_tokens:,} / "
        f"total={usage.total_tokens:,}"
    )
    return report


def main():
    print("=" * 60)
    print("  한국은행 통화정책방향 결정문 보고서 자동 생성")
    print(f"  대상: {SEARCH_YEAR}년 {SEARCH_MONTH}월")
    print("=" * 60)

    print("\n" + "=" * 60)
    print("  [Step 1] 결정문 PDF 크롤링")
    print("=" * 60)

    os.makedirs(INPUT_PDF_DIR, exist_ok=True)
    pdf_paths = crawl_bok_decision(SEARCH_YEAR, SEARCH_MONTH, INPUT_PDF_DIR)

    if not pdf_paths:
        existing = sorted([
            os.path.join(INPUT_PDF_DIR, f)
            for f in os.listdir(INPUT_PDF_DIR)
            if f.lower().endswith(".pdf")
        ])
        if existing:
            print(f"\n  → 기존 PDF {len(existing)}개 발견, 이를 사용합니다.")
            pdf_paths = existing
        else:
            print("\n⚠️  처리할 PDF가 없습니다. 종료합니다.")
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

            print(f"\n[생성된 보고서]\n{report}")
            print(f"\n✅ 저장: {output_path}")

        except Exception as e:
            print(f"❌ 오류: {e}")

    print("\n" + "=" * 60)
    print("  파이프라인 완료")
    print("=" * 60)
    
    return final_report


if __name__ == "__main__":
    main()

# python BOT/api_통화정책.py