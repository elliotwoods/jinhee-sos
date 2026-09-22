"""The vendored front end must work offline and reference only files that exist."""
import hashlib
import re
import sys
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'web'


class StaticTests(unittest.TestCase):
    def files(self, *suffixes):
        return [p for p in WEB.rglob('*') if p.suffix in suffixes and 'tests' not in p.parts]

    def test_no_external_urls(self):
        for path in self.files('.html', '.js', '.css', '.mjs'):
            text = path.read_text(encoding='utf-8')
            for match in re.finditer(r'https?://[^\s"\'`)]+', text):
                url = match.group(0)
                if url.startswith('http://www.w3.org/'):
                    continue  # XML namespace identifiers, never fetched
                if path.parent.name == 'vendor' and ('preact' in url or 'htm' in url or 'github' in url):
                    continue  # licence headers name project pages
                self.fail(f'{path.relative_to(WEB)} references {url}: the console must work offline')

    def test_import_map_targets_exist(self):
        html = (WEB / 'index.html').read_text(encoding='utf-8')
        targets = re.findall(r'"\./([^"]+\.mjs)"', html)
        self.assertEqual(len(targets), 3, targets)
        for target in targets:
            self.assertTrue((WEB / target).is_file(), target)
        self.assertIn('type="importmap"', html)
        self.assertIn('src="app.js"', html)

    def test_relative_imports_resolve(self):
        for path in self.files('.js'):
            for match in re.finditer(r'from\s+[\'"](\.{1,2}/[^\'"]+)[\'"]', path.read_text(encoding='utf-8')):
                target = (path.parent / match.group(1)).resolve()
                self.assertTrue(target.is_file(), f'{path.relative_to(WEB)} imports missing {match.group(1)}')

    def test_vendor_hashes_recorded(self):
        recorded = {}
        for line in (WEB / 'vendor' / 'VERSIONS').read_text(encoding='utf-8').splitlines():
            parts = line.split()
            if len(parts) == 2 and len(parts[0]) == 64:
                recorded[parts[1]] = parts[0]
        for name in ('preact.mjs', 'hooks.mjs', 'htm.mjs'):
            digest = hashlib.sha256((WEB / 'vendor' / name).read_bytes()).hexdigest()
            self.assertEqual(recorded.get(name), digest, f'{name} does not match VERSIONS')
        for name in ('LICENSE-preact', 'LICENSE-htm'):
            self.assertTrue((WEB / 'vendor' / name).is_file(), name)

    def test_no_bundled_fonts_or_modals(self):
        css = (WEB / 'styles.css').read_text(encoding='utf-8')
        self.assertNotIn('@font-face', css)
        for path in self.files('.js'):
            text = path.read_text(encoding='utf-8')
            for word in ('window.alert(', 'window.confirm(', 'window.prompt(', ' alert(', ' confirm(', ' prompt('):
                self.assertNotIn(word, text, f'{path.relative_to(WEB)} uses a modal dialog')

    def test_colours_only_in_tokens(self):
        # Colours are CSS custom properties in the theme blocks; rules and scripts refer to them, so the
        # light/dark themes and the canvas drawings cannot drift apart.
        css = (WEB / 'styles.css').read_text(encoding='utf-8')
        tokens, marker, rules = css.partition('/* ---------- Scales')
        self.assertTrue(marker, 'styles.css lost its token/rule boundary comment')
        colour = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\(')
        for line in tokens.splitlines():
            if colour.search(line):
                self.assertRegex(line.strip(), r'^--[\w-]+:', f'colour outside a token declaration: {line.strip()}')
        self.assertIsNone(colour.search(rules), 'literal colour below the token blocks in styles.css')
        for path in self.files('.js'):
            if 'vendor' in path.parts:
                continue
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'[\'"`]#[0-9a-fA-F]{6}\b', text), f'{path.relative_to(WEB)} has a literal colour; use a token')

    def test_no_inline_spacing(self):
        # Spacing comes from the stylesheet (cards space their children); inline margins drifted before.
        for path in self.files('.js'):
            if 'vendor' in path.parts:
                continue
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(re.search(r'style=[\'"$]\{?[^>]*?\b(margin|padding)\s*:', text), f'{path.relative_to(WEB)} sets margin/padding inline')


if __name__ == '__main__':
    unittest.main()
