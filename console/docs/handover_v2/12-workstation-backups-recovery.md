> <span color="red">*This document was written by Kimchi and Chips*</span>

## Obtain the intended release | 사용할 릴리스 확보

[Repository](https://github.com/elliotwoods/jinhee-sos). The inspected baseline is commit **7191c5d** ("Windows support, CI tests workflow and ResetZone firmware") plus the working-copy console, General Radio and show work on 23 September 2026. A clean clone of that commit alone does not include the NCT Console. Engineering Six should obtain an agreed source snapshot and matching verified binaries/manifest before deployment; this documentation task did not commit or push them.
검토 기준은 **7191c5d** 커밋("Windows support, CI tests workflow and ResetZone firmware")과 2026년 9월 23일 작업 사본의 콘솔·General Radio·쇼 작업입니다. 해당 커밋만 새로 복제하면 NCT Console이 없습니다. 배포 전 엔지니어링식스는 합의된 소스 사본과 일치하는 검증 바이너리·매니페스트를 확보해야 합니다. 본 문서 작업은 커밋·푸시하지 않았습니다.

## Set up a Mac | Mac 설치

Install Git and Python 3.14 with matching Tk, obtain the agreed project revision, and run `Setup.command` from the project folder. Setup recreates the shared `pairing_station/.venv`, installs pinned dependencies including **pywebview** (the console's native window), verifies included cube build hashes and imports shared inventory. Initial setup requires internet. It does not flash hardware.
Git과 Tk가 포함된 Python 3.14를 설치하고 합의한 프로젝트 버전을 받은 뒤 프로젝트 폴더의 Setup.command를 실행합니다. Setup은 공통 가상환경을 만들고 **pywebview**(콘솔 네이티브 창)를 포함한 고정 의존성 설치·큐브 빌드 해시 확인·공유 인벤토리 가져오기를 수행합니다. 초기 인터넷이 필요하며 장비 플래싱은 하지 않습니다.

```bash
brew install git python@3.14 python-tk@3.14
git clone https://github.com/elliotwoods/jinhee-sos.git
cd jinhee-sos
./Setup.command
./console/Launch.command
```

Arduino is not required to flash the included verified cube binary; it is required to build changed firmware (zone firmware, General Radio, Mainshow controller). The console's **This computer › Firmware builds** shows each build's state and offers **Rebuild**; the card "Firmware builds are unavailable" appears when Arduino CLI is missing.
포함된 검증 큐브 바이너리 플래싱에는 Arduino가 필요 없지만 펌웨어 변경 빌드(존 펌웨어, General Radio, 메인쇼 컨트롤러)에는 필요합니다. 콘솔의 **This computer › Firmware builds**는 각 빌드 상태와 **Rebuild**를 제공하며 Arduino CLI가 없으면 카드 "Firmware builds are unavailable"이 표시됩니다.

## Windows | Windows

The working copy includes `Setup.bat` and `console\Launch.bat`. Install Python 3.14 with tcl/tk and Git, then run Setup.bat. The shared interpreter is `pairing_station\.venv\Scripts\python.exe`. The console needs the WebView2 runtime for its native window; without it, `--browser` serves the same page to the default browser (the launcher falls back automatically). Ports are COM-style and never chosen by hand: the console identifies boards. Recreate the virtual environment; do not copy a Mac environment.
작업 사본에는 Setup.bat와 `console\Launch.bat`가 있습니다. tcl/tk를 포함한 Python 3.14 및 Git 설치 후 Setup.bat를 실행합니다. 공통 인터프리터는 위 경로입니다. 콘솔 네이티브 창에는 WebView2 런타임이 필요하며 없으면 `--browser`로 같은 페이지를 기본 브라우저에 띄웁니다(런처가 자동 전환). COM 포트는 수동 선택하지 않으며 콘솔이 보드를 식별합니다. Mac 가상환경을 복사하지 말고 새로 만듭니다.

Mac is the bench-tested environment. Windows portability code/tests are present and run in CI, but no Windows hardware has been bench-tested. Perform first-machine identity, serial, flash, NFC and visual acceptance before operational use.
Mac은 실물 벤치 테스트 환경입니다. Windows 호환 코드·테스트는 있고 CI에서 실행되지만 Windows 실물 테스트는 없습니다. 운영 전 신원·시리얼·플래시·NFC·시각 검수를 수행합니다.

## Launcher directory | 실행기 위치

- **NCT Console:** `console/Launch.command` / `console/Launch.bat` — every tool. Options: `--simulate` (fake boards on a temporary copy of the database), `--browser` (page in the default browser), `--database PATH`.<br>NCT Console: `console/Launch.command` / `console/Launch.bat` — 모든 도구. 옵션: `--simulate`(임시 DB 사본에서 가짜 보드), `--browser`(기본 브라우저에서 페이지), `--database PATH`.
- Fallback separate apps (unchanged): pairing `pairing_station/`, cube firmware `flashing_station/`, inventory Web Sync `inventory_web/`, zone provisioning `zones/flasher/`, wireless database `zones/dbmanager/`, Pool calibration `zones/calibration/`, main show `zones/mainshow/`, maintenance tests `zones/preshow_test/`, `poolzone_test/`, `rangetest/`.<br>예비용 개별 앱(변경 없음): 등록 `pairing_station/`, 큐브 펌웨어 `flashing_station/`, 인벤토리 웹 동기화 `inventory_web/`, 존 설정 `zones/flasher/`, 무선 DB `zones/dbmanager/`, 풀존 보정 `zones/calibration/`, 메인쇼 `zones/mainshow/`, 유지보수 테스트 `zones/preshow_test/`, `poolzone_test/`, `rangetest/`.

**Instance locks.** The console and the separate apps share one database and cannot run at the same time: the console holds the pairing, cube-flasher, zone-database and mainshow locks while it runs, and each side refuses to start while the other is open, naming it ("Another app is open on this database: …"). Close one before opening the other. Never bypass a port lock: close the competing app or Arduino Serial Monitor instead.
**인스턴스 잠금.** 콘솔과 개별 앱은 같은 DB를 공유하므로 동시에 실행할 수 없습니다. 콘솔은 실행 중 등록·큐브 플래셔·존 DB·메인쇼 잠금을 보유하고, 상대가 열려 있으면 각각 실행을 거부하며 상대 이름을 표시합니다("Another app is open on this database: …"). 한쪽을 닫은 뒤 다른 쪽을 엽니다. 포트 잠금을 우회하지 말고 점유 앱·Arduino Serial Monitor를 닫습니다.

## Shared inventory versus full backup | 공유 인벤토리와 전체 백업

Sync transfers identity records, not a complete local workstation. Git per-MAC JSON does not contain all local scan events, flash receipts, zone state or recovery binaries. Web sightings are separate uploaded evidence and do not make the shared inventory a complete SQLite backup.
Sync는 신원 기록을 전달하며 컴퓨터 전체를 복제하지 않습니다. Git의 MAC별 JSON에는 모든 로컬 스캔 이력·플래시 영수증·존 상태·복구 바이너리가 없습니다. 웹 관측은 별도 업로드 증빙이며 공유 인벤토리가 전체 SQLite 백업이 되는 것은 아닙니다.

For a private full backup, finish operations and close the console (and any separate app), then copy `pairing_station/data/devices.sqlite3` to a protected backup location. If a live snapshot is necessary, use SQLite's backup API as documented in `docs/SETUP.md`; copying only a live .sqlite3 file can omit committed WAL data.
전체 개인 백업은 작업을 끝내고 콘솔(및 개별 앱)을 닫은 뒤 devices.sqlite3를 보호된 백업 위치에 복사합니다. 실행 중 스냅샷이 필요하면 docs/SETUP.md의 SQLite backup API를 사용합니다. 실행 중 sqlite3 파일만 복사하면 WAL의 확정 데이터가 누락될 수 있습니다.

Keep firmware receipts (`flashing_station/data/runs/`), NVS/full-flash backups, Pool calibration/tuning records and guided recordings (`console/data/recordings/`), the agreed source revision and build manifests alongside the private backup. Protect passwords/API tokens: the web password lives in `pairing_station/data/web_password` and the console's loopback API token in `pairing_station/data/api.curl`; both are recreated locally and never shared or published.
펌웨어 영수증(`flashing_station/data/runs/`)·NVS/전체 플래시 백업·풀존 보정/튜닝 기록과 가이드 녹화(`console/data/recordings/`)·소스 버전·빌드 매니페스트도 비공개 보관합니다. 비밀번호·API 토큰을 보호합니다. 웹 비밀번호는 `pairing_station/data/web_password`, 콘솔 로컬 API 토큰은 `pairing_station/data/api.curl`에 있으며 둘 다 로컬에서 재생성되고 공유·공개하지 않습니다.

## Restore / move machines | 복구·PC 이전

1. Back up the destination before replacing its database; close the console on both computers.<br>대상 DB 교체 전 대상 백업을 만들고 양쪽 콘솔을 닫습니다.
2. Choose either shared-record Sync or a private full SQLite restore deliberately. Use a full restore when local audit/recovery state is required.<br>공유 기록 Sync 또는 전체 SQLite 복구를 목적에 맞게 선택합니다. 로컬 감사·복구 상태가 필요하면 전체 복구를 사용합니다.
3. Recreate dependencies, open the console, verify database integrity and compare several known label/MAC/UID records in Inventory › Cubes.<br>의존성을 새로 설치하고 콘솔을 연 뒤 DB 무결성과 Inventory › Cubes의 알려진 번호/MAC/UID 몇 건을 비교합니다.
4. Run **Inventory › Web sync › Check** before relying on Sync: a restored older database can interact with newer shared records, and the plan shows what would move and what the merge would decide. Make deliberate corrections, then Sync and publish/distribute only the intended mappings.<br>Sync에 의존하기 전 **Inventory › Web sync › Check**를 실행합니다. 복원한 과거 DB와 최신 공유 기록이 병합될 수 있으며 계획 표에 옮겨질 내용과 병합 판단이 표시됩니다. 의도한 수정을 하고 Sync 후 올바른 매핑만 게시·배포합니다.
5. Test one cube through registration/zone lookup and one representative firmware update under maintenance conditions. Leave USB intake off and every lease released.<br>유지보수 상태에서 큐브 한 개의 등록·존 조회와 대표 펌웨어 업데이트를 검증합니다. USB intake는 끄고 모든 리스를 해제합니다.

## Sources | 근거

`docs/SETUP.md`, `scripts/setup.py`, `console/Launch.command`, `console/Launch.bat`, `console/app.py`, `console/locks.py` (instance locks), `console/window.py` / `httpbridge.py` (native window and browser fallback), `hostos.py`. Evidence class: code-inspected; the lock refusal both ways is simulation-verified (`console/tests/test_locks.py`) and dongle-verified on the bench (chapter 15).
위 소스 기준. 근거 구분: 코드 확인. 양방향 잠금 거부는 시뮬레이션 확인(`console/tests/test_locks.py`) 및 벤치 동글 확인(15장).

## Related guides | 관련 안내

{{page:00}}
{{page:13}}
{{page:05}}
