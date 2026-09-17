import pandas as pd
import datetime

# 파일 읽기 (Bloomberg 형식에 맞게 4행 skip)
df = pd.read_excel(r'C:\Users\intern9\truston_quant_dev\K2_K2F\코스피선물_분봉.xlsx', skiprows=4, header=None)
df.columns = ['Datetime', 'Close', 'Volume']

# datetime 변환
df['Datetime'] = pd.to_datetime(df['Datetime'])

# 시간 추출
df['Time'] = df['Datetime'].dt.time

# 정규장 시간대 필터링 (09:00:00 ~ 15:45:00)
day_start = datetime.time(9, 0, 0)
day_end = datetime.time(15, 45, 0)

# 정규장 데이터만 남기기
df_day = df[(df['Time'] >= day_start) & (df['Time'] <= day_end)].copy()

# Time 컬럼 제거 (필요 없으면)
df_day = df_day.drop(columns=['Time'])

# 인덱스 리셋
df_day = df_day.reset_index(drop=True)

print(f"원본 데이터: {len(df):,}건")
print(f"정규장 데이터: {len(df_day):,}건")
print(f"제거된 야간 데이터: {len(df) - len(df_day):,}건")

# 결과 저장 (필요시)
df_day.to_excel('K2_선물_분봉_정규장2.xlsx', index=False)
# python K2_K2F\preprocessing.py