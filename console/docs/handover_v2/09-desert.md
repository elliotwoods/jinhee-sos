> <span color="red">*This document was written by Kimchi and Chips*</span>

## Repair and current status | 개선 사항·현황

**Hojun's supplied field report:** increased NFC receiver gain to improve reading through the table; fixed a timing case where cube colour commands could be ignored; built and installed eight replacement tag-module sets. He reported the zone working. The Jisung / Jimin reader locations were reported misaligned beneath the table and needing carpentry; verify their actual labels before work.
Hojun 현장 보고: 테이블을 통한 인식 개선을 위해 NFC 수신 게인을 높였고, 큐브 색 명령이 타이밍상 무시되는 문제를 수정했으며, 태그 모듈 8세트를 새로 제작·설치했습니다. 현재 동작한다고 보고했습니다. 지성 / 지민 리더 위치는 테이블 아래 정렬 불량으로 목공 조치가 필요하다고 보고되었으며 작업 전 실제 라벨을 확인해야 합니다.

Sunday's report described seven nonworking sets; the later report says eight replacements. These describe different times and should not be reconciled into an invented final fault count. The "Jimin" spelling is retained from the supplied report, not silently changed to another member name.
일요일 보고의 미작동 7세트와 이후 교체 8세트는 서로 다른 시점의 수치입니다. 이를 임의의 최종 불량 개수로 합치지 않습니다. "지민"은 제공된 보고 표기를 유지했으며 임의로 다른 멤버명으로 바꾸지 않았습니다.

## Normal behaviour | 정상 동작

A **registered** cube found in the reader's database turns the local panel on through GPIO1 and receives DESERT colour (yellow). The plate sends TAG_STATE 1 on entry, 0 on removal; removal turns the local panel off. The shared tag core treats absence for about 700 ms as removal. An unknown tag does not activate the normal DesertZone panel path.
리더 DB에서 확인되는 **등록 큐브**는 GPIO1을 통해 로컬 패널을 켜고 DESERT 색상(노랑)을 받습니다. 진입 시 TAG_STATE 1, 제거 시 0을 보내며 제거 시 로컬 패널은 꺼집니다. 공통 태그 코어는 약 700 ms 부재를 제거로 처리합니다. 미등록 태그는 정상 DesertZone 패널 경로를 활성화하지 않습니다.

## Two separate checks, with the console | 콘솔을 이용한 두 가지 별도 확인

A desert plate plugged into the console opens the Zone panel; its **Monitor** tab shows each tap as it happens (UID, lookup result, radio delivery, reader health), and the Attention panel names the likely cause. There is no desert-specific walkthrough capture; the plate walkthrough in chapter 07 ({{shot:07-4}}, {{shot:C-2}}) applies.
사막 플레이트를 콘솔에 꽂으면 Zone 패널이 열립니다. **Monitor** 탭에 태그가 발생할 때마다(UID, 조회 결과, 무선 전달, 리더 상태) 표시되고 Attention 패널이 추정 원인을 알려 줍니다. 사막 전용 화면은 없으며 07장의 플레이트 화면({{shot:07-4}}, {{shot:C-2}})이 적용됩니다.

1. Place a known-good cube at the marked position. If no tag appears in the Monitor history, inspect actual reader position, power and PN532 rather than starting with cube firmware. The header's NFC pill (scanning / degraded / not responding) and the card "Plate … NFC reader not responding" → **Ask the plate to recover the reader** cover the reader side.<br>정상 큐브를 표시 위치에 댑니다. Monitor 이력에 태그가 없으면 큐브 펌웨어부터 바꾸기보다 리더 실제 위치·전원·PN532를 확인합니다. 헤더의 NFC 칩(scanning / degraded / not responding)과 카드 "Plate … NFC reader not responding" → **Ask the plate to recover the reader**가 리더 쪽을 다룹니다.
2. If the UID is seen but unknown, the Attention card says whether the plate's database is behind (**Update database over USB** / **Update database over the air**), the mapping is unpublished (**Sync & publish**) or the tag is unregistered (**Register at the station**). Compare Inventory › Zone database if in doubt.<br>UID는 보이나 미등록이면 Attention 카드가 플레이트 DB 구버전(**Update database over USB** / **Update database over the air**), 미게시 매핑(**Sync & publish**), 미등록 태그(**Register at the station**) 중 어느 경우인지 알려 줍니다. 의심스러우면 Inventory › Zone database와 비교합니다.
3. If lookup succeeds but the local lamp stays off, investigate local lamp supply, MOSFET output and wiring. Cube radio repair does not repair that local circuit, and the console cannot see the lamp.<br>조회 성공·로컬 조명 꺼짐이면 조명 전원·MOSFET·배선을 확인합니다. 큐브 무선 수리는 로컬 회로 수리가 아니며 콘솔은 조명을 볼 수 없습니다.
4. If the lamp works but the cube stays the wrong colour, read the Monitor's delivery pill: **No radio ACK** raises the card "Plate … could not reach cube #…" (cube off, out of range or on another channel); **Delivered** means the radio answered but says nothing about the LEDs. Compare another cube, cube power/firmware, mapping MAC and observe the cube after the repeated colour sends.<br>조명은 켜지지만 큐브 색이 다르면 Monitor의 전달 칩을 읽습니다. **No radio ACK**는 카드 "Plate … could not reach cube #…"(큐브 꺼짐·범위 밖·다른 채널)를 띄웁니다. **Delivered**는 무선 응답만 뜻하며 LED 상태는 알 수 없습니다. 다른 큐브, 큐브 전원·펌웨어, 매핑 MAC을 비교하고 색 재전송 이후 실제 큐브를 확인합니다.
5. If the issue follows one position across several cubes, retain it as a reader/mounting fault. If it follows one cube across good positions, remove that cube for registration/firmware diagnosis (plug it into USB: its Cube panel and cards show registration and firmware state).<br>여러 큐브에서 한 위치만 실패하면 리더·장착 문제로 분류합니다. 정상 위치 여러 곳에서 한 큐브만 실패하면 해당 큐브를 분리해 등록·펌웨어를 진단합니다(USB에 꽂으면 Cube 패널과 카드에 등록·펌웨어 상태가 표시됨).

Hojun's expectation that future faults are likely cube-related is field guidance, not proof that every subsequent fault is a cube fault.
향후 문제는 큐브일 가능성이 높다는 Hojun 의견은 현장 판단이며 이후 모든 고장을 큐브 문제로 확정하는 근거는 아닙니다.

## Why the colour repeat was added | 색 재전송을 추가한 이유

The inherited cube can keep only one pending received packet; a following packet can replace a colour command before the main loop processes it. A radio ACK may still have been sent. The tag core therefore sends two unconditional colour repeats at 120 and 400 ms, then retries a failing radio at 600 ms cadence within a 3-second window. Repeats are cancelled when another plate takes over to avoid repainting the cube after it moves. The General Radio's **Set zone** and the console's Monitor **Set zone** buttons use the same ×3 repeat.
기존 큐브는 대기 수신 패킷 한 개만 저장하여 메인 루프 처리 전 후속 패킷이 색 명령을 덮을 수 있습니다. 그래도 무선 ACK는 나갈 수 있습니다. 따라서 태그 코어는 120·400 ms에 무조건 두 번 색을 재전송하고, 무선 실패 시 3초 범위에서 600 ms 간격으로 재시도합니다. 다른 플레이트가 제어하면 이동 후 이전 색을 덮지 않도록 재전송을 취소합니다. General Radio의 **Set zone**과 콘솔 Monitor의 **Set zone** 버튼도 같은 3회 재전송을 사용합니다.

## Maintenance boundaries | 유지보수 범위

Use the Zone panel's Firmware & database tab for a replacement DesertZone board (profile **Desert**) and the Zone relay tab for database/gain updates over the air. Read actual gain application status (the RX gain pill and the "stored but the reader did not accept it" card). Receiver gain cannot correct a reader mounted away from the target. Reopening/repositioning the table should be coordinated with the installation/carpentry team and followed by NFC and visual-light tests.
DesertZone 교체는 Zone 패널의 Firmware & database 탭(프로파일 **Desert**), DB·게인 무선 변경은 Zone relay 탭을 사용합니다. 실제 게인 적용 상태(RX gain 칩과 "stored but the reader did not accept it" 카드)를 확인합니다. 타깃에서 벗어난 리더 위치는 게인으로 고칠 수 없습니다. 테이블 개방·위치 조정은 설치·목공팀과 협의하고 NFC·실제 조명 테스트를 수행합니다.

## Sources | 근거

`zones/firmware/DesertZone/DesertZone.ino` (desert-2.4.0), `NctTagPlate.h`; `console/advisor.py` (`zone.nfc_down`, `zone.not_acknowledged`, `tag.*`); Engineering Six PDF pages 15–18; Sangeun report 20 September and Hojun's later report supplied by Elliot. Evidence class: code-inspected; the NACK card path is simulation-verified.
위 소스, 원 PDF 15–18페이지, 9월 20일 Sangeun 보고 및 Elliot이 제공한 Hojun의 후속 보고 기준. 근거 구분: 코드 확인. NACK 카드 경로는 시뮬레이션 확인.

## Related guides | 관련 안내

{{page:00}}
{{page:07}}
{{page:03}}
