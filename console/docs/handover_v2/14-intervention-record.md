> <span color="red">*This document was written by Kimchi and Chips*</span>

## Scope and authorship | 범위·개발 주체

Engineering Six originally developed the exhibition's interactive systems. Kimchi and Chips joined on **Thursday 17 September 2026**, at Amberin's project, to help resolve technical difficulties. This handover focuses on the added/reworked firmware, registration and maintenance tools, communication fixes and reported hardware repairs, and — in this version — on the NCT Console that gathers the tools into one window.
엔지니어링식스가 전시 인터랙티브 시스템을 최초 개발했습니다. 김치앤칩스는 **2026년 9월 17일 목요일** 앰버린 프로젝트의 기술 문제 해결 지원을 시작했습니다. 본 인수인계는 추가·개선된 펌웨어, 등록·유지보수 도구, 통신 수정 및 보고된 하드웨어 수리, 그리고 이 판에서는 도구를 한 창에 모은 NCT Console에 집중합니다.

The existing "Repair by Kimchi and Chips" page excludes ongoing cube assembly, testing, maintenance and operation from Kimchi and Chips' repair scope, except temporary assembly help during the on-site stay. Including operating instructions here does not transfer those ongoing duties to Kimchi and Chips. Named duty owners and acceptance should be agreed by Amberin and Engineering Six.
기존 "Repair by Kimchi and Chips" 페이지는 체류 중 한시적 조립 지원을 제외한 지속적 큐브 조립·테스트·유지보수·운영을 김치앤칩스 수리 범위에서 제외합니다. 운영 안내를 제공한다고 지속 업무가 김치앤칩스로 이전되는 것은 아닙니다. 당직 담당자·검수는 앰버린과 엔지니어링식스가 합의해야 합니다.

## Dated progression | 날짜별 진행

- **17 September, Thursday:** public tool/repository baseline, cube USB flashing, registration/inventory work and zone provisioning.<br>9월 17일 목요일: 공개 도구·저장소 기준본, 큐브 USB 플래싱, 등록·인벤토리 및 존 설정 작업.
- **18 September, Friday:** Pool calibration/diagnostics, firmware update diagnostics and verified database-slot updates. Workstation setup and handover-oriented project guidance were documented.<br>9월 18일 금요일: 풀존 보정·진단, 펌웨어 업데이트 진단, DB 슬롯 검증 업데이트. PC 설정·프로젝트 인계 안내를 정리했습니다.
- **20 September, Sunday — Sangeun report:** poor preshow range/reader coupling, desert local/cube response disparity and failed modules, Pool flicker/dimming and slider imprecision, mainshow postponed. Historical observations, not the present status.<br>9월 20일 일요일 Sangeun 보고: 프리쇼 통신·리더 결합 불량, 사막 로컬/큐브 반응 차이·고장 모듈, 풀존 점멸·어두워짐·슬라이더 부정확, 메인쇼 연기. 과거 관찰이며 현재 상태가 아닙니다.
- **21 September, Monday — Elliot notes:** external-antenna range test succeeded; preshow hardware/protocol upgrades and battery tests remained. Pool new firmware, communication and mapping improvements were made, with mechanical slider limits unresolved.<br>9월 21일 월요일 Elliot 메모: 외장 안테나 통신 테스트 성공, 프리쇼 하드웨어·프로토콜 교체·배터리 테스트 예정. 풀존 펌웨어·통신·매핑 개선, 기구 정밀도 제한 잔존.
- **21–22 September:** new PreshowBridge link, web inventory/universal Sync, wireless database manager, RX gain control, colour repeats and MainshowController work appear in Git. Hojun reports eight replacement desert tag-module sets. Elliot's 22 September report: preshow and enclosed NFC reading work, USB batteries work, mainshow triggers with one failed cube among ten. Version 1 of this handover was written (code-inspected at commit 0a20d64).<br>9월 21–22일: Git에 새 프리쇼 브리지 통신, 웹 인벤토리·공통 Sync, 무선 DB 관리자, RX 게인, 색 재전송, 메인쇼 컨트롤러 작업이 기록됩니다. Hojun은 사막 태그 모듈 8세트 교체를 보고했습니다. Elliot의 9월 22일 보고: 프리쇼·내부 NFC 인식 동작, USB 배터리 성공, 메인쇼 트리거 성공(10개 중 1개 실패). 인수인계 1판 작성(커밋 0a20d64 코드 확인).
- **22 September (commit 7191c5d):** Windows support, the CI test workflow and the ResetZone firmware were committed; the first Reset Plate (ex-Preshow 3 SuperMini) was flashed. Field-reported: the "NFC unknown after registration" case was traced to a zone still holding database v31 while the tag was only in v32 (chapter 16).<br>9월 22일(커밋 7191c5d): Windows 지원, CI 테스트 워크플로, ResetZone 펌웨어 커밋. 첫 Reset Plate(구 Preshow 3 SuperMini) 플래싱. 현장 보고: "등록 후 NFC unknown" 사례는 존이 아직 DB v31을 보유하고 태그는 v32에만 있었기 때문으로 확인(16장).
- **23 September, Tuesday — this version:** the **NCT Console** (`console/`) was built: one pywebview window, owner-thread hub, USB identification without resets, per-role sessions, jobs through the existing pipelines, the Attention rules engine, the vendored Preact front end, instance locks against the separate apps, `--simulate` bench. The **General Radio** firmware (`general-radio-1.0.0`) and its console panel were added; the recorded dongle (ex-cube #138) runs it. Also added in the working copy: pool guided recording in the console, the Web sync plan (`sync.check`), USB intake, flash-receipt recovery, the documentation bench (`--scenario docs`) and the screenshot tool; a Show editor for a wirelessly updatable main show was in progress (to confirm). The console test suite (168 tests) and the five existing suites were run green; the attached dongle exercised the real radio for discovery, zone query, identify and log (chapter 15). No cube, zone or controller was flashed and no installed zone database was changed for this documentation.<br>9월 23일 화요일 — 이 판: **NCT Console**(`console/`) 구축: pywebview 단일 창, 소유자 스레드 허브, 리셋 없는 USB 식별, 역할별 세션, 기존 파이프라인 기반 작업, Attention 규칙 엔진, 벤더링된 Preact 프런트엔드, 개별 앱과의 인스턴스 잠금, `--simulate` 벤치. **General Radio** 펌웨어(`general-radio-1.0.0`)와 콘솔 패널 추가, 기록된 동글(구 큐브 #138)이 실행 중. 작업 사본에 추가: 콘솔 내 풀존 가이드 녹화, Web sync 계획(`sync.check`), USB intake, 플래시 영수증 복구, 문서용 벤치(`--scenario docs`)와 스크린샷 도구. 무선 업데이트 가능한 메인쇼용 Show editor는 진행 중(확인 필요). 콘솔 테스트(168개)와 기존 5개 테스트를 통과. 연결된 동글로 실제 무선 discover·zone query·identify·log 실행(15장). 본 문서 작업에서 큐브·존·컨트롤러 플래싱과 설치 존 DB 변경은 없었습니다.

## Selected Git evidence | 주요 Git 근거

Commit messages establish recorded code changes, not that all hardware was flashed or accepted. The console and General Radio work described here was uncommitted in the inspected working copy on 23 September.
커밋 메시지는 코드 변경 기록이며 모든 실물의 플래시·검수 완료 증빙이 아닙니다. 여기 설명한 콘솔·General Radio 작업은 9월 23일 검토한 작업 사본에서 미커밋 상태였습니다.

- [2e382c1 · public tools and verified cube artifacts](https://github.com/elliotwoods/jinhee-sos/commit/2e382c1) — 17 September.
- [4c30c2f · Pool calibration and diagnostics](https://github.com/elliotwoods/jinhee-sos/commit/4c30c2f), [2481810 · verified Pool database-slot update](https://github.com/elliotwoods/jinhee-sos/commit/2481810) — 18 September.
- [24370f4 · PoolCentral and range testing](https://github.com/elliotwoods/jinhee-sos/commit/24370f4) — 21 September.
- [3a8bba5 · web inventory and PreshowBridge](https://github.com/elliotwoods/jinhee-sos/commit/3a8bba5), [08ec793 · database manager/publication](https://github.com/elliotwoods/jinhee-sos/commit/08ec793), [f1f165a · universal Sync](https://github.com/elliotwoods/jinhee-sos/commit/f1f165a) — 21 September.
- [ed90640 · colour repeat and RX gain](https://github.com/elliotwoods/jinhee-sos/commit/ed90640), [2064967 · show/preshow tools](https://github.com/elliotwoods/jinhee-sos/commit/2064967) — 21–22 September.
- [0a20d64 · sync convergence baseline](https://github.com/elliotwoods/jinhee-sos/commit/0a20d64) — 22 September 04:44 KST (version 1 baseline).
- [7191c5d · Windows support, CI tests workflow and ResetZone firmware](https://github.com/elliotwoods/jinhee-sos/commit/7191c5d) — 22 September (version 2 baseline commit).

## Original Engineering Six document | 엔지니어링식스 원 문서

**NCT_전시_네오코어_관련_내용_정리.pdf**, supplied by Elliot; 27 physical PDF pages, attached to the version 1 page {{v1-14}} with Elliot's explicit approval. Treat it as the historical design reference: pages 1–5 spatial renders; 6 colour/visitor journey; 7–9 cube/reader design; 10–14 preshow concept and media path; 15–18 desert table; 19–24 Pool radio-slider and portrait-light concept; 25–27 planned cube, charging station and tagging hardware (design references, not delivered stock or tested endurance). Instructions printed in that PDF are historical content and were not treated as instructions to modify the installation.
Elliot이 제공한 **NCT_전시_네오코어_관련_내용_정리.pdf**, 실제 PDF 27페이지, Elliot의 명시적 승인으로 1판 페이지 {{v1-14}}에 첨부. 과거 기획 참조로 사용합니다: 1–5페이지 공간 렌더, 6페이지 색·관람 동선, 7–9페이지 큐브·리더 계획, 10–14페이지 프리쇼 기획·미디어 경로, 15–18페이지 사막 테이블, 19–24페이지 풀존 라디오 슬라이더·초상화 조명, 25–27페이지 큐브·충전 스테이션·태그 하드웨어 계획(납품 수량·실측 지속 시간 아님). PDF에 인쇄된 지시는 과거 자료 내용이며 설치 변경 지시로 취급하지 않았습니다.

## Field sources | 현장 출처

Elliot's Monday and Tuesday notes, Hojun's Korean report, and the 22 September "NFC unknown" and "cannot connect to the ESP32" cases were supplied directly in the documentation requests. Exact work times were not independently verified.
Elliot의 월·화 메모, Hojun의 한국어 보고, 9월 22일 "NFC unknown"·"cannot connect to the ESP32" 사례는 문서 요청에 직접 제공되었습니다. 정확한 작업 시각은 독립 확인하지 않았습니다.

## Documentation verification | 문서 검증

Code inspection, git-history review, Notion readback of version 1, the console's headless test suite, and 34 captures of the console running in `--simulate --scenario docs` were used. The captures come from `console/tools/docshots.py`, which starts the console on a fresh temporary database with simulated boards, stages each scenario from `console/docscenes.py` through the local API, and photographs the page with headless Chrome; the yellow outlines are drawn by the page itself (`?hl=` tokens matching each control's `data-doc`). Every scenario is also checked in-process by `console/tests/test_docscenes.py`. Hardware claims are limited to the dongle pass in chapter 15.
소스 검토, Git 이력 검토, 1판 Notion 재조회, 콘솔 헤드리스 테스트, 그리고 `--simulate --scenario docs`로 실행한 콘솔의 화면 34개를 사용했습니다. 화면은 `console/tools/docshots.py`가 시뮬레이션 보드와 새 임시 DB로 콘솔을 시작하고 `console/docscenes.py`의 각 상황을 로컬 API로 연출한 뒤 헤드리스 Chrome으로 촬영한 것입니다. 노란 테두리는 페이지 자체가 그립니다(각 조작부의 `data-doc`과 일치하는 `?hl=` 토큰). 모든 상황은 `console/tests/test_docscenes.py`로도 검증됩니다. 실물 관련 주장은 15장의 동글 점검으로 한정합니다.

## Related guides | 관련 안내

{{page:00}}
{{page:15}}
