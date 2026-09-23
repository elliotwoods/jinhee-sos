<span color="red">*This document was written by Kimchi and Chips*</span>

> [!INFO] **Who:** Amberin, Engineering Six · **When:** to see what changed and what is still open · **You need:** nothing
> **누가:** 앰버린, 엔지니어링식스 · **언제:** 무엇이 바뀌었고 무엇이 남았는지 확인할 때 · **준비물:** 없음

Engineering Six developed the exhibition. Kimchi and Chips joined on Thursday 17 September 2026, at Amberin's request, to help solve technical problems. This page lists what we fixed, area by area, and how sure we are.
<kr>엔지니어링식스가 전시를 개발했습니다. 김치앤칩스는 2026년 9월 17일 목요일 앰버린의 요청으로 기술 문제 해결을 돕기 시작했습니다. 이 페이지는 영역별로 무엇을 고쳤는지, 얼마나 확실한지 정리합니다.</kr>

"Problem before" is mostly Sangeun's report of 20 September; a few rows come from the original code. It is history, not the current state.
<kr>"이전 문제"는 대부분 9월 20일 Sangeun의 보고이며, 일부는 원래 코드에서 확인한 내용입니다. 과거 기록이며 현재 상태가 아닙니다.</kr>

## Preshow | 프리쇼

| Problem before · 이전 문제 | What we changed · 변경 내용 | Status now · 현재 상태 | Evidence · 근거 |
|---|---|---|---|
| Tags read poorly through the enclosure; readers disturbed each other · 함 너머로 태그 인식 불량, 리더 간 간섭 | New boards with an external antenna; reader gain raised; readers repositioned in the wooden enclosure · 외장 안테나 보드로 교체, 리더 게인 상향, 목재 함 안 위치 조정 | Reliable reading through the wood · 목재 너머 안정적 인식 | Field-reported (Elliot, 22 Sep) |
| The original media receiver only listened: no acknowledgement and no retry, so a lost cue went unnoticed (from its archived code) · 원래 미디어 수신부는 듣기만 함: 확인 응답·재전송 없음, 유실된 큐를 알 수 없음(보관된 코드 기준) | New **Preshow bridge**: every event is acknowledged and retried. Boards and bridge can be updated in either order · 새 **프리쇼 브리지**: 모든 이벤트 확인 응답·재전송. 순서와 관계없이 업데이트 가능 | Butterfly cues work · 나비 큐 동작 | Code-checked; Field-reported (Elliot, 22 Sep) |
| Batteries · 배터리 | Small LiPo batteries tried; they failed. USB batteries work · 소형 LiPo 시도 실패, USB 배터리 동작 | Runtime not yet measured · 지속 시간 미측정 | To confirm |

More detail: {{page:X04}}
<kr>자세한 내용: {{page:X04}}</kr>

## Desert | 사막

| Problem before · 이전 문제 | What we changed · 변경 내용 | Status now · 현재 상태 | Evidence · 근거 |
|---|---|---|---|
| The name panel lit but the cube sometimes stayed the wrong colour · 이름 패널은 켜지지만 큐브 색이 가끔 바뀌지 않음 | The zone board now sends the colour three times and retries for up to 3 s, so a cube cannot miss it · 존 보드가 색을 3회 보내고 최대 3초 재시도 | Fixed in firmware desert-2.3.0, which most desert boards run · 대부분의 사막 보드가 쓰는 desert-2.3.0에서 수정 | Code-checked; zone Field-reported (Hojun) |
| Tags did not read through the table; seven tag modules failed · 테이블 너머 인식 불량, 태그 모듈 7세트 불량 | Reader gain raised; eight replacement tag-module sets built and installed (Hojun) · 리더 게인 상향, 교체 모듈 8세트 제작·설치(Hojun) | Zone reported working · 존 동작 보고 | Field-reported (Hojun) |
| Jisung / Jimin readers misaligned under the table · 지성/지민 리더 정렬 불량 | Not fixed: needs carpentry · 미수정, 목공 필요 | Open · 미결 | To confirm |

More detail: {{page:X05}}
<kr>자세한 내용: {{page:X05}}</kr>

## Pool / forest | 풀·숲

| Problem before · 이전 문제 | What we changed · 변경 내용 | Status now · 현재 상태 | Evidence · 근거 |
|---|---|---|---|
| Frame lamps flickered and dimmed · 프레임 조명 깜빡임·어두워짐 | New pool radio and **Pool central controller** firmware; the radio link rebuilt with heartbeats and hold times · 풀 라디오·**풀 중앙 컨트롤러** 펌웨어 교체, 무선 연결 재구성 | With no cube present, every lamp is off · 큐브가 없으면 모든 조명 꺼짐 | Code-checked; Field-reported |
| Sliders lit the wrong frame · 슬라이더가 엉뚱한 프레임을 켬 | Slider calibration and filtering in the console; output-to-frame map corrected · 콘솔 슬라이더 보정·필터, 출력·프레임 대응 수정 | Every slider position 1–23 lights its own lamp · 위치 1–23이 각각 자기 조명을 켬 | Field-reported (Hojun, 23 Sep) |
| Faulty relay module and wiring · 릴레이 모듈·배선 불량 | 16-channel relay module replaced by three 8-channel modules; rewired; frame map re-measured (poolcentral-4.2.2) · 16채널 → 8채널 3개 교체, 재배선, 매핑 재측정 | Working; relay power supply still to check · 동작, 릴레이 전원 확인 필요 | Field-reported (Hojun) |
| Slider cannot return exactly to a printed name · 슬라이더가 인쇄 이름 위치로 정확히 못 돌아감 | Mechanical limit; software cannot fix it · 기구 한계, 소프트웨어로 해결 불가 | Label treatment needs a decision · 이름 표시 처리 결정 필요 | To confirm |

More detail: {{page:X06}}
<kr>자세한 내용: {{page:X06}}</kr>

## Main show | 메인쇼

| Problem before · 이전 문제 | What we changed · 변경 내용 | Status now · 현재 상태 | Evidence · 근거 |
|---|---|---|---|
| Cubes ignored the old M5 show starter: it sent the wrong command · 예전 M5 시작 장치가 잘못된 명령을 보내 큐브가 무시 | New **Mainshow controller** (#134); the media team's 5 V signal adapted to it · 새 **메인쇼 컨트롤러**(#134), 미디어팀 5 V 신호 변환 | The show starts on site; 9 of 10 test cubes played · 현장에서 쇼 시작, 시험 큐브 10개 중 9개 재생 | Field-reported (Elliot, 22 Sep) |
| The show animation was fixed inside the cube firmware · 쇼 애니메이션이 큐브 펌웨어에 고정 | Show as data (cube v1.5.0+): the **Show editor** edits, publishes and sends a show without reflashing · 쇼가 데이터가 됨: **Show editor**로 편집·게시·전송, 재플래시 불필요 | Show v6 published; six cubes hold it · 쇼 v6 게시, 큐브 6개 보유 | Bench-verified (cube reports; room-wide playback not watched) |
| A cube that missed the start stayed dark · 시작을 놓친 큐브는 꺼진 채 | **Show clock** (mainshow-1.3.0): a late cube joins the running show · **쇼 타임코드**로 늦은 큐브 합류 | Bench only; #134 still runs mainshow-1.2.0 · 벤치만, #134는 1.2.0 | Bench-verified (cube #17, serial logs) |

More detail: {{page:X07}}
<kr>자세한 내용: {{page:X07}}</kr>

## Cubes & registration | 큐브·등록

| Problem before · 이전 문제 | What we changed · 변경 내용 | Status now · 현재 상태 | Evidence · 근거 |
|---|---|---|---|
| Cube firmware carried Wi-Fi update code and credentials; no safe way to reflash · 큐브 펌웨어에 Wi-Fi 업데이트·자격증명, 안전한 재플래시 방법 없음 | v1.4.1-USB.2: Wi-Fi removed, USB identity added. USB flashing that keeps the cube number and tag, checks the result and keeps a receipt · Wi-Fi 제거, USB 신원 추가. 번호·태그를 유지하고 결과를 확인·기록하는 USB 플래시 | Fleet on v1.4.1-USB.2; six cubes on v1.7.0-USB.1 · 대부분 v1.4.1, 큐브 6개 v1.7.0 | Bench-verified (six cubes, console receipts; LEDs not recorded) |
| Registration and cube number records needed rework (our first work item, 17 Sep; no fault report in the sources) · 등록과 큐브 번호 기록 재작업 필요(9월 17일 첫 작업, 출처에 결함 보고 없음) | Registration with the tag reader, number suggestions, safe tag transfer; **Register** page for many cubes · 태그 리더 등록, 번호 제안, 안전한 태그 이전; 여러 큐브용 **Register** 페이지 | Old app proven; the console route not yet run on hardware · 기존 앱 검증됨, 콘솔 경로는 실물 미실행 | Simulation-verified (console) |
| A newly registered cube was "unknown" at a zone · 새로 등록한 큐브를 존이 모름 | Zone databases published on the web inventory and sent to zones automatically, over the air or USB · 존 DB를 웹에 게시하고 무선·USB로 자동 배포 | Zones out of range still hold older databases · 범위 밖 존은 이전 DB 보유 | Bench-verified (zone query); automatic path Simulation-verified |
| Computers disagreed about the inventory · 컴퓨터마다 인벤토리가 다름 | **Web inventory** and a **Sync** that never asks a question and gives the same answer everywhere · **웹 인벤토리**와 질문 없이 어디서나 같은 결과를 내는 **Sync** | Works if every computer runs current code · 모든 컴퓨터가 최신 코드일 때 동작 | Simulation-verified |
| No zone board returned a collected cube to idle (idle saves battery) · 회수한 큐브를 대기로 돌리는 존 보드 없음(대기는 배터리 절약) | New zone kind: the **Reset plate** returns a tapped cube to idle · 새 존 종류: **리셋 플레이트**가 태그한 큐브를 대기로 | Two boards run it; tap-to-idle not yet watched with a real cube · 보드 2개 설치, 실제 큐브로 미확인 | Code-checked; To confirm |

More detail: {{page:X03}} · {{page:X08}}
<kr>자세한 내용: {{page:X03}} · {{page:X08}}</kr>

## Operator tools: the NCT Console | 운영 도구: NCT 콘솔

| Problem before · 이전 문제 | What we changed · 변경 내용 | Status now · 현재 상태 | Evidence · 근거 |
|---|---|---|---|
| Ten separate apps; USB ports chosen by hand · 개별 앱 10개, USB 포트 수동 선택 | One window, the **NCT Console**. Plugged-in boards are identified without a restart · 하나의 창 **NCT 콘솔**, 꽂은 보드를 재시작 없이 식별 | Logic tested; bench pass with board #138 · 로직 테스트, #138 벤치 점검 | Simulation-verified; Bench-verified (#138) |
| "Sent" could look like success; pop-ups interrupted work · "전송"이 성공처럼 보임, 팝업이 작업 방해 | **Result status** on every action; **suggestion cards** that never block; **hold to confirm** on risky buttons · 모든 작업에 **결과 상태**, 막지 않는 **제안 카드**, 위험 버튼 **길게 눌러 확인** | In use · 사용 중 | Simulation-verified |
| English only · 영어만 | **EN / KR** switch · **EN / KR** 스위치 | Korean needs native review · 한국어 원어민 검토 필요 | Simulation-verified |
| Pairing station and radio dongle were different boards · 등록 스테이션과 무선 동글이 별개 | One **Workstation** firmware merges them · 하나의 **워크스테이션** 펌웨어로 통합 | Built; not yet on any board · 빌드됨, 아직 설치된 보드 없음 | Simulation-verified, build only |

Until each console path has run once on real hardware, the older separate apps remain the proven route for that job.
<kr>콘솔의 각 경로를 실물로 한 번씩 실행하기 전까지는 해당 작업에 기존 개별 앱이 검증된 경로입니다.</kr>

More detail: {{page:X11}}
<kr>자세한 내용: {{page:X11}}</kr>

## Still open | 남은 항목

| Item · 항목 | Owner · 담당 | Evidence · 근거 |
|---|---|---|
| Pool printed names: cover or treat them · 풀존 인쇄 이름 처리 | Amberin / Lotte decide · 앰버린·롯데 결정 | To confirm |
| Desert Jisung / Jimin alignment · 사막 지성/지민 정렬 | Engineering Six, carpentry · 엔지니어링식스·목공 | To confirm |
| Battery runtime (preshow, cubes) · 배터리 지속 시간 | Operator · 운영사 | To confirm |
| Find and fix the one failed main-show cube · 메인쇼 실패 큐브 1개 | Cube desk · 큐브 담당 | Field-reported (Elliot) |
| Zone database v38 holds fake test records; publish a clean version · 존 DB v38 가짜 기록 정리 | Elliot | Code-checked |
| 19 zones hold older zone databases · 존 19개 이전 DB 보유 | Cube desk · 큐브 담당 | Bench-verified |
| Every computer must run current code before it syncs · 모든 컴퓨터 최신 코드 필요 | Engineering team · 기술팀 | Field-reported (Elliot) |
| Pool relay power supply; duplicate pool radio ids · 풀 릴레이 전원, 풀 라디오 id 중복 | Engineering Six, Hojun | Field-reported |
| Media records: TouchDesigner, 5 V show signal interface · 미디어 기록: TouchDesigner, 5 V 신호부 | Media team, Engineering Six · 미디어팀·엔지니어링식스 | To confirm |
| Console hardware checks; flash the Workstation firmware · 콘솔 실물 점검, 워크스테이션 펌웨어 설치 | Engineering team · 기술팀 | Simulation-verified |

The full list, the acceptance walk and the sign-off form: {{page:X13}}
<kr>전체 목록, 인수 검수 순회, 서명 양식: {{page:X13}}</kr>

## Where the details are | 자세한 내용

Dates, commits, field sources and how this document was checked: {{page:X12}}
<kr>날짜, 커밋, 현장 출처, 문서 검증 방법: {{page:X12}}</kr>

<span color="red">*This document was written by Kimchi and Chips*</span>
