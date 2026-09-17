"""
고용동향 보고서 크롤링 봇 (국가데이터처)
pip install openai PyMuPDF selenium webdriver-manager requests
"""

import os
import re
import time
import openai
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ════════════════════════════════════════════════════════════════
# config.py에서 설정 import
# ════════════════════════════════════════════════════════════════

try:
    from 보고서_API.BOT.config import EMPLOYMENT_CONFIG
    SEARCH_TITLE = EMPLOYMENT_CONFIG['search_title']
    OPENAI_API_KEY = EMPLOYMENT_CONFIG['openai_api_key']
    MODEL = EMPLOYMENT_CONFIG['model']
    TEMPERATURE = EMPLOYMENT_CONFIG['temperature']
    MAX_TOKENS = EMPLOYMENT_CONFIG['max_tokens']
    INPUT_DIR = EMPLOYMENT_CONFIG['input_dir']
    OUTPUT_DIR = EMPLOYMENT_CONFIG['output_dir']
    BASE_URL = EMPLOYMENT_CONFIG['base_url']
    MAX_PAGES = EMPLOYMENT_CONFIG['max_pages']
except ImportError:
    # config.py가 없을 경우 기본값 사용
    SEARCH_TITLE = "2026년 1월 고용동향"
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    MODEL = "gpt-4o"
    TEMPERATURE = 0.1
    MAX_TOKENS = 40000
    INPUT_DIR = r"C:\Users\intern9\truston_quant_dev\employment_test"
    OUTPUT_DIR = r"C:\Users\intern9\truston_quant_dev\employment_output"
    BASE_URL = "https://mods.go.kr"
    MAX_PAGES = 50

LIST_URL = (
    f"{BASE_URL}/board.es"
    f"?mid=a10301030100&bid=210&act=list"
    f"&nPage={{page}}"
    f"&ref_bid=210,211,11109,11113,11814"
    f"&keyField=T&keyWord=%EA%B3%A0%EC%9A%A9%EB%8F%99%ED%96%A5"
)

client = openai.OpenAI(api_key=OPENAI_API_KEY)


# System prompt

SYSTEM_PROMPT = """당신은 통계청 고용동향 보도자료의 줄글 요약본을 읽고 간결한 한 문장짜리 매크로 메모를 작성하는 전문 분석관입니다.

[형식]
- "- "를 붙이고 본문 시작.
- 본문은 단 하나의 문장. 줄바꿈 없이 쉼표로 이어 쓴다.
- 제목·머리말·번호 매기기 금지.

[작성 방식 — 가장 중요]
- "N월 고용은 취업자수가 전년 대비 X만명이 증가(감소)하였고, OECD 비교 기준인 15-64세 고용률은 X%로 전년동월 대비 +X.X%p 상승(하락)." 형식을 반드시 따른다.
- 취업자 수 증감은 천명 단위를 만명 단위(소수점 한 자리)로 변환하여 표기한다.
  예) 193천명 → 19.3만명,  312천명 → 31.2만명
- 15~64세 OECD 고용률과 전년동월 대비 %p 증감을 반드시 포함한다.
- 두 수치(취업자 증감, 고용률) 외 다른 항목은 추가하지 않는다.

[출력 예시]
- 9월 고용은 취업자수가 전년 대비 31.2만명이 증가하였고, OECD 비교 기준인 15-64세 고용률은 70.4%로 전년동월 대비 +0.5%p 상승.

[금지]
- 실업률·비경제활동 등 다른 항목 추가 금지.
- 주관적 표현·정책 제언 금지.
- 본문 내부 줄바꿈 금지.
- 원문에 없는 수치 생성·추론 금지.
"""


# training dictionary

EXAMPLE_REPORTS = {
    "2025년 10월 고용동향": {
        "body": """[2025년 10월 고용동향]

▣ 15~64세 고용률(OECD 비교기준)은 70.1%로 전년동월대비 0.3%p 상승

▣ 실업률은 2.2%로 전년동월대비 0.1%p 하락

   ○ 실업자는 658천명으로 전년동월대비 2만명(-2.9%) 감소

   ○ 청년층 실업률은 5.3%로 전년동월대비 0.2%p 하락 

   ○ 계절조정 실업률은 2.6%로 전월대비 0.1%p 상승

▣ 2025년 10월 취업자는 29,040천명으로 전년동월대비 193천명(0.7%) 증가""",
        "report": """
10월 고용은 취업자수가 전년 대비 19.3만명이 증가하였고, OECD 비교 기준인 15-64세 고용률은 70.1%로 전년동월 대비 +0.3%p 상승""",
    },
    "2025년 9월 고용동향": {
        "body": """▣ 15~64세 고용률(OECD 비교기준)은 70.4%로 전년동월대비 0.5%p 상승

▣ 실업률은 2.1%로 전년동월과 동일

   ○ 실업자는 635천명으로 전년동월대비 12천명(2.0%) 증가

   ○ 청년층 실업률은 4.8%로 전년동월대비 0.3%p 하락 

   ○ 계절조정 실업률은 2.5%로 전월대비 0.1%p 하락

▣ 2025년 9월 취업자는 29,154천명으로 전년동월대비 312천명(1.1%) 증가""",
        "report": """
- 9월 고용은 취업자수가 전년 대비 31.2만명이 증가하였고, OECD 비교 기준인 15-64세 고용률은 70.4%로 전년동월 대비 +0.5%p 상승. """,
    },
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


def extract_body_text(driver) -> str:
# 본문 글 반환
    time.sleep(2)
    page_source = driver.page_source

    BODY_SELECTORS = [
        (By.CLASS_NAME, "view_con"),
        (By.CLASS_NAME, "board_view"),
        (By.CLASS_NAME, "cont_area"),
        (By.CLASS_NAME, "bbs_view"),
        (By.CLASS_NAME, "view_content"),
        (By.CLASS_NAME, "article_view"),
        (By.ID,         "content"),
        (By.ID,         "articleBody"),
        (By.CLASS_NAME, "view_body"),
    ]
    for by, selector in BODY_SELECTORS:
        try:
            elem = driver.find_element(by, selector)
            text = elem.text.strip()
            if len(text) > 100:
                print(f"  📄 줄글 추출 완료 ({len(text):,}자) — selector: {selector}")
                return text
        except Exception:
            continue
    candidates = []
    for tag in ["p", "li", "td"]:
        for elem in driver.find_elements(By.TAG_NAME, tag):
            t = elem.text.strip()
            if len(t) > 20:
                candidates.append(t)
    if candidates:
        joined = "\n".join(candidates)
        print(f"  📄 줄글 추출 완료 (fallback, {len(joined):,}자)")
        return joined

    print("  ⚠️ 줄글 추출 실패")
    return ""


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


def download_pdf_attachments(driver, save_dir: str) -> list:
# 첨부파일 pdf 다운로드
    print(f"\n  첨부파일 탐색 중...")
    time.sleep(2)
    os.makedirs(save_dir, exist_ok=True)

    pdf_pairs = []   # (filename, target, mode)  mode: "url" | "click"
    pending_pdf_name = None

    for link in driver.find_elements(By.TAG_NAME, "a"):
        try:
            text    = link.text.strip()
            href    = link.get_attribute("href") or ""
            onclick = link.get_attribute("onclick") or ""

            if re.search(r'\.pdf', text, re.I):
                pending_pdf_name = extract_filename(text)
                print(f"  📎 PDF 파일명 발견: {pending_pdf_name}")

                # 같은 링크에 직접 onclick 다운로드가 있는 경우
                m = re.search(r"(/(?:upload|attach|file|down)[\w/._%-]+\.pdf)", onclick, re.I)
                if m:
                    url = m.group(1)
                    if url.startswith("/"):
                        url = BASE_URL + url
                    pdf_pairs.append((pending_pdf_name, url, "url"))
                    print(f"     onclick URL: {url}")
                    pending_pdf_name = None
                    continue

                # href에 직접 pdf 경로가 있는 경우
                if re.search(r"\.pdf", href, re.I) and href.startswith("http"):
                    pdf_pairs.append((pending_pdf_name, href, "url"))
                    print(f"     href URL: {href[:80]}")
                    pending_pdf_name = None
                    continue

            elif text in ("다운로드", "download") and pending_pdf_name:
                m = re.search(r"(/(?:upload|attach|file|down)[\w/._%-]+)", onclick, re.I)
                if m:
                    url = m.group(1)
                    if url.startswith("/"):
                        url = BASE_URL + url
                    pdf_pairs.append((pending_pdf_name, url, "url"))
                    print(f"     다운로드 onclick URL: {url[:80]}")
                else:
                    # onclick 없으면 직접 클릭
                    pdf_pairs.append((pending_pdf_name, link, "click"))
                    print(f"     다운로드 click 등록")
                pending_pdf_name = None

        except Exception:
            continue

    # 다운로드 실패 할 경우 진단 로직
    if not pdf_pairs:
        print("  ❌ PDF 다운로드 링크를 찾지 못했습니다. 진단 정보:")
        for link in driver.find_elements(By.TAG_NAME, "a"):
            try:
                t = link.text.strip()
                h = link.get_attribute("href") or ""
                o = link.get_attribute("onclick") or ""
                if any(x in (t+h+o).lower() for x in ["pdf","hwp","다운","down","upload","attach","file"]):
                    print(f"    text='{t[:50]}' href='{h[:80]}' onclick='{o[:80]}'")
            except Exception:
                pass
        return []

    print(f"\n  총 {len(pdf_pairs)}개 PDF 다운로드 시작")
    downloaded = []

    for filename, target, mode in pdf_pairs:
        print(f"\n  📥 다운로드: {filename}")
        before = set(os.listdir(save_dir))

        if mode == "url":
            driver.get(target)
        else:
            try:
                driver.execute_script("arguments[0].scrollIntoView();", target)
                driver.execute_script("arguments[0].click();", target)
            except Exception as e:
                print(f"  ⚠️ 클릭 실패: {e}")
                continue

        time.sleep(1)
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

def crawl_employment(title: str, save_dir: str):
    print(f"\n[크롤링] '{title}'")
    print("-" * 50)

    driver = create_driver(download_dir=save_dir)
    body_text = ""
    pdf_paths = []

    try:
        if navigate_to_article(driver, title):
            # 줄글 먼저 추출
            body_text = extract_body_text(driver)
            if body_text:
                print(f"\n  [줄글 미리보기]\n{body_text[:400]}\n  ...")

            # PDF 다운로드
            pdf_paths = download_pdf_attachments(driver, save_dir)
    finally:
        driver.quit()
        print("  브라우저 종료")

    return body_text, pdf_paths


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


def generate_report(body_text: str, pdf_paths: list) -> str:
    """
    body_text: 상세 페이지 줄글 (주 입력)
    pdf_paths: 다운로드된 PDF (줄글이 짧을 경우 보완용)
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Few-shot 예시 로드
    loaded = 0
    for month_title, example in EXAMPLE_REPORTS.items():
        body = example.get("body", "").strip()
        report = example.get("report", "").strip()
        if not body or not report:
            continue
        messages.append({
            "role": "user",
            "content": f"다음 고용동향 보도자료 줄글을 읽고 요약 보고서를 작성하세요.\n\n[줄글]\n{body}"
        })
        messages.append({
            "role": "assistant",
            "content": report
        })
        loaded += 1

    print(f"  예시 {loaded}개 로드 완료")

    # 입력 텍스트 결정: 줄글 우선, 없으면 PDF 텍스트
    if body_text and len(body_text.strip()) > 50:
        input_text = body_text.strip()
        print(f"  줄글 사용 ({len(input_text):,}자)")
    elif pdf_paths:
        print(f"  줄글 없음 → PDF 텍스트 추출")
        input_text = load_pdf_text(pdf_paths[0])[:15000]
        print(f"  PDF 텍스트 ({len(input_text):,}자)")
    else:
        raise ValueError("줄글도 PDF도 없습니다.")

    messages.append({
        "role": "user",
        "content": f"다음 고용동향 보도자료 줄글을 읽고 요약 보고서를 작성하세요.\n\n[줄글]\n{input_text}"
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
    print(f"  토큰: input={usage.prompt_tokens:,} / output={usage.completion_tokens:,}")
    return report



def main():
    print("=" * 60)
    print("  고용동향 보고서 자동 생성 파이프라인")
    print(f"  크롤링 대상: {SEARCH_TITLE}")
    print("=" * 60)

    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\n" + "=" * 60)
    print("  [Step 1] 줄글 크롤링 + PDF 다운로드")
    print("=" * 60)

    body_text, pdf_paths = crawl_employment(SEARCH_TITLE, INPUT_DIR)

    if not body_text and not pdf_paths:
        # 이미 다운로드된 PDF가 있으면 그걸 사용
        existing = [
            os.path.join(INPUT_DIR, f)
            for f in os.listdir(INPUT_DIR)
            if f.lower().endswith(".pdf")
        ]
        if existing:
            print(f"  → 기존 PDF {len(existing)}개 사용")
            pdf_paths = existing
        else:
            print("  ❌ 데이터 없음. 종료.")
            return None

    print("\n" + "=" * 60)
    print("  [Step 2] 보고서 생성")
    print("=" * 60)

    try:
        report = generate_report(body_text, pdf_paths)
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', SEARCH_TITLE)
        output_path = os.path.join(OUTPUT_DIR, f"{safe_name}_보고서.txt")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"\n[생성된 보고서]")
        print(report)
        print(f"\n✅ 저장: {output_path}")
        return report

    except Exception as e:
        print(f"❌ 오류: {e}")
        return None

    print("\n" + "=" * 60)
    print("  파이프라인 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()

# python BOT/api_고용동향.py