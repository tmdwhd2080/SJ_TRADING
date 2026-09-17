from pykrx import stock

# 삼성전자 종목코드: 005930
# 2026.02.24 종가 크롤링 테스트
df = stock.get_market_ohlcv_by_date("20260224", "20260224", "000250")
print(df)
print(f"\n삼성전자 2026-02-24 종가: {df['종가'].iloc[0]:,}원")
#python K2_K2F/test.py