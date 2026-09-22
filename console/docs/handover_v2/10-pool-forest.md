> <span color="red">*This document was written by Kimchi and Chips*</span>

## What was implemented | 구현한 내용

Kimchi and Chips replaced the Pool radio/central firmware path, repaired communication/state handling, added slider mapping/filtering/calibration and corrected the physical frame mapping. The existing repair report also records relay replacement, COM–NO rewiring, terminal cleanup and board mounting. Idle lamps now correspond to de-energised relays.
김치앤칩스는 풀존 라디오·중앙 펌웨어 경로를 교체하고 통신·상태 처리를 수정했으며, 슬라이더 매핑·필터·보정과 실제 프레임 매핑을 구현했습니다. 기존 수리 보고에는 릴레이 교체, COM–NO 재배선, 단자 정리, 보드 고정도 기록되어 있습니다. 대기 시 소등은 릴레이 비여자 상태에 해당합니다.

**Remaining physical limitation:** the slider mechanism/sensor cannot reliably reproduce the printed member positions. Software calibration cannot guarantee precision the mechanism does not provide. Covering names with white PVC tape is a proposal requiring Amberin/Lotte confirmation; this document does not say it has been approved or applied.
**남은 물리적 제한:** 슬라이더 기구·센서는 인쇄된 멤버 위치를 안정적으로 재현하지 못합니다. 소프트웨어 보정으로 기구 자체에 없는 정밀도를 보장할 수 없습니다. 흰색 PVC 테이프로 이름을 가리는 방안은 앰버린·롯데 확인이 필요한 제안이며 승인·적용 완료로 기록하지 않습니다.

## Normal behaviour | 정상 동작

Six radio structures select among 23 member frames. A tag activates the radio strip; registered cubes receive blue. Pool retains the original behaviour that unknown tags can activate the interaction even though the cube cannot be addressed from a missing mapping. No selected index, invalid readings or removal eventually release the frame.
라디오 구조물 6개가 멤버 프레임 23개 중 하나씩 선택합니다. 태그가 라디오 스트립을 활성화하고 등록 큐브는 파란색을 받습니다. 풀존은 매핑이 없어 큐브에 명령할 수 없어도 미등록 태그가 체험을 활성화하는 기존 동작을 유지합니다. 선택 인덱스 없음·잘못된 측정·제거 시 프레임은 해제됩니다.

The central combines all active radio requests using OR: a frame stays lit while any radio holds it. Current source keys sender slots by MAC, so duplicate claimed radio IDs are diagnosed rather than allowed to overwrite each other's lease; the console raises "Two pool radios share radio id …" / "Pool central sees live radios sharing an id". Still label/configure the six physical radios uniquely.
중앙은 활성 요청을 OR로 합쳐 어떤 라디오라도 유지하면 프레임이 켜집니다. 현재 소스는 MAC으로 송신 슬롯을 구분하므로 중복 라디오 ID가 서로 임대를 덮지 않고 진단됩니다. 콘솔은 "Two pool radios share radio id …" / "Pool central sees live radios sharing an id"를 표시합니다. 그래도 실물 라디오 6개는 고유 번호로 표시·설정해야 합니다.

## Actual-app walkthrough | 실제 앱 단계별 안내

These are captures of the console in simulation. Yellow outlines mark the real controls or result to check. The example captures tick 12 after endpoints are already set. On an uncalibrated radio, establish ticks 1 and 23 first as described below. Setting a point changes a draft on the board; only **Apply & save to flash** writes it. Reload saved ticks and recheck the slider after saving.
시뮬레이션으로 실행한 콘솔 화면입니다. 노란 테두리는 실제 클릭할 항목 또는 확인할 결과입니다. 이 예시는 양 끝점 설정 후 12번 눈금을 기록하는 경우입니다. 미보정 라디오는 아래 절차대로 1번과 23번 눈금을 먼저 설정하세요. 점 설정은 보드의 초안만 바꾸며 **Apply & save to flash**가 저장을 수행합니다. 저장 후 다시 읽고 슬라이더를 확인하세요.

### 1. Calibration: lease and live reading | 캘리브레이션: 리스와 실시간 값
{{shot:10-1}}
Calibration: lease taken, the live reading and the band diagram / 캘리브레이션: 리스 획득, 실시간 값과 밴드 다이어그램

### 2. Capture control point 12 | 제어점 12 캡처
{{shot:10-2}}
Capture control point 12 from the live reading / 실시간 값으로 제어점 12 캡처

### 3. Apply & save | Apply & save
{{shot:10-3}}
Apply & save: the board confirms with saved=true / Apply & save: 보드가 saved=true로 확인

### 4. Guided recording | 가이드 녹화
{{shot:10-4}}
Guided recording: hold the slider at the prompted tick / 가이드 녹화: 안내된 눈금에서 슬라이더 고정

## Manual control-point calibration | 수동 제어점 보정

1. Plug the PoolZone radio into the console; it is identified as a pool radio and its Zone panel gains **Calibration** and **Diagnostics** tabs. Open **Calibration**: the saved control points, tuning and the live distance reading appear as soon as the board answers `CAL GET` / `TUNE GET`. Tracking works without a tag; the output override starts off.<br>PoolZone 라디오를 콘솔에 꽂으면 풀 라디오로 식별되고 Zone 패널에 **Calibration**·**Diagnostics** 탭이 추가됩니다. **Calibration**을 열면 보드가 `CAL GET` / `TUNE GET`에 응답하는 즉시 저장 제어점·튜닝·실시간 거리값이 표시됩니다. 태그 없이도 위치 추적은 가능하며 출력 강제 제어는 꺼진 상태로 시작합니다.
2. Select tick 1 in the band diagram, move the physical slider to tick 1, then **Capture** (Set from the live reading). Repeat at tick 23. Capture uses the latest displayed filtered reading, not a separate stability test.<br>밴드 다이어그램에서 눈금 1을 선택하고 실물을 해당 위치로 이동한 뒤 **Capture**(실시간 값으로 설정)를 누릅니다. 23도 반복합니다. 캡처는 별도 안정성 시험 없이 최신 필터 측정값을 사용합니다.
3. Capture useful intermediate control points where spacing differs. The board interpolates all 23 positions between anchored points; it does not extrapolate beyond endpoints. Increasing or decreasing distance direction is supported.<br>간격이 다른 곳에 필요한 중간 제어점을 추가합니다. 보드는 기준점 사이의 23개 위치를 보간하며 양 끝 밖으로 외삽하지 않습니다. 거리 증가·감소 방향 모두 지원합니다.
4. Use **Set (mm)** only with a known measured value; **Remove** clears an anchor. Values must be 10–1000 mm and the resulting ticks at least 1 mm apart; the board refuses otherwise and the timeline shows its error.<br>측정값을 알고 있을 때만 **Set (mm)**를 사용하고 **Remove**로 기준점을 제거합니다. 값은 10–1000 mm이며 결과 눈금 간격은 최소 1 mm여야 합니다. 그렇지 않으면 보드가 거부하고 타임라인에 오류가 표시됩니다.
5. **Apply & save to flash** (one-click hardware button: "Replaces the saved calibration; note the previous values first") commits and reads back the calibration; the panel shows **saved** when the board confirms. **Reload saved** discards draft edits. A saved indicator and successful readback are required before claiming the board was calibrated.<br>**Apply & save to flash**(한 번 클릭 하드웨어 버튼: "저장된 보정을 교체함; 이전 값을 먼저 기록")는 보정값을 저장·읽기 검증합니다. 보드가 확인하면 패널에 **saved**가 표시됩니다. **Reload saved**는 임시 변경을 버립니다. 저장 표시와 읽기 검증 성공 후에만 보정 완료로 판단합니다.
6. Test several positions in both travel directions, release the tag, reconnect and confirm saved values. If the same physical position gives different readings, record the mechanical error instead of repeatedly retuning around it.<br>양방향 이동으로 여러 위치를 테스트하고 태그를 제거하며 재연결 후 저장값을 확인합니다. 같은 위치의 측정이 달라지면 반복 튜닝으로 감추지 말고 기구 오차를 기록합니다.

## Guided recording and tuning | 가이드 기록·튜닝

On the **Diagnostics** tab, **Start guided recording** asks you to move to each requested tick (stride and hold time are settable) and press **Reached this position** before its hold is recorded; the countdown and sample count are shown, and the radio streams raw samples (`RAW ON`) only while recording. Endpoints are always included. When the last hold ends the console analyses the recording (per-tick noise and movement warnings), proposes filter tuning fitted to the settling budget, and shows a before/after simulation. **Apply recording** applies the tuning live and can optionally save it and the measured control points to flash; it is not read-only measurement, so note the prior values before applying. The recording is saved under `console/data/recordings/`. **Abort** turns the raw stream off.
**Diagnostics** 탭의 **Start guided recording**은 각 요청 눈금으로 이동한 뒤(간격과 유지 시간 설정 가능) **Reached this position**을 눌러야 유지 구간을 기록합니다. 카운트다운과 샘플 수가 표시되며 라디오는 녹화 중에만 원시 샘플을 보냅니다(`RAW ON`). 양 끝은 항상 포함됩니다. 마지막 유지가 끝나면 콘솔이 녹화를 분석하고(눈금별 노이즈·이동 경고) 정착 시간 예산에 맞춘 필터 튜닝을 제안하며 전후 시뮬레이션을 보여 줍니다. **Apply recording**은 튜닝을 실시간 적용하고 선택적으로 튜닝과 측정 제어점을 플래시에 저장할 수 있습니다. 읽기 전용 측정이 아니므로 적용 전 기존 값을 기록합니다. 녹화는 `console/data/recordings/`에 저장됩니다. **Abort**는 원시 스트림을 끕니다.

Filtering uses a One Euro filter plus entry/exit windows and timing. The tuning fields on the Calibration tab show the board's saved values with the firmware defaults for comparison. **Apply live** changes RAM settings; **Apply & save** persists tuning. Use output-stability counters and actual frame behaviour to compare results. A radio without tuning support (older than pool-2.8.0) raises "Pool radio … runs firmware without tuning support" → **Update pool radio firmware**.
필터는 One Euro와 진입·이탈 범위 및 시간 조건을 사용합니다. Calibration 탭의 튜닝 항목은 보드 저장값과 비교용 펌웨어 기본값을 표시합니다. **Apply live**는 RAM, **Apply & save**는 비휘발성 튜닝 저장입니다. 출력 안정성 카운터와 실제 프레임으로 비교합니다. 튜닝 미지원 라디오(pool-2.8.0 이전)는 "Pool radio … runs firmware without tuning support" → **Update pool radio firmware**를 표시합니다.

## Overrides, firmware and radio identity | 강제 제어·펌웨어·라디오 신원

**Override output without a cube** (Calibration tab) lets the slider drive real lights with no tag. It is a lease: the console pings every 0.35 s while the page holds it and the board drops it 1.5 s after the pings stop (closing the panel, Esc, or **Stop** releases it); reconnect does not re-arm. A real tag can still keep the interaction active after the override is off. The status bar lists every lease the console holds.
**Override output without a cube**(Calibration 탭)는 태그 없이 슬라이더로 실제 조명을 구동합니다. 리스 방식입니다: 페이지가 유지하는 동안 콘솔이 0.35초마다 핑을 보내고 핑이 멈추면 1.5초 후 보드가 해제합니다(패널 닫기, Esc, **Stop**으로 해제). 재연결 시 자동 활성화하지 않습니다. 강제 제어를 꺼도 실제 태그가 있으면 동작이 유지될 수 있습니다. 상태 표시줄에 콘솔이 유지 중인 모든 리스가 나열됩니다.

The **Firmware & database** tab of a pool radio offers **Flash pool firmware** ("Pool radios and the pool central are a matched set"), **Update database over USB** and **Assign radio id** (1–6, with the ids already seen by the console listed so a clash is visible; a forced override of a clash is a separate deliberate choice). The updater backs up full flash, checks partitions, preserves/verifies NVS and zone identity, stages the database in the inactive slot, then checks rebooted firmware/build and database. Use the provisioning form for blank boards or layout changes.
풀 라디오의 **Firmware & database** 탭은 **Flash pool firmware**("풀 라디오와 풀 중앙은 세트"), **Update database over USB**, **Assign radio id**(1–6, 콘솔이 본 id를 함께 표시해 충돌이 보이도록; 충돌 강제 덮어쓰기는 별도 명시적 선택)를 제공합니다. 업데이터는 전체 백업·파티션 확인·NVS와 존 신원 보존 검증·비활성 슬롯 DB 준비 후 재부팅 펌웨어·빌드·DB를 확인합니다. 빈 보드나 구조 변경은 프로비저닝 폼을 사용합니다.

## Central diagnostics | 중앙 진단

PoolCentral uses SDA GPIO8 / SCL GPIO9 and PCA9685 addresses 0x40 and 0x41. Plugged into the console it opens the **Pool central** panel: STATUS telemetry (radios heard, leases, outputs verified / UNVERIFIED) and **Recover I²C** (re-initialises both PCA9685 boards; outputs blink). Its README documents a historical **40 MHz flash** requirement; resolve the target recipe before rebuilding (chapter 13). Radio states carry leases (default 800 ms); a 400 ms release hold reduces brief relay flicker.
PoolCentral은 SDA GPIO8 / SCL GPIO9, PCA9685 주소 0x40·0x41을 사용합니다. 콘솔에 꽂으면 **Pool central** 패널이 열립니다: STATUS 텔레메트리(관측 라디오, 리스, 출력 verified / UNVERIFIED)와 **Recover I²C**(PCA9685 두 보드 재초기화, 출력 점멸). README는 과거 플래시 40 MHz 필요 사례를 기록합니다. 재빌드 전 대상 설정을 확정합니다(13장). 무선 상태 임대 기본값은 800 ms이며 400 ms 해제 유지로 순간 점멸을 줄입니다.

Output writes are read back; failed writes remain pending and driver state is audited/recovered. "verified" means driver-register state, not actual light emission. On power-up the relay drivers can briefly request lamps ON before firmware darkens them; `outputs=UNVERIFIED` requires investigation.
출력 쓰기는 읽기로 검증하며 실패 쓰기는 대기·재시도하고 드라이버 상태를 점검·복구합니다. verified는 드라이버 레지스터 상태이지 실제 발광이 아닙니다. 전원 인가부터 펌웨어 소등 전까지 릴레이 드라이버가 잠시 점등을 요청할 수 있습니다. outputs=UNVERIFIED는 점검이 필요합니다.

Maintenance-only direct output on the central's Console tab: `OUT ARM`, `OUT <1-23|ALL> ON|OFF`, `OUT DISARM`. Arming temporarily takes control from radios; the lease expires after two minutes without commands. The **Pool light test** bridge (a separate board identified as such) emulates all six radios from its own panel (member toggles, **Sequential test**, **All Off**); isolate real transmitters for that test and finish with All Off. The General Radio's **Pool lamp** tab holds one member as an emulated radio alongside the real ones ({{shot:C-8}}).
중앙 Console 탭의 유지보수 전용 직접 출력 명령은 `OUT ARM`, `OUT <1-23|ALL> ON|OFF`, `OUT DISARM`입니다. ARM은 라디오 제어를 임시 대체하며 명령 없이 2분 뒤 해제됩니다. **Pool light test** 브리지(별도 보드로 식별)는 자체 패널에서 라디오 6개를 모사합니다(멤버 토글, **Sequential test**, **All Off**). 테스트 시 실제 송신기를 분리하고 All Off로 마칩니다. General Radio의 **Pool lamp** 탭은 실제 라디오와 함께 멤버 하나를 모사 라디오로 유지합니다({{shot:C-8}}).

## Sources | 근거

`PoolZone.ino` (pool-3.2.0), `PoolCentral.ino` (poolcentral-4.2.0), `PoolArbiter.h`, `PoolOutput.h`, `zones/calibration/recording.py`, `firmware.py` (reused); `console/sessions/pool_radio.py` (lease, calibration, tuning, guided recording), `console/sessions/pool_central.py`, `console/commands_extra.py` (`pool.record_*`); existing repair report and supplied field notes. Evidence class: code-inspected; the lease, CAL/TUNE round trips and the recording state machine are simulation-verified (`console/tests/test_pool_recording.py`); no pool board was connected while writing this handover. Mechanical repeatability and long-duration operation remain physical checks.
위 소스 및 기존 수리·현장 보고 기준. 근거 구분: 코드 확인. 리스, CAL/TUNE 왕복, 녹화 상태 기계는 시뮬레이션 확인(`console/tests/test_pool_recording.py`). 본 문서 작성 중 풀 보드를 연결하지 않았습니다. 기구 반복 정밀도와 장시간 동작은 별도 실물 확인 항목입니다.

## Related guides | 관련 안내

{{page:00}}
{{page:13}}
{{page:15}}
