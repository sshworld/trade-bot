"""One end-to-end Telegram check of the real message formats (alert / entry / exit / daily settlement), produced by
the engine on an in-memory exchange and clearly marked [TESTNET 테스트]. Needs TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID."""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET"):
    os.environ.pop(k, None)
os.environ["LIVE_V6_FORBID_MAINNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from live_v6.engine import Settings, V6Engine  # noqa: E402
from live_v6.notify import Notifier  # noqa: E402
from live_v6.store import MemoryStore  # noqa: E402
from live_v6.tests.fakes import FakeExchange  # noqa: E402

TAG = "[TESTNET 테스트 · 실거래 아님]\n"


class Capture(Notifier):
    def __init__(self):
        super().__init__("", "")

    def send(self, text):
        self.sent.append(text)
        return True


cap = Capture()
eng = V6Engine(FakeExchange(), Settings(symbols=("DOGEUSDT",), entry_order=("DOGEUSDT",), cid_prefix="v6e2e",
                                        query_delay_s=0, exit_retry_delay_s=0, income_interval_s=0, bootstrap_bars=60),
               store=MemoryStore(), notifier=cap, sleep=lambda s: None)
eng.on_bar_close = lambda *a, **k: None
eng.startup()
eng.enter("DOGEUSDT", Decimal("0.0045"), int(time.time()) * 1000)
eng.ex.set_price("DOGEUSDT", "0.1620")
eng.close("DOGEUSDT", "signal_exit")
eng.alert("손절 등록 실패 — 이 포지션만 정리", "DOGEUSDT 1111 · 손절 0.14550 · rejected · 다른 포지션 유지")
day = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
msgs = [next(m for m in cap.sent if m.startswith(p)) for p in ("🚨", "🟢", "🔵")] + [eng.daily_summary(day)]
tg = Notifier()
if not tg.configured:
    sys.exit("missing env: " + ", ".join(tg.missing_env()))
ok = [tg.send(TAG + m) for m in msgs]
print("sent", sum(ok), "of", len(ok))
