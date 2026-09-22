> <span color="red">*This document was written by Kimchi and Chips*</span>

## Source and version inventory | 소스·버전 목록

These are **source versions inspected on 23 September**, not a claim about what every installed board runs. The console shows each connected board's reported version next to the local build.
아래는 **9월 23일 검토한 소스 버전**이며 모든 설치 보드의 실행 버전 주장이 아닙니다. 콘솔은 연결된 보드의 보고 버전을 로컬 빌드 옆에 표시합니다.

<table header-row="true">
<tr><td>Role / 역할</td><td>Source / 소스</td><td>Version / 버전</td></tr>
<tr><td>NCT Console / 콘솔</td><td>console/</td><td>0.1.0</td></tr>
<tr><td>Cube / 큐브 (bundled, verified)</td><td>flashing_station/firmware/neocore_usb</td><td>bundled v1.7.0-USB.1 (show as data, fanning, live preview); fleet on v1.4.1-USB.2, #17 on v1.7.0</td></tr>
<tr><td>Pairing station / relay · 등록/중계</td><td>pairing_station/firmware/pairing_station</td><td>nct-pairing-1.8-zones</td></tr>
<tr><td>General Radio</td><td>zones/firmware/GeneralRadio</td><td>general-radio-1.2.0 (1.1.0 show relay + timecode, 1.2.0 live preview; #138)</td></tr>
<tr><td>Preshow plate / 프리쇼</td><td>zones/firmware/PreshowZone</td><td>preshow-3.4.0</td></tr>
<tr><td>Entrance / safety plate · 입구/안전 플레이트</td><td>zones/firmware/TagPlateZone</td><td>tagplate-2.4.0</td></tr>
<tr><td>Desert / 사막</td><td>zones/firmware/DesertZone</td><td>desert-2.4.0</td></tr>
<tr><td>Pool radio / 풀존 라디오</td><td>zones/firmware/PoolZone</td><td>pool-3.2.0</td></tr>
<tr><td>Pool central / 풀존 중앙</td><td>zones/firmware/PoolCentral</td><td>poolcentral-4.2.0</td></tr>
<tr><td>Preshow media bridge / 프리쇼 브리지</td><td>zones/firmware/PreshowBridge</td><td>preshowbridge-1.0.0</td></tr>
<tr><td>Main show trigger / 메인쇼 트리거</td><td>zones/firmware/MainshowController</td><td>mainshow-1.3.0 (timecode); installed #134 still on mainshow-1.2.0</td></tr>
<tr><td>Reset plate / 리셋 플레이트</td><td>zones/firmware/ResetZone</td><td>see zones/README.md</td></tr>
</table>

## Console architecture | 콘솔 구조

- `console/hub.py` is the owner thread: SQLite, every serial session, the reused controllers (`pairing_station/controller.py`, `zone_registry.py`), job bookkeeping and the snapshot the page polls. It ticks every 100 ms like the old Tk `root.after` loop; nothing on it sleeps or reads serial.<br>`console/hub.py`는 소유자 스레드입니다: SQLite, 모든 시리얼 세션, 재사용 컨트롤러(`pairing_station/controller.py`, `zone_registry.py`), 작업 관리, 페이지가 폴링하는 스냅샷. 기존 Tk `root.after` 루프처럼 100 ms마다 틱하며 sleep이나 시리얼 읽기를 하지 않습니다.
- `scanner.py` enumerates USB off-thread; `probe.py` asks each new board what it is without resetting it (`?`, JSON `hello`, `STATUS`; never an arming command); `devices.py` keeps per-port state (present → probing → idle → session / job / foreign / protected).<br>`scanner.py`는 별도 스레드에서 USB를 열거하고, `probe.py`는 새 보드에 리셋 없이 정체를 묻습니다(`?`, JSON `hello`, `STATUS`; arming 명령은 절대 아님). `devices.py`는 포트별 상태(present → probing → idle → session / job / foreign / protected)를 유지합니다.
- `sessions/` hold a port per role; leases (`HOST PING`) are driven from the tick only while the page keeps touching them. `jobs/` run flashes, builds and syncs on worker threads through the existing pipelines; a session's port is released before a job and re-probed after it.<br>`sessions/`는 역할별 포트를 잡습니다. 리스(`HOST PING`)는 페이지가 계속 터치하는 동안에만 틱에서 유지됩니다. `jobs/`는 기존 파이프라인으로 플래시·빌드·동기화를 작업 스레드에서 실행하며, 작업 전 세션 포트를 해제하고 작업 후 다시 프로브합니다.
- `advisor.py` is a pure rules engine: `evaluate(sections, now, dismissed)` turns the snapshot into suggestion cards with actions naming commands in `commands.py` (+ `commands_extra.py`, `commands_show.py`). Hardware commands run on one click with a warning tooltip from `uitext.ACTIONS`; destructive commands need a confirmation token obtained by the page's press-and-hold (`confirm` then `call`), enforced by the backend.<br>`advisor.py`는 순수 규칙 엔진입니다: `evaluate(sections, now, dismissed)`가 스냅샷을 `commands.py`(+ `commands_extra.py`, `commands_show.py`)의 명령을 가리키는 제안 카드로 바꿉니다. 하드웨어 명령은 `uitext.ACTIONS`의 경고 툴팁과 함께 한 번 클릭으로 실행되고, 파괴적 명령은 페이지의 길게 누르기로 얻는 확인 토큰(`confirm` 후 `call`)이 필요하며 백엔드가 강제합니다.
- `api.py` is what the page calls (`pull`, `call`, `confirm`, `get_copy`, `get_lines`); `window.py` hosts it in pywebview, `httpbridge.py` in a browser. `web/` is vendored Preact + htm, no build step, no network. Every colour is a token in `web/styles.css`; every command button carries `data-doc="<command>"` (used by the screenshot tool).<br>`api.py`는 페이지가 호출하는 함수(`pull`, `call`, `confirm`, `get_copy`, `get_lines`)이며 `window.py`는 pywebview, `httpbridge.py`는 브라우저에서 호스팅합니다. `web/`은 벤더링된 Preact + htm이며 빌드 단계·네트워크가 없습니다. 모든 색은 `web/styles.css`의 토큰이고 모든 명령 버튼은 `data-doc="<command>"`를 가집니다(스크린샷 도구가 사용).
- **Language (EN/KR):** front-end strings go through `t('English')` / `hint()` / `tk()` (`web/lib/i18n.js`) with Korean in `web/lib/ko/*.js` keyed by the English text; operator copy in `uitext.py` has Korean in `uitext_ko.py`. `web/tests/i18n.test.js` and `tests/test_uitext.py` fail on any untranslated string, and rewording English in `uitext.py` fails until the Korean is revisited and `console/uitext_ko.py --stamp` is run. Python-generated text (advisor cards, job stages, logs, errors) stays English; protocol tokens and product names are never translated. The choice is stored per browser (`nct.lang`); `?lang=ko` applies it to one page.<br>**언어(EN/KR):** 프런트엔드 문자열은 `t('English')` / `hint()` / `tk()`(`web/lib/i18n.js`)를 거치며 한국어는 영어 문장을 키로 `web/lib/ko/*.js`에 있습니다. 운영 문구 `uitext.py`의 한국어는 `uitext_ko.py`에 있습니다. 번역 누락 시 `web/tests/i18n.test.js`와 `tests/test_uitext.py`가 실패하며, `uitext.py`의 영어를 바꾸면 한국어를 검토하고 `console/uitext_ko.py --stamp`를 실행할 때까지 실패합니다. Python이 생성하는 문구(제안 카드, 작업 단계, 로그, 오류)는 영어로 유지되고 프로토콜 용어·제품명은 번역하지 않습니다. 선택은 브라우저별(`nct.lang`)로 저장되며 `?lang=ko`는 한 페이지에만 적용됩니다.

## Protocol boundaries | 프로토콜 경계

All maintained radios use channel 2, but their messages are not interchangeable. Cube Packet is the legacy **24-byte unpacked C ABI**; preserve alignment/offsets. Zone management, Pool and Preshow have distinct protocol definitions. Pool/Preshow frames share NZ but must remain outside `NctZoneProtocol.h::frameType()` so they reach the sketch through `TagPlate::onFrame`. The bridge also accepts legacy 2-byte frames. The General Radio speaks a strict superset of the pairing-station relay protocol (JSON lines, `id` echoed, host gate on `hello`/`ping` within 5 s, 1.5 s leases for lamp and cue).

The main show has a fifth protocol, `zones/firmware/libraries/NctShow/src/NctShowProtocol.h` (types 0x50–0x55: show announce, chunk, query, status, `SHOW_TIMECODE`, and `SHOW_LIVE` for the editor's live preview, broadcast only). Its frames are also absent from `frameType()`. Cubes before v1.5.0 drop them, since they accept only 24-byte frames. `MSG_SHOW_START` (8) is unchanged and is still the only thing a cube needs. Show versions are allocated by the web and only increase; never allocate one locally. The show format lives in four engines that must change together: `NctShowEngine.h`, `pairing_station/showfile.py`, `console/web/lib/showengine.js` and `web/src/lib/show.ts`. `python pairing_station/showfile.py --header` regenerates `DefaultShow.h` and the JS test vectors.
유지관리 무선은 모두 채널 2지만 메시지는 서로 호환되지 않습니다. Cube Packet은 레거시 **24바이트 비압축 C ABI**이며 정렬·오프셋을 유지합니다. 존 관리·풀존·프리쇼는 별도 정의입니다. 풀존·프리쇼는 NZ 헤더를 공유하지만 frameType()에서 처리하지 않아야 TagPlate::onFrame으로 스케치에 전달됩니다. 브리지는 레거시 2바이트도 수신합니다. General Radio는 등록 스테이션 중계 프로토콜의 엄격한 상위 집합(JSON 줄, `id` 회신, 5초 이내 `hello`/`ping` 호스트 게이트, 램프·큐 1.5초 리스)을 사용합니다.

메인쇼는 다섯 번째 프로토콜 `NctShowProtocol.h`(타입 0x50–0x55: 쇼 공지, 청크, 조회, 상태, `SHOW_TIMECODE`, 에디터 실시간 미리보기용 `SHOW_LIVE`, 방송 전용)를 사용합니다. 이 프레임도 `frameType()`에서 제외됩니다. v1.5.0 이전 큐브는 24바이트 프레임만 받으므로 이를 버립니다. `MSG_SHOW_START`(8)는 변경 없고 큐브에 필요한 유일한 신호입니다. 쇼 버전은 웹이 할당하며 증가만 합니다(로컬 할당 금지). 쇼 형식은 네 엔진(`NctShowEngine.h`, `showfile.py`, `showengine.js`, `web/src/lib/show.ts`)을 함께 바꿔야 하며, `python pairing_station/showfile.py --header`가 `DefaultShow.h`와 JS 벡터를 재생성합니다.

Do not print serial output, drive I2C or run long work in the Wi-Fi receive callback. Hand off frames and process them in the main loop. Python workers must use queues; SQLite and sessions stay on the hub owner thread. Preserve request IDs, fresh-tag gating and matching MAC/ID checks.
Wi-Fi 수신 콜백에서 시리얼 출력·I2C·긴 작업을 하지 말고 프레임을 인계해 메인 루프에서 처리합니다. Python 작업자는 큐를 사용하며 SQLite·세션은 허브 소유자 스레드에 유지합니다. 요청 ID·새 태그 조건·MAC/ID 일치 검사를 보존합니다.

## Zone storage and integrity | 존 저장·무결성

Zone partition map: NVS 0x9000/0x5000; app 0x10000/0x200000; zcfg 0x210000/0x1000; zdb_a 0x211000/0x8000; zdb_b 0x219000/0x8000. Use the maintained partitions.csv, not these notes as a hand-written flashing recipe.
존 파티션은 위 오프셋/크기이며 실제 작업에는 유지관리 partitions.csv를 사용합니다. 이 요약으로 수동 쓰기 명령을 만들지 않습니다.

The inactive slot receives records, is read back and CRC-checked, then gets its final header. A power cut before valid activation leaves the previous slot available. Boot chooses the highest valid version/generation. Each slot holds up to 1,819 records; full chunks carry 12. Updates are integrity-checked but not cryptographically signed. Web allocation is the version authority; do not revive per-computer counters. Mirror record validation changes in `inventory_sync.py` and `web/src/lib/records.ts`, and zone validation in `zones/tools/zonedb.py` and `web/src/lib/zonedb.ts`.
비활성 슬롯에 기록·읽기·CRC 검증 후 최종 헤더를 씁니다. 활성화 전 전원 단절 시 이전 슬롯이 남습니다. 부팅은 유효한 최고 버전·세대를 선택합니다. 슬롯당 최대 1,819건, 전체 청크당 12건입니다. 무결성 검증은 있지만 암호학적 서명은 없습니다. 버전 기준은 웹 할당이며 컴퓨터별 카운터를 되살리지 않습니다. 기록·존 검증 변경은 위 Python·웹 파일 쌍에 함께 반영합니다.

## Pool physical output mapping | 풀존 실제 출력 매핑

Frame/member numbers 1–23 map to output indices below. Output indices 1–16 are 0x40 channels 0–15; 17–23 are 0x41 channels 0–6. Names and frame numbers must be checked against the installed labels before rewiring.
프레임·멤버 1–23은 아래 출력 인덱스에 대응합니다. 출력 1–16은 0x40의 채널 0–15, 17–23은 0x41의 채널 0–6입니다. 재배선 전 이름·프레임 번호를 실물 라벨과 대조합니다.

```plain text
frame :  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23
output:  1 19 15 22  5 11  6 13 23 18 20  9 12 17  2  4 16 10 21  3  8 14  7
```

Current `PoolOutput.h` uses **POOL_ACTIVE_LOW_OUTPUTS = 0x7FFFFF**, a per-output bitmask. Re-measure the mapping if looms change. Readback confirms driver registers, not relay contacts, lamp supply or emitted light.
현재 PoolOutput.h는 출력별 비트마스크 **POOL_ACTIVE_LOW_OUTPUTS = 0x7FFFFF**를 사용합니다. 배선 변경 시 매핑을 재측정합니다. 읽기 검증은 드라이버 레지스터를 확인하며 릴레이 접점·조명 전원·발광은 확인하지 않습니다.

## Release discrepancy requiring resolution | 해결해야 할 릴리스 불일치

The PoolCentral README documents a board that required **FlashFreq=40** and says to flash bootloader/application as a compatible pair. The inspected `scripts/build_all_firmware.py` selects generic **C3** for that target while C3_SLOW_FLASH is defined but unused. Confirm the actual replacement/installed board and choose/reconcile the release recipe before building or flashing PoolCentral. This documentation did not change the code or test either recipe on hardware.
PoolCentral README는 **FlashFreq=40**이 필요했던 보드와 부트로더·앱의 호환 쌍 설치를 설명합니다. 검토한 build_all_firmware.py는 해당 대상에 일반 **C3**를 선택하며 C3_SLOW_FLASH은 정의되어도 사용하지 않습니다. 실제 보드를 확인해 중앙 빌드·플래시 전 릴리스 설정을 확정·일치시켜야 합니다. 이 문서 작업은 코드를 수정하거나 두 설정을 실물 테스트하지 않았습니다.

## Build and validation workflow | 빌드·검증 절차

Use the shared project Python, Arduino ESP32 core **3.3.11**, and dependencies/build recipes in docs/SETUP.md. Rebuild manifests through the tools (or the console's This computer › Firmware builds); never edit hashes to silence a stale-build error.
공통 프로젝트 Python, Arduino ESP32 코어 **3.3.11**, docs/SETUP.md의 의존성·빌드 설정을 사용합니다. 매니페스트는 도구(또는 콘솔의 This computer › Firmware builds)로 재생성하며 해시 직접 수정으로 오류를 숨기지 않습니다.

The following are **commands for the receiving technical team**. Those marked ✓ were run for this handover on 23 September (results in {{page:15}}); the others are listed for completeness. On Windows substitute the shared Scripts/python.exe path.
다음은 **인수 기술팀 실행 명령**입니다. ✓ 표시는 본 인수인계 작업에서 9월 23일 실행한 항목(결과는 15장)이며 나머지는 참고용입니다. Windows는 공통 Scripts/python.exe 경로로 대체합니다.

```bash
pairing_station/.venv/bin/python -m unittest discover -s console/tests -p 'test_*.py'      # ✓ console suite (headless, simulated boards)
node --test 'console/web/tests/*.test.js'                                                    # ✓ front-end helpers
pairing_station/.venv/bin/python -m unittest discover -s pairing_station/tests               # ✓
pairing_station/.venv/bin/python -m unittest discover -s flashing_station/tests              # ✓
pairing_station/.venv/bin/python -m unittest discover -s zones/tests                         # ✓
pairing_station/.venv/bin/python -m unittest discover -s zones/calibration                   # ✓
pairing_station/.venv/bin/python zones/tests/run_firmware_tests.py                           # host firmware simulators
pairing_station/.venv/bin/python scripts/build_all_firmware.py --dry-run                     # 14 maintained targets, no upload
pairing_station/.venv/bin/python console/app.py --simulate --scenario docs --browser          # the documentation bench, no hardware
pairing_station/.venv/bin/python console/tools/docshots.py --list                            # the 34 screenshot scenarios; run without --list to recapture
```

The dry run enumerates 14 maintained targets without upload; running without --dry-run compiles them, but first resolve the PoolCentral recipe. GUI tests need a desktop and isolated databases. Firmware host simulation and the console's simulated boards are not hardware evidence. Run physical output scripts only during an intended maintenance window.
dry-run은 업로드 없이 유지관리 대상 14개를 열거합니다. 옵션 없이 실행하면 빌드하므로 먼저 PoolCentral 설정을 해결합니다. GUI 테스트에는 데스크톱과 독립 DB가 필요합니다. 호스트 펌웨어 모사와 콘솔의 시뮬레이션 보드는 실물 증빙이 아닙니다. 물리 출력 스크립트는 지정된 유지보수 시간에만 실행합니다.

## Local automation interface | 로컬 자동화 인터페이스

The console hosts the pairing app's loopback Python API unchanged: owner-only `pairing_station/data/api.curl` (token recreated at every launch, never printed or shared), normally `127.0.0.1:8765`; off in `--simulate` unless `--api-port` is given. The `/execute` namespace has `app`, `controller`, `db`, `zones` plus `hub`, `sessions`, `jobs`, `devices` and `store`. Read `/status` before acting. `/execute` runs on the owner thread; do not block it. HTTP 202 means poll the returned job, not resubmit a mutation. Do not expose the credential or use it as a remote public control service.
콘솔은 등록 앱의 로컬 Python API를 그대로 호스팅합니다: 소유자 전용 `pairing_station/data/api.curl`(실행마다 토큰 재생성, 출력·공유 금지), 기본 `127.0.0.1:8765`, `--simulate`에서는 `--api-port`를 주지 않으면 꺼짐. `/execute` 네임스페이스에는 `app`, `controller`, `db`, `zones`와 `hub`, `sessions`, `jobs`, `devices`, `store`가 있습니다. 작업 전 `/status`를 읽습니다. `/execute`는 소유자 스레드에서 실행하므로 차단하지 않습니다. HTTP 202는 반환 작업을 조회하라는 뜻이며 변경 명령 재전송이 아닙니다. 자격증명을 공개하거나 원격 공개 제어 서비스로 사용하지 않습니다.

## Maintained wiring reference | 유지관리 배선 참조

These pin assignments are source references; verify board model and the installed harness before replacement.
아래 핀은 소스 기준이며 교체 전 보드 모델·설치 배선을 확인합니다.

- Pairing station: ESP32-C3, PN532 SDA=4 / SCL=3; the installed red PN532 was documented powered from station 5V/GND. General Radio and dongles: XIAO ESP32-C3, status LEDs on GPIO10, no reader.<br>등록 스테이션: ESP32-C3, PN532 SDA=4 / SCL=3. 설치된 빨간 PN532는 스테이션 5V/GND 전원으로 기록되어 있습니다. General Radio·동글: XIAO ESP32-C3, 상태 LED GPIO10, 리더 없음.
- Standard zone readers: SDA=4 / SCL=3. Replacement Preshow XIAO fallback: D4/D5 = GPIO6/7; the console shows the reported pins in the zone header.<br>일반 존 리더: SDA=4 / SCL=3. 교체 프리쇼 XIAO 대체 핀은 D4/D5=GPIO6/7이며 콘솔 존 헤더에 보고 핀이 표시됩니다.
- Desert local MOSFET control: GPIO1. Pool radio strip control: GPIO5; VL53L4CD distance sensing shares the reader I2C bus in the maintained design.<br>사막 로컬 MOSFET 제어는 GPIO1, 풀 라디오 스트립은 GPIO5입니다. 유지관리 설계에서 VL53L4CD 거리 센서는 리더 I2C 버스를 공유합니다.
- PoolCentral: SDA=8 / SCL=9, I2C 100 kHz, PCA9685 0x40 and 0x41. Mainshow trigger: XIAO D1=GPIO3 to GND, through the documented installed signal interface; controller LEDs on D10=GPIO10.<br>풀 중앙은 SDA=8 / SCL=9, I2C 100 kHz, PCA9685 0x40·0x41입니다. 메인쇼 트리거는 확인된 설치 신호 변환부를 통해 XIAO D1=GPIO3을 GND로 당기는 방식이며 컨트롤러 LED는 D10=GPIO10입니다.

## Related guides | 관련 안내

{{page:00}}
{{page:14}}
{{page:15}}
