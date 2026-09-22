#!/usr/bin/env python3
"""Re-measure the pool central's frame -> output wiring map, and compute the correction.

Lights one frame at a time over USB (no slider needed) and asks which lamp actually lit.
The firmware ALREADY applies a map, so the readings compose with it rather than replace it:
if the current table is M and selecting frame i lights lamp L(i), the corrected table is
M' = M o L^-1. Doing that by hand is easy to get backwards, which is the point of this.

    pairing_station/.venv/bin/python poolzone_test/tests/frame_map.py /dev/cu.usbmodem101

Arms the central's leased output test, so the sliders are ignored while measuring and the
lamps are handed back at the end (and on their own after two minutes if this is killed).
"""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pairing_station'))
import serial                                    # noqa: E402
from port_lock import PortLock                   # noqa: E402

HEADER = ROOT / 'zones/firmware/PoolCentral/PoolOutput.h'
COUNT = 23
OUTPUTS = 24   # three 8-channel relay modules; one output has no frame


def current_map():
    """POOL_OUTPUT_FOR_MEMBER as a list, so this can never drift from the firmware."""
    text = HEADER.read_text(encoding='utf-8')
    body = re.search(r'POOL_OUTPUT_FOR_MEMBER\[23\]\s*=\s*\{([^}]*)\}', text)
    if not body:
        raise SystemExit(f'Could not find POOL_OUTPUT_FOR_MEMBER in {HEADER}')
    table = [int(v) for v in body[1].replace('\n', ' ').split(',')]
    if len(table) != COUNT or len(set(table)) != COUNT or not all(1 <= v <= OUTPUTS for v in table):
        raise SystemExit(f'POOL_OUTPUT_FOR_MEMBER must map {COUNT} frames to distinct outputs 1..{OUTPUTS}')
    return table


def drain(conn, seconds=0.35):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        conn.read(4096)


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else '/dev/cu.usbmodem101'
    mapping = current_map()
    observed = {}
    print(f'Current map: {mapping}')
    print('Lighting one frame at a time. Type the number of the lamp that actually lit,')
    print('blank to skip that frame, or q to stop early.\n')
    with PortLock(port):
        with serial.Serial(port, 115200, timeout=0.1, write_timeout=1, exclusive=True) as conn:
            conn.dtr = True
            conn.rts = False
            time.sleep(1.0)
            conn.write(b'\nOUT ARM\nOUT ALL OFF\n')
            drain(conn, 1.0)
            try:
                for frame in range(1, COUNT + 1):
                    conn.write(f'OUT {frame} ON\n'.encode())
                    drain(conn)
                    try:
                        answer = input(f'  frame {frame:2d} (output {mapping[frame-1]:2d}) -> which lamp lit? ').strip()
                    except (EOFError, KeyboardInterrupt):
                        answer = 'q'
                    conn.write(f'OUT {frame} OFF\n'.encode())
                    drain(conn, 0.2)
                    if answer.lower().startswith('q'):
                        break
                    if answer:
                        observed[frame] = int(answer)
            finally:
                conn.write(b'OUT ALL OFF\nOUT DISARM\n')
                drain(conn, 0.5)
                print('\nOutput test released; the sliders have the lamps back.')

    if len(observed) != COUNT:
        print(f'\nOnly {len(observed)}/{COUNT} frames recorded — need all of them to rebuild the map.')
        return 1
    if sorted(observed.values()) != list(range(1, COUNT + 1)):
        dupes = [lamp for lamp in set(observed.values()) if list(observed.values()).count(lamp) > 1]
        print(f'\nReadings are not a permutation (repeated: {dupes or "none"}; missing: '
              f'{sorted(set(range(1, COUNT+1)) - set(observed.values()))}). Re-check those frames.')
        return 1

    # observed[i] = lamp lit when frame i was requested, i.e. L(i).
    inverse_l = {lamp: frame for frame, lamp in observed.items()}
    corrected = [mapping[inverse_l[lamp] - 1] for lamp in range(1, COUNT + 1)]
    changed = [lamp for lamp in range(1, COUNT + 1) if corrected[lamp-1] != mapping[lamp-1]]
    print(f'\n{"Already correct." if not changed else f"{len(changed)} frames move: {changed}"}')
    print('\nCorrected POOL_OUTPUT_FOR_MEMBER for PoolOutput.h:\n')
    print('constexpr uint8_t POOL_OUTPUT_FOR_MEMBER[23] = {' + ', '.join(str(v) for v in corrected) + '};')
    print('\nAlso update the measurement comment above it:')
    print('  output index driven : ' + ' '.join(f'{o:2d}' for o in range(1, OUTPUTS + 1)))
    lamp_for_output = {corrected[lamp-1]: lamp for lamp in range(1, COUNT + 1)}
    print('  frame that lit      : ' + ' '.join(f'{lamp_for_output.get(o, "--"):>2}' for o in range(1, OUTPUTS + 1)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
