import pandas as pd
from datetime import datetime, timedelta
import os

# ============================================================
# 경로 설정
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # MSCI_W_port 폴더
DATA_DIR = os.path.join(BASE_DIR, 'data')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# Excel serial date → datetime 변환
# ============================================================
def excel_to_date(serial):
    return datetime(1899, 12, 30) + timedelta(days=int(serial))

# ============================================================
# MSCI 데이터 로드 함수
# ============================================================
def load_msci_data(filepath, index_name):
    """MSCI 엑셀 파일을 읽어서 정리된 DataFrame 반환"""
    df = pd.read_excel(filepath, skiprows=2)
    
    # 날짜 변환
    df['Date'] = df['Date'].apply(excel_to_date)
    
    # 필요한 컬럼만 선택 & 이름 변경
    df = df[['Date', 'Price', 'Total Return (Gross, Unhedged)']].copy()
    df.columns = ['Date', 'Price', 'Gross_TR']
    
    # 날짜 오름차순 정렬
    df = df.sort_values('Date').reset_index(drop=True)
    
    # 월별 수익률 계산
    df['Price_Return'] = df['Price'].pct_change() * 100
    df['Gross_TR_Return'] = df['Gross_TR'].pct_change() * 100
    
    # 누적 수익률
    df['Cumul_Price_Return'] = (df['Price'] / df['Price'].iloc[0] - 1) * 100
    df['Cumul_Gross_TR_Return'] = (df['Gross_TR'] / df['Gross_TR'].iloc[0] - 1) * 100
    
    df['Index'] = index_name
    return df

# ============================================================
# 데이터 로드
# ============================================================
files = {
    'MSCI World': 'MSCI WORLD Price.xlsx',
    'MSCI EM': 'MSCI EM Price.xlsx',
    'MSCI ACWI': 'MSCI AC WORLD Price.xlsx',
    'MSCI World ex USA': 'MSCI WORLD(ex USA) Price.xlsx',
}

data = {}
for name, filename in files.items():
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        data[name] = load_msci_data(filepath, name)
        print(f"✅ {name} 로드 완료 ({len(data[name])}개월)")
    else:
        print(f"❌ {name} 파일 없음: {filepath}")

# ============================================================
# 요약 출력
# ============================================================
print("\n" + "=" * 60)
print("MSCI 월별 수익률 요약")
print("=" * 60)

for name, df in data.items():
    years = (df['Date'].iloc[-1] - df['Date'].iloc[0]).days / 365.25
    annualized = ((df['Gross_TR'].iloc[-1] / df['Gross_TR'].iloc[0]) ** (1/years) - 1) * 100
    
    print(f"\n--- {name} ---")
    print(f"  기간: {df['Date'].iloc[0].strftime('%Y-%m')} ~ {df['Date'].iloc[-1].strftime('%Y-%m')}")
    print(f"  누적 수익률 (Price):    {df['Cumul_Price_Return'].iloc[-1]:+.2f}%")
    print(f"  누적 수익률 (Gross TR): {df['Cumul_Gross_TR_Return'].iloc[-1]:+.2f}%")
    print(f"  연환산 수익률 (Gross TR): {annualized:+.2f}%")
    print(f"  월 평균 수익률: {df['Gross_TR_Return'].mean():+.2f}%")
    print(f"  월 표준편차:    {df['Gross_TR_Return'].std():.2f}%")

# ============================================================
# 엑셀 저장
# ============================================================
output_path = os.path.join(OUTPUT_DIR, 'MSCI_Monthly_Returns.xlsx')

with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
    # Combined 시트
    combined = pd.DataFrame({'Date': data['MSCI World']['Date']})
    for name, df in data.items():
        short = name.replace('MSCI ', '')
        combined[f'{short}_Price'] = df['Price'].values
        combined[f'{short}_Price_Return'] = df['Price_Return'].values
        combined[f'{short}_Gross_TR'] = df['Gross_TR'].values
        combined[f'{short}_Gross_TR_Return'] = df['Gross_TR_Return'].values
    combined.to_excel(writer, sheet_name='Combined', index=False)
    
    # 개별 시트
    for name, df in data.items():
        sheet_name = name.replace('MSCI ', '')[:31]  # 시트명 31자 제한
        df.to_excel(writer, sheet_name=sheet_name, index=False)

print(f"\n✅ 저장 완료: {output_path}")