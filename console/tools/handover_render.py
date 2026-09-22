#!/usr/bin/env python
"""Render a Handover v2 chapter draft (console/docs/handover_v2/NN-*.md) into final Notion markdown.

    python console/tools/handover_render.py NN [--uploads console/docs/handover_v2/uploads.json] [--out FILE]

Placeholders: {{shot:ID}} → `![EN caption / KR caption](<markdown_source>)` from uploads.json (id → markdown_source,
written by the publishing step after each notion-create-file-upload); the caption line that follows the placeholder
in the draft is consumed into the image caption. {{page:NN}} → <mention-page url="…"> from PAGES.json (00 = root);
{{v1-root}}, {{v1-14}} → mentions of the v1 pages; {{test-report-table}} → the acceptance table below.
Unresolved placeholders make the script exit 1 so a page is never published with a raw token.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent / 'docs' / 'handover_v2'
V1_14 = 'https://app.notion.com/p/3e35e8c80bde8198b785f8910d56729f'

TEST_REPORT_TABLE = """| Check (console/TEST_REPORT_2026-09-23.md) | Result | Evidence class |
|---|---|---|
| Dongle identified without reset (General Radio general-radio-1.1.0, AC:27:6E:82:68:54) | done: session opened, `connected=true` | dongle-verified |
| Discover cubes over the radio | 113 cubes answered; all in the inventory | dongle-verified (radio reply only) |
| Query zones | 27 zones in range (−61…−96 dBm), all *current* at v37; 19 out-of-range records *behind* | dongle-verified |
| Identify one zone (Preshow 4) + request its log | delivered; log frame with 8 entries = acknowledged; blink not observed | dongle-verified (acknowledged, not visually verified) |
| Set RX gain (48 dB = stored value) | zone replied `set_result=1 (ok)`; nothing changed | dongle-verified (acknowledged) |
| Old pairing app refused while the console runs | refused: "This database is already open in another pairing window." | dongle-verified (one direction) |
| Advisor readability on the real inventory | 9 cards; `apps.legacy_open` false positive fixed | dongle-verified |
| Zone database update over the air | **not performed** (needs an explicit go: it changes an installation board) | unverified |
| Cube flash, database over USB, calibration, cue test, show trigger, USB intake, receipts recovery through the console | simulation only (`console/tests`, 168 tests green) | simulation-verified |
| 34 screenshot scenarios stage and settle | `tests/test_docscenes.py` green; captures reviewed | simulation-verified |

| 점검 항목 | 결과 | 근거 등급 |
|---|---|---|
| 리셋 없이 동글 식별 (General Radio general-radio-1.1.0) | 완료: 세션 열림 | 동글 검증 |
| 무선 큐브 탐색 | 113개 큐브 응답, 모두 인벤토리에 있음 | 동글 검증(무선 응답만) |
| 존 조회 | 범위 내 27개 존 모두 v37 *current*, 범위 밖 19개 레코드 *behind* | 동글 검증 |
| 존 하나 Identify + 로그 요청 (Preshow 4) | 전달됨, 8개 항목의 로그 프레임 = 확인 응답, 점멸은 미확인 | 동글 검증(응답 확인, 육안 미검증) |
| RX gain 설정 (저장값과 같은 48 dB) | 존 응답 `set_result=1 (ok)`, 변경 없음 | 동글 검증(응답 확인) |
| 콘솔 실행 중 기존 페어링 앱 거부 | 거부됨 | 동글 검증(한 방향) |
| 실제 인벤토리에서 Attention 카드 가독성 | 카드 9개, `apps.legacy_open` 오탐 수정 | 동글 검증 |
| 무선 존 데이터베이스 업데이트 | **수행하지 않음**(설치 보드를 바꾸므로 명시적 승인 필요) | 미검증 |
| 콘솔을 통한 큐브 플래시·USB DB·보정·큐 테스트·쇼 트리거·USB 인테이크·영수증 복구 | 시뮬레이션만(`console/tests` 168개 통과) | 시뮬레이션 검증 |
| 스크린샷 시나리오 34개 스테이징·정착 | `tests/test_docscenes.py` 통과, 캡처 검토 | 시뮬레이션 검증 |"""


def manifest_captions():
    try:
        manifest = json.loads((HERE.parent / 'docs' / 'shots' / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {s['id']: f"{s['en']} / {s['kr']}" for s in manifest.get('shots', [])}


def inline_shots(text, uploads):
    """A {{shot:ID}} inside a sentence becomes "(capture below)" / "(아래 캡처)" and the image follows the paragraph."""
    captions = manifest_captions()
    paragraphs = text.split('\n\n')
    out = []
    for paragraph in paragraphs:
        ids = re.findall(r'\{\{shot:([A-Za-z0-9-]+)\}\}', paragraph)
        if not ids:
            out.append(paragraph)
            continue
        seen = []
        for sid in ids:
            if sid not in seen:
                seen.append(sid)

        def swap(m):
            line_start = paragraph.rfind('\n', 0, m.start()) + 1
            korean = re.search(r'[\uac00-\ud7a3]', paragraph[line_start:m.start()]) is not None
            return '(아래 캡처)' if korean else '(capture below)'

        paragraph = re.sub(r'\{\{shot:[A-Za-z0-9-]+\}\}', swap, paragraph)
        paragraph = re.sub(r'\(\s*\(capture below\)(?:\s*,\s*\(capture below\))*\s*\)', '(captures below)', paragraph)
        paragraph = re.sub(r'\(\s*\(아래 캡처\)(?:\s*,\s*\(아래 캡처\))*\s*\)', '(아래 캡처)', paragraph)
        images = []
        for sid in seen:
            source = uploads.get(sid)
            if not source:
                raise SystemExit(f'no upload for shot {sid}')
            images.append(f'![{captions.get(sid, sid)}]({source})')
        out.append(paragraph + '\n\n' + '\n\n'.join(images))
    return '\n\n'.join(out)


def render(number, uploads, pages):
    files = sorted(DOCS.glob(f'{number}-*.md'))
    if not files:
        raise SystemExit(f'no draft for chapter {number}')
    text = files[0].read_text(encoding='utf-8')
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.fullmatch(r'\s*\{\{shot:([A-Za-z0-9-]+)\}\}\s*', line)
        if m:
            sid = m.group(1)
            caption = ''
            if i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith(('#', '{{', '!')):
                caption = lines[i + 1].strip()
                i += 1
            source = uploads.get(sid)
            if not source:
                raise SystemExit(f'no upload for shot {sid}')
            out.append(f'![{caption}]({source})')
            i += 1
            continue
        out.append(line)
        i += 1
    text = '\n'.join(out)
    text = inline_shots(text, uploads)

    def page(m):
        key = m.group(1)
        entry = pages['root'] if key == '00' else pages.get(key)
        if not entry:
            raise SystemExit(f'no page for {{page:{key}}}')
        return f'<mention-page url="{entry["url"]}"/>'

    text = re.sub(r'\{\{page:(\d\d)\}\}', page, text)
    text = text.replace('{{v1-root}}', f'<mention-page url="{pages["v1_root"]["url"]}"/>')
    text = text.replace('{{v1-14}}', f'<mention-page url="{V1_14}"/>')
    text = text.replace('{{test-report-table}}', TEST_REPORT_TABLE)
    left = re.findall(r'\{\{[^}]*\}\}', text)
    if left:
        raise SystemExit(f'unresolved placeholders: {sorted(set(left))}')
    # Notion pages get their title from properties: drop a leading H1 if the draft carries one
    if text.lstrip().startswith('# '):
        text = text.lstrip().split('\n', 1)[1]
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('number', help='chapter number NN (00 = root)')
    parser.add_argument('--uploads', type=Path, default=DOCS / 'uploads.json')
    parser.add_argument('--pages', type=Path, default=DOCS / 'PAGES.json')
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args(argv)
    uploads = json.loads(args.uploads.read_text(encoding='utf-8')) if args.uploads.exists() else {}
    pages = json.loads(args.pages.read_text(encoding='utf-8'))
    text = render(args.number, uploads, pages)
    if args.out:
        args.out.write_text(text, encoding='utf-8', newline='\n')
        print(f'{args.out} ({len(text)} chars)')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
