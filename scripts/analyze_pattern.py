"""
거래 패턴 검증: "장을 오래 기다리고 크게 가져가는" 구조인지 확인.

closed trade 의 정확한 스키마 (47건 전부 동일):
  avg_entry_price, avg_exit_price, quantity, leverage, side,
  realized_pnl, pnl_percent, total_fees, close_reason,
  opened_at, closed_at, duration_seconds, signal_type, signal_details
"""
import json
import sqlite3
import statistics as st
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "backend/data/trading.db"

rows = sqlite3.connect(DB).execute(
    "SELECT data FROM trade_history ORDER BY closed_at"
).fetchall()

trades = []
for (raw,) in rows:
    d = json.loads(raw)
    entry = float(d.get("avg_entry_price") or 0)
    exit_ = float(d.get("avg_exit_price") or 0)
    qty = float(d.get("quantity") or 0)
    lev = float(d.get("leverage") or 1)
    side = d.get("side")
    realized = float(d.get("realized_pnl") or 0)
    fees = float(d.get("total_fees") or 0)
    net = realized - fees
    notional = entry * qty
    margin = notional / lev if lev else 0
    pct_margin = (net / margin * 100) if margin else 0
    pct_notional = (net / notional * 100) if notional else 0
    # BTC price move from entry to exit (favorable side = positive)
    if entry and exit_:
        if side == "long":
            move_pct = (exit_ - entry) / entry * 100
        else:
            move_pct = (entry - exit_) / entry * 100
    else:
        move_pct = 0
    dur_h = float(d.get("duration_seconds") or 0) / 3600
    reason = d.get("close_reason") or "?"
    pnl_pct = float(d.get("pnl_percent") or 0)
    trades.append(dict(
        entry=entry, exit=exit_, qty=qty, lev=lev, side=side,
        realized=realized, fees=fees, net=net,
        notional=notional, margin=margin,
        pct_margin=pct_margin, pct_notional=pct_notional, move_pct=move_pct,
        pnl_pct_recorded=pnl_pct,
        dur_h=dur_h, reason=reason,
        signal=d.get("signal_type"),
    ))

n = len(trades)
print(f"=== 거래 {n}건 (2026-04-27 ~ 2026-05-21, 24일) ===\n")

# 1. 보유시간
holds = [t["dur_h"] for t in trades]
print("[1] 보유시간 (duration_seconds 기준)")
print(f"  평균 {st.mean(holds):.2f}h / 중앙값 {st.median(holds):.2f}h / 최대 {max(holds):.2f}h")
buckets = [("<1h", 0, 1), ("1-4h", 1, 4), ("4-12h", 4, 12), ("12-24h", 12, 24), ("24-48h", 24, 48), ("48-72h", 48, 72), (">72h", 72, 10**9)]
for label, lo, hi in buckets:
    c = sum(1 for h in holds if lo <= h < hi)
    if c:
        print(f"    {label:7s} : {c:2d}건 ({c/n*100:.1f}%)")

# 2. 청산 사유
print("\n[2] 청산 사유 분포")
reasons = Counter(t["reason"] for t in trades)
for r, c in reasons.most_common():
    print(f"  {r:30s} : {c}건 ({c/n*100:.1f}%)")

# 3. PnL 분포
print(f"\n[3] PnL 분포 (수수료 차감)")
nets = [t["net"] for t in trades]
wins = [t for t in trades if t["net"] > 0]
losses = [t for t in trades if t["net"] < 0]
zeros = [t for t in trades if t["net"] == 0]
print(f"  총합 net : ${sum(nets):.2f}  /  총 fees: ${sum(t['fees'] for t in trades):.2f}")
print(f"  승률 (net>0) : {len(wins)}/{n} = {len(wins)/n*100:.1f}%   (loss {len(losses)}, zero {len(zeros)})")
print(f"  평균 net per trade : ${st.mean(nets):.2f}")
if wins:
    print(f"  win 평균 : ${st.mean(t['net'] for t in wins):.2f}  /  중앙값 ${st.median(t['net'] for t in wins):.2f}")
if losses:
    print(f"  loss 평균: ${st.mean(t['net'] for t in losses):.2f}  /  중앙값 ${st.median(t['net'] for t in losses):.2f}")
print(f"  최대 win : ${max(nets):.2f}  /  최대 loss : ${min(nets):.2f}")
# R:R
if wins and losses:
    rr = st.mean(t['net'] for t in wins) / abs(st.mean(t['net'] for t in losses))
    expectancy = st.mean(nets)
    print(f"  R:R 비율 : {rr:.2f}  /  기대값 per trade : ${expectancy:+.3f}")
# 마진 대비 % - notional & margin 정확히 계산됨
margin_pcts = [t["pct_margin"] for t in trades if t["margin"]]
notional_pcts = [t["pct_notional"] for t in trades if t["notional"]]
recorded_pcts = [t["pnl_pct_recorded"] for t in trades]
if margin_pcts:
    print(f"  마진 대비 net% : 평균 {st.mean(margin_pcts):+.2f}% / 중앙값 {st.median(margin_pcts):+.2f}%")
if notional_pcts:
    print(f"  노셔널 대비 net%: 평균 {st.mean(notional_pcts):+.3f}% / 중앙값 {st.median(notional_pcts):+.3f}%")
print(f"  pnl_percent (기록값): 평균 {st.mean(recorded_pcts):+.2f}% / 중앙값 {st.median(recorded_pcts):+.2f}%")

# 4. BTC 가격 이동 % (favorable side)
moves = [t["move_pct"] for t in trades if t["exit"]]
print(f"\n[4] BTC 가격 이동 % (entry → exit, side 보정, n={len(moves)})")
if moves:
    print(f"  평균 {st.mean(moves):+.3f}% / 중앙값 {st.median(moves):+.3f}%")
    tp1 = sum(1 for m in moves if m >= 0.6)   # 마진 3% @5x
    tp2 = sum(1 for m in moves if m >= 1.2)   # 마진 6%
    tp3 = sum(1 for m in moves if m >= 2.0)   # 마진 10%
    print(f"  TP1 zone (BTC ≥0.6%, 마진 3%) 도달 청산: {tp1}/{len(moves)} = {tp1/len(moves)*100:.1f}%")
    print(f"  TP2 zone (BTC ≥1.2%, 마진 6%) 도달 청산: {tp2}/{len(moves)} = {tp2/len(moves)*100:.1f}%")
    print(f"  TP3 zone (BTC ≥2.0%, 마진10%) 도달 청산: {tp3}/{len(moves)} = {tp3/len(moves)*100:.1f}%")
    # SL 거리
    sl_moves = [t["move_pct"] for t in trades if t["reason"] == "stop_loss" and t["exit"]]
    if sl_moves:
        print(f"  SL trade BTC 이동: 평균 {st.mean(sl_moves):+.3f}% / 중앙값 {st.median(sl_moves):+.3f}%")
    tp_moves = [t["move_pct"] for t in trades if t["reason"] == "take_profit" and t["exit"]]
    if tp_moves:
        print(f"  TP trade BTC 이동: 평균 {st.mean(tp_moves):+.3f}% / 중앙값 {st.median(tp_moves):+.3f}%")

# 5. 진입 사이즈 분포
print("\n[5] 진입 사이즈 (notional / margin)")
notionals = [t["notional"] for t in trades if t["notional"]]
margins = [t["margin"] for t in trades if t["margin"]]
if notionals:
    print(f"  notional : 평균 ${st.mean(notionals):.2f} / 중앙값 ${st.median(notionals):.2f} / max ${max(notionals):.2f}")
if margins:
    print(f"  margin   : 평균 ${st.mean(margins):.2f} / 중앙값 ${st.median(margins):.2f} / max ${max(margins):.2f}")

# 6. 거래 빈도
span_days = (max(t.get("dur_h", 0) for t in trades) + 24)  # dummy
opened = [t for t in trades]
print(f"\n[6] 거래 빈도 : {n}건 / 24.7일 = 일평균 {n/24.7:.2f}건")

# 7. 보유시간 구간별 결과
print("\n[7] 보유시간 구간별 승률·평균 net·평균 fees")
for label, lo, hi in buckets:
    sub = [t for t in trades if lo <= t["dur_h"] < hi]
    if not sub:
        continue
    sw = sum(1 for t in sub if t["net"] > 0)
    avg_pnl = st.mean(t["net"] for t in sub)
    avg_fee = st.mean(t["fees"] for t in sub)
    print(f"  {label:7s} n={len(sub):2d}  승률 {sw/len(sub)*100:5.1f}%  평균 net ${avg_pnl:+.2f}  평균 fee ${avg_fee:.2f}")

# 8. close_reason 별 평균 보유시간·PnL
print("\n[8] 청산 사유별 통계")
for r in reasons:
    sub = [t for t in trades if t["reason"] == r]
    if not sub: continue
    print(f"  {r:25s} n={len(sub):2d}  평균 보유 {st.mean(t['dur_h'] for t in sub):.2f}h  평균 net ${st.mean(t['net'] for t in sub):+.2f}  평균 BTC이동 {st.mean(t['move_pct'] for t in sub):+.3f}%")
