"""The handover screenshot tooling: every documentation token resolves to a data-doc hook in the front end,
`docshots.py --list` names every scenario, and (opt-in, needs Chrome) one capture produces a PNG."""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401

CONSOLE = Path(__file__).resolve().parents[1]
WEB = CONSOLE / 'web'

import docscenes  # noqa: E402
import commands  # noqa: E402
import commands_extra  # noqa: E402,F401
try:
    import commands_show  # noqa: E402,F401
except ImportError:
    pass

# Where a data-doc token is spelled in the front end:
#   data-doc="name" / data-doc=${'name'} / data-doc=${`name:${x}`} / data-doc=${'tab:' + id}
#   doc="name" / doc: `name:${x}` (the `doc` prop of ActionButton, HoldButton, DataTable, LedRing, Banner, Ladder…)
#   rowDoc=${(z) => `relay.zone:${z.mac}`} (a DataTable row)
#   ['Committed tag (uid)', value, 'cube.tag'] (a KeyValue item's third element)
PATTERNS = [
    re.compile(r'''(?:data-doc|\bdoc)=(?:\$\{)?[`'"]([A-Za-z0-9_.:*-]+)'''),
    re.compile(r'''\bdoc:\s*[`'"]([A-Za-z0-9_.:*-]+)'''),
    re.compile(r'''rowDoc=\$\{\(\w+\)\s*=>\s*`([A-Za-z0-9_.:*-]+)'''),
    re.compile(r''',\s*'([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)'\]'''),
]


def static_tokens():
    found = set()
    for path in WEB.rglob('*.js'):
        if 'vendor' in path.parts or 'tests' in path.parts:
            continue
        text = path.read_text(encoding='utf-8')
        for pattern in PATTERNS:
            for m in pattern.finditer(text):
                found.add(m.group(1).rstrip(':'))
    return found


def resolves(token, literals):
    """A token names a literal data-doc (a dynamic suffix after ':' is stripped) or a command (ActionButton/HoldButton
    put the command name on data-doc)."""
    if token.startswith('css:'):
        return True
    base = token[:-1] if token.endswith('*') else token
    if base in literals or base in commands.COMMANDS:
        return True
    prefix = base.split(':', 1)[0]
    return prefix in literals


class DocTokensTest(unittest.TestCase):
    def test_every_scenario_token_has_a_hook(self):
        literals = static_tokens()
        self.assertIn('rail', literals)
        missing = []
        for s in docscenes.SCENARIOS:
            for token in list(s['hl']) + list(s['open']):
                if not resolves(token, literals):
                    missing.append(f'{s["id"]}: {token}')
        self.assertEqual(missing, [], 'documentation tokens without a data-doc hook in console/web')

    def test_routes_are_hashes(self):
        for s in docscenes.SCENARIOS:
            r = s['route']
            if isinstance(r, str):
                self.assertTrue(r.startswith('#/'), s['id'])
                self.assertNotIn('#/devices/this', r, 'the This computer panel lives at #/devices/computer')


class DocshotsCliTest(unittest.TestCase):
    def run_tool(self, *args, timeout=600):
        return subprocess.run([sys.executable, str(CONSOLE / 'tools' / 'docshots.py'), *args], capture_output=True, text=True,
                              encoding='utf-8', timeout=timeout, cwd=str(CONSOLE.parent))

    def test_list_prints_every_scenario(self):
        r = self.run_tool('--list', timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for s in docscenes.SCENARIOS:
            self.assertRegex(r.stdout, rf'(?m)^{re.escape(s["id"])}\s')

    @unittest.skipUnless(os.environ.get('NCT_DOCSHOTS_SMOKE') == '1', 'set NCT_DOCSHOTS_SMOKE=1 (needs Chrome and a free port)')
    def test_one_capture_writes_a_png(self):
        out = Path(tempfile.mkdtemp(prefix='nct-docshots-test-'))
        r = self.run_tool('--only', 'C-1', '--out', str(out), '--port', os.environ.get('NCT_DOCSHOTS_PORT', '8769'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        png = out / 'C-1.png'
        self.assertTrue(png.is_file(), r.stdout)
        self.assertGreater(png.stat().st_size, 10_000)
        self.assertTrue((out / 'manifest.json').is_file())


if __name__ == '__main__':
    unittest.main()
