import logging
import os

from .bot import TradingBot
from .config import Config


def main():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("logs/bot.log", encoding="utf-8")],
    )
    cfg = Config.from_env()
    if not cfg.dry_run and not cfg.demo:
        answer = input("⚠️  실거래 모드입니다. 진짜 돈으로 주문합니다. 계속하려면 'YES' 입력: ")
        if answer != "YES":
            return
    try:
        TradingBot(cfg).run()
    except KeyboardInterrupt:
        logging.info("봇 종료")


if __name__ == "__main__":
    main()
