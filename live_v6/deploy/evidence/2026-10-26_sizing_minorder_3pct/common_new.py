import json, sys
sys.path.insert(0, "/workspace/sizing-minorder-3pct")
from decimal import Decimal
D = json.load(open("/workspace/replay-0c/data/vps_data.json"))
SIX = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT"]
