# Offline test results — branch r4-testnet-findings
Run 2026-10-21 18:14 KST on the box, tree = this commit (parent 4588887).
```
LIVE_V6_REQUIRE_PYLINT=1 python -m pytest live_v6/tests -m "not testnet and not slow" -rs
live_v6/tests/test_faults.py::test_partial_fills_and_failed_final_exit[offline] PASSED [ 25%]
live_v6/tests/test_rate_limit.py::test_rest_418_ban_sends_nothing_not_even_protective_calls PASSED [ 42%]
live_v6/tests/test_rate_limit.py::test_rest_429_backoff_only_protective_calls_sent PASSED [ 43%]
live_v6/tests/test_rate_limit.py::test_rest_429_without_retry_after_uses_default PASSED [ 44%]
live_v6/tests/test_rate_limit.py::test_engine_429_blocks_entries_keeps_protection_never_flattens PASSED [ 44%]
live_v6/tests/test_rate_limit.py::test_engine_418_ban_sends_nothing_alerts_and_never_flattens PASSED [ 45%]
live_v6/tests/test_rate_limit.py::test_startup_pacing_waits_when_weight_high PASSED [ 46%]
live_v6/tests/test_static.py::test_pylint_w0101_unreachable PASSED       [ 48%]
live_v6/tests/test_stop_monitor.py::test_stop_cancelled_during_429_backoff_replaced_at_once PASSED [ 49%]
live_v6/tests/test_stop_monitor.py::test_stop_expired_order_trade_update_replaced PASSED [ 49%]
live_v6/tests/test_stop_monitor.py::test_own_cancel_is_not_a_lost_stop PASSED [ 50%]
live_v6/tests/test_stop_monitor.py::test_replacement_fails_during_429_then_mark_cross_closes_reduce_only PASSED [ 50%]
live_v6/tests/test_stop_monitor.py::test_stop_lost_during_418_queued_and_sent_on_first_tick_after_ban PASSED [ 51%]
live_v6/tests/test_stop_monitor.py::test_stop_lost_and_mark_cross_during_418_close_queued_then_sent_at_unban PASSED [ 52%]
===================== 163 passed, 53 deselected in 29.19s ======================
python -m pytest live_v6/tests -m slow   → 2 passed, 214 deselected in 164.46s
python -m pytest live_v6/tests -m testnet --collect-only → 51/216 collected
```
