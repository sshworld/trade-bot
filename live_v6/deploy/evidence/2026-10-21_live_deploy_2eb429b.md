# LIVE deploy — 2eb429b `live_v6/` → `live_v6-live` (mainnet) — 2026-10-21

Path: hand deploy per `live_v6/deploy/DEPLOY_950438b.md` (same procedure as 0d82b19), Option B approved by TA 21:45 KST
(TA final PASS 21:42 KST; 성헌 standing OK for deploys after TA PASS). The CI pipeline was not used (not enabled on main;
live approval in the GitHub UI is 성헌-only). No orders placed, nothing deleted on the server.

| item | value |
|---|---|
| code | commit `2eb429b` (tree `31f81054`), `live_v6` subtree `0694b1ca46acc23223a4eeaefa973240f386a5f0` |
| archive | `git archive --format=tar 2eb429b live_v6` sha256 `bd647b2381291f359cff1c6ecdd33e73c81c5816697e7fc55efc7a71f687060f` (same on box and VPS after upload) |
| release path | `/opt/tradebot/app/2eb429b` (`current` → it; `/opt/tradebot/app/DEPLOYED` = `2eb429b`) |
| previous | `/opt/tradebot/app/0d82b19` (PID 36258, NRestarts 0) — kept intact, `.ta_pass_verified` untouched |
| restart | `systemctl restart live_v6-live` at 21:48:49 KST (12:48:49 UTC); active again 21:48:55 KST |
| new process | MainPID **51227**, NRestarts **0**, ActiveState active/running (re-checked 21:50:11 KST) |

## 1. Pre-checks
* Box offline suite on the archived tree, `LIVE_V6_REQUIRE_PYLINT=1 pytest -m "not testnet and not slow"`:
  at 21:46 KST wall clock → 162 passed, 1 failed: `test_notify.py::test_daily_settlement_and_heartbeat`. Cause = the test
  itself depends on the wall clock: when it runs < 4 h before KST midnight, the 4 h heartbeat (`heartbeat_s`) falls due
  inside its "not before heartbeat_s" step (2 == 1). The same test fails the same way on the currently-live `0d82b19`
  tree, and the test file is unchanged 0d82b19→2eb429b (test-only issue, not runtime). Re-run of the full suite under
  `faketime '2026-10-21 15:00:00'` → **163 passed, 53 deselected** (pylint W0101 test ran). Follow-up: make the test use
  a fixed t0 (not done here — the deployed tree must equal 2eb429b).
* VPS (§1b) HEARTBEAT_URL: unit env 0, live.env 0, telegram.env 0, drop-in 0, heartbeat.env 1, running bot env 0.
* VPS (§1c) clock: NTPSynchronized yes, offset 0.015 ms OK.
* VPS (§1d) `live_v6-live` active, PID 36258, NRestarts 0; no `CI_HALTED`; state intents `{}`, not halted.
  State backup `/root/mainnet.json.bak-20261021T124827Z`.
* Import check of the staged tree as `tradebot` (no bytecode written): `import ok, tick calls on_bar_close`.

## 2. Positions / orders snapshot (`/opt/tradebot/verify_stops_live.py`, read-only)
| when | pass | positions | open orders | open algo orders |
|---|---|---|---|---|
| pre (21:48:27 KST, and again right before restart) | true (exit 0) | 0 | 0 | 0 |
| post (≈21:49:45 KST) | true (exit 0) | 0 | 0 | 0 |
Flat before and after → no exchange stop to preserve.

## 3. Post-restart verification (§4)
* Journal since restart: `▶️ live_v6 시작 · BinanceREST(https://fapi.binance.com) · 포지션 0개 · 진입 가능`;
  Traceback/CRITICAL/ERROR/모델 재구성 = 0; `HTTP Request` lines = 0; `live_v6.deadman` lines = 0.
  (Old process logged the normal `user stream error: ConnectionClosedOK` + `⏹ live_v6 종료 (거래소 손절은 그대로 유지)` on SIGTERM.)
* State: `last_bar_close` 1792584000000 (= 12:00 UTC / 21:00 KST boundary), all 6 `last_open` 1792569600000
  (= boundary − 4h), `health.ok` true, `blocks` [], not halted → **OK: caught up**.
* New bot env HEARTBEAT_URL count 0. Telegram (mainnet only): the usual ⏹ stop / ▶️ start messages, `sent: true`
  in `/var/log/tradebot/alerts-live.jsonl`; no other alerts.
* `heartbeat_ping.sh`: unchanged between 0d82b19 and 2eb429b (installed sha256 `3d0fd1da…` = release copy), so §5 was not
  needed; `heartbeat-ping.timer` active, last run 21:49:09 KST finished OK.

## 4. Deployed files vs git tree (TA condition 1)
Server: `cd /opt/tradebot/app/2eb429b && find . -type f -not -path '*/__pycache__/*' | sort | xargs sha256sum`.
Box: same over `git archive 2eb429b live_v6` extracted; archive file list = `git ls-tree -r --name-only 2eb429b live_v6`.
Result: **72 files on the server, 72 in the git tree, 72/72 sha256 identical, 0 missing, 0 extra** (`diff` empty).
Exclusions: pattern `__pycache__/` only — **0 such directories exist** (unit has ProtectSystem=strict, no bytecode is
written). State/logs live outside the release (`/var/lib/live_v6-live`, `/var/log/tradebot`). No symlinks/other
entries in the release; the only top-level entry is `live_v6/`. (Mode note: git marks `deploy/heartbeat_ping.sh` 100755;
the release copy is not executed — the installed one is `/opt/tradebot/heartbeat_ping.sh`.)
Rollback target unchanged: file-list sha256 of `/opt/tradebot/app/0d82b19` = `18b4b4ab…5c3d` before and after;
`.ta_pass_verified` sha256 `ca4791cd…3ce3` before and after.

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
    3d0fd1da16f3519ff515b7b899e27e7dc39cdd339997782c2a3f483e0459e950  live_v6/deploy/heartbeat_ping.sh
    12647e724b3d677f925c95eea323e63da39c40d1c55471551161017d5e4defea  live_v6/deploy/live_v6.service
    c4b36c341d206162d3cffb1edbff4498fcf0d6ac5ac8d3c0da356b54ed3cf897  live_v6/engine.py
    afcf900caba35b9acc7b739df41f41d0d798407d5d033b029d665bf8ec108e0d  live_v6/events.py
    e8c9bf7cec95f3165b825dd533e6aeb65d963d354b136455d686bb816108e130  live_v6/exchange.py
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
    63d58c84a1e25c3dbd4aea39c49c2189a9720d4f554092b0e428801bbbc03e7d  live_v6/replay/sim_exchange.py
    6b37c55a8ef325885624d4fe17d3597e76b8ef499f118802d45d39507f47b363  live_v6/reports/gate_sigkill_mid_entry.json
    47ded1f6d98b3c289afa1d46d3bb17ef3d36ce62a20656932e6eefc61da3f7fd  live_v6/reports/gate_sigkill_steady.json
    5c5e7f4c0acf3411f67827070e5f90f993db24b462ebb662c2ecf4f257f2a46c  live_v6/reports/h7t_killed_after_entry.json
    678e3946f4ece7ccbb35943e5a518a3f7af1b776fd3ed2d8ffdf52a97ca8e0c7  live_v6/requirements-dev.txt
    a3a6640656a257332785bb6ba934ef1ef54fa28213ba7b6c6b32760740f46ac3  live_v6/requirements.txt
    73a0baf9b069b4d5be532c6f746c71459bfa1ccee78199c68778be0ef9dfcc07  live_v6/rules.py
    f1ca23db6c9d8bbc80452cfccd3ed86ad2a810e59a9a5c7abfd6ab53def77c30  live_v6/runner.py
    aa5a9b89fc00f3330bb2163359616e294cf276282fe5a7b629c6c5c324acc61f  live_v6/sizing.py
    1e34ea3e770f00500b16cc71b8af11e78df9e45a618e158a3e13be9b1421a655  live_v6/store.py
    16bc4abbc2bd0fed3bc99579c29139a178371540695da60e76797fea647c4627  live_v6/strategies/__init__.py
    524bd7f98e1493ea6f141339d17be5a664d6242f3bf669c375900239b25ddfec  live_v6/strategies/base.py
    7f9060ef97555174b3277021dcf428729634f766de4d33434b195ac64d951ed9  live_v6/strategies/h7t.py
    c0864321db0d9a47df48a5249ff3dba6c4ad0ff711fb73dbc467b1ad82794922  live_v6/strategies/v6_h7.py
    7edd73c37b5c1828938851ee0550e2354197f857da589798605b11ec030db4cd  live_v6/strategy.py
    7794ab93b806302c055e94615c791eab4aca8ade867b5de9ec552fc96734d3ad  live_v6/stream.py
    e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  live_v6/tests/__init__.py
    978b8ec7b63b4d7d95929edac0b01a32075e03cc0b682f08b95f36ebf751e5fd  live_v6/tests/bot_proc.py
    a283ceed18675f79842276e5148a946d52929741963fa835db730c59f7baedd7  live_v6/tests/conftest.py
    db4c0dcc72a7424d50377cc9469de8a18b5991f8230a76a04100ad8aca6c04a9  live_v6/tests/drill_stop_cancel.py
    55ed4493bd0cfac76268636387fa9f3a1339ab8db73e05c38711ea0cab58c725  live_v6/tests/fakes.py
    0248632afb395f5e0376691a42992461a65ef1a6aac4e3dce96711decb83d2d4  live_v6/tests/test_bar_close_live.py
    4f980a42ff3757fb0f0b9cdea85697a39e680f2594ed0ee896e99ab7fb808b26  live_v6/tests/test_deadman.py
    0d6af7b91de65235d5c5617ac7e9c7f3c348aa92d441aba17ebb23c5dc7900f0  live_v6/tests/test_faults.py
    50868e2245c54a154c4c7ee72d3b7affe9e82fbd24397cc6514b8e99119a66fa  live_v6/tests/test_gate_sigkill.py
    1a2a7263ffa903ac4e5da70e443113e06a6ea3fb436e58cade875fd3f49ab04e  live_v6/tests/test_h7t.py
    b35fcd382190d76b59f84ab956b790b6724942ae466d68ca37aa0f0fb760933d  live_v6/tests/test_heartbeat_script.py
    c59394795a4ab4036b319f911019c5dd5c832767c92a9a14030254bf44353d81  live_v6/tests/test_notify.py
    640aa5ac0fe757e1dc82c3353a9c71934e665b98901799dae4ecb3511b201c09  live_v6/tests/test_rate_limit.py
    084757426e906733bfa84cec13e78aced8f44b68a9eab38941975239a57389e8  live_v6/tests/test_runner_e2e.py
    dc8b4d8272a068a23c966ea8aaeb85719d2a0ebdacf52362dba17eebaa5e7f64  live_v6/tests/test_static.py
    254cc58eb5caac9ff0c52a2bed50f95a7c7c7bb7cfc681a0237191670fd9e199  live_v6/tests/test_stop_monitor.py
    267c3af5a18bc2d85b5a316bfdf73181f3cdc6699a131b4d5feda3e9af6869bd  live_v6/tests/test_streams.py
    7dfe6c5e63b101f1828f6d9993e1a60871ce81577295c9793c55b87c8cfdda75  live_v6/tests/test_tgcmd.py
    e1631c5ce4b1cb54591d27074f29124de4cf8b33e5231fc17f9aa016eb2a35d5  live_v6/tests/test_token_logs.py
    7cd5750bfd1bca018450a75029950af3e21925d6647afa5f918a215bc27fb175  live_v6/tests/test_units.py
    6b8fd2de11bd3551c58a0957e5b9bac909c26ac2ff7c09c63ce6cf2916ebb875  live_v6/tests/test_unknown_position.py
    78a915d04969839c2fa81b043913ef631eee51dfef0ab1aa43bd60cfbe005013  live_v6/tgcmd.py
    3b6b8d318219a2e246e718e7fc119ea05480f726466c7c67d4ce4d13d7de29a6  live_v6/tools/adopt_position.py
    1955c8a0c32538cf2621b099fd4e130da0cf9d423fb45bb40c162cd003fe3512  live_v6/tools/tg_e2e.py
    c90cf8aed2e6600fe6aabc69494c8e894300843d95173d8f001a2593e3f8be12  live_v6/tools/verify_stops.py
    2d8c0dc6be44d5a907e6773442b6da5c5f59f1230d7f9bc59ab950bf404881aa  live_v6/tools/ws_check_mainnet.py

## 5. Rollback to 0d82b19 (as ops on the VPS; planned use only ≥15 min after / ≥20 min before a 4h close, except a crash loop)
```bash
sudo python3 /opt/tradebot/verify_stops_live.py; echo exit=$?          # must be 0 before the restart
sudo cp -p /var/lib/live_v6-live/mainnet.json /root/mainnet.json.bak-$(date -u +%Y%m%dT%H%M%SZ)
sudo ln -sfn /opt/tradebot/app/0d82b19 /opt/tradebot/app/current.new && sudo mv -T /opt/tradebot/app/current.new /opt/tradebot/app/current
echo 0d82b19 | sudo tee /opt/tradebot/app/DEPLOYED
sudo systemctl restart live_v6-live && sleep 45
systemctl show live_v6-live -p ActiveState,MainPID,NRestarts; readlink -f /opt/tradebot/app/current   # → /opt/tradebot/app/0d82b19
# then the §4 checks of DEPLOY_950438b.md (journal clean, caught up, verify_stops exit 0, HEARTBEAT_URL 0)
```
heartbeat_ping.sh is identical in both releases → nothing to restore. State stays compatible (2eb429b adds only optional keys).

## 6. Still open (TA condition 4)
Evidence at the first real close after the deploy (01:00 KST 2026-10-22): all 6 models caught up, verify-stops pass,
PID 51227 / NRestarts 0 unchanged. H15 logger only after that.
