#!/usr/bin/env python3
"""Backtest: 현행 vs 신규 파라미터 비교 시뮬레이션.

최근 7일 Binance 1m 캔들 → 다중 TF 재구성 → 시그널 생성 → 체결 시뮬.
기존 모듈을 import하되, DB/Alert 없이 순수 인메모리로 실행.

Usage:
    cd backend && python -m scripts.backtest
    # 또는
    cd backend && uv run python ../scripts/backtest.py
"""

import asyncio
import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

# backend를 sys.path에 추가
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import httpx
import pandas as pd

# 시그널 생성만 import (DB, alert 등 side-effect 없음)
from app.analysis.signals import generate_signals, CONFLUENCE_THRESHOLDS, DEFAULT_THRESHOLD

# ── 설정 ──────────────────────────────────────────────────────────

SYMBOL = "BTCUSDT"
DAYS = 7  # 최근 7일
ENTRY_TIMEFRAMES = {"30m", "1h", "4h"}
SIGNAL_TIMEFRAMES = ["15m", "30m", "1h", "4h"]
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}

# ATR 파라미터 (현행)
TF_ATR_CURRENT = {
    "30m": {"sl": 1.2, "tp1": 1.0, "tp2": 1.8, "tp3": 3.0, "split": [0.50, 0.30, 0.20]},
    "1h":  {"sl": 1.5, "tp1": 1.2, "tp2": 2.0, "tp3": 3.5, "split": [0.50, 0.30, 0.20]},
    "4h":  {"sl": 2.0, "tp1": 1.5, "tp2": 2.5, "tp3": 4.0, "split": [0.50, 0.30, 0.20]},
}

# ATR 파라미터 (합의안: TP1 > SL 보장)
TF_ATR_NEW = {
    "30m": {"sl": 1.2, "tp1": 1.3, "tp2": 2.2, "tp3": 3.5, "split": [0.40, 0.35, 0.25]},
    "1h":  {"sl": 1.5, "tp1": 1.7, "tp2": 2.8, "tp3": 4.5, "split": [0.40, 0.35, 0.25]},
    "4h":  {"sl": 2.0, "tp1": 2.2, "tp2": 3.5, "tp3": 5.5, "split": [0.40, 0.35, 0.25]},
}


@dataclass
class SimConfig:
    """시뮬레이션 설정."""
    name: str
    initial_balance: float = 200.0
    leverage: int = 5
    risk_pct: float = 2.0  # 현행
    fee_taker_pct: float = 0.04
    fee_maker_pct: float = 0.02
    min_notional: float = 110.0  # Binance 최소 + 버퍼
    slippage_buffer: float = 0.95
    # 분할 관련
    entry_offsets_trend: list = field(default_factory=lambda: [0.0, -0.3, -0.6])
    entry_split_trend: list = field(default_factory=lambda: [0.50, 0.30, 0.20])
    entry_offsets_counter: list = field(default_factory=lambda: [0.0, -0.3])
    entry_split_counter: list = field(default_factory=lambda: [0.60, 0.40])
    max_entry_tranches_trend: int = 3
    max_entry_tranches_counter: int = 2
    # 동적 분할 여부
    dynamic_tranches: bool = False
    # 시그널 스로틀
    signal_throttle_sec: int = 5
    # 최소 시그널 강도
    min_signal_strength: float = 0.0
    # TP override (합의안: TP1 > SL)
    tp_override: bool = False
    # % 기반 TP/SL (새 합의안)
    pct_based_tp: bool = False
    tp_margin_pcts: list = field(default_factory=lambda: [3.0, 6.0, 10.0])  # 마진 대비 %
    tp_split: list = field(default_factory=lambda: [0.50, 0.30, 0.20])
    margin_cap_pct: float = 55.0  # 잔고 대비 마진 캡 %
    min_sl_pct: float = 0.3  # 최소 SL 거리 %
    # 시간 청산
    time_exit_hours: float = 8.0  # 0이면 비활성
    # 일일 제한
    daily_loss_tier1: float = 3.0
    daily_loss_tier2: float = 5.0


@dataclass
class SimTrade:
    """완료된 거래."""
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    leverage: int
    pnl: float
    pnl_pct: float
    fees: float
    reason: str  # tp1, tp_all, stop_loss, breakeven, time_exit
    duration_s: int
    timeframe: str
    num_entry_tranches: int
    num_exit_tranches: int
    signal_type: str


@dataclass
class SimPosition:
    """진행 중인 포지션."""
    id: int
    side: str  # "long" / "short"
    leverage: int
    timeframe: str
    signal_type: str
    signal_strength: float
    # 진입
    entry_targets: list  # [(price, qty, filled)]
    entry_filled: list   # [(price, qty)]
    # 퇴출
    exit_targets: list   # [(price, qty, filled)]
    stop_loss: float
    # ATR
    atr: float
    atr_params: dict
    # 추적
    margin: float
    highest_price: float = 0.0
    lowest_price: float = 999999.0
    opened_at: int = 0
    total_fees: float = 0.0
    realized_pnl: float = 0.0

    @property
    def avg_entry(self) -> float:
        if not self.entry_filled:
            return 0
        total_val = sum(p * q for p, q in self.entry_filled)
        total_qty = sum(q for _, q in self.entry_filled)
        return total_val / total_qty if total_qty > 0 else 0

    @property
    def total_qty(self) -> float:
        return sum(q for _, q in self.entry_filled)

    @property
    def filled_entry_count(self) -> int:
        return len(self.entry_filled)


class BacktestEngine:
    """순수 인메모리 백테스트 엔진."""

    def __init__(self, config: SimConfig):
        self.config = config
        self.balance = config.initial_balance
        self.margin_used = 0.0
        self.position: SimPosition | None = None
        self.trades: list[SimTrade] = []
        self.daily_pnl = 0.0
        self.daily_start = config.initial_balance
        self.current_day = 0
        self.halted_until = 0
        self._recent_signals: dict[str, int] = {}
        self._pos_counter = 0
        # 통계
        self.max_drawdown = 0.0
        self.peak_equity = config.initial_balance
        self.tranche_dist = defaultdict(int)  # {1: N, 2: N, 3: N}
        self.skipped_min_notional = 0

    def _check_daily_reset(self, ts: int):
        day = ts // 86400
        if day != self.current_day:
            self.current_day = day
            self.daily_pnl = 0.0
            self.daily_start = self.balance + self.margin_used
            self.halted_until = 0

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period + 1:
            return 0
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        tr = []
        for i in range(1, len(h)):
            tr.append(max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])))
        return sum(tr[-period:]) / period if len(tr) >= period else (sum(tr) / len(tr) if tr else 0)

    def _min_tranche_qty(self, price: float) -> float:
        raw = self.config.min_notional / price
        return math.ceil(raw * 1000) / 1000

    def _calc_num_tranches(self, total_qty: float, price: float, max_tranches: int) -> int:
        """동적 분할: floor(effective_size / min_qty), cap at max."""
        min_qty = self._min_tranche_qty(price)
        effective = total_qty * self.config.slippage_buffer
        n = int(effective / min_qty)
        return max(1, min(n, max_tranches))

    def _make_entry_targets(self, side: str, price: float, total_qty: float,
                            is_counter: bool, num_tranches: int) -> list:
        """진입 tranche 생성. 동적이면 num_tranches에 맞춰 균등 분배."""
        if self.config.dynamic_tranches:
            # 균등 분배
            offsets = [0.0, -0.3, -0.6][:num_tranches]
            split = self._even_split(num_tranches)
        else:
            if is_counter:
                offsets = self.config.entry_offsets_counter
                split = self.config.entry_split_counter
            else:
                offsets = self.config.entry_offsets_trend
                split = self.config.entry_split_trend

        targets = []
        remaining = total_qty
        for i, (sp, off) in enumerate(zip(split, offsets)):
            if i == len(split) - 1:
                qty = remaining
            else:
                qty = round(total_qty * sp, 3)
                remaining -= qty

            if side == "long":
                target = price * (1 + off / 100)
            else:
                target = price * (1 - off / 100)
            targets.append([round(target, 2), qty, False])

        # tail merge: 최소 수량 미달 tranche 합침
        min_qty = self._min_tranche_qty(price)
        while len(targets) > 1 and targets[-1][1] < min_qty:
            last = targets.pop()
            prev = targets[-1]
            total_val = prev[0] * prev[1] + last[0] * last[1]
            total_q = prev[1] + last[1]
            prev[0] = round(total_val / total_q, 2)
            prev[1] = total_q

        return targets

    def _make_exit_targets(self, side: str, avg_entry: float, total_qty: float,
                           atr: float, atr_params: dict, num_tranches: int,
                           margin: float = 0) -> list:
        """퇴출 tranche 생성. pct_based_tp이면 마진 % 기반."""
        if self.config.pct_based_tp and margin > 0:
            # ── % 기반 TP ──
            tp_pcts = self.config.tp_margin_pcts[:num_tranches]
            split = self.config.tp_split[:num_tranches]
            # split 합이 1이 되도록 조정
            s_sum = sum(split)
            split = [s / s_sum for s in split]

            targets = []
            remaining = total_qty
            for i, (sp, tp_pct) in enumerate(zip(split, tp_pcts)):
                if i == len(split) - 1:
                    qty = remaining
                else:
                    qty = round(total_qty * sp, 3)
                    remaining -= qty
                # 마진 대비 tp_pct% 수익 = price distance
                distance = (margin * tp_pct / 100) / total_qty
                if side == "long":
                    target = avg_entry + distance
                else:
                    target = avg_entry - distance
                targets.append([round(target, 2), qty, False])
        else:
            # ── ATR 기반 TP ──
            tp_multiples = [atr_params["tp1"], atr_params["tp2"], atr_params["tp3"]]
            if self.config.dynamic_tranches:
                tp_multiples = tp_multiples[:num_tranches]
                split = self._even_split(num_tranches)
            else:
                split = atr_params["split"]

            targets = []
            remaining = total_qty
            for i, (sp, tp_m) in enumerate(zip(split, tp_multiples)):
                if i == len(split) - 1:
                    qty = remaining
                else:
                    qty = round(total_qty * sp, 3)
                    remaining -= qty
                distance = atr * tp_m
                if side == "long":
                    target = avg_entry + distance
                else:
                    target = avg_entry - distance
                targets.append([round(target, 2), qty, False])

        # tail merge
        min_qty = self._min_tranche_qty(avg_entry)
        while len(targets) > 1 and targets[-1][1] < min_qty:
            last = targets.pop()
            prev = targets[-1]
            total_val = prev[0] * prev[1] + last[0] * last[1]
            total_q = prev[1] + last[1]
            prev[0] = round(total_val / total_q, 2)
            prev[1] = total_q

        return targets

    def _even_split(self, n: int) -> list[float]:
        if n == 1:
            return [1.0]
        elif n == 2:
            return [0.55, 0.45]
        else:
            return [0.50, 0.30, 0.20]

    def _breakeven_price(self, pos: SimPosition) -> float:
        """본전가 = 진입가 ± 왕복 수수료."""
        if not pos.entry_filled:
            return 0
        fee_rate = (self.config.fee_taker_pct * 2) / pos.leverage / 100
        avg = pos.avg_entry
        if pos.side == "long":
            return avg * (1 + fee_rate)
        else:
            return avg * (1 - fee_rate)

    def on_signal(self, signal: dict, current_price: float, ts: int, tf_dfs: dict) -> bool:
        """시그널 처리. 포지션 열렸으면 True."""
        self._check_daily_reset(ts)

        if ts < self.halted_until:
            return False

        # 일일 손실 체크
        daily_base = self.daily_start if self.daily_start > 0 else self.config.initial_balance
        daily_loss_pct = (-self.daily_pnl / daily_base * 100) if self.daily_pnl < 0 else 0
        if daily_loss_pct >= self.config.daily_loss_tier2:
            self.halted_until = ((ts // 86400) + 1) * 86400
            return False

        # 속도 제한
        recent_sl = [t for t in self.trades[-10:] if t.reason == "stop_loss" and ts - (t.duration_s + t.duration_s) < 3600]
        if len([t for t in self.trades[-3:] if t.reason == "stop_loss"]) >= 3:
            last_sl = self.trades[-1]
            if ts - (last_sl.duration_s) < 1800:
                self.halted_until = ts + 1800
                return False

        # 스로틀
        sig_key = f"{signal['type']}_{signal['direction']}"
        if sig_key in self._recent_signals and ts - self._recent_signals[sig_key] < self.config.signal_throttle_sec:
            return False
        self._recent_signals[sig_key] = ts

        # 시그널 강도 필터
        if signal.get("strength", 0) < self.config.min_signal_strength:
            return False

        side = "long" if signal["direction"] == "bullish" else "short"

        # 기존 포지션 있으면 스킵 (교체 로직은 단순화)
        if self.position is not None:
            return False

        # TF ATR (물타기 offset용)
        signal_tf = signal.get("timeframe", "1h")
        tf_df = tf_dfs.get(signal_tf)
        atr = self._calc_atr(tf_df) if tf_df is not None and len(tf_df) > 15 else current_price * 0.01

        size_mult = 0.5 if daily_loss_pct >= self.config.daily_loss_tier1 else 1.0
        risk_amount = self.balance * (self.config.risk_pct / 100) * size_mult

        if self.config.pct_based_tp:
            # ── % 기반 TP/SL ──
            # 마진 캡 적용
            max_margin = self.balance * (self.config.margin_cap_pct / 100)
            margin = max_margin * size_mult
            position_notional = margin * self.config.leverage
            if position_notional < 100:
                self.skipped_min_notional += 1
                return False
            total_qty = round(position_notional / current_price * self.config.slippage_buffer, 3)
            margin = round(position_notional * self.config.slippage_buffer / self.config.leverage, 2)
            if total_qty <= 0:
                return False
            # SL: 잔고 2% 고정 → 거리 역산
            sl_distance = risk_amount / total_qty
            min_sl = current_price * (self.config.min_sl_pct / 100)
            sl_distance = max(sl_distance, min_sl)
            atr_params = {"sl": 0, "tp1": 0, "tp2": 0, "tp3": 0, "split": self.config.tp_split}
        else:
            # ── ATR 기반 (현행) ──
            atr_table = TF_ATR_NEW if self.config.tp_override else TF_ATR_CURRENT
            atr_params = atr_table.get(signal_tf, atr_table["1h"])
            sl_distance = atr * atr_params["sl"]
            sl_distance = max(sl_distance, atr * 1.5)
            sl_distance = min(sl_distance, atr * 4.0)
            if sl_distance <= 0:
                return False
            position_notional = risk_amount / (sl_distance / current_price)
            if position_notional < 100:
                self.skipped_min_notional += 1
                return False
            margin = position_notional / self.config.leverage
            total_qty = round(position_notional / current_price, 3)
            if total_qty <= 0:
                return False

        # 동적 분할 계산
        is_counter = signal.get("type", "").startswith("consensus")
        max_tr = self.config.max_entry_tranches_counter if is_counter else self.config.max_entry_tranches_trend

        if self.config.dynamic_tranches:
            num_tranches = self._calc_num_tranches(total_qty, current_price, max_tr)
        else:
            num_tranches = max_tr

        # 진입 tranche 생성
        entry_targets = self._make_entry_targets(side, current_price, total_qty, is_counter, num_tranches)

        # 최소 수량 체크 — merge 후에도 첫 tranche가 min 미달이면 스킵
        min_qty = self._min_tranche_qty(current_price)
        if entry_targets[0][1] < min_qty:
            self.skipped_min_notional += 1
            return False

        # SL 계산
        if side == "long":
            stop_loss = current_price - sl_distance
        else:
            stop_loss = current_price + sl_distance

        self._pos_counter += 1
        self.position = SimPosition(
            id=self._pos_counter,
            side=side,
            leverage=self.config.leverage,
            timeframe=signal_tf,
            signal_type=signal["type"],
            signal_strength=signal.get("strength", 0.5),
            entry_targets=entry_targets,
            entry_filled=[],
            exit_targets=[],
            stop_loss=round(stop_loss, 2),
            atr=atr,
            atr_params=atr_params,
            margin=round(margin, 2),
            opened_at=ts,
        )

        # 잔고 차감
        self.balance -= margin
        self.margin_used += margin

        # 첫 tranche 즉시 체결
        first = entry_targets[0]
        first[2] = True
        fee = current_price * first[1] * self.config.fee_taker_pct / 100
        self.position.entry_filled.append((current_price, first[1]))
        self.position.total_fees += fee
        self.balance -= fee
        self.position.highest_price = current_price
        self.position.lowest_price = current_price

        # exit tranche 생성 (동적이면 진입 수 연동)
        actual_num = len(entry_targets)  # merge 후 실제 수
        self.tranche_dist[actual_num] += 1
        exit_targets = self._make_exit_targets(
            side, current_price, self.position.total_qty,
            atr, atr_params, actual_num, margin=margin
        )
        self.position.exit_targets = exit_targets

        return True

    def on_tick(self, price: float, ts: int) -> list[str]:
        """매 tick마다 체결 체크. 이벤트 목록 반환."""
        if self.position is None:
            return []

        pos = self.position
        events = []

        # 최고/최저 추적
        if price > pos.highest_price:
            pos.highest_price = price
        if price < pos.lowest_price:
            pos.lowest_price = price

        # 진입 tranche 체결
        for target in pos.entry_targets:
            if target[2]:  # already filled
                continue
            # offset 방향에 따라 체결 조건 분기:
            #   음수 offset (물타기): LONG은 price <= target, SHORT은 price >= target
            #   양수 offset (확인): LONG은 price >= target, SHORT은 price <= target
            first_entry = pos.entry_filled[0][0] if pos.entry_filled else target[0]
            is_confirmation = (pos.side == "long" and target[0] > first_entry) or \
                             (pos.side == "short" and target[0] < first_entry)
            if is_confirmation:
                should_fill = (pos.side == "long" and price >= target[0]) or \
                             (pos.side == "short" and price <= target[0])
            else:
                should_fill = (pos.side == "long" and price <= target[0]) or \
                             (pos.side == "short" and price >= target[0])
            if should_fill:
                target[2] = True
                fee = price * target[1] * self.config.fee_maker_pct / 100
                pos.entry_filled.append((price, target[1]))
                pos.total_fees += fee
                self.balance -= fee

                # exit tranche 재생성
                filled_exit_qty = sum(t[1] for t in pos.exit_targets if t[2])
                remaining = pos.total_qty - filled_exit_qty
                if remaining > 0:
                    actual_num = len([t for t in pos.entry_targets if t[2]])
                    new_exits = self._make_exit_targets(
                        pos.side, pos.avg_entry, remaining,
                        pos.atr, pos.atr_params,
                        min(actual_num, len(pos.exit_targets)) or actual_num,
                        margin=pos.margin
                    )
                    filled_exits = [t for t in pos.exit_targets if t[2]]
                    pos.exit_targets = filled_exits + new_exits

                    # SL 재계산
                    if self.config.pct_based_tp:
                        risk_amount = (self.balance + pos.margin) * (self.config.risk_pct / 100)
                        sl_dist = risk_amount / pos.total_qty
                        min_sl = pos.avg_entry * (self.config.min_sl_pct / 100)
                        sl_dist = max(sl_dist, min_sl)
                    else:
                        sl_dist = pos.atr * pos.atr_params["sl"]
                    if pos.side == "long":
                        pos.stop_loss = round(pos.avg_entry - sl_dist, 2)
                    else:
                        pos.stop_loss = round(pos.avg_entry + sl_dist, 2)

        # 퇴출 tranche 체결
        for i, target in enumerate(pos.exit_targets):
            if target[2]:
                continue
            should_fill = (pos.side == "long" and price >= target[0]) or \
                         (pos.side == "short" and price <= target[0])
            if should_fill:
                target[2] = True
                fee = price * target[1] * self.config.fee_maker_pct / 100
                pos.total_fees += fee
                self.balance -= fee
                if pos.side == "long":
                    pnl = (price - pos.avg_entry) * target[1]
                else:
                    pnl = (pos.avg_entry - price) * target[1]
                pos.realized_pnl += pnl
                events.append(f"TP{i+1}")

                # 트레일링 SL (TP1 후 본전, TP2 후 TP1가격)
                filled_exits = sum(1 for t in pos.exit_targets if t[2])
                if filled_exits == 1:
                    pos.stop_loss = round(self._breakeven_price(pos), 2)
                elif filled_exits == 2 and len(pos.exit_targets) > 1:
                    pos.stop_loss = round(pos.exit_targets[0][0], 2)

                # 전부 체결되면 종료
                if all(t[2] for t in pos.exit_targets):
                    self._close("take_profit", price, ts)
                    events.append("CLOSED:TP")
                    return events

        # 동적 트레일링 (TP2 이후)
        filled_exits = sum(1 for t in pos.exit_targets if t[2])
        if filled_exits >= 2 and pos.atr > 0:
            profit_distance = (pos.highest_price - pos.avg_entry) if pos.side == "long" else (pos.avg_entry - pos.lowest_price)
            trail_mult = 1.0 if profit_distance > pos.atr * 5 else 2.0
            if pos.side == "long":
                trail_sl = pos.highest_price - pos.atr * trail_mult
                if trail_sl > pos.stop_loss:
                    pos.stop_loss = round(trail_sl, 2)
            else:
                trail_sl = pos.lowest_price + pos.atr * trail_mult
                if trail_sl < pos.stop_loss:
                    pos.stop_loss = round(trail_sl, 2)

        # 손절 체크
        if pos.entry_filled:
            should_sl = (pos.side == "long" and price <= pos.stop_loss) or \
                       (pos.side == "short" and price >= pos.stop_loss)
            if should_sl:
                filled_tp = sum(1 for t in pos.exit_targets if t[2])
                reason = "breakeven" if filled_tp > 0 else "stop_loss"
                self._close(reason, price, ts)
                events.append(f"CLOSED:{reason.upper()}")

        # 시간 청산 (config.time_exit_hours, 0이면 비활성)
        if self.config.time_exit_hours > 0 and pos.entry_filled:
            age_hours = (ts - pos.opened_at) / 3600
            if age_hours > self.config.time_exit_hours:
                self._close("time_exit", price, ts)
                events.append("CLOSED:TIME")
            elif age_hours > self.config.time_exit_hours * 0.5:
                be = self._breakeven_price(pos)
                bump = pos.atr * 0.5
                if pos.side == "long":
                    new_sl = be + bump
                    if new_sl > pos.stop_loss:
                        pos.stop_loss = round(new_sl, 2)
                else:
                    new_sl = be - bump
                    if new_sl < pos.stop_loss:
                        pos.stop_loss = round(new_sl, 2)

        return events

    def _close(self, reason: str, price: float, ts: int):
        pos = self.position
        if pos is None:
            return

        # 미체결 수량 시장가 청산
        remaining_qty = 0
        for t in pos.exit_targets:
            if not t[2]:
                remaining_qty += t[1]
        for t in pos.entry_targets:
            if not t[2]:
                t[2] = True  # cancel

        if remaining_qty > 0 and pos.avg_entry > 0:
            if pos.side == "long":
                pnl = (price - pos.avg_entry) * remaining_qty
            else:
                pnl = (pos.avg_entry - price) * remaining_qty
            pos.realized_pnl += pnl
            fee = price * remaining_qty * self.config.fee_taker_pct / 100
            pos.total_fees += fee
            self.balance -= fee

        # 잔고 반환
        self.balance += pos.margin + pos.realized_pnl
        self.margin_used -= pos.margin
        self.daily_pnl += pos.realized_pnl

        # 거래 기록
        pnl_pct = (pos.realized_pnl / pos.margin * 100) if pos.margin > 0 else 0
        self.trades.append(SimTrade(
            side=pos.side,
            entry_price=pos.avg_entry,
            exit_price=price,
            quantity=pos.total_qty,
            leverage=pos.leverage,
            pnl=round(pos.realized_pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            fees=round(pos.total_fees, 2),
            reason=reason,
            duration_s=ts - pos.opened_at,
            timeframe=pos.timeframe,
            num_entry_tranches=pos.filled_entry_count,
            num_exit_tranches=sum(1 for t in pos.exit_targets if t[2]),
            signal_type=pos.signal_type,
        ))

        # drawdown
        equity = self.balance + self.margin_used
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = (self.peak_equity - equity) / self.peak_equity * 100 if self.peak_equity > 0 else 0
        if dd > self.max_drawdown:
            self.max_drawdown = dd

        self.position = None

    def summary(self) -> dict:
        total = len(self.trades)
        wins = sum(1 for t in self.trades if t.pnl > 0)
        losses = sum(1 for t in self.trades if t.pnl <= 0)
        total_pnl = sum(t.pnl for t in self.trades)
        total_fees = sum(t.fees for t in self.trades)
        avg_win = sum(t.pnl for t in self.trades if t.pnl > 0) / wins if wins > 0 else 0
        avg_loss = sum(t.pnl for t in self.trades if t.pnl <= 0) / losses if losses > 0 else 0
        avg_duration = sum(t.duration_s for t in self.trades) / total if total > 0 else 0

        # R:R
        avg_win_abs = abs(avg_win)
        avg_loss_abs = abs(avg_loss)
        rr = f"1:{avg_win_abs/avg_loss_abs:.1f}" if avg_loss_abs > 0 else "N/A"

        # 청산 사유별
        reasons = defaultdict(int)
        for t in self.trades:
            reasons[t.reason] += 1

        return {
            "name": self.config.name,
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "total_fees": round(total_fees, 2),
            "net_pnl": round(total_pnl - total_fees, 2),
            "final_balance": round(self.balance + self.margin_used, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "rr_ratio": rr,
            "avg_duration_min": round(avg_duration / 60, 1),
            "reasons": dict(reasons),
            "tranche_dist": dict(self.tranche_dist),
            "skipped_min_notional": self.skipped_min_notional,
        }


# ── 데이터 수집 ──────────────────────────────────────────────────

async def fetch_klines(symbol: str, interval: str, limit: int = 1000) -> pd.DataFrame:
    """Binance REST API에서 캔들 데이터 가져오기."""
    url = "https://fapi.binance.com/fapi/v1/klines"
    all_data = []
    end_time = None

    while len(all_data) < limit:
        batch = min(1500, limit - len(all_data))
        params = {"symbol": symbol, "interval": interval, "limit": batch}
        if end_time:
            params["endTime"] = end_time - 1

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if not data:
            break

        all_data = data + all_data
        end_time = data[0][0]  # oldest candle open_time

        if len(data) < batch:
            break

    rows = []
    for k in all_data:
        rows.append({
            "open_time": k[0] / 1000,  # seconds
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return pd.DataFrame(rows)


def resample_1m_to_tf(df_1m: pd.DataFrame, tf_minutes: int) -> pd.DataFrame:
    """1분봉을 상위 TF로 재구성."""
    if tf_minutes == 1:
        return df_1m.copy()

    rows = []
    i = 0
    n = len(df_1m)
    while i < n:
        # TF 경계에 맞추기
        start_ts = df_1m.iloc[i]["open_time"]
        boundary = (int(start_ts) // (tf_minutes * 60)) * (tf_minutes * 60)
        next_boundary = boundary + tf_minutes * 60

        batch = df_1m[(df_1m["open_time"] >= boundary) & (df_1m["open_time"] < next_boundary)]
        if len(batch) == 0:
            i += 1
            continue

        rows.append({
            "open_time": boundary,
            "open": batch.iloc[0]["open"],
            "high": batch["high"].max(),
            "low": batch["low"].min(),
            "close": batch.iloc[-1]["close"],
            "volume": batch["volume"].sum(),
        })
        i = batch.index[-1] + 1

    return pd.DataFrame(rows)


# ── 메인 시뮬레이션 ──────────────────────────────────────────────

async def run_backtest():
    print("=" * 70)
    print("  BTC/USDT 선물 백테스트: 현행 vs 신규 파라미터")
    print("=" * 70)

    # 1. 데이터 수집
    print(f"\n[1/4] Binance에서 최근 {DAYS}일 1분봉 데이터 수집 중...")
    needed_candles = DAYS * 24 * 60  # 7일 × 1440분
    df_1m = await fetch_klines(SYMBOL, "1m", limit=needed_candles)
    print(f"  → {len(df_1m)} 캔들 수집 완료 ({df_1m.iloc[0]['open_time']:.0f} ~ {df_1m.iloc[-1]['open_time']:.0f})")

    start_date = pd.Timestamp(df_1m.iloc[0]["open_time"], unit="s")
    end_date = pd.Timestamp(df_1m.iloc[-1]["open_time"], unit="s")
    print(f"  → 기간: {start_date.strftime('%Y-%m-%d %H:%M')} ~ {end_date.strftime('%Y-%m-%d %H:%M')} UTC")

    # 2. TF별 캔들 재구성
    print("\n[2/4] 다중 TF 캔들 재구성 중...")
    tf_full: dict[str, pd.DataFrame] = {}
    for tf, minutes in TF_MINUTES.items():
        tf_full[tf] = resample_1m_to_tf(df_1m, minutes)
        print(f"  → {tf}: {len(tf_full[tf])} 캔들")

    # 3. 시뮬레이션 설정
    configs = [
        SimConfig(
            name="% 기반 + 5초쓰로틀",
            risk_pct=2.0,
            dynamic_tranches=True,
            entry_offsets_trend=[0.0, -0.3, -0.6],
            entry_split_trend=[0.50, 0.30, 0.20],
            signal_throttle_sec=5,
            pct_based_tp=True,
            tp_margin_pcts=[3.0, 6.0, 10.0],
            tp_split=[0.50, 0.30, 0.20],
            margin_cap_pct=55.0,
            min_sl_pct=0.3,
            time_exit_hours=48,
        ),
        SimConfig(
            name="% 기반 + 3분쓰로틀",
            risk_pct=2.0,
            dynamic_tranches=True,
            entry_offsets_trend=[0.0, -0.3, -0.6],
            entry_split_trend=[0.50, 0.30, 0.20],
            signal_throttle_sec=180,
            pct_based_tp=True,
            tp_margin_pcts=[3.0, 6.0, 10.0],
            tp_split=[0.50, 0.30, 0.20],
            margin_cap_pct=55.0,
            min_sl_pct=0.3,
            time_exit_hours=48,
        ),
        SimConfig(
            name="% 기반 + 쓰로틀 없음",
            risk_pct=2.0,
            dynamic_tranches=True,
            entry_offsets_trend=[0.0, -0.3, -0.6],
            entry_split_trend=[0.50, 0.30, 0.20],
            signal_throttle_sec=0,
            pct_based_tp=True,
            tp_margin_pcts=[3.0, 6.0, 10.0],
            tp_split=[0.50, 0.30, 0.20],
            margin_cap_pct=55.0,
            min_sl_pct=0.3,
            time_exit_hours=48,
        ),
    ]

    # 4. 시뮬레이션 실행
    print(f"\n[3/4] 시뮬레이션 실행 중... ({len(configs)}개 설정)")

    for config in configs:
        print(f"\n  ▶ {config.name}")
        engine = BacktestEngine(config)

        # 시그널 스캔 주기: 30초마다 (1분봉 기준)
        scan_interval = 30  # seconds
        last_scan = 0

        tick_count = 0
        signal_count = 0

        for idx in range(len(df_1m)):
            row = df_1m.iloc[idx]
            ts = int(row["open_time"])
            price = row["close"]

            # 매 tick에 체결 체크
            engine.on_tick(price, ts)
            tick_count += 1

            # 주기적 시그널 스캔
            if ts - last_scan >= scan_interval:
                last_scan = ts

                # 각 TF의 "현재까지" 데이터로 시그널 생성
                tf_dfs = {}
                for tf, minutes in TF_MINUTES.items():
                    if tf == "1m":
                        continue
                    full = tf_full[tf]
                    current = full[full["open_time"] <= ts]
                    if len(current) >= 50:
                        tf_dfs[tf] = current.tail(500)

                for tf in SIGNAL_TIMEFRAMES:
                    if tf not in ENTRY_TIMEFRAMES:
                        continue
                    df_tf = tf_dfs.get(tf)
                    if df_tf is None or len(df_tf) < 30:
                        continue

                    signals = generate_signals(df_tf, SYMBOL, timeframe=tf)

                    for sig in signals:
                        if not (sig["type"].startswith("confluence_") or sig["type"].startswith("consensus_override")):
                            continue
                        sig["timeframe"] = tf
                        if engine.on_signal(sig, price, ts, tf_dfs):
                            signal_count += 1

            # 진행 상태 (10% 단위)
            if idx % (len(df_1m) // 10) == 0 and idx > 0:
                pct = idx / len(df_1m) * 100
                print(f"    {pct:.0f}% | 거래: {len(engine.trades)} | 잔고: ${engine.balance + engine.margin_used:.2f}")

        # 열린 포지션 강제 청산
        if engine.position is not None:
            last_price = df_1m.iloc[-1]["close"]
            engine._close("time_exit", last_price, int(df_1m.iloc[-1]["open_time"]))

        summary = engine.summary()
        config._summary = summary
        config._trades = engine.trades
        print(f"    완료 | 총 {summary['total_trades']}건 거래")

    # 5. 결과 비교
    print("\n" + "=" * 70)
    print("  [4/4] 결과 비교")
    print("=" * 70)

    headers = ["지표", *[c.name for c in configs]]
    rows = []

    for key, label in [
        ("total_trades", "총 거래 수"),
        ("wins", "승리"),
        ("losses", "패배"),
        ("win_rate", "승률 (%)"),
        ("total_pnl", "총 PnL ($)"),
        ("total_fees", "총 수수료 ($)"),
        ("final_balance", "최종 잔고 ($)"),
        ("max_drawdown", "최대 DD (%)"),
        ("avg_win", "평균 승리 ($)"),
        ("avg_loss", "평균 패배 ($)"),
        ("rr_ratio", "R:R 비율"),
        ("avg_duration_min", "평균 보유 (분)"),
    ]:
        vals = [str(c._summary[key]) for c in configs]
        rows.append([label, *vals])

    # 청산 사유
    all_reasons = set()
    for c in configs:
        all_reasons.update(c._summary["reasons"].keys())
    for reason in sorted(all_reasons):
        vals = [str(c._summary["reasons"].get(reason, 0)) for c in configs]
        rows.append([f"  {reason}", *vals])

    # 분할 분포
    placeholder = [""] * len(configs)
    rows.append(["분할 분포", *placeholder])
    all_tranche_keys = set()
    for c in configs:
        all_tranche_keys.update(c._summary["tranche_dist"].keys())
    for n in sorted(all_tranche_keys):
        vals = [str(c._summary["tranche_dist"].get(n, 0)) for c in configs]
        rows.append([f"  {n}분할", *vals])

    rows.append(["노셔널 미달 스킵", *[str(c._summary["skipped_min_notional"]) for c in configs]])

    # 테이블 출력
    col_widths = [max(len(row[i]) for row in [headers] + rows) + 2 for i in range(len(headers))]
    col_widths[0] = max(col_widths[0], 20)

    header_line = "".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(f"\n{header_line}")
    print("-" * sum(col_widths))
    for row in rows:
        line = "".join(str(v).ljust(w) for v, w in zip(row, col_widths))
        print(line)

    # 개별 거래 상세
    for config in configs:
        s = config._summary
        trades = config._trades
        print(f"\n{'=' * 70}")
        print(f"  {config.name} — 전체 거래 내역 ({len(trades)}건)")
        print(f"{'=' * 70}")
        print(f"{'#':>3} {'방향':>4} {'TF':>4} {'진입가':>10} {'청산가':>10} {'수량':>7} {'PnL':>8} {'PnL%':>7} {'수수료':>6} {'사유':>10} {'분할':>4} {'시간(분)':>8}")
        print("-" * 95)
        for i, t in enumerate(trades, 1):
            side = "롱" if t.side == "long" else "숏"
            pnl_str = f"{'+'if t.pnl>0 else ''}{t.pnl:.2f}"
            pct_str = f"{'+'if t.pnl_pct>0 else ''}{t.pnl_pct:.1f}%"
            reason_map = {"stop_loss": "손절", "take_profit": "익절", "breakeven": "본전", "time_exit": "시간"}
            reason = reason_map.get(t.reason, t.reason)
            dur = t.duration_s // 60
            tr = f"{t.num_entry_tranches}/{t.num_exit_tranches}"
            print(f"{i:>3} {side:>4} {t.timeframe:>4} ${t.entry_price:>9,.2f} ${t.exit_price:>9,.2f} {t.quantity:>7.3f} {pnl_str:>8} {pct_str:>7} {t.fees:>6.2f} {reason:>10} {tr:>4}  {dur:>6}")

    print("\n" + "=" * 70)
    print("  시뮬레이션 완료")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_backtest())
