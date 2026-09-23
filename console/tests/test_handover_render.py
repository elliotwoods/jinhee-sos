"""The handover renderer (tools/handover_render.py): draft dialect → Notion-flavored markdown, placeholder failures,
code fences left alone, page keys (H/X/legacy NN), draft lookup,
table-cell escaping, shot nesting and the --all mode. Offline: temporary drafts, PAGES and uploads only."""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import handover_render as hr  # noqa: E402

PAGES = {
    'root': {'id': 'r00t', 'url': 'https://app.notion.com/p/root'},
    '01': {'id': 'p01', 'url': 'https://app.notion.com/p/p01'},
    '02': {'id': 'TO_CREATE', 'url': 'TO_CREATE'},
    'H1': {'id': 'h1', 'url': 'https://app.notion.com/p/h1'},
    'H3': {'id': 'h3', 'url': 'https://app.notion.com/p/h3'},
    'H6': {'id': 'TO_CREATE', 'url': 'TO_CREATE'},
    'XP': {'id': 'TO_CREATE', 'url': 'TO_CREATE'},
    'X06': {'id': 'x06', 'url': 'https://app.notion.com/p/x06'},
    'X11': {'id': 'TO_CREATE', 'url': 'TO_CREATE'},
    'v1_root': {'id': 'v1', 'url': 'https://app.notion.com/p/v1'},
    'legacy_NN': {'09': {'id': 'x06', 'url': 'https://app.notion.com/p/x06'}},
}
UPLOADS = {'C-1': 'file-upload://c1'}


def render(text, allow_missing=False):
    return hr.render_text(text, UPLOADS, PAGES, allow_missing)


class TableTests(unittest.TestCase):
    def test_pipe_table_becomes_notion_table(self):
        out = render('| You see · 화면 | It means |\n|---|:---:|\n| **Green** | ok |\n')
        self.assertEqual(out.split('\n')[:10], [
            '<table header-row="true">',
            '\t<tr>', '\t\t<td>You see · 화면</td>', '\t\t<td>It means</td>', '\t</tr>',
            '\t<tr>', '\t\t<td>**Green**</td>', '\t\t<td>ok</td>', '\t</tr>',
            '</table>',
        ])

    def test_kr_and_escaped_pipe_in_cells(self):
        out = render('| A | B |\n|---|---|\n| x \\| y | Verified <kr>검증됨</kr> |\n| `a\\|b` | |\n')
        self.assertIn('\t\t<td>x \\| y</td>', out)
        self.assertIn('\t\t<td>Verified <span color="gray">검증됨</span></td>', out)
        self.assertIn('\t\t<td>`a|b`</td>', out)
        self.assertIn('\t\t<td></td>', out)

    def test_short_and_long_rows_fit_header(self):
        out = render('| A | B |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |\n')
        self.assertEqual(out.count('<td>'), 6)
        self.assertNotIn('3', out)

    def test_pipe_heading_is_not_a_table(self):
        self.assertEqual(render('## English | 한국어\n'), '## English | 한국어\n')

    def test_leading_list_markers_in_cells_escaped(self):
        out = render('| A | B |\n|---|---|\n| `PreshowEvent` + bridge ACK/beacon | + plus |\n'
                     '| - minus | * star |\n| `x` - y | a + b `c + d` |\n| a-b | 1 * 2 |\n')
        # Notion drops a backslash escape here (checked on the live pages): " + " after code/bold/italic becomes "and"
        self.assertIn('\t\t<td>`PreshowEvent` and bridge ACK/beacon</td>', out)
        self.assertIn('\t\t<td>\\+ plus</td>', out)
        self.assertIn('\t\t<td>\\- minus</td>', out)
        self.assertIn('\t\t<td>\\* star</td>', out)
        self.assertIn('\t\t<td>`x` \\- y</td>', out)
        self.assertIn('\t\t<td>a + b `c + d`</td>', out)   # plain " + " and code span untouched
        self.assertIn('\t\t<td>a-b</td>', out)
        self.assertIn('\t\t<td>1 * 2</td>', out)
        # no cell may start with a list marker, even after a leading code span
        for cell in re.findall(r'<td>(.*?)</td>', out):
            self.assertIsNone(re.match(r'(`[^`]+`\s+)?[-+*] ', cell), cell)

    def test_list_marker_outside_tables_untouched(self):
        self.assertEqual(render('- item + more\n+ other'), '- item + more\n+ other')

    def test_test_report_table_is_converted(self):
        out = render('{{test-report-table}}')
        self.assertEqual(out.count('<table header-row="true">'), 1)   # English only (page X13)
        self.assertIsNone(re.search(r'[\uac00-\ud7a3]', out))
        self.assertTrue(out.startswith('Dongle pass of 23 September 2026 (historical counts; the console suite now runs '
                                       '247 tests; 43 captures)\n\n<table header-row="true">'))
        self.assertIn('168 tests green', out)   # historical counts kept
        self.assertNotIn('|---', out)
        self.assertIn('\t\t<td>**not performed** (needs an explicit go: it changes an installation board)</td>', out)


class CalloutTests(unittest.TestCase):
    def test_kinds_icons_and_colors(self):
        for kind, (icon, color) in hr.CALLOUTS.items():
            out = render(f'> [!{kind}] Text')
            self.assertEqual(out, f'<callout icon="{icon}" color="{color}">\n\tText\n</callout>')
        self.assertEqual(hr.CALLOUTS['WARNING'], ('⚠️', 'yellow_bg'))

    def test_multiline_with_kr_and_paragraphs(self):
        out = render('> [!INFO] **Who:** cube desk\n> <kr>**누가:** 큐브 담당</kr>\n>\n> Second paragraph\n\nAfter')
        self.assertEqual(out, '<callout icon="ℹ️" color="blue_bg">\n\t**Who:** cube desk\n'
                              '\t<span color="gray">**누가:** 큐브 담당</span>\n\tSecond paragraph\n</callout>\n\nAfter')

    def test_marker_on_its_own_line(self):
        out = render('> [!TIP]\n> Only line')
        self.assertEqual(out, '<callout icon="💡" color="green_bg">\n\tOnly line\n</callout>')

    def test_plain_quote_untouched_and_unknown_kind_fails(self):
        self.assertEqual(render('> just a quote'), '> just a quote')
        with self.assertRaises(SystemExit):
            render('> [!CAUTION] x')


class KrTests(unittest.TestCase):
    def test_inline_and_whole_line(self):
        out = render('Plug it in.\n<kr>큐브를 꽂습니다.</kr>\n- Item <kr>항목</kr>')
        self.assertEqual(out, 'Plug it in.\n<span color="gray">큐브를 꽂습니다.</span>\n'
                              '- Item <span color="gray">항목</span>')

    def test_inline_code_kept(self):
        self.assertEqual(render('Write `<kr>…</kr>` here'), 'Write `<kr>…</kr>` here')

    def test_unbalanced_fails(self):
        with self.assertRaises(SystemExit):
            render('<kr>open only')


class ToggleTests(unittest.TestCase):
    def test_details_children_indented_and_processed(self):
        out = render('<details><summary>Sources <kr>출처</kr></summary>\n\n- `a.py`\n<kr>설명</kr>\n\n</details>\nNext')
        self.assertEqual(out, '<details>\n<summary>Sources <span color="gray">출처</span></summary>\n'
                              '\t- `a.py`\n\t<span color="gray">설명</span>\n</details>\nNext')

    def test_summary_on_next_line(self):
        out = render('<details>\n<summary>T</summary>\nBody\n</details>')
        self.assertEqual(out, '<details>\n<summary>T</summary>\n\tBody\n</details>')

    def test_table_inside_toggle(self):
        out = render('<details><summary>T</summary>\n\n| A | B |\n|---|---|\n| <kr>가</kr> | 2 |\n\n</details>')
        lines = out.split('\n')
        self.assertEqual(lines[2], '\t<table header-row="true">')
        self.assertIn('\t\t\t<td><span color="gray">가</span></td>', lines)
        self.assertEqual(lines[-2], '\t</table>')

    def test_nested_toggle_and_callout_in_toggle(self):
        out = render('<details><summary>A</summary>\n> [!NOTE] n\n<details><summary>B</summary>\ninner\n</details>\n'
                     '</details>')
        self.assertEqual(out, '<details>\n<summary>A</summary>\n\t<callout icon="📝" color="gray_bg">\n\t\tn\n'
                              '\t</callout>\n\t<details>\n\t<summary>B</summary>\n\t\tinner\n\t</details>\n</details>')

    def test_unterminated_fails(self):
        with self.assertRaises(SystemExit):
            render('<details><summary>T</summary>\nbody')


class FenceTests(unittest.TestCase):
    MERMAID = '```mermaid\nflowchart LR\n  A["Cube<br/>큐브"] --> B["{{page:01}} | <kr>x</kr>"]\n\n  B --> C\n```'

    def test_mermaid_passed_through_verbatim(self):
        out = render('Intro\n\n' + self.MERMAID + '\n\nAfter <kr>뒤</kr>')
        self.assertIn(self.MERMAID, out)
        self.assertTrue(out.endswith('After <span color="gray">뒤</span>'))

    def test_language_normalised(self):
        self.assertTrue(render('```Mermaid\nx\n```').startswith('```mermaid\n'))

    def test_nothing_transformed_inside_other_fences(self):
        body = '```\n| A | B |\n|---|---|\n> [!WARNING] w\n<details><summary>s</summary>\n{{shot:none}}\n```'
        self.assertEqual(render(body), body)

    def test_fence_inside_toggle_is_indented_not_changed(self):
        out = render('<details><summary>T</summary>\n```mermaid\nflowchart TD\n\n  A --> B\n```\n</details>')
        self.assertEqual(out, '<details>\n<summary>T</summary>\n\t```mermaid\n\tflowchart TD\n\t\n'
                              '\t  A --> B\n\t```\n</details>')

    def test_unterminated_fence_fails(self):
        with self.assertRaises(SystemExit):
            render('```mermaid\nflowchart LR')


class PlaceholderTests(unittest.TestCase):
    def test_page_mentions(self):
        self.assertEqual(render('See {{page:01}} and {{page:00}} and {{v1-root}}'),
                         'See <mention-page url="https://app.notion.com/p/p01"/> and '
                         '<mention-page url="https://app.notion.com/p/root"/> and '
                         '<mention-page url="https://app.notion.com/p/v1"/>')

    def test_uncreated_page_fails_unless_allowed(self):
        with self.assertRaises(SystemExit) as caught:
            render('See {{page:02}}')
        self.assertIn('--allow-missing-pages', str(caught.exception))
        self.assertEqual(render('See {{page:02}}', allow_missing=True), 'See **Glossary & names**')

    def test_unknown_page_and_unresolved_placeholders_fail(self):
        for text in ('{{page:42}}', '{{mystery}}', '{{shot:none}}\ncaption'):
            with self.assertRaises(SystemExit):
                render(text)

    def test_shot_with_caption_line(self):
        self.assertEqual(render('{{shot:C-1}}\nThe console / 콘솔\nNext'), '![The console / 콘솔](file-upload://c1)\nNext')

    def test_caption_is_plain_text(self):
        out = render('{{shot:C-1}}\nPress **Update all** in `Zones` / <kr>**모두 업데이트**를 누릅니다</kr>\n')
        self.assertEqual(out, '![Press Update all in Zones / 모두 업데이트를 누릅니다](file-upload://c1)\n')

    def test_shot_under_numbered_step_is_nested(self):
        out = render('1. Plug the cube in. <kr>큐브를 꽂습니다.</kr>\n\n{{shot:C-1}}\nThe console / 콘솔\n\n'
                     '2. Press **Register**.\n\n  {{shot:C-1}}\n  Again\n3. Done')
        self.assertEqual(out, '1. Plug the cube in. <span color="gray">큐브를 꽂습니다.</span>\n'
                              '\t![The console / 콘솔](file-upload://c1)\n2. Press **Register**.\n'
                              '\t![Again](file-upload://c1)\n3. Done')

    def test_shot_after_paragraph_is_not_nested(self):
        out = render('Some text.\n\n{{shot:C-1}}\nCap\n\nAfter')
        self.assertEqual(out, 'Some text.\n\n![Cap](file-upload://c1)\n\nAfter')

    def test_new_page_keys(self):
        self.assertEqual(render('{{page:H1}} {{page:H3}} {{page:X06}} {{page:H0}} {{page:root}}'),
                         '<mention-page url="https://app.notion.com/p/h1"/> <mention-page url="https://app.notion.com/p/h3"/> '
                         '<mention-page url="https://app.notion.com/p/x06"/> <mention-page url="https://app.notion.com/p/root"/> '
                         '<mention-page url="https://app.notion.com/p/root"/>')

    def test_legacy_nn_resolves_through_legacy_map(self):
        self.assertEqual(render('{{page:09}}'), '<mention-page url="https://app.notion.com/p/x06"/>')
        self.assertEqual(render('{{page:01}}'), '<mention-page url="https://app.notion.com/p/p01"/>')   # top-level fallback

    def test_uncreated_new_pages_use_style_guide_titles(self):
        for key, title in (('H6', 'What Kimchi and Chips fixed'), ('XP', 'Extended reference (English)'),
                           ('X11', 'Console controls, Attention cards & troubleshooting catalogue')):
            with self.assertRaises(SystemExit):
                render(f'{{{{page:{key}}}}}')
            self.assertEqual(render(f'See {{{{page:{key}}}}}', allow_missing=True), f'See **{title}**')

    def test_bad_page_keys_fail(self):
        for text in ('{{page:H}}', '{{page:X1}}', '{{page:X99}}', '{{page:H9}}'):
            with self.assertRaises(SystemExit):
                render(text)

    def test_leading_h1_dropped(self):
        self.assertEqual(render('# Title\nBody <kr>본문</kr>'), 'Body <span color="gray">본문</span>')


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='handover-render-test-'))
        self.docs = self.tmp / 'docs'
        for folder in ('handbook', 'extended'):
            (self.docs / folder).mkdir(parents=True)
        write = lambda rel, text: (self.docs / rel).write_text(text, encoding='utf-8', newline='\n')
        write('handbook/H0-root.md', '# Root\n{{page:H1}}\n')
        write('handbook/H1-introduction.md', '> [!INFO] a\n> <kr>가</kr>\n')
        write('handbook/H5-troubleshooting.md', 'Fixed: {{page:H6}}\n')
        write('handbook/_notes.md', '{{not a page}}\n')
        write('extended/X06-pool-forest.md', '# Pool\n| A | B |\n|---|---|\n| `x` + y | 1 |\n')
        write('00-root.md', '# Old root\n{{page:01}}\n')
        write('STYLE_GUIDE.md', '{{not a chapter}}\n')
        self.pages = self.tmp / 'PAGES.json'
        self.pages.write_text(json.dumps(PAGES), encoding='utf-8', newline='\n')

    def run_cli(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                code = hr.main(['--docs', str(self.docs), '--pages', str(self.pages),
                                '--uploads', str(self.tmp / 'none.json'), *argv])
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, err.getvalue()

    def test_all_renders_handbook_and_extended(self):
        out = self.tmp / 'out'
        code, _ = self.run_cli('--all', '--outdir', str(out), '--allow-missing-pages')
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ['H0-root.md', 'H1-introduction.md', 'H5-troubleshooting.md', 'X06-pool-forest.md'])
        self.assertIn('<callout icon="ℹ️" color="blue_bg">', (out / 'H1-introduction.md').read_text(encoding='utf-8'))
        self.assertEqual((out / 'H5-troubleshooting.md').read_text(encoding='utf-8'),
                         'Fixed: **What Kimchi and Chips fixed**\n')
        self.assertIn('<td>`x` and y</td>', (out / 'X06-pool-forest.md').read_text(encoding='utf-8'))

    def test_all_without_flag_fails_on_uncreated_page(self):
        out = self.tmp / 'out'
        code, err = self.run_cli('--all', '--outdir', str(out))
        self.assertEqual(code, 1)
        self.assertIn('H5-troubleshooting.md', err)
        self.assertTrue((out / 'H0-root.md').exists())
        self.assertFalse((out / 'H5-troubleshooting.md').exists())

    def test_all_with_no_drafts_fails(self):
        empty = self.tmp / 'empty'
        empty.mkdir()
        code, err = self.run_cli('--docs', str(empty), '--all', '--outdir', str(self.tmp / 'o'))
        self.assertEqual(code, 1)
        self.assertIn('no handbook/extended drafts', err)

    def test_draft_lookup_by_key(self):
        self.assertEqual(hr.draft_path('H0', self.docs).name, 'H0-root.md')
        self.assertEqual(hr.draft_path('root', self.docs).name, 'H0-root.md')
        self.assertEqual(hr.draft_path('H1', self.docs).name, 'H1-introduction.md')
        self.assertEqual(hr.draft_path('X06', self.docs).name, 'X06-pool-forest.md')
        self.assertEqual(hr.draft_path('00', self.docs).name, '00-root.md')
        for key in ('H2', 'X01', 'XP', 'H', '7'):
            with self.assertRaises(SystemExit):
                hr.draft_path(key, self.docs)

    def test_single_page_exit_codes(self):
        target = self.tmp / 'one.md'
        self.assertEqual(self.run_cli('H1', '--out', str(target))[0], 0)
        self.assertIn('<span color="gray">가</span>', target.read_text(encoding='utf-8'))
        self.assertEqual(self.run_cli('X06', '--out', str(target))[0], 0)
        self.assertTrue(target.read_text(encoding='utf-8').startswith('<table header-row="true">'))
        self.assertEqual(self.run_cli('root', '--out', str(target))[0], 0)
        self.assertEqual(target.read_text(encoding='utf-8'), '<mention-page url="https://app.notion.com/p/h1"/>\n')
        self.assertEqual(self.run_cli('00', '--out', str(target))[0], 0)   # old chapter drafts still render
        self.assertEqual(self.run_cli('H5')[0], 1)
        self.assertEqual(self.run_cli('H2')[0], 1)
        self.assertEqual(self.run_cli('--all')[0], 2)

if __name__ == '__main__':
    unittest.main()
