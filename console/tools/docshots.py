#!/usr/bin/env python
"""Capture the handover screenshots from the simulated NCT Console.

    pairing_station/.venv/bin/python console/tools/docshots.py [--list] [--only 03-1,03-2] [--out console/docs/shots]
                                                                [--port 8766] [--size 1440x1000] [--scale 2] [--keep]

Per chapter it starts `app.py --simulate --scenario docs --browser --no-open --api-port PORT` on a fresh temporary
database, stages every scenario through the loopback API (console/docscenes.py) and captures the page with headless
Chrome. Nothing here touches hardware or the real database. Output: PNGs plus manifest.json (id, file, chapter, step,
EN/KR titles, route, highlight tokens, console version, git revision).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONSOLE = HERE.parent
ROOT = CONSOLE.parent
sys.path.insert(0, str(CONSOLE))
import paths  # noqa: E402,F401
import docscenes  # noqa: E402

CHROME_CANDIDATES = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    'google-chrome', 'chromium', 'chromium-browser', 'chrome',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
]


def find_chrome(explicit=None):
    for candidate in ([explicit] if explicit else []) + CHROME_CANDIDATES:
        if not candidate:
            continue
        path = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if path:
            return path
    raise SystemExit('No Chrome/Chromium found; pass --chrome PATH')


class Console:
    """One simulated console process and its loopback API."""

    def __init__(self, port, python):
        self.port, self.python = port, python
        self.proc = self.url = self.api_url = self.token = None
        self.tmp = Path(tempfile.mkdtemp(prefix='nct-docshots-'))

    def start(self):
        env = dict(os.environ)
        # --database points at a file that does not exist, so the simulation starts from an empty inventory
        # instead of a copy of this computer's real database.
        self.proc = subprocess.Popen([self.python, str(CONSOLE / 'app.py'), '--simulate', '--scenario', 'docs', '--browser',
                                      '--no-open', '--api-port', str(self.port), '--database', str(self.tmp / 'empty.sqlite3')],
                                     cwd=str(ROOT), env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    raise RuntimeError('console exited before it printed its URL')
                continue
            sys.stderr.write('  ' + line)
            m = re.match(r'NCT Console: (\S+)', line)
            if m:
                self.url = m.group(1)
            m = re.match(r'NCT Console API: (\S+) · token (.+)$', line.strip())
            if m:
                self.api_url = m.group(1)
                self.token = self._read_token(Path(m.group(2).strip()))
            if self.url and self.api_url:
                break
        if not (self.url and self.api_url):
            raise RuntimeError('console did not print both URLs')
        import threading
        threading.Thread(target=self._drain, daemon=True).start()
        return self

    def _drain(self):
        for line in self.proc.stdout:
            if os.environ.get('NCT_DOCSHOTS_VERBOSE'):
                sys.stderr.write('  ' + line)

    @staticmethod
    def _read_token(config):
        text = config.read_text(encoding='utf-8')
        m = re.search(r'Authorization: Bearer (\S+)', text)
        if not m:
            raise RuntimeError('api.curl has no bearer token')
        return m.group(1)

    def execute(self, code, wait=20.0):
        body = json.dumps(dict(code=code)).encode()
        request = urllib.request.Request(self.api_url + '/execute', data=body, method='POST',
                                         headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.token}'})
        with urllib.request.urlopen(request, timeout=wait + 5) as response:
            result = json.loads(response.read().decode())
            status = response.status
        deadline = time.monotonic() + wait
        while status == 202 and time.monotonic() < deadline:
            time.sleep(0.1)
            job = urllib.request.Request(f'{self.api_url}/jobs/{result["id"]}', headers={'Authorization': f'Bearer {self.token}'})
            with urllib.request.urlopen(job, timeout=10) as response:
                result = json.loads(response.read().decode())
                status = 202 if result.get('state') in ('queued', 'running') else 200
        if result.get('exception') or result.get('error'):
            raise RuntimeError(f'/execute failed: {result.get("exception") or result.get("error")}\n{result.get("stderr", "")}')
        return result.get('value')

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.execute('hub.shutdown(force=True)', wait=4)
            except Exception:
                pass
            try:
                self.proc.wait(8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)


def capture(chrome, url, out, size, scale, budget_ms=4000):
    w, h = size
    cmd = [chrome, '--headless=new', '--hide-scrollbars', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
           f'--window-size={w},{h}', f'--force-device-scale-factor={scale}', f'--virtual-time-budget={budget_ms}',
           f'--screenshot={out}', '--user-data-dir=' + str(Path(tempfile.gettempdir()) / 'nct-docshots-chrome'), url]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    return out


def git_rev():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT), capture_output=True, text=True).stdout.strip()
    except Exception:
        return ''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--only', default='', help='comma-separated scenario ids')
    parser.add_argument('--out', type=Path, default=CONSOLE / 'docs' / 'shots')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--size', default='1440x1000')
    parser.add_argument('--scale', type=int, default=2)
    parser.add_argument('--chrome', default=None)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--keep', action='store_true', help='keep the console running after the last capture')
    args = parser.parse_args(argv)
    if args.list:
        for s in docscenes.SCENARIOS:
            print(f'{s["id"]:5} ch{s["chapter"]:02d} step {s["step"]}  {s["en"]}')
        return 0
    only = {x.strip() for x in args.only.split(',') if x.strip()}
    size = tuple(int(x) for x in args.size.lower().split('x'))
    chrome = find_chrome(args.chrome)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = dict(generated=time.strftime('%Y-%m-%dT%H:%M:%S'), git=git_rev(), size=list(size), scale=args.scale, shots=[])
    version = ''
    for chapter, scenarios in docscenes.chapters().items():
        wanted = [s for s in scenarios if not only or s['id'] in only]
        if not wanted:
            continue
        print(f'chapter {chapter}: {", ".join(s["id"] for s in wanted)}')
        console = Console(args.port, args.python).start()
        try:
            console.execute('import docscenes; docscenes.base(hub)', wait=30)
            version = console.execute('hub.sections["meta"]["version"] if hub.sections.get("meta") else ""') or version
            for s in wanted:
                console.execute(f'import docscenes; docscenes.run_setup(hub, {s["id"]!r})', wait=30)
                deadline = time.monotonic() + s['settle']
                ok = False
                while time.monotonic() < deadline:
                    ok = console.execute(f'import docscenes; docscenes.is_settled(hub, {s["id"]!r})')
                    if ok:
                        break
                    time.sleep(0.2)
                route = console.execute(f'import docscenes; docscenes.route(hub, docscenes.by_id({s["id"]!r}))')
                url = console.url.rstrip('/') + '/' + route
                file = args.out / f'{s["id"]}.png'
                capture(chrome, url, file, s.get('size') or size, args.scale)
                print(f'  {s["id"]:5} {"settled" if ok else "NOT SETTLED"}  {file.name}  {route}')
                manifest['shots'].append(dict(id=s['id'], file=file.name, chapter=chapter, step=s['step'], en=s['en'], kr=s['kr'],
                                              route=route, hl=s['hl'], open=s['open'], settled=bool(ok)))
        finally:
            if not args.keep:
                console.stop()
    manifest['console_version'] = version
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(f'{len(manifest["shots"])} captures → {args.out}')
    return 0 if all(s['settled'] for s in manifest['shots']) else 1


if __name__ == '__main__':
    sys.exit(main())
