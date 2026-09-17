# BOT 통합 관리 시스템 (설명서)

## 📋 개요

BOT 폴더의 6개 개별 API 파일들이 모두 중앙 설정 파일(`config.py`)을 통해 관리되도록 통합되었습니다.  
`run.py`만 실행하면 모든 BOT을 순차적으로 실행할 수 있습니다.

---

## 📁 파일 구조

```
BOT/
├── config.py                 ← ★ 중앙 설정 파일 (하드코딩 수치 한 곳 관리)
├── run.py                    ← ★ 통합 실행 파일
├── api_고용동향.py            ← config.py import
├── api_글로벌매크로.py         ← config.py import
├── api_리뷰.py                ← config.py import
├── api_산업활동동향.py         ← config.py import
├── api_수출입.py              ← config.py import
└── api_통화정책.py            ← config.py import
```

---

## 🎯 사용 방법

### 1️⃣ 모든 BOT 실행 (기본)
```bash
cd C:\Users\intern9\truston_quant_dev\BOT
python run.py
```

### 2️⃣ 특정 BOT만 실행
```bash
python run.py --bot 고용동향
python run.py --bot 글로벌매크로
python run.py --bot 리뷰
python run.py --bot 산업활동동향
python run.py --bot 수출입동향
python run.py --bot 통화정책
```

### 3️⃣ 설정 확인
```bash
python run.py --config
```

---

## ⚙️ 설정 변경 방법

모든 하드코딩 설정은 `config.py`의 맨 위에 있습니다. 다음만 수정하면 됩니다:

### [1] 고용동향
```python
EMPLOYMENT_CONFIG = {
    'search_title': "2026년 1월 고용동향",  # ← 수정
    'temperature': 0.1,
    'max_tokens': 40000,
}
```

### [2] 글로벌매크로
```python
GLOBAL_MACRO_CONFIG = {
    'test_file': str(INPUT_DIR / "[KB증권] 글로벌 시황_202604.pptx"),  # ← 파일명 수정
    'target_month': "2026년 3월",  # ← 수정
    'next_month': "2026년 4월",    # ← 수정
    'temperature': 0.3,
}
```

### [3] 리뷰
```python
REVIEW_CONFIG = {
    'test_file': str(INPUT_DIR / "트러스톤-2026년 4월 주식 전망.docx"),  # ← 파일명 수정
    'temperature': 0.1,
}
```

### [4] 산업활동동향
```python
INDUSTRY_CONFIG = {
    'search_title': "'26.2월 산업활동동향 및 평가",  # ← 수정
    'temperature': 0.1,
}
```

### [5] 수출입동향
```python
TRADE_CONFIG = {
    'search_title': "2026년 3월 수출입 동향",  # ← 수정
    'temperature': 0.1,
}
```

### [6] 통화정책
```python
MONETARY_POLICY_CONFIG = {
    'search_year': 2026,   # ← 수정
    'search_month': 3,     # ← 수정
    'temperature': 0.1,
}
```

---

## 🔧 내부 구조

### config.py의 역할
1. **중앙 경로 관리**: 모든 input/output 디렉토리를 한 곳에서 관리
2. **OpenAI 설정**: API 키, 모델, 토큰 한도 등 중앙 관리
3. **BOT별 설정**: 각 BOT의 검색어, 파일 경로, 파라미터 저장
4. **버전 관리**: 기본값과 config.py 설정 비교로 자동 폴백

### run.py의 역할
1. **동적 import**: 각 api_*.py 파일의 main() 함수 호출
2. **오류 처리**: 각 BOT의 실행 여부와 소요시간 기록
3. **명령행 인터페이스**: --bot, --config 옵션 지원
4. **성공/실패 요약**: 최종 결과 요약 출력

### 각 api_*.py 파일의 변경
- **Import 추가**: `from config import XXX_CONFIG`
- **변수 초기화**: config에서 가져온 값으로 초기화
- **대체 경로**: config.py가 없으면 기본값 사용

---

## 📊 실행 결과 예시

```
════════════════════════════════════════════════════════════════
  ─  STEP1: 글로벌매크로  ─
════════════════════════════════════════════════════════════════
...실행 내용...
  ✅  글로벌매크로 완료  (14.3초)

════════════════════════════════════════════════════════════════
  ─  STEP2: 리뷰  ─
════════════════════════════════════════════════════════════════
...실행 내용...
  ✅  리뷰 완료  (17.2초)
```

---

## ☑️ 체크리스트

- [x] config.py 생성 (모든 BOT 설정 중앙 관리)
- [x] api_고용동향.py config import 적용
- [x] api_글로벌매크로.py config import 적용
- [x] api_리뷰.py config import 적용
- [x] api_산업활동동향.py config import 적용
- [x] api_수출입.py config import 적용
- [x] api_통화정책.py config import 적용
- [x] run.py 작성 (통합 실행 및 설정 표시)
- [x] 테스트 완료 (글로벌매크로, 리뷰 정상 작동)

---

## 💡 팁

1. **설정 미리 확인**
   ```bash
   python run.py --config
   ```

2. **특정 BOT만 디버깅**
   ```bash
   python run.py --bot 고용동향
   ```

3. **모든 설정은 config.py에서 관리** → 6개 파일을 수정할 필요 없음

4. **새로운 파일 추가 시**
   - config.py에 새 CONFIG 딕셔너리 추가
   - api_새파일.py 맨 위에 `from config import 새CONFIG` 추가
   - run.py의 bots 리스트에 추가

---

## ❓ FAQ

**Q: 특정 검색어만 변경하고 싶어요**  
A: config.py에서 해당 BOT의 search_title만 수정하세요.

**Q: OpenAI API 키를 변경하고 싶어요**  
A: config.py의 최상단 `OPENAI_API_KEY`를 수정하면 모든 BOT에 적용됩니다.

**Q: 특정 BOT이 실패했어요**  
A: `python run.py --bot 해당BOT명`으로 개별 실행하여 로그를 확인하세요.

**Q: 경로를 변경하고 싶어요**  
A: config.py의 `BASE_DIR`, `INPUT_DIR`, `OUTPUT_DIR` 등을 수정하세요.

---

## 📝 버전 정보
- 작성일: 2026-04-01
- BOT 통합 버전 1.0
- 지원 BOT: 6개 (고용동향, 글로벌매크로, 리뷰, 산업활동동향, 수출입동향, 통화정책)
