#!/usr/bin/env python3
"""Two-board acceptance test for the ESP-NOW range test firmware.

Proves real radio delivery rather than a successful compile. Run with both
boards powered and within a metre of each other:

    pairing_station/.venv/bin/python rangetest/tests/e2e_check.py /dev/cu.usbmodemTX /dev/cu.usbmodemRX

Evidence is written to rangetest/build/e2e-latest.log. Close the GUI first: it
holds both serial ports exclusively.
"""
import sys
import time
from pathlib import Path

import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serial_open import open_serial  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'build' / 'e2e-latest.log'

CLOSE_RANGE_RSSI = -75      # boards on a bench should be far stronger than this
MAX_BENCH_LOSS_PCT = 5.0


class Board:
    def __init__(self, port, tag, log):
        self.tag = tag
        self.log = log
        self.serial = open_serial(port, write_timeout=1)
        self.buffer = b''
        self.lines = []
        time.sleep(0.4)

    def send(self, command):
        self.serial.write((command + '\n').encode())
        self.log(f'{self.tag} << {command}')

    def pump(self):
        self.buffer += self.serial.read(65536)
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            text = raw.decode('utf8', 'replace').strip()
            if text:
                self.lines.append(text)
                self.log(f'{self.tag} >> {text}')

    def collect(self, seconds):
        start = len(self.lines)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump()
            time.sleep(0.02)
        return self.lines[start:]

    def close(self):
        self.serial.close()


def fields(line):
    return {k: v for k, _, v in (t.partition('=') for t in line.split()) if k}


def stats(lines, role):
    """The STAT lines for one role, skipping the first (a partial window)."""
    rows = [fields(l) for l in lines if l.startswith('STAT ') and f'role={role}' in l]
    return rows[1:] if len(rows) > 1 else rows


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    LOG.parent.mkdir(parents=True, exist_ok=True)
    handle = LOG.open('w')

    def log(text):
        line = f'{time.strftime("%H:%M:%S")} {text}'
        handle.write(line + '\n')
        handle.flush()

    def report(ok, name, detail=''):
        results.append((ok, name, detail))
        print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  — {detail}' if detail else ''))
        log(f'{"PASS" if ok else "FAIL"} {name} {detail}')

    results = []
    tx = Board(sys.argv[1], 'TX', log)
    rx = Board(sys.argv[2], 'RX', log)
    try:
        # ---------------------------------------------------------- L1 identity
        for board, expected in ((tx, 'TX'), (rx, 'RX')):
            board.send('MUTE OFF')
            board.send('VERBOSE ON')
            board.send('STATUS')
        banner_tx = tx.collect(1.5)
        banner_rx = rx.collect(0.5)
        for board, lines, expected in ((tx, banner_tx, 'TX'), (rx, banner_rx, 'RX')):
            role = next((l for l in lines if l.startswith('Role:')), '')
            channel = next((l for l in lines if l.startswith('ESP-NOW CHANNEL:')), '')
            radio = next((l for l in lines if 'radio_ok=' in l), '')
            power = next((l for l in lines if l.startswith('TX power:')), '')
            report(f'Role: {expected} (mac table)' == role, f'{board.tag} role resolved from MAC table', role)
            report(channel.endswith(' 2'), f'{board.tag} on channel 2', channel)
            report('radio_ok=1' in radio, f'{board.tag} ESP-NOW initialised', radio)
            report('ESP_OK' in power, f'{board.tag} TX power readable', power)
            report(any('NCT RANGE TEST' in l for l in lines), f'{board.tag} banner signature', '')

        # -------------------------------------------- L2 negative control first
        # Prove the TX "delivered" indication is a real application ACK. The RX
        # keeps receiving and counting while it stops answering; if TX loss does
        # not go to 100% here, every later PASS is meaningless.
        rx.send('MUTE ON')
        tx.send('RESET')
        rx.send('RESET')
        time.sleep(0.3)
        tx.collect(0.1)
        rx.collect(0.1)
        muted_tx = tx.collect(4.0)
        muted_rx = rx.collect(0.1)
        rows = stats(muted_tx, 'TX')
        losses = [float(r.get('loss_pct', 0)) for r in rows]
        departed = [int(r.get('departed', 0)) for r in rows]
        report(bool(losses) and all(l == 100.0 for l in losses),
               'Negative control: TX reports 100% loss when the RX stops answering',
               f'loss_pct={losses}')
        report(all(d > 0 for d in departed),
               'Negative control: TX keeps transmitting while unacknowledged',
               f'departed={departed}')
        rx_rows = stats(muted_rx, 'RX')
        received = [int(r.get('received', 0)) for r in rx_rows]
        report(bool(received) and all(r > 0 for r in received),
               'Negative control: RX still receives every ping while muted',
               f'received={received}')

        # ------------------------------------------------ L3 positive control
        rx.send('MUTE OFF')
        tx.send('RESET')
        rx.send('RESET')
        time.sleep(0.3)
        tx.collect(0.1)
        rx.collect(0.1)
        live_tx = tx.collect(6.0)
        live_rx = rx.collect(0.1)

        tx_rows = stats(live_tx, 'TX')
        rx_rows = stats(live_rx, 'RX')
        tx_loss = [float(r.get('loss_pct', 100)) for r in tx_rows]
        rx_loss = [float(r.get('loss_pct', 100)) for r in rx_rows]
        report(bool(tx_loss) and max(tx_loss) <= MAX_BENCH_LOSS_PCT,
               'TX ACK loss is near zero at bench range', f'loss_pct={tx_loss}')
        report(bool(rx_loss) and max(rx_loss) <= MAX_BENCH_LOSS_PCT,
               'RX sequence-gap loss is near zero at bench range', f'loss_pct={rx_loss}')

        packets = [fields(l) for l in live_tx if l.startswith('PKT ') and 'ack=1' in l]
        report(bool(packets), 'TX receives application ACKs', f'{len(packets)} acked pings')
        if packets:
            uplink = [int(p['up_rssi']) for p in packets if 'up_rssi' in p]
            downlink = [int(p['dn_rssi']) for p in packets if 'dn_rssi' in p]
            report(bool(uplink) and all(CLOSE_RANGE_RSSI < v < 0 for v in uplink),
                   'Uplink RSSI measured by the RX is plausible',
                   f'min={min(uplink)} max={max(uplink)} dBm')
            report(bool(downlink) and all(CLOSE_RANGE_RSSI < v < 0 for v in downlink),
                   'Downlink RSSI measured by the TX is plausible',
                   f'min={min(downlink)} max={max(downlink)} dBm')
            air = [int(p['air_us']) for p in packets if 'air_us' in p]
            rtt = [int(p['rtt_us']) for p in packets if 'rtt_us' in p]
            report(bool(air) and sum(air) < sum(rtt),
                   'Air time excludes the responder turnaround',
                   f'rtt_avg={sum(rtt)//len(rtt)}us air_avg={sum(air)//len(air)}us')

        # L5: the channel field is filled by the Wi-Fi driver, not by our code,
        # so it is independent evidence that the frames really were on channel 2.
        rx_packets = [fields(l) for l in live_rx if l.startswith('PKT ')]
        channels = {p.get('ch') for p in rx_packets}
        report(channels == {'2'}, 'Every frame was received on channel 2 (driver-reported)',
               f'channels={sorted(channels)}')
        noise = [int(p['nf']) for p in rx_packets if 'nf' in p]
        report(bool(noise) and all(-110 < v < -60 for v in noise),
               'Noise floor is plausible', f'min={min(noise)} max={max(noise)} dBm' if noise else '')

        # ------------------------------------------------ L4 restart integrity
        before = [fields(l) for l in live_rx if l.startswith('STAT ') and 'role=RX' in l]
        boot_before = before[-1].get('boot') if before else None
        tx.send('REBOOT')
        restart_rx = rx.collect(6.0)
        tx.collect(0.1)
        restarts = [l for l in restart_rx if l.startswith('EVENT tx_restart')]
        report(bool(restarts), 'RX detects a TX restart via bootId', restarts[0] if restarts else '')
        after = stats(restart_rx, 'RX')
        boot_after = after[-1].get('boot') if after else None
        report(boot_before is not None and boot_after is not None and boot_before != boot_after,
               'TX boot id changed across the restart', f'{boot_before} -> {boot_after}')
        tail = after[-2:] if len(after) >= 2 else after
        gaps = [int(r.get('gap_lost', 0)) for r in tail]
        report(bool(gaps) and max(gaps) == 0,
               'Restart produces no phantom sequence-gap loss', f'gap_lost={gaps}')

        # --------------------------------- L4b radio is independent of USB logs
        tx.send('VERBOSE OFF')
        rx.send('VERBOSE OFF')
        quiet_rx = rx.collect(4.0)
        quiet_rows = stats(quiet_rx, 'RX')
        report(bool(quiet_rows) and all(int(r.get('received', 0)) > 0 for r in quiet_rows),
               'Radio keeps running with per-packet logging disabled',
               f'received={[r.get("received") for r in quiet_rows]}')
        report(all(int(r.get('log_drops', 0)) == 0 for r in quiet_rows),
               'No log lines dropped while a reader is attached',
               f'log_drops={[r.get("log_drops") for r in quiet_rows]}')
    finally:
        for board in (tx, rx):
            try:
                board.send('VERBOSE ON')
                board.send('MUTE OFF')
            except (serial.SerialException, OSError):
                pass
            board.close()
        handle.close()

    failed = [name for ok, name, _ in results if not ok]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed. Evidence: {LOG}')
    if failed:
        print('Failed: ' + '; '.join(failed))
        return 1
    print('An RF and application-ACK pass does not prove anything about cube LED behaviour.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
