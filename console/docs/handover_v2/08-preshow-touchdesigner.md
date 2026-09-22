> <span color="red">*This document was written by Kimchi and Chips*</span>

## Repair and current status | 개선 사항·현황

**Field-reported, 22 September:** external-antenna ESP32 replacement, more robust signalling, TouchDesigner device settings updated, PN532 gain raised, and improved reader positioning/mounting inside the wooden enclosure. Elliot reported reliable detection through the enclosure and working interactive butterfly cues. Small LiPo batteries did not work in the attempted arrangement; USB batteries did.
9월 22일 현장 보고: 외장 안테나 ESP32 교체, 신호 전송 개선, TouchDesigner 장치 설정 변경, PN532 게인 상향, 목재 내부 리더 위치·고정 개선이 이루어졌습니다. Elliot은 목재를 통한 안정적 인식과 나비 인터랙션 동작을 보고했습니다. 시도한 소형 LiPo 구성은 실패했고 USB 배터리는 동작했습니다.

This supersedes Sunday's reported lack of reception. Battery endurance and each point's final media routing still need a recorded operating acceptance; the Sunday note that only one point was in the media programming must not be treated as a verified current limit.
이는 일요일의 수신 실패 보고 이후의 결과입니다. 배터리 지속 시간과 포인트별 최종 미디어 연결은 운영 검수 기록이 필요합니다. 일요일에 미디어 프로그램에 한 포인트만 포함됐다는 기록을 현재 확정 제한으로 해석하지 않습니다.

## Signal path | 신호 경로

Registered cube tag → PN532 → PreshowZone lookup → cube red + PreshowEvent → PreshowBridge USB serial → TouchDesigner cue.
등록 큐브 태그 → PN532 → PreshowZone 조회 → 큐브 빨강 및 PreshowEvent → PreshowBridge USB 시리얼 → TouchDesigner 큐.

Only a registered cube found in the plate's database triggers normal preshow media. Tag removal releases the cue after the tag-leave handling interval. Keep point IDs unique and aligned with media routing; the console raises "Two preshow plates are flashed as point …" when it sees a clash over the radio or USB.
정상 프리쇼 미디어는 플레이트 DB에서 조회된 등록 큐브만 트리거합니다. 태그 제거는 제거 처리 시간 후 큐를 해제합니다. 포인트 ID는 중복 없이 미디어 연결과 맞춥니다. 콘솔은 무선·USB로 충돌을 감지하면 "Two preshow plates are flashed as point …"를 표시합니다.

## Actual-app walkthrough | 실제 앱 단계별 안내

These are captures of the console in simulation. Yellow outlines mark the real controls or result to check. The cue test raises real media cues on site.
시뮬레이션으로 실행한 콘솔 화면입니다. 노란 테두리는 실제 클릭할 항목 또는 확인할 결과입니다. 현장에서 큐 테스트는 실제 미디어 큐를 발생시킵니다.

### 1. Cue test: take the lease | Cue test: 리스 획득
{{shot:08-1}}
Cue test: take the lease, cue point 1 ON / Cue test: 리스 획득 후 포인트 1 ON

### 2. Point 2 ON, acknowledged | 포인트 2 ON, 확인 응답
{{shot:08-2}}
Point 2 ON, acknowledged by the media bridge / 포인트 2 ON, 미디어 브리지가 확인 응답

## Media server connection | 미디어 서버 연결

The bridge is a dedicated ESP32, not a cube and not a zone reader. Select its actual current USB device in the existing TouchDesigner Serial DAT at **115200 baud**. Preserve the established parser contract:
브리지는 전용 ESP32이며 큐브나 존 리더가 아닙니다. 기존 TouchDesigner Serial DAT에서 실제 현재 USB 장치를 선택하고 **115200 baud**를 사용합니다. 기존 파싱 규약을 유지합니다.

```plain text
PRESHOW,1,ON
PRESHOW,1,OFF
```

Point number is 1–4. One serial cue is emitted on a state change; duplicate retries/reassertions do not create repeated cues. The serial text format is unchanged from the original bridge; the changed hardware may need a new port selection. If the bridge is plugged into the console computer, the console identifies it as **Preshow media bridge** and shows its telemetry (plates seen, acknowledgements); **Disconnect** it in the console before giving the port to TouchDesigner. Its **Test cue** button writes `PRESHOW,n,ON|OFF` directly. The TouchDesigner project itself is not in this repository, so exact DAT names, routing and startup automation must be recorded by the media team.
포인트는 1–4입니다. 상태 변경 시 한 줄을 내보내고 재시도·재확인 중복은 큐를 반복하지 않습니다. 시리얼 형식은 원 브리지와 같으며 하드웨어 교체로 포트 재선택이 필요할 수 있습니다. 브리지를 콘솔 컴퓨터에 꽂으면 콘솔이 **Preshow media bridge**로 식별하고 텔레메트리(관측 플레이트, 확인 응답)를 보여 줍니다. TouchDesigner에 포트를 넘기기 전 콘솔에서 **Disconnect**합니다. **Test cue** 버튼은 `PRESHOW,n,ON|OFF`를 직접 씁니다. TouchDesigner 프로젝트는 저장소에 없으므로 정확한 DAT명·연결·자동 시작은 미디어팀이 기록해야 합니다.

## Find the failing stage | 실패 단계 찾기

1. No NFC scan: compare a known-good cube, positioning, enclosure spacing, power and reader gain. The plate's Zone panel header shows reader pins (`pins=`) and NFC health; preshow source tries SDA/SCL 4/3, then 6/7 for the replacement XIAO board. The Attention card "Plate … NFC reader not responding" offers **Ask the plate to recover the reader**.<br>NFC 스캔 없음: 정상 큐브·위치·목재 간격·전원·게인을 비교합니다. 플레이트 Zone 패널 헤더에 리더 핀(`pins=`)과 NFC 상태가 있습니다. 프리쇼 소스는 SDA/SCL 4/3 다음 교체 XIAO용 6/7을 시도합니다. Attention 카드 "Plate … NFC reader not responding"이 **Ask the plate to recover the reader**를 제공합니다.
2. UID seen but unknown: the Monitor tab shows the unknown tag and the Attention panel says whether it is a registered cube on an older plate database (**Update database over USB**), an unpublished mapping (**Sync & publish**) or an unregistered tag (**Register at the station**). Higher gain cannot fix a missing database record.<br>UID 인식·미등록: Monitor 탭에 알 수 없는 태그가 표시되고 Attention 패널이 구버전 플레이트 DB의 등록 큐브(**Update database over USB**), 미게시 매핑(**Sync & publish**), 미등록 태그(**Register at the station**) 중 어느 경우인지 알려 줍니다. 게인 증가로 DB 누락을 고칠 수 없습니다.
3. Cube red but no butterfly: the plate header's **MEDIA** pills show mode (legacy / modern), bridge address, bridge_sees_me and ACK/retry/failure counters; the cards "Preshow plate … is in legacy media mode" and "… reported MEDIA FAIL" explain them. Check bridge power, antenna and channel 2.<br>큐브 빨강·나비 없음: 플레이트 헤더의 **MEDIA** 칩에 모드(legacy / modern), 브리지 주소, bridge_sees_me, ACK/재시도/실패 카운터가 있습니다. 카드 "Preshow plate … is in legacy media mode"와 "… reported MEDIA FAIL"이 설명합니다. 브리지 전원·안테나·채널 2를 점검합니다.
4. Bridge emitted the correct line but no effect: media team checks Serial DAT port, parser and point-to-effect mapping. A bridge ACK establishes its serial-side processing, not rendered pixels.<br>브리지가 올바른 줄을 출력했지만 효과 없음: 미디어팀이 포트·파서·포인트 매핑을 확인합니다. 브리지 ACK는 시리얼 측 처리를 나타내며 실제 영상 출력은 증명하지 않습니다.
5. Cue stuck: remove real tags, switch the cue override off (Cue test tab), inspect ON/OFF status and media-side behaviour. Reassertion repairs latest state when communication returns; it does not recreate a missed historical butterfly event.<br>큐 고정: 실제 태그를 제거하고 큐 override(Cue test 탭)를 끈 뒤 ON/OFF와 미디어 동작을 확인합니다. 재확인은 통신 복구 후 최신 상태를 복원하며 과거에 놓친 나비 이벤트를 재생성하지는 않습니다.

## Engineering detail | 기술 설명

Bridge beacons every 500 ms let plates discover the destination. Modern events use unicast and application ACKs keyed by bootId/sequence; retries occur every 120 ms for up to 3 seconds, followed by periodic state reassertion every second. Duplicates are also acknowledged. The bridge accepts the older two-byte frame; newer plates send legacy copies until first hearing a modern beacon, then stop legacy fallback for that boot session.
브리지는 500 ms마다 비콘을 보내 목적지를 알립니다. 최신 이벤트는 유니캐스트와 bootId·sequence 기반 앱 ACK를 사용하며 최대 3초 동안 120 ms마다 재시도하고 이후 매초 상태를 재확인합니다. 중복에도 ACK합니다. 브리지는 구형 2바이트 프레임도 받습니다. 새 플레이트는 최신 비콘을 처음 받을 때까지 레거시 복사본을 보내며 그 부팅 세션에서는 이후 레거시 전송을 중지합니다.

For a no-reader maintenance test, use the preshow plate's **Cue test** tab in the console (it replaces `zones/preshow_test`). **Cue override** takes the plate's HOST lease (1.5 s, renewed every 350 ms while the page holds it); the **POINT 1–4** buttons raise or drop cues and the panel shows the plate's state, sequence and whether the bridge acknowledged. It can produce real media cues. Switch the override off at completion; a real tag takes control. The General Radio's **Preshow cue** tab can raise a cue as a fifth plate without any reader (chapter 13). Bridge console `TEST <1-4> ON|OFF` also creates cues; coordinate serial-port ownership with TouchDesigner.
리더 없는 유지보수 테스트는 콘솔의 프리쇼 플레이트 **Cue test** 탭을 사용합니다(`zones/preshow_test` 대체). **Cue override**는 플레이트의 HOST 리스(1.5초, 페이지가 유지하는 동안 350 ms마다 갱신)를 가져오고 **POINT 1–4** 버튼이 큐를 켜고 끄며 패널에 플레이트 상태·시퀀스·브리지 확인 여부가 표시됩니다. 실제 미디어 큐를 발생시킵니다. 종료 시 override를 끄며 실제 태그가 우선합니다. General Radio의 **Preshow cue** 탭은 리더 없이 다섯 번째 플레이트로 큐를 올릴 수 있습니다(13장). 브리지 TEST 명령도 큐를 만들므로 TouchDesigner와 포트 점유를 조정합니다.

## Sources | 근거

`PreshowZone.ino` (preshow-3.4.0), `PreshowBridge.ino` (preshowbridge-1.0.0), `NctPreshowProtocol.h`, `NctTagPlate.h`; `console/sessions/preshow_plate.py`, `preshow_bridge.py`, `console/advisor.py` (`preshow.*`); Elliot's supplied 22 September report. Evidence class: code-inspected; the lease and cue path are simulation-verified; installed versions were not inventoried.
위 소스와 Elliot의 9월 22일 보고 기준. 근거 구분: 코드 확인. 리스·큐 경로는 시뮬레이션 확인. 설치 버전 실사는 하지 않았습니다.

## Related guides | 관련 안내

{{page:00}}
{{page:07}}
{{page:02}}
