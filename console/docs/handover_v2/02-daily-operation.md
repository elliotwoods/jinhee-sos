> <span color="red">*This document was written by Kimchi and Chips*</span>

## Before opening | 개장 전

This is a proposed operating checklist based on the implemented system. Engineering Six should adopt it into the venue's opening procedure and assign a named duty technician. Where a check uses the computer, it uses the NCT Console: open it once, plug in the dongle or General Radio, and read the **Attention** panel before doing anything else — it lists what the console already knows is wrong (a plate holding an older database, a station without NFC, unpublished mappings, a stale build).
구현된 시스템을 바탕으로 제안하는 운영 체크리스트입니다. 엔지니어링식스는 이를 현장 개장 절차에 반영하고 당일 담당 기술자를 지정해야 합니다. 컴퓨터가 필요한 점검은 NCT Console을 사용합니다. 콘솔을 한 번 열고 동글 또는 General Radio를 꽂은 뒤 다른 작업보다 먼저 **Attention** 패널을 읽습니다. 콘솔이 이미 파악한 문제(구버전 DB를 가진 플레이트, NFC가 없는 스테이션, 미게시 매핑, 오래된 빌드)가 나열됩니다.

- [ ] Count charged, tested cubes and reserve spares. Separate damaged or unreliable cubes; record their physical numbers.<br>충전·테스트 완료 큐브와 예비 수량을 확인합니다. 파손·불안정 큐브는 분리하고 실물 번호를 기록합니다.
- [ ] Check preshow USB power banks, cables, antennas and reader mounting. Use the established USB battery arrangement; the small LiPo trial was unsuccessful.<br>프리쇼 USB 보조배터리, 케이블, 안테나, 리더 고정을 확인합니다. 소형 LiPo 시도는 실패했으므로 현장에서 사용 중인 USB 배터리 구성을 사용합니다.
- [ ] Start the venue media system and check the correct PreshowBridge serial device at 115200 baud. Close any competing serial monitor. If the bridge is plugged into the console computer, the console identifies it as "Preshow media bridge" and must not hold its port while TouchDesigner needs it: use Disconnect on its panel.<br>현장 미디어 시스템을 켜고 PreshowBridge의 올바른 시리얼 장치와 115200 baud를 확인합니다. 포트를 점유하는 다른 시리얼 모니터는 닫습니다. 브리지가 콘솔 컴퓨터에 꽂혀 있으면 콘솔이 "Preshow media bridge"로 식별하며, TouchDesigner가 포트를 써야 할 때 콘솔이 포트를 잡고 있으면 안 됩니다. 패널의 Disconnect를 사용합니다.
- [ ] Test all four preshow points using a known-good registered cube: NFC detection, cube red, the intended butterfly cue, then release. Confirm the media team has mapped all intended points.<br>정상 등록 큐브로 프리쇼 4개 포인트 모두 NFC 인식, 큐브 빨강, 해당 나비 큐, 제거 후 해제를 확인합니다. 미디어팀이 예정된 포인트를 모두 연결했는지 확인합니다.
- [ ] Test all 23 desert positions for both local lamp and cube yellow. Pay particular attention to the reported Jisung / Jimin reader alignment positions; confirm their actual site labels.<br>사막 23개 위치에서 로컬 조명과 큐브 노랑을 각각 확인합니다. 보고된 지성 / 지민 리더 정렬 위치는 특히 확인하고 실제 현장 표기를 대조합니다.
- [ ] Check all six Pool radios: tag activation, blue cube, slider selection and the actual corresponding frame. Test two radios selecting the same frame: removing one must not extinguish the other's selection.<br>풀존 라디오 6개에서 태그 활성화, 큐브 파랑, 슬라이더 선택, 실제 프레임을 확인합니다. 라디오 2개로 같은 프레임을 선택한 뒤 하나만 해제했을 때 다른 선택이 유지되는지 확인합니다.
- [ ] With the media team, test entrance tagging and a scheduled main-show cue. Watch actual cube playback. Controller green LEDs or the console's running show clock alone are insufficient.<br>미디어팀과 입구 태그 및 예정된 메인쇼 큐를 테스트합니다. 실제 큐브 재생을 확인합니다. 컨트롤러의 초록 LED나 콘솔의 쇼 시계만으로는 충분하지 않습니다.
- [ ] If mappings changed, click **Sync** in the console top bar (it uploads, downloads and publishes the zone database in one click), then on the dongle's **Zone relay** tab run **Query zones** and **Update all out-of-date zones**; reconcile every physical reader against the relay table.<br>매핑 변경 시 콘솔 상단의 **Sync**를 누르고(업로드·다운로드·존 DB 게시를 한 번에 수행) 동글의 **Zone relay** 탭에서 **Query zones**와 **Update all out-of-date zones**를 실행합니다. 전체 실물 리더를 relay 표와 대조합니다.
- [ ] Finish maintenance with **USB intake** off (This computer panel: Auto-flash cubes / Auto-flash zones), Settings › Automatic updates as agreed (on by default: they only update zones and cubes that are behind), and every override lease released (pool override, cue override, General Radio lamp and cue). The status bar shows what is still held.<br>유지보수 종료 시 **USB intake**(This computer 패널의 Auto-flash cubes / Auto-flash zones) 끄기, Settings › Automatic updates는 합의대로 유지(기본 켜짐: 뒤처진 존·큐브만 업데이트), 모든 강제 제어 리스(풀 override, 큐 override, General Radio 램프·큐) 해제를 확인합니다. 상태 표시줄에 아직 유지 중인 항목이 표시됩니다.

## During opening | 운영 중

Use charged spares for a failing visitor cube and diagnose the removed cube away from the audience. Note time, zone/point, cube number, symptom and whether a known-good cube works there. Do not re-register a whole batch or broadcast a show just to diagnose one failed cube. In the console, plug the cube into USB: its Cube panel shows the number, committed tag, registration status and reported firmware, and the Attention panel says what it can (an unverified firmware, an unconfirmed registration, a missing number).
관람객 큐브가 실패하면 충전된 예비 큐브로 교체하고 회수한 큐브는 관람 구역 밖에서 진단합니다. 시간, 존·포인트, 큐브 번호, 증상, 정상 큐브의 동일 위치 반응을 기록합니다. 큐브 하나를 진단하려고 전체 재등록이나 메인쇼 브로드캐스트를 하지 않습니다. 콘솔에서 큐브를 USB에 꽂으면 Cube 패널에 번호, 확정 태그, 등록 상태, 보고된 펌웨어가 표시되고 Attention 패널이 가능한 진단(미검증 펌웨어, 미확인 등록, 번호 없음)을 알려 줍니다.

If one cube fails at several good readers, investigate that cube's charge, tag, registration and firmware. If several good cubes fail at one reader, investigate that reader's position, power, PN532 and local database. If readers detect tags but a downstream effect fails, check the relevant radio/controller/media or lighting path. A plate on USB shows all of this on its **Monitor** tab: the tag read, the lookup result, the radio delivery and the reader health.
한 큐브가 여러 정상 리더에서 실패하면 해당 큐브의 충전, 태그, 등록, 펌웨어를 확인합니다. 여러 정상 큐브가 한 리더에서 실패하면 리더 위치, 전원, PN532, 로컬 DB를 확인합니다. 태그는 인식되지만 후단 효과가 실패하면 무선·컨트롤러·미디어 또는 조명 경로를 확인합니다. USB에 꽂은 플레이트는 **Monitor** 탭에서 태그 읽기, 조회 결과, 무선 전달, 리더 상태를 모두 보여 줍니다.

If equipment is hot, damaged or has unstable power, stop using that equipment and refer it to the duty technician under venue procedures. Software reset is not a repair for a physical electrical fault.
장비 발열·파손·불안정 전원이 있으면 해당 장비 사용을 중단하고 현장 절차에 따라 담당 기술자에게 전달합니다. 소프트웨어 리셋은 물리적 전기 고장의 수리 방법이 아닙니다.

## Closing and handover | 폐장 및 인계

1. Stop visitor intake and coordinate the final media cue before powering down controls.<br>관람객 입장을 마감하고 마지막 미디어 큐를 협의한 뒤 제어 장비를 종료합니다.
2. Collect/count cubes; separate "ready", "charging" and "needs repair". Park waiting cubes on a Reset Plate. Do not infer battery level from a radio dot or inventory status.<br>큐브를 회수·계수하고 "사용 가능", "충전 중", "수리 필요"로 구분합니다. 대기 큐브는 Reset Plate에 태그해 둡니다. 무선 점이나 인벤토리 상태로 배터리 잔량을 판단하지 않습니다.
3. Disarm maintenance tools: USB intake off, leases released (automatic updates may stay on). Wait for any running job to finish; the console refuses to close while a flash write is in progress.<br>유지보수 도구를 해제합니다: USB intake 끄기, 리스 해제(자동 업데이트는 켜 둘 수 있음). 진행 중인 작업이 끝날 때까지 기다립니다. 콘솔은 플래시 쓰기 중에는 종료를 거부합니다.
4. Click **Sync** for deliberate inventory changes and record zones still out of date (Inventory › Zone database lists what each zone last reported). Close the console before copying a private backup.<br>의도한 인벤토리 변경은 **Sync**로 동기화하고 아직 업데이트가 필요한 존을 기록합니다(Inventory › Zone database에 각 존의 최근 보고가 있음). 개인 백업 복사 전 콘솔을 닫습니다.
5. Charge using the operator-approved hardware procedure. Measure actual endurance and set a swap interval from observations; neither the PDF's planned capacities nor this guide establish a tested runtime.<br>운영사가 승인한 하드웨어 절차로 충전합니다. 실제 지속 시간을 측정하여 교체 주기를 정합니다. PDF 계획 용량이나 본 문서가 검증된 사용 시간을 의미하지는 않습니다.

## Troubleshooting | 문제 해결

Recorded symptom → cause → fix cases are kept in {{page:16}}, each with what the console shows for it. Add new cases there after resolving them.<br>증상 → 원인 → 조치 사례는 16장에 콘솔 표시 내용과 함께 정리되어 있습니다. 새 사례는 해결 후 16장에 추가합니다.

## Shift log template | 교대 기록 양식

Date/time · operator · usable/spare/faulty cube counts · affected cube/MAC · zone/point · observed symptom · known-good comparison · action · result · published DB version (from the console's top-bar Sync chip or Inventory › Zone database) · zones still out of date · Attention cards left open · next owner.
일시 · 운영자 · 사용 가능/예비/불량 큐브 수 · 큐브/MAC · 존/포인트 · 증상 · 정상 장비 비교 · 조치 · 결과 · 게시 DB 버전(콘솔 상단 Sync 칩 또는 Inventory › Zone database) · 미갱신 존 · 남겨 둔 Attention 카드 · 후속 담당자.

## Sources | 근거

`console/advisor.py` (the Attention rules), `console/uitext.py` (panel and status copy), `console/intake.py` (USB intake, off at launch), current component READMEs; Elliot/Hojun field reports in the supplied request; Sangeun report (20 September). Opening frequency and division of duties above are handover recommendations, not claims of completed site tests. Evidence class: code-inspected and simulation-verified (console suite).
위 소스, 요청에 제공된 Elliot/Hojun 현장 보고, 9월 20일 Sangeun 보고. 위 점검 주기와 역할 구분은 인수인계 제안이며 완료된 현장 테스트 주장이 아닙니다. 근거 구분: 코드 확인·시뮬레이션 확인(콘솔 테스트).

## Related guides | 관련 안내

{{page:00}}
{{page:03}}
{{page:15}}
{{page:16}}
