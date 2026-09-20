#!/usr/bin/env python3
"""Drive the range test console against the receiver without clicking.

Opens the real Tk app, lets it auto-connect, and checks it parses identity,
statistics, per-packet RSSI and the live LED mirror, and that it writes nothing
to disk.

    pairing_station/.venv/bin/python rangetest/tests/gui_check.py /dev/cu.usbmodemRX

Requires a desktop session. Close the console first: it holds the port exclusively.
"""
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gui  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def pump(root, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.02)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    before = {p for p in ROOT.rglob('*') if p.is_file()}
    root = tk.Tk()
    application = gui.App(root, port=sys.argv[1])
    failures = []

    def check(ok, name, detail=''):
        print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  — {detail}' if detail else ''))
        if not ok:
            failures.append(name)

    try:
        pump(root, 4.0)
        receiver = application.receiver
        check(receiver.connected, 'Auto-connected without being asked', receiver.port or '')
        check(receiver.banner.get('Role') == 'RX (mac table)', 'Identity parsed',
              receiver.banner.get('Role', ''))
        check(bool(receiver.stat), 'STAT parsed', receiver.stat.get('loss_pct', ''))
        check(len(receiver.packets) > 5, 'Per-packet history populated',
              f'{len(receiver.packets)} packets')
        check(bool(receiver.samples), 'One-second history populated',
              f'{len(receiver.samples)} samples')

        lit = [p for p in receiver.pixels if p != '000000']
        check(len(receiver.pixels) == 8, 'LED mirror has eight pixels')
        check(bool(lit), 'LED mirror is receiving live frames', ','.join(receiver.pixels))
        check(receiver.pixels[7].endswith('0000') and receiver.pixels[7] != '000000',
              'Pixel 7 is the red role marker', receiver.pixels[7])
        check(all(p == '000000' or p.endswith('0000') for p in receiver.pixels),
              'Receiver shows no green at all', ','.join(receiver.pixels))

        check(application.headline.get() == 'LINK GOOD', 'Headline reflects a good link',
              application.headline.get())
        check(application.metrics['rssi'][0].get() not in ('', '—'), 'Signal metric shown',
              application.metrics['rssi'][0].get())
        check(application.metrics['snr'][0].get() not in ('', '—'), 'SNR metric shown',
              application.metrics['snr'][0].get())
    finally:
        application.close()

    after = {p for p in ROOT.rglob('*') if p.is_file()}
    created = {p for p in after - before if '__pycache__' not in p.parts}
    check(not created, 'Nothing written to disk', ', '.join(p.name for p in created))

    if failures:
        print('\nFailed: ' + '; '.join(failures))
        return 1
    print('\nConsole check passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
