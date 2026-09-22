> <span color="red">*This document was written by Kimchi and Chips*</span>

## How to use this chapter | 사용 방법

Each entry records an observed symptom, its confirmed cause and the fix that resolved it, with the evidence class from the handbook cover. New in this version: **What the console shows** — the exact Attention card title and the action buttons it offers for that case, so the operator can recognise the situation from the screen. First-response triage during opening hours stays in chapter 02; this chapter is the growing case record.
각 항목은 관측된 증상, 확인된 원인, 실제로 해결된 조치를 표지의 근거 구분과 함께 기록합니다. 이 판에서 새로 추가된 **콘솔 표시**는 해당 사례에 대한 Attention 카드 제목과 제공되는 동작 버튼을 정확히 적어 운영자가 화면에서 상황을 알아볼 수 있게 합니다. 운영 중 초기 대응은 02장에 있으며, 본 장은 누적되는 사례 기록입니다.

## Newly registered cube is not recognized at a zone ("NFC unknown") | 새로 등록한 큐브를 존이 인식하지 못함("NFC unknown")

**Symptoms / 증상**
- A cube registered a moment ago is not recognized at a reader; the zone reports NFC unknown.<br>방금 등록한 큐브를 리더가 인식하지 못하고 존이 NFC unknown으로 표시합니다.
- The registration exists on the computer's inventory, so the cube looks correct on its Cube panel.<br>PC 인벤토리에는 등록이 있어 Cube 패널에서는 정상으로 보입니다.
- Reset / release at that reader also fails, because the registration is not in the reader's own database.<br>해당 리더에서 리셋·해제도 실패합니다. 등록 정보가 리더 자체 DB에 없기 때문입니다.

**What the console shows / 콘솔 표시**
With the plate on USB, its Monitor tab lists the tap as **unknown tag** and the Attention panel raises one of:<br>플레이트를 USB에 꽂으면 Monitor 탭에 **unknown tag**로 표시되고 Attention 패널에 다음 중 하나가 나타납니다:
- **"Unknown tag on "‹plate›" is cube #‹n› — the plate's database is behind"** — actions **Update database over USB** (plate on USB) and **Update database over the air** (a dongle connected).<br>동작: **Update database over USB**(플레이트 USB 연결), **Update database over the air**(동글 연결).
- **"Unknown tag on "‹plate›" is cube #‹n› — not yet in the published database"** — action **Sync & publish**; the mapping is only on this computer.<br>동작: **Sync & publish**. 매핑이 이 컴퓨터에만 있습니다.
- **"Unknown tag on "‹plate›" is a pending registration for cube #‹n›"** — action **Retry the saved registration**; the cube never acknowledged.<br>동작: **Retry the saved registration**. 큐브가 확인 응답하지 않았습니다.
Over the air, the Zone relay table shows the plate as **Out of date** and the card **"Zone "‹plate›" holds database v‹old›; published is v‹new›"** offers **Update database over the air**.<br>무선으로는 Zone relay 표에 플레이트가 **Out of date**로 표시되고 카드 **"Zone "‹plate›" holds database v‹old›; published is v‹new›"**가 **Update database over the air**를 제공합니다.
{{shot:C-2}}
Unknown tag on the plate, known here: Update database over USB / 플레이트에서 알 수 없는 태그, 여기서는 알려짐: USB로 데이터베이스 업데이트

**Cause / 원인**
The ESP32 in the zone still holds an older copy of the database (in the reported case v31, while the new tag was only in v32). Registering on the computer does not reach the zone by itself; the zone must receive the new published database.<br>존의 ESP32에 이전 버전 DB가 남아 있습니다(보고된 사례에서는 v31, 새 태그는 v32에만 있었음). PC에서 등록해도 자동으로 존에 전달되지 않으며, 존이 새 게시 DB를 받아야 합니다.

**Fix / 조치**
1. Click **Sync** in the top bar (uploads and publishes), then update the zone by one of two routes: **Update database over USB** on the plate's Firmware & database tab (or the card's button), or **Update database over the air** / **Update all out-of-date zones** on the dongle's Zone relay tab.<br>상단 **Sync**(업로드·게시) 후 두 가지 중 하나로 존을 갱신합니다: 플레이트의 Firmware & database 탭(또는 카드 버튼)의 **Update database over USB**, 또는 동글 Zone relay 탭의 **Update database over the air** / **Update all out-of-date zones**.
2. Confirm the zone reports the intended version and CRC (**Current** pill; timeline "Database v… confirmed"), then re-tag the cube at that reader and check the expected effect and release. The Monitor tab should now show **FOUND Cube #n**.<br>존이 목표 버전·CRC를 보고하는지(**Current** 칩, 타임라인 "Database v… confirmed") 확인한 뒤 해당 리더에서 큐브를 다시 태그해 효과와 해제를 확인합니다. Monitor 탭에 **FOUND Cube #n**이 표시되어야 합니다.

**Notes / 참고**
- With **Auto-update all** on, the console keeps querying zones and updates out-of-date ones automatically; zones that were powered off appear and update as soon as power is restored. It is on by default (Settings › Automatic updates); a plate plugged in over USB is also updated automatically.<br>**Auto-update all**을 켜 두면 콘솔이 계속 존을 조회해 구버전을 자동 갱신합니다. 꺼져 있던 존은 전원이 들어오는 즉시 나타나 갱신됩니다. 기본 켜짐이며(Settings › Automatic updates), USB로 꽂은 플레이트도 자동 갱신됩니다.
- The plate on USB and the dongle can be connected at the same time, so the update and the retest can be done in one pass.<br>USB 플레이트와 동글을 동시에 연결할 수 있어 갱신과 재시험을 한 번에 진행할 수 있습니다.
- A separate, occasional report exists of register → flash → tag still failing. That is a different symptom and was not the cause in this case; log it separately if seen.<br>등록 → 플래싱 → 태그 후에도 간헐적으로 실패한다는 별도 보고가 있습니다. 이번 사례와는 다른 증상이므로 발생 시 별도로 기록합니다.

Field-reported, 22 September 2026; console cards code-inspected and simulation-verified.<br>현장 보고, 2026년 9월 22일. 콘솔 카드는 코드 확인·시뮬레이션 확인.

## Registration fails with a "cannot connect to the ESP32" message | 등록 중 ESP32 통신 실패 메시지

**Symptoms / 증상**
- A cube connected over USB is identified and shows an ID, which may be a previously used identity from an earlier cube.<br>USB로 연결한 큐브가 식별되며 ID가 표시되고, 이전 큐브에 사용되던 신원일 수 있습니다.
- When the tag is presented to the NFC reader, registration fails and the interface reports that it cannot communicate with the ESP32.<br>태그를 NFC 리더에 올리면 등록이 실패하고 인터페이스에 ESP32와 통신할 수 없다는 메시지를 표시합니다.

**What the console shows / 콘솔 표시**
The station panel banner turns to **TAG NOT REGISTERED** or the timeline shows the attempts with **No radio ACK** and the card **"Registration not confirmed"** (**Retry the saved registration**) or, after three attempts, **"Plate/station could not reach cube #n"** — the cube is off, out of range or on another channel. The cube's own card keeps the **Unconfirmed** / **Registering** pill.<br>스테이션 패널 배너가 **TAG NOT REGISTERED**로 바뀌거나 타임라인에 **No radio ACK** 시도와 카드 **"Registration not confirmed"**(**Retry the saved registration**), 3회 시도 후에는 **"… could not reach cube #n"**(큐브 꺼짐·범위 밖·다른 채널)이 표시됩니다. 큐브 카드에는 **Unconfirmed** / **Registering** 칩이 유지됩니다.

**Likely cause / 추정 원인**
An unreliable wireless link to the device, most likely an antenna connection or a device that needs to be restarted, rather than a database or registration problem. The exact wording of the error message was not recorded.<br>DB나 등록 문제가 아니라 안테나 연결 불량 또는 재시작이 필요한 장치 등 무선 연결 불안정으로 추정됩니다. 오류 메시지의 정확한 문구는 기록되지 않았습니다.

**Fix / 조치**
1. Disconnect and reconnect the antenna, checking that it is fully seated.<br>안테나를 분리했다가 다시 체결하고 완전히 결합되었는지 확인합니다.
2. Press the reset button on the device.<br>장치의 리셋 버튼을 누릅니다.
3. Repeat the registration (**Retry the saved registration** on the card, or **Send saved mapping** on the cube card). In the observed case it then succeeded.<br>등록을 다시 수행합니다(카드의 **Retry the saved registration** 또는 큐브 카드의 **Send saved mapping**). 관측된 사례에서는 이후 정상 등록되었습니다.

**Notes / 참고**
- If the message returns repeatedly on the same device, treat it as a hardware/antenna fault and set the device aside rather than retrying registration many times.<br>동일 장치에서 반복되면 등록을 여러 번 재시도하지 말고 하드웨어·안테나 결함으로 보고 분리합니다.
- Record the exact error message next time it occurs (the console's timeline dock keeps it); it will distinguish a link failure from a database or identity conflict.<br>다음 발생 시 오류 메시지를 정확히 기록합니다(콘솔 타임라인 도크에 남음). 통신 장애와 DB·신원 충돌을 구분하는 데 도움이 됩니다.

Field-reported, 22 September 2026.<br>현장 보고, 2026년 9월 22일.

## The console or a separate app refuses to start | 콘솔 또는 개별 앱이 실행되지 않음

**Symptoms / 증상:** "Another app is open on this database: …" naming the pairing app, cube flasher, zone database manager, mainshow app or the NCT Console.<br>"Another app is open on this database: …"에 등록 앱, 큐브 플래셔, 존 DB 관리자, 메인쇼 앱 또는 NCT Console 이름이 표시됩니다.

**What the console shows / 콘솔 표시:** if the console is the one running, the Attention card **"Another app is open on this database"** lists the other app; the separate app's own message names the console.<br>콘솔이 실행 중이면 Attention 카드 **"Another app is open on this database"**에 상대 앱이 표시되고, 개별 앱의 메시지에는 콘솔 이름이 표시됩니다.

**Cause / 원인:** the instance locks are intentional; the console and the separate apps must never write the same database at the same time.<br>인스턴스 잠금은 의도된 것입니다. 콘솔과 개별 앱이 같은 DB를 동시에 쓰면 안 됩니다.

**Fix / 조치:** close one, then start the other. Do not delete lock files while an app is running.<br>한쪽을 닫은 뒤 다른 쪽을 시작합니다. 앱 실행 중 잠금 파일을 삭제하지 않습니다.

Code-inspected and simulation-verified (`console/tests/test_locks.py`); dongle pass on 23 September.<br>코드 확인·시뮬레이션 확인(`console/tests/test_locks.py`); 9월 23일 동글 점검.

## Related guides | 관련 안내

{{page:00}}
{{page:02}}
{{page:03}}
{{page:06}}
