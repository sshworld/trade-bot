# CI v2 설치 절차서 — main 머지 → 테스트 → 실서버 자동 배포

> 이 문서는 **절차만** 적는다. 아래 명령은 아직 아무것도 실행되지 않았다(2026-11-16 작성 시점).
> `<VPS>` = Vultr 서버 주소, 저장소 = `sshworld/trade-bot`. 서버 관리는 `ssh ops@<VPS>` + `sudo` 로만 한다
> (root 는 forced command 전용).

## 0. 무엇이 어떻게 도나

```
main 에 push(머지) ─► GitHub Actions deploy-live
  test   : ubuntu-24.04 · Python 3.12 · live_v6/requirements-dev.txt · pytest -m "not testnet and not slow" (비밀 없음)
  deploy : 환경 live (승인자 없음, main 만) · concurrency 1
           gh_ssh_deploy.sh: VPS status 로 현재 릴리스 sha 조회 → 커밋 제목 목록(릴리즈 노트)을 넣어 git archive
           → ssh root@<VPS> (키에 묶인 forced command: ci_deploy_entry.sh live) → JOB id → 완료까지 폴링
VPS  ci_job.sh → systemd-run (SSH 끊겨도 계속) → ci_deploy.sh deploy live <sha> <tar>
  1 아카이브 검사(일반 파일만, live_v6/ 아래만) · 격리 import 검사(네트워크 없음, 유닛이 쓰는 전략으로)
  2 사전 검사: 유닛 active · meta.health 신선하고 ok(또는 기존 halt 그대로 + 차단 없음) · TimeoutStopSec ≥ 20s
  3 설치(/opt/tradebot/app/<sha40>, root 소유 읽기 전용) → 진행 중 진입 없음(state.intents 비어 있음 — post-only
    대기 주문 포함) 까지 최대 6분 대기 → 거래소 손절 확인(verify_stops_live.py) → state 백업 → 심링크 교체 → restart
  4 사후 검증: active · state 와 meta.health 가 새 프로세스로 재기록 · health ok · 45초간 PID/NRestarts 그대로
    · 새 PID 저널에 Traceback/CRITICAL 없음 · 모든 열린 포지션에 거래소 손절
  5 통과 → .ci_verified.pending + 텔레그램(릴리즈 노트). 실패 → 같은 전략의 마커 릴리스로 즉시 롤백(재검증)
    → 롤백도 실패/대상 없음 → 봇 정지 + CI_HALTED + 텔레그램 + Healthchecks /fail
tradebot-ci-confirm.timer (5분마다): 재시작 30분 뒤 같은 프로세스·health·Traceback 없음·손절 확인 → .ci_verified
```

포지션 정리·주문·손절 취소는 어느 경로에도 없다. 봇을 멈출 때도 거래소 손절은 그대로 남는다.

## 1. 사전 확인 (읽기 전용)

```bash
ssh ops@<VPS>
sudo /opt/tradebot/ci/ci_deploy.sh status live 2>&1 | tail -5      # (v1 스크립트) 현재 릴리스 확인
readlink /opt/tradebot/app/current                                 # 실행 중 릴리스 디렉터리(7자리 또는 40자리)
sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value live_v6-live)/environ | grep -E '^LIVE_V6_(STRATEGY|NETWORK)='
sudo test -r /etc/tradebot/telegram.env && sudo grep -c -E '^(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=' /etc/tradebot/telegram.env   # expect 2
sudo grep -c 'ci_deploy_entry.sh' /root/.ssh/authorized_keys        # v1 CI 키 줄 수(현재 2: live, testnet)
systemctl show live_v6-live -p TimeoutStopUSec                      # ≥ 20s
systemctl cat live_v6-live | grep -n CI_HALTED                      # halt-guard drop-in 적용 여부
```

## 2. VPS 에 v2 스크립트 설치 (ops + sudo)

검토가 끝난 커밋(이 문서가 들어 있는 커밋, `<C>`)에서 맥으로 보낸다:

```bash
# 맥(저장소 체크아웃)에서
git archive <C> live_v6/deploy/ci live_v6/tools/verify_stops_live.py \
  | ssh ops@<VPS> 'rm -rf /tmp/ci-v2 && mkdir -p /tmp/ci-v2 && tar -x -C /tmp/ci-v2'
ssh ops@<VPS> 'sudo bash /tmp/ci-v2/live_v6/deploy/ci/install_vps_ci.sh /tmp/ci-v2'
```

설치기는 이전 파일을 `/opt/tradebot/ci/backup-<ts>/` 에 남기고 `ci_deploy.sh`·`ci_deploy_entry.sh`·`ci_job.sh`·
`verify_stops_live.py`·confirm 타이머(5분)·halt-guard drop-in 만 바꾼다. 봇 유닛은 시작·정지·재시작하지 않는다.
배포는 이 스크립트들을 절대 바꾸지 않는다(서버 쪽은 사람이 설치한 것만 실행).

## 3. 지금 돌고 있는 릴리스를 롤백 기준으로 등록 (adopt)

v1 마커(`.ta_pass_verified`, 옛 H7-T 코드)는 v2 에서 롤백 대상이 아니다. 등록된 릴리스가 하나도 없으면 첫 CI 배포가
검증에 실패했을 때 롤백할 곳이 없어 **봇이 정지**된다. 그래서 첫 배포 전에 지금 정상으로 돌고 있는 릴리스를 등록한다.

```bash
# 맥에서: 실행 중 디렉터리 이름(예: 06e48e7)의 40자리 sha
git rev-parse 06e48e7
# VPS 에서: 같은 검사(유닛 active, 최근 30분 Traceback 없음, health 신선·ok, 손절 확인)를 먼저 dry-run
sudo /opt/tradebot/ci/ci_deploy.sh adopt live <sha40> --dry-run
sudo /opt/tradebot/ci/ci_deploy.sh adopt live <sha40>
sudo /opt/tradebot/ci/ci_deploy.sh status live          # marker=yes, strategy=<유닛 전략>
```

`adopt` 는 SSH forced command 로는 부를 수 없다(ops 수동 전용).

## 4. CI 전용 SSH 키 (서버에서 생성 → 사람이 GitHub 에 넣음)

예전 키(`tradebot_ci_live`)의 개인키 위치를 확신할 수 없으면 새로 만든다. 개인키는 화면에 출력하지 않는다.

```bash
# VPS (ops)
sudo install -d -m 700 /root/ci-keys
sudo ssh-keygen -t ed25519 -N '' -C tradebot_ci_live_v2 -f /root/ci-keys/tradebot_ci_live_v2
PUB=$(sudo cat /root/ci-keys/tradebot_ci_live_v2.pub)
sudo cp -p /root/.ssh/authorized_keys /root/.ssh/authorized_keys.bak-$(date -u +%Y%m%dT%H%M%SZ)
echo "restrict,command=\"/opt/tradebot/ci/ci_deploy_entry.sh live\" $PUB" | sudo tee -a /root/.ssh/authorized_keys >/dev/null
# 옛 live CI 키 줄 삭제(새 키 등록 후 · 줄 끝 주석 tradebot_ci_live 확인 후). testnet 키 줄은 v2 워크플로가 안 쓰므로 삭제해도 됨.
sudo grep -n 'ci_deploy_entry.sh' /root/.ssh/authorized_keys
sudo sed -i '/ tradebot_ci_live$/d' /root/.ssh/authorized_keys
sudo grep -c PermitRootLogin /etc/ssh/sshd_config.d/00-tradebot.conf   # forced-commands-only 유지 확인
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub                  # 호스트 키 지문(아래 known_hosts 대조용)
```

```bash
# 맥에서 — 👤 사람이 실행: 개인키를 파이프로 GitHub 환경 시크릿에 바로 넣는다(화면·파일에 남기지 않음)
ssh ops@<VPS> 'sudo cat /root/ci-keys/tradebot_ci_live_v2' | gh secret set VPS_SSH_KEY --env live --repo sshworld/trade-bot
ssh-keyscan -t ed25519 <VPS> 2>/dev/null > /tmp/kh && ssh-keygen -lf /tmp/kh     # 위 지문과 같은지 확인 후
gh secret set VPS_KNOWN_HOSTS --repo sshworld/trade-bot < /tmp/kh && rm /tmp/kh
gh secret set VPS_HOST --repo sshworld/trade-bot --body '<VPS>'
ssh ops@<VPS> 'sudo shred -u /root/ci-keys/tradebot_ci_live_v2'                  # 서버의 개인키 삭제(.pub 는 남김)
gh secret list --repo sshworld/trade-bot             # 저장소 수준에 VPS_SSH_KEY 가 있으면 안 됨(있으면 삭제)
gh secret list --env live --repo sshworld/trade-bot  # VPS_SSH_KEY 만
```

## 5. GitHub 환경 `live` (승인자 없음, main 만)

사용자 결정(2026-11-16): main 머지가 승인이다. 10월 설정(승인자 sshworld, `ta-pass-*` 태그 허용)을 바꾼다.

```bash
R=repos/sshworld/trade-bot
gh api $R/environments/live --jq '{reviewers: .protection_rules, policy: .deployment_branch_policy}'   # 현재 상태
gh api -X PUT $R/environments/live --input - <<'JSON'
{"wait_timer": 0, "prevent_self_review": false, "reviewers": [],
 "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
gh api $R/environments/live/deployment-branch-policies --jq '.branch_policies[] | [.id, .type, .name] | @tsv'
gh api -X POST $R/environments/live/deployment-branch-policies -f name=main -f type=branch    # 없을 때만
gh api -X DELETE $R/environments/live/deployment-branch-policies/<ta-pass-* 정책 id>         # 남아 있으면
```

`ta-pass-tags` 룰셋과 `testnet` 환경은 v2 에서 안 쓴다(남겨 둬도 무해).

## 6. 켜는 순서 (첫 실배포를 통제하려면)

워크플로 파일이 main 에 들어가는 **그 push 가 곧 첫 배포**다. 순서:

1. §2 설치 → §3 adopt 까지 끝낸다.
2. §4 시크릿을 **넣기 전에** 이 브랜치를 main 에 머지한다 → deploy 잡은 SSH 키가 없어 접속 단계에서 실패
   (서버에서는 아무것도 바뀌지 않음). test 잡이 리눅스 러너에서 통과하는지 여기서 확인.
3. §4 시크릿, §5 환경 설정.
4. Actions → deploy-live → Run workflow, `dry_run` 체크 → 서버에서 아카이브·import·사전 검사만 하고 끝(변경 없음).
   로그 끝에 `DRY-RUN would: …` 와 `rollback to <adopt 한 릴리스>` 가 보여야 한다.
5. 같은 화면에서 `dry_run` 없이 실행 → 실배포. 텔레그램에 `✅ [CI 배포·live] 배포 완료 … 릴리즈 노트` 가 온다.
   30분 뒤 `✅ … 재시작 30분 확인 통과` 가 오면 새 릴리스가 롤백 기준이 된다.

이후로는 main 머지마다 자동이다. 연속 머지는 GitHub concurrency 로 하나씩 돌고, 대기 중인 오래된 실행은 최신 실행으로
대체될 수 있다(최신 main 이 앞의 커밋을 모두 포함하므로 릴리즈 노트는 서버의 현재 릴리스 기준으로 계산).

## 7. 롤백·비상 조치

| 상황 | 방법 |
|---|---|
| 배포 후 문제 발견(코드) | 해당 PR 을 revert 해서 main 에 머지 → 자동 배포(정상 경로) |
| 즉시 이전 릴리스로 | `ssh ops@<VPS> 'sudo /opt/tradebot/ci/ci_deploy.sh rollback live --dry-run'` → 확인 후 `--dry-run` 없이. 마커 있는 같은 전략 릴리스로, 진입 진행 중 없을 때만, 사후 검증까지 |
| 봇 긴급 정지 | `ssh ops@<VPS> 'sudo systemctl stop live_v6-live'` (손절 유지, 정리 안 함) |
| CI 가 봇을 정지시킴(텔레그램 🚨, `CI_HALTED`) | 원인 확인(`/var/log/tradebot/ci-jobs/live-<id>.log`, `journalctl -u live_v6-live`) → 띄울 릴리스 `<dir>` 결정 → `sudo ln -sfn /opt/tradebot/app/<dir> /opt/tradebot/app/current.new && sudo mv -T /opt/tradebot/app/current.new /opt/tradebot/app/current` → `sudo python3 /opt/tradebot/verify_stops_live.py; echo $?`(0 확인) → `sudo rm /opt/tradebot/app/CI_HALTED && sudo systemctl start live_v6-live` → `sudo /opt/tradebot/ci/ci_deploy.sh status live` 로 health 확인 후 §3 adopt. 텔레그램이 '정지 실패'면 먼저 `sudo systemctl stop live_v6-live`. CI 는 `CI_HALTED` 를 절대 지우지 않고, 있는 동안 배포·롤백을 거부한다(exit 13) |
| 자동 배포 끄기 | `gh workflow disable deploy-live --repo sshworld/trade-bot` (또는 authorized_keys 의 CI 줄 삭제) |
| v1 스크립트로 되돌리기 | `sudo cp -p /opt/tradebot/ci/backup-<ts>/* /opt/tradebot/ci/` (서비스·타이머 파일은 `/etc/systemd/system/` 로) → `sudo systemctl daemon-reload` |

## 8. 참고

- 종료 코드(ci_deploy.sh): 0 정상 · 2 사용법/아카이브 · 4 수동 롤백 대상 없음 · 5 손절 미확인 · 6 롤백 검증 실패(정지)
  · 7 다른 작업 중 · 8 import 실패 · 9 배포 실패→롤백 완료 · 10 롤백 대상 없음(정지) · 11 진입 진행 중이 안 끝남
  · 12 TimeoutStopSec · 13 CI_HALTED · 14 confirm 실패 · 15 봇이 안 돌거나 비정상(배포 보류)
- 2·5·8·11·12·15 는 "아무것도 안 바뀜"(봇은 기존 릴리스로 계속) + 텔레그램 `⏸ 배포 보류`.
- 서버 로그: `/var/log/tradebot/ci-deploy.log`, `/var/log/tradebot/ci-jobs/`, `/var/log/tradebot/ci-confirm.log`.
- 시험: `live_v6/tests/test_ci_deploy.py` (가짜 systemctl/journalctl/curl 로 정상·롤백·정지·보류·confirm·adopt 분기).
