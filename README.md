# OKX 비트코인 자동매매 봇

OKX REST API v5로 BTC-USDT **현물**을 자동매매하는 파이썬 봇입니다.
레버리지는 쓰지 않습니다(`tdMode=cash`).

## 구조
```
okx_bot/
  client.py    OKX API 클라이언트 (HMAC 서명, 시세/잔고/주문, 재시도)
  strategy.py  EMA 크로스 전략 + 손절/익절
  bot.py       메인 루프, 포지션 상태 저장(state.json)
  config.py    .env 설정 로드/검증
tests/         단위 테스트
```

## 전략 (기본값)
- 15분봉에서 **EMA 9가 EMA 21을 상향 돌파(골든크로스)하면 매수**, 하향 돌파(데드크로스)하면 매도
- 마감된 캔들만 사용 (진행 중인 캔들로는 판단하지 않음)
- 매 루프마다 **손절 -2% / 익절 +4%** 체크
- 1회 매수 금액 `ORDER_USDT` (기본 20 USDT), 포지션은 한 번에 하나

## 실행
```bash
pip install -r requirements.txt
cp .env.example .env      # API 키 입력
python -m okx_bot
```

### 권장 순서
1. `DRY_RUN=true` — 주문 없이 시그널 로그만 확인 (API 키 없어도 됨)
2. `DRY_RUN=false`, `OKX_DEMO=1` — OKX **데모 트레이딩** 키로 모의 주문
3. 충분히 검증한 뒤에만 `OKX_DEMO=0` (실거래, 시작 시 `YES` 입력 필요)

## API 키 발급 시 주의
- 권한: **읽기 + 거래**만. **출금 권한은 절대 주지 마세요.**
- IP 화이트리스트를 봇을 돌리는 서버 IP로 지정하세요.
- `.env`는 `.gitignore`에 포함되어 있어 커밋되지 않습니다.
- 데모 키는 OKX 웹에서 "데모 트레이딩" 모드로 전환한 뒤 따로 발급합니다.

## 테스트
```bash
python -m pytest
```

> ⚠️ 이 코드는 학습/개발용 출발점입니다. 수익을 보장하지 않으며, 실거래 손실의 책임은 사용자에게 있습니다.
