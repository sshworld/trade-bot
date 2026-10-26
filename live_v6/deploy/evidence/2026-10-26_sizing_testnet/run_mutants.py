import subprocess, sys, json, re, pathlib
R = pathlib.Path("/workspace/sizing-minorder-3pct"); 
M = [  # (id, boundary, file, old, new)
 ("M01","3% cap `>` -> `>=` (<= vs <)","live_v6/sizing.py","if loss_frac > p.min_order_loss_cap + 1e-12:","if loss_frac >= p.min_order_loss_cap + 1e-12:"),
 ("M02","3% cap 0.03 -> 0.031","live_v6/sizing.py","min_order_loss_cap: float = 0.03 ","min_order_loss_cap: float = 0.031 "),
 ("M03","3% cap 0.03 -> 0.029","live_v6/sizing.py","min_order_loss_cap: float = 0.03 ","min_order_loss_cap: float = 0.029 "),
 ("M04","5% total cap `>` -> `>=` (sizing)","live_v6/sizing.py","if sum(o[\"risk_frac\"] for o in open_positions) + rf > cap + 1e-12:","if sum(o[\"risk_frac\"] for o in open_positions) + rf >= cap + 1e-12:"),
 ("M05","5% total cap 0.05 -> 0.051","live_v6/sizing.py","total_risk_cap: float = 0.05 ","total_risk_cap: float = 0.051 "),
 ("M06","5% total cap 0.05 -> 0.049","live_v6/sizing.py","total_risk_cap: float = 0.05 ","total_risk_cap: float = 0.049 "),
 ("M07","2.5% q0 cap 0.025 -> 0.026","live_v6/sizing.py","portfolio_risk_cap: float = 0.025 ","portfolio_risk_cap: float = 0.026 "),
 ("M08","2.5% q0 cap 0.025 -> 0.024","live_v6/sizing.py","portfolio_risk_cap: float = 0.025 ","portfolio_risk_cap: float = 0.024 "),
 ("M09","open-risk `>` -> `>=` (engine 2nd pass, 2.5%/5%)","live_v6/engine.py","+ sz.risk_frac > sz.cap_frac + 1e-12:","+ sz.risk_frac >= sz.cap_frac + 1e-12:"),
 ("M10","engine 2nd-pass cap tolerance: cap + 1e-12 -> cap + 1e-3 (cap loosened)","live_v6/engine.py","+ sz.risk_frac > sz.cap_frac + 1e-12:","+ sz.risk_frac > sz.cap_frac + 1e-3:"),
 ("M11","sizing cap tolerance 1e-12 -> 1e-3 (loosened)","live_v6/sizing.py","+ rf > cap + 1e-12:","+ rf > cap + 1e-3:"),
 ("M12","margin 90% `>` -> `>=` (<= vs <)","live_v6/sizing.py","if need > available * D(p.margin_use):","if need >= available * D(p.margin_use):"),
 ("M13","margin 90% -> 91%","live_v6/sizing.py","margin_use: float = 0.9 ","margin_use: float = 0.91 "),
 ("M14","margin 90% -> 89%","live_v6/sizing.py","margin_use: float = 0.9 ","margin_use: float = 0.89 "),
 ("M15","price buffer 2% -> 3% (param, both sites)","live_v6/sizing.py","price_buffer: float = 0.02 ","price_buffer: float = 0.03 "),
 ("M16","price buffer 2% -> 1% (param, both sites)","live_v6/sizing.py","price_buffer: float = 0.02 ","price_buffer: float = 0.01 "),
 ("M17","precheck worst-price buffer only: 0.98 -> 0.97","live_v6/sizing.py","    worst = ref * (1 - D(p.price_buffer))\n    if qty * worst < rules.min_notional:","    worst = ref * (1 - D(p.price_buffer) - D('0.01'))\n    if qty * worst < rules.min_notional:"),
 ("M18","precheck worst-price buffer only: 0.98 -> 0.99","live_v6/sizing.py","    worst = ref * (1 - D(p.price_buffer))\n    if qty * worst < rules.min_notional:","    worst = ref * (1 - D(p.price_buffer) + D('0.01'))\n    if qty * worst < rules.min_notional:"),
 ("M19","size_entry worst-price buffer only: 0.98 -> 0.97","live_v6/sizing.py","    worst = ref * (1 - D(p.price_buffer))\n    q0 = floor_to","    worst = ref * (1 - D(p.price_buffer) - D('0.01'))\n    q0 = floor_to"),
 ("M20","size_entry worst-price buffer only: 0.98 -> 0.99","live_v6/sizing.py","    worst = ref * (1 - D(p.price_buffer))\n    q0 = floor_to","    worst = ref * (1 - D(p.price_buffer) + D('0.01'))\n    q0 = floor_to"),
 ("M21","minNotional precheck `<` -> `<=` (qty*worst == minNotional rejected)","live_v6/sizing.py","if qty * worst < rules.min_notional:","if qty * worst <= rules.min_notional:"),
 ("M22","minNotional precheck `<` -> `<` +1 tick (needs one step more)","live_v6/sizing.py","if qty * worst < rules.min_notional:","if (qty - step) * worst < rules.min_notional:"),
 ("M23","q0 path minNotional `>=` -> `>` (q0*worst == minNotional goes to qty_floor)","live_v6/sizing.py","q0 * worst >= rules.min_notional:","q0 * worst > rules.min_notional:"),
 ("M24","q_min ceil_to -> floor_to (-1 tick below minNotional)","live_v6/sizing.py","q_min = max(ceil_to(rules.min_notional / worst, step)","q_min = max(floor_to(rules.min_notional / worst, step)"),
 ("M25","q_min +1 tick (one step more than needed)","live_v6/sizing.py","q_min = max(ceil_to(rules.min_notional / worst, step)","q_min = max(ceil_to(rules.min_notional / worst, step) + step"),
]
sel = sys.argv[1:] 
res = {}
for mid, bd, f, old, new in M:
    if sel and mid not in sel: continue
    p = R/f; src = p.read_text()
    if src.count(old) != 1:
        res[mid] = {"boundary": bd, "error": f"pattern count {src.count(old)}"}; print(mid, "PATTERN ERR", src.count(old)); continue
    p.write_text(src.replace(old, new))
    try:
        r = subprocess.run("cd %s && LIVE_V6_REQUIRE_PYLINT=0 /workspace/.venv-live6/bin/python -m pytest live_v6/tests -m 'not testnet and not slow' -q -rf --maxfail=8 -p no:cacheprovider $DESEL 2>&1 | grep -E '^(FAILED|ERROR)|passed|failed'" % R, shell=True, capture_output=True, text=True, timeout=600).stdout
    finally:
        p.write_text(src)
    fails = [re.sub(r"^FAILED live_v6/tests/", "", l).split(" - ")[0] for l in r.splitlines() if l.startswith("FAILED")]
    res[mid] = {"boundary": bd, "killed": bool(fails), "failing": fails}
    print(mid, "KILLED" if fails else "SURVIVED", len(fails), fails[:3], flush=True)
json.dump(res, open("/workspace/mut/result%s.json" % ("_" + "_".join(sel) if sel else ""), "w"), indent=1)
