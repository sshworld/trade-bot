# LIVE deploy — 4d8d16c `live_v6/` → `live_v6-live` (mainnet) — 2026-10-26

Change: `qty_zero` skip label, one `bar_close` INFO line per completed 4h bar per model, `entered SYM long qty …` INFO line,
`runner.setup_logging()`; **no trading-logic change** (branch `fix-skip-label-barlog`, base e2695d9). TA approved the live deploy;
성헌 standing OK (10/21) for deploys after TA PASS. Hand deploy, same procedure as e2695d9 (`DEPLOY_950438b.md` §1–§4).
Timing rule kept: start 09:16 KST (≥15 min after the 09:00 KST close), restart 09:17 KST, well before 12:45 KST.
No orders placed, nothing deleted on the server.

| item | value |
|---|---|
| code | commit `4d8d16c` (tree `59d8ed0f`), `live_v6` subtree `8c4704d8be212203360dd0d7669fbff5ec92e25c` |
| archive | `git archive --format=tar 4d8d16c live_v6` sha256 `9a1daab91d9d90950ab60338fd58374925762625357060856408d3814eb06bc5` (same on box and VPS after upload, 716800 bytes) |
| release path | `/opt/tradebot/app/4d8d16c` (`current` → it; `/opt/tradebot/app/DEPLOYED` = `4d8d16c`) |
| before | `/opt/tradebot/app/e2695d9`, MainPID **60556** (since 2026-10-21 20:29:56 UTC), NRestarts **0**, active/running |
| restart | `systemctl restart live_v6-live` at **09:17:09 KST** (00:17:09 UTC); active again 09:17:15 KST |
| after | MainPID **108050**, NRestarts **0**, active/running (re-checked 09:18:14 KST) |
| rollback target | `/opt/tradebot/app/e2695d9` (then 2eb429b) — both untouched |
| rollback needed | **no** |

## 1. Pre-checks (09:16–09:17 KST)
* Box offline suite on the archived 4d8d16c tree, `LIVE_V6_REQUIRE_PYLINT=1 pytest -m "not testnet and not slow"` → **203 passed, 1 skipped, 53 deselected**, 0 failed.
* VPS §1b HEARTBEAT_URL: unit env 0, live.env 0, telegram.env 0, drop-in (`10-ci-halt-guard.conf`) 0, heartbeat.env 1, running bot env 0.
* VPS §1c clock: NTPSynchronized yes, offset 0.066 ms OK.
* VPS §1d: `live_v6-live` active, PID 60556, NRestarts 0; no `CI_HALTED`; intents `{}`, not halted, `health.ok` true;
  `last_bar_close` 1792972800000 (= 09:00 KST close), all 6 models `last_open` = boundary − 4h.
  State backups `/root/mainnet.json.bak-20261026T001635Z` and `/root/mainnet.json.bak-20261026T001709Z` (right before the swap).
* Import check of the staged tree as `tradebot` (PYTHONDONTWRITEBYTECODE=1): `import ok, tick calls on_bar_close`, `setup_logging` present; 0 `__pycache__`.
* `setup_logging()` self-test on the VPS (as `tradebot`): `INFO live_v6.engine bar_close …` is emitted, `httpx` INFO is not.
  `LIVE_V6_LOG` unset in the bot env → default INFO.

## 2. Positions / orders (`/opt/tradebot/verify_stops_live.py`, read-only)
| when | pass | positions | open orders | open algo orders |
|---|---|---|---|---|
| pre (09:16:35 KST, and again 09:17:08 right before restart) | true (exit 0) | 0 | 0 | 0 |
| post (09:18:14 KST) | true (exit 0) | 0 | 0 | 0 |

Flat before and after → no exchange stop to preserve. Margin/leverage per coin (unchanged by the restart):
BTC ISOLATED 5x, ETH ISOLATED 20x, SOL ISOLATED 20x, BNB ISOLATED 10x, XRP ISOLATED 20x, DOGE ISOLATED 20x.

## 3. Post-restart verification (§4)
Journal (secrets-free excerpt, UTC):

    00:17:09 systemd: Stopping live_v6-live.service ...
    00:17:13 python[60556]: WARNING live_v6.notify [tg:live] ⏹ live_v6 종료 (거래소 손절은 그대로 유지)
    00:17:15 systemd: live_v6-live.service: Deactivated successfully. / Started live_v6-live.service
    00:17:16 python[108050]: WARNING live_v6.notify [tg:live] ▶️ live_v6 시작 · BinanceREST(https://fapi.binance.com) · 포지션 0개 · 진입 가능

* Since restart: Traceback/CRITICAL/ERROR/모델 재구성 = 0; `HTTP Request` = 0; `live_v6.deadman` = 0.
* State: `last_bar_close` 1792972800000 = boundary, all 6 `last_open` 1792958400000 (= boundary − 4h), `health.ok` true,
  `blocks` [], not halted, intents `{}` → **OK: caught up**.
* New bot env HEARTBEAT_URL count 0. Telegram: the usual ⏹ / ▶️ messages, `sent: true` in `alerts-live.jsonl`; no other alerts.
* `heartbeat_ping.sh` unchanged (installed copy `cmp`-identical to the 4d8d16c release copy); `heartbeat-ping.timer` active.
* `bar_close` lines since restart: **0** (expected — the first completed 4h bar after the restart closes at 13:00 KST).

## 4. Deployed files vs git tree
Server: `cd /opt/tradebot/app/4d8d16c && find . -type f -not -path '*/__pycache__/*' | LC_ALL=C sort | xargs sha256sum`.
Box: same over a fresh extract of `git archive 4d8d16c live_v6`; file list compared with `git ls-tree -r --name-only 4d8d16c live_v6`.
Result: **88 files on the server, 88 in the git tree, 88/88 sha256 identical, 0 mismatched, 0 missing, 0 extra** (`diff` empty).
0 `__pycache__` dirs, 0 non-regular entries.
Rollback releases untouched (sha256 over `find . -type f | LC_ALL=C sort | xargs sha256sum`, before = after):
`0d82b19` `f04c2472…3387`, `2eb429b` `853765a3…44af`, `e2695d9` `c6396934…0f38`.

Server manifest (sha256, path relative to the release):

    862263fa1f46c20f0d1e4dac5ffcc75abd55c08211b2c3864c5f8764b9d87793  live_v6/.gitignore
    1330c493e3154bcaa8aadd074e9e0f3fcb23c706ac36be6421d1d7eaf3c277a3  live_v6/README.md
    c41db6f8c106ac938220583d983d1aecee9611f3ce1df245f5ed14cd4459cb04  live_v6/__init__.py
    c135405bf15457e30195783351b92d413ad992327c67ea8a45954e11e7315f25  live_v6/__main__.py
    fbc4e47fdbffa8c0a3c6be78996905c78995d74177e66ac10a3b7fd11567f24a  live_v6/deadman.py
    ee32a16c62a4a5a6437703d7920f284d1450ab1e53e99500b33cf3de67350c92  live_v6/deploy/DEPLOY.md
    8332140fe732bcba7d1e1863cfebeabd860288eb11ac841bf8ca91db73d62f9e  live_v6/deploy/DEPLOY_950438b.md
    1bc8c56bd6127a6a33932435dd1e38320219c8d82b13b455ccd9eba7c28f3e66  live_v6/deploy/evidence/2026-10-21_R4_429_418_decision.md
    4772a5dfb555872024605dbd384fac736b3d78050eac7fda81cc62a573404cab  live_v6/deploy/evidence/2026-10-21_R4_offline_results.md
    7ed9ab744f0f516f92dcf8933884097efdf3a52ae63851a844ceeab1344b1a20  live_v6/deploy/evidence/2026-10-21_R4_proposed_test_changes.diff
    312a1c202dd51d5f0d5c74858b3de0a083d96f006be3db7e880fa0d2e5cc450d  live_v6/deploy/evidence/2026-10-21_R4_testnet51_progress.md
    33c0afc0957bcfe33f9cab636816a73acb5b48f35f21f367bfc995495585df30  live_v6/deploy/evidence/2026-10-21_R4_testnet_failures_rootcause.md
    a472d98ea8883edb184a3c14cb679f43b787ddcb2b41ed685a2b7ab4b50e88a2  live_v6/deploy/evidence/2026-10-21_R4_unknown_position.md
    6a568943b7b70614b08e265152c5d3380591a84bd6fe76c2643e14a5952bd379  live_v6/deploy/evidence/2026-10-22_bnb_leverage_readback.md
    99deae7f5b5d88c2610545636b81f65af93b2d9546affa0604dcb3d2cae2c1ff  live_v6/deploy/evidence/2026-10-22_leverage_readback.md
    dc84e806428c2563805fe0766b0eccd99e579a7c5a8686b85cffb60bdb1e2ccb  live_v6/deploy/evidence/2026-10-26_skip_label_barlog.md
    eb7a808ef6d6000498ebd09ae510b8035c75ec24b10b83a4d5db6c7524a31642  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/common.py
    d954f530f3b24dd76ab46ca8b91b8f9451fd331c2efbcdb4b759d3506091298d  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/fetch_vps.py
    2501105fb6f18bc459cf5205a10939e8de8d1d7baa249463cd22508b0bad99fa  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/replay_out.txt
    1c39241541dd8226872e9cf79ab170dbd4989f4c409090aa2852f84d13699998  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/replay_recent.py
    a5e0edaad33126ca232a66a81ae435b14ad4b6081f7175b88fcd83b4c9fe9ed2  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/replay_results.json
    8bfa74fd1d6a7010f3d08a573439e430fc60b95a9ed7d14c88c1d0531c4fe70f  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/table_A.json
    eba73bb62ab31350a6579aaa19c4ba4489ece2ab554c090c34501ad89ff64c51  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/table_A.py
    941adb84541724ab1ef3ecfcf7adbe3ede02de519b20c792141f83f3204ce63e  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/table_A.txt
    8162dd32cd517c29337013fd77bb1b6c6ca435ee81a4948c74731fd8e765f1a3  live_v6/deploy/evidence/2026-10-26_skip_label_barlog/table_A_rule3.json
    3d0fd1da16f3519ff515b7b899e27e7dc39cdd339997782c2a3f483e0459e950  live_v6/deploy/heartbeat_ping.sh
    12647e724b3d677f925c95eea323e63da39c40d1c55471551161017d5e4defea  live_v6/deploy/live_v6.service
    521859f702e723b9b2ecbb7dfd86e8b45ede3895b0945820ff9b43becd50f660  live_v6/engine.py
    afcf900caba35b9acc7b739df41f41d0d798407d5d033b029d665bf8ec108e0d  live_v6/events.py
    f7302f66dde585b5ffa0b80033000ec6da50c6e5a2590d6bb426548698ee0951  live_v6/exchange.py
    e4625bb2abb69437832b59fd885f499c3560491c113997321b579d8ddb85b6a1  live_v6/notify.py
    3ef9dc588ed4fded26c5c865f4b4ed58d6b0407ceb2de696cf8312d0a802be02  live_v6/pytest.ini
    e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  live_v6/replay/__init__.py
    6fa8d7856c9f984b4c8fefcf1c1a3920827a8d6d3cb0ed730c2addfbf7676f4a  live_v6/replay/data.py
    e6f148b5e5843083efbcfad052095015ee9582cee81f055745526d2be372a866  live_v6/replay/export_1m.py
    38ee13d5c9e7143661b77e46f94f2ed66b382a8b5d086f79df1fe9895455c16c  live_v6/replay/export_data.py
    29aea6116e7cd07bac65c892a1cd5be0c7cb0f0395fb1d52498b3f8ec04f7713  live_v6/replay/replay.py
    d5923856641cff77b01a025fb031ffd02fa46643ac742538e4b7aa8ed3f06fc0  live_v6/replay/replay_h7t.py
    aecd4e515e75c63f8f572816f1313b83cec517fbc1a6df7e88a250a21d4b949d  live_v6/replay/results/replay_default-order_research-fill.json
    c887117b6dc820b720abfe778eb753e4d4369f53e116df10565cce79437eca00  live_v6/replay/results/replay_h7t.json
    d3d1e4481f45bcbc67d134267513a82a300f4f182c96d55343a40a7666b07acb  live_v6/replay/results/replay_research-order_research-fill.json
    2702ada1de40a7c247f2286ba82fffe5ee32a7ba6acfc67b4f7b251339cea79d  live_v6/replay/results/replay_research-order_trigger-fill.json
    1383a5762b678924af0ca6ca08f2714a2f63290fef60faa0fa325d023c61f63b  live_v6/replay/sim_exchange.py
    6b37c55a8ef325885624d4fe17d3597e76b8ef499f118802d45d39507f47b363  live_v6/reports/gate_sigkill_mid_entry.json
    47ded1f6d98b3c289afa1d46d3bb17ef3d36ce62a20656932e6eefc61da3f7fd  live_v6/reports/gate_sigkill_steady.json
    5c5e7f4c0acf3411f67827070e5f90f993db24b462ebb662c2ecf4f257f2a46c  live_v6/reports/h7t_killed_after_entry.json
    678e3946f4ece7ccbb35943e5a518a3f7af1b776fd3ed2d8ffdf52a97ca8e0c7  live_v6/requirements-dev.txt
    a3a6640656a257332785bb6ba934ef1ef54fa28213ba7b6c6b32760740f46ac3  live_v6/requirements.txt
    73a0baf9b069b4d5be532c6f746c71459bfa1ccee78199c68778be0ef9dfcc07  live_v6/rules.py
    6778eb27a26287bdfc5c72045392e733292d9143a60e8c552a1118b7a495a132  live_v6/runner.py
    1479a40f89bda222b61c94eb715ed4747b7002a07327ab52a9b49c1b34b8d7ff  live_v6/sizing.py
    1e34ea3e770f00500b16cc71b8af11e78df9e45a618e158a3e13be9b1421a655  live_v6/store.py
    16bc4abbc2bd0fed3bc99579c29139a178371540695da60e76797fea647c4627  live_v6/strategies/__init__.py
    7c63991736987303e5e283d9577633f2241e7b754547c8e94277d4620e1f4779  live_v6/strategies/base.py
    556e91508b5d44f27b0a6502bf9ed63757aca1a07d0b71457d5a0ca6d97d433b  live_v6/strategies/h7t.py
    c0864321db0d9a47df48a5249ff3dba6c4ad0ff711fb73dbc467b1ad82794922  live_v6/strategies/v6_h7.py
    7edd73c37b5c1828938851ee0550e2354197f857da589798605b11ec030db4cd  live_v6/strategy.py
    7794ab93b806302c055e94615c791eab4aca8ade867b5de9ec552fc96734d3ad  live_v6/stream.py
    e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  live_v6/tests/__init__.py
    978b8ec7b63b4d7d95929edac0b01a32075e03cc0b682f08b95f36ebf751e5fd  live_v6/tests/bot_proc.py
    a283ceed18675f79842276e5148a946d52929741963fa835db730c59f7baedd7  live_v6/tests/conftest.py
    8167bc28c925d6bd78a756d67cfff40ef181aab58c23ec744fadfe49b23c80e5  live_v6/tests/drill_leverage_readback.py
    db4c0dcc72a7424d50377cc9469de8a18b5991f8230a76a04100ad8aca6c04a9  live_v6/tests/drill_stop_cancel.py
    4286b0ba03a428888af42e9d25ae5a99cb1a3c8b55d64c6c74bcb4dc8d02af07  live_v6/tests/fakes.py
    0248632afb395f5e0376691a42992461a65ef1a6aac4e3dce96711decb83d2d4  live_v6/tests/test_bar_close_live.py
    4f980a42ff3757fb0f0b9cdea85697a39e680f2594ed0ee896e99ab7fb808b26  live_v6/tests/test_deadman.py
    0d6af7b91de65235d5c5617ac7e9c7f3c348aa92d441aba17ebb23c5dc7900f0  live_v6/tests/test_faults.py
    50868e2245c54a154c4c7ee72d3b7affe9e82fbd24397cc6514b8e99119a66fa  live_v6/tests/test_gate_sigkill.py
    1a2a7263ffa903ac4e5da70e443113e06a6ea3fb436e58cade875fd3f49ab04e  live_v6/tests/test_h7t.py
    b35fcd382190d76b59f84ab956b790b6724942ae466d68ca37aa0f0fb760933d  live_v6/tests/test_heartbeat_script.py
    1a9ea37ffd5d4d1e31572d8db430c9476e2d6dd1529ba88cf75a2458e399d8db  live_v6/tests/test_leverage_failsafe.py
    53e04d9068aa9dcfb7199a5c7f40b9da49d577d6295e6cc062a0db5f9aa4827d  live_v6/tests/test_leverage_readback.py
    c59394795a4ab4036b319f911019c5dd5c832767c92a9a14030254bf44353d81  live_v6/tests/test_notify.py
    3dd75846582548e9b53c3c709d9993a73519d8316060323525ed53762fae3ca0  live_v6/tests/test_rate_limit.py
    084757426e906733bfa84cec13e78aced8f44b68a9eab38941975239a57389e8  live_v6/tests/test_runner_e2e.py
    f06c4a9b29d00d93073104c33ff1b45fb2fae21141f7f1183788479221cce199  live_v6/tests/test_skip_label_barlog.py
    dc8b4d8272a068a23c966ea8aaeb85719d2a0ebdacf52362dba17eebaa5e7f64  live_v6/tests/test_static.py
    254cc58eb5caac9ff0c52a2bed50f95a7c7c7bb7cfc681a0237191670fd9e199  live_v6/tests/test_stop_monitor.py
    267c3af5a18bc2d85b5a316bfdf73181f3cdc6699a131b4d5feda3e9af6869bd  live_v6/tests/test_streams.py
    7dfe6c5e63b101f1828f6d9993e1a60871ce81577295c9793c55b87c8cfdda75  live_v6/tests/test_tgcmd.py
    030d0685266c35edcafb84b24c7da648498e82ef2d792fe7163b760094face9c  live_v6/tests/test_token_logs.py
    8249e6de2ab37404011618e33c8c55c23f3957f5eb03b0eaa0bc6848235271ad  live_v6/tests/test_units.py
    6b8fd2de11bd3551c58a0957e5b9bac909c26ac2ff7c09c63ce6cf2916ebb875  live_v6/tests/test_unknown_position.py
    78a915d04969839c2fa81b043913ef631eee51dfef0ab1aa43bd60cfbe005013  live_v6/tgcmd.py
    3b6b8d318219a2e246e718e7fc119ea05480f726466c7c67d4ce4d13d7de29a6  live_v6/tools/adopt_position.py
    1955c8a0c32538cf2621b099fd4e130da0cf9d423fb45bb40c162cd003fe3512  live_v6/tools/tg_e2e.py
    c90cf8aed2e6600fe6aabc69494c8e894300843d95173d8f001a2593e3f8be12  live_v6/tools/verify_stops.py
    2d8c0dc6be44d5a907e6773442b6da5c5f59f1230d7f9bc59ab950bf404881aa  live_v6/tools/ws_check_mainnet.py

## 5. First-close check (13:00 KST 10/26) — command
```bash
sudo journalctl -u live_v6-live --since "2026-10-26 04:00:00" --until "2026-10-26 04:30:00" --no-pager | grep ' bar_close '
# any time range:  sudo journalctl -u live_v6-live --since "-12 hours" --no-pager | grep ' bar_close '
```
Expect 6 lines (h7t and the other 5 models) per 4h close, i.e. about 6 lines/day/model; format
`bar_close model=h7t bar_open=<KST> SYM=<no_signal|in_position|entered|skip:<reason>|exit:<reason>> …`.
(The journal clock is UTC; 13:00 KST = 04:00 UTC.)

## 6. Rollback to e2695d9 (as ops on the VPS; planned use only ≥15 min after / ≥20 min before a 4h close, except a crash loop)
```bash
sudo python3 /opt/tradebot/verify_stops_live.py; echo exit=$?          # must be 0 before the restart
sudo cp -p /var/lib/live_v6-live/mainnet.json /root/mainnet.json.bak-$(date -u +%Y%m%dT%H%M%SZ)
sudo ln -sfn /opt/tradebot/app/e2695d9 /opt/tradebot/app/current.new && sudo mv -T /opt/tradebot/app/current.new /opt/tradebot/app/current
echo e2695d9 | sudo tee /opt/tradebot/app/DEPLOYED
sudo systemctl restart live_v6-live && sleep 45
systemctl show live_v6-live -p ActiveState,MainPID,NRestarts; readlink -f /opt/tradebot/app/current   # → /opt/tradebot/app/e2695d9
# then the §4 checks of DEPLOY_950438b.md (journal clean, caught up, verify_stops exit 0, HEARTBEAT_URL 0)
```
State format unchanged. Rollback was **not** needed.
