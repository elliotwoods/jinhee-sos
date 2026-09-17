"""Pairing state machine independent of Tk and physical serial hardware."""
import time
import uuid
from database import hex_bytes

class Controller:
    def __init__(self, db, send, log=print, clock=time.monotonic):
        self.db, self.send, self.log, self.clock = db, send, log, clock
        self.connected = self.reader_ok = False
        self.hello_request = None
        self.nfc_poll_request = None
        self.discovered = {}
        self.telemetry = {}
        self.station = {}
        self.mode = self.phase = ''
        self.active = None
        self.request = None
        self.batch = []
        self.skipped = set()
        self.tag_present = True
        self.next_discovery = 0
        self.deadline = None
        self.progress = self.total = 0
        self.message = 'Connect the station to begin.'
        self.after_stop = None
        self.feedback = {}

    def notify(self, kind, title, detail):
        self.feedback = dict(kind=kind, title=title, detail=detail, token=uuid.uuid4().hex)

    def emit(self, command, **fields):
        request = uuid.uuid4().hex
        if command == "hello":
            self.hello_request = request
        self.send(dict(cmd=command, id=request, **fields))
        mac = fields.get('mac') or (self.active['mac'] if self.active and command == 'stop' else None)
        if mac and command in ('identify', 'register', 'stop'):
            self.telemetry.setdefault(mac, {}).update(command=command, command_at=self.clock(), request=request,
                                                       delivery='awaiting radio result')
        return request

    def available(self, reader=False):
        if not self.connected:
            raise ValueError('Connect a ready station first')
        if self.mode:
            raise ValueError('An operation is active. Stop it first.')
        if reader and not self.reader_ok:
            raise ValueError('PN532 is unavailable; check wiring and restart the station')

    def discover(self):
        if self.connected and self.phase not in ('registering', 'stopping'):
            self.emit('discover')
            self.next_discovery = self.clock() + 3

    def start_pair(self):
        self.available(reader=True)
        self.feedback = {}
        self.mode, self.phase = 'pair', 'waiting'
        self.skipped.clear()
        self.message = 'Discovering new cubes… Existing mappings are skipped.'
        self.discover()
        self.choose()

    def choose(self):
        if self.mode != 'pair' or self.phase != 'waiting':
            return
        for mac, seen in sorted(self.discovered.items()):
            row = self.db.get(mac)
            if self.clock() - seen > 10 or mac in self.skipped or self.db.excluded(mac):
                continue
            if row and (row['uid'] or row['pending_uid'] or row['cube_id'] is None):
                continue
            self.active = self.db.reserve(mac)
            self.identify()
            return
        self.message = 'Waiting for a new cube. Use Re-pair selected for an existing mapping.'

    def identify(self):
        self.phase = 'identifying'
        self.request = self.emit('identify', mac=self.active['mac'], duration_ms=0)
        self.deadline = None
        self.message = f'Cube #{self.active["cube_id"]} · {self.active["mac"]}: remove any tag, then scan the blinking cube.'
        self.notify('scan', f'CLEAR THE READER · NEOCORE #{self.active["cube_id"]}',
                    f'{self.active["mac"]} · Remove any tag. Wait for READY TO SCAN, then scan the continuously flashing device.')

    def repair(self, mac, number=None):
        if not self.connected or not self.reader_ok:
            raise ValueError('Connect a station with NFC ready first')
        if self.mode and not (self.mode == 'preview' and self.phase == 'flashing'):
            raise ValueError('An operation is active. Stop it first.')
        if self.db.excluded(mac): raise ValueError('This device is excluded as a reader / base station')
        row = self.db.get(mac)
        if row and row['cube_id'] is None:
            self.db.validate_number(mac, number)
        if self.mode == 'preview':
            self.stop(then=('repair', mac, number))
            self.notify('scan', 'PREPARING TO REGISTER', f'{mac} · Switching from the selection preview to continuous flashing…')
            return
        if row and row['cube_id'] is None:
            self.db.rename(mac, number, fresh_scan=True)
        self.active = self.db.reserve(mac)
        if self.active['cube_id'] is None:
            raise ValueError('Assign a number before registration')
        self.mode = 'repair'
        self.identify()

    def rename(self, mac, number):
        if self.mode and not (self.mode == 'preview' and self.phase == 'flashing'):
            raise ValueError('Stop the current operation before renaming a device')
        row = self.db.validate_number(mac, number)
        if row['cube_id'] == number:
            return
        if self.mode == 'preview':
            self.stop(then=('rename', mac, number))
            return
        row = self.db.rename(mac, number)
        if row['uid'] and self.connected:
            self.transmit([row])
            self.message = f'Number changed to {number}. Sending the updated mapping…'
        else:
            self.feedback = {}
            self.message = f'Device renamed to #{number}. ' + ('Use Transmit saved mapping when connected.' if row['uid'] else 'Ready for NFC registration.')
        self.log(self.message)

    def transmit(self, rows):
        self.available()
        if any(self.db.excluded(r['mac']) for r in rows):
            raise ValueError('Selection includes an excluded reader / base station')
        if not rows:
            raise ValueError('No mappings to transmit')
        if any(r['cube_id'] is None for r in rows):
            raise ValueError('Use Rename device to assign a number before transmission')
        if any(not (r['pending_uid'] or r['uid']) for r in rows):
            raise ValueError('Scan a tag for this cube first')
        self.feedback = {}
        self.mode, self.phase = 'bulk', 'waiting'
        self.batch = list(rows)
        self.progress, self.total = 0, len(rows)
        self.next_bulk()

    def next_bulk(self):
        if not self.batch:
            self.complete('Transmission sequence complete. Review per-device statuses.')
            return
        self.active = self.batch.pop(0)
        self.register(self.active['pending_uid'] or self.active['uid'])

    def register(self, uid):
        scanned = self.mode in ('pair', 'repair') and self.phase == 'identifying'
        self.active = self.db.prepare(self.active['mac'], uid, take_over=scanned)
        transfer = ('Tag transferred from ' + ', '.join(self.active['transferred_from']) + '. ') if self.active['transferred_from'] else ''
        if transfer: self.log(transfer)
        if scanned:
            self.db.mark_nfc_seen(self.active['mac'], uid)
        self.phase = 'registering'
        self.request = self.emit('register', mac=self.active['mac'], cube_id=self.active['cube_id'], uid=uid)
        self.deadline = self.clock() + 15
        self.message = f'Registering cube #{self.active["cube_id"]}: {uid}'
        if self.mode in ('pair', 'repair'):
            self.notify('sending', f'TAG DETECTED · REGISTERING NEOCORE #{self.active["cube_id"]}',
                        transfer + f'UID {uid} · Flashing has stopped. Waiting for the device’s acknowledgment…')

    def flash(self, rows, sequential=False):
        self.available()
        if any(self.db.excluded(r['mac']) for r in rows):
            raise ValueError('Selection includes an excluded reader / base station')
        if not rows:
            raise ValueError('Select a device first')
        self.feedback = {}
        self.mode = 'flash_all' if sequential else 'flash'
        self.batch = list(rows)
        self.total, self.progress = len(rows), 0
        self.next_flash()

    def preview(self, mac):
        """One-second selection flash; rapid selections keep only the latest target."""
        if not self.connected or self.db.excluded(mac):
            if self.mode == 'preview': self.batch = []
            return False
        row = self.db.get(mac) or dict(mac=mac, cube_id=None)
        if self.mode == 'preview' and self.phase == 'flashing':
            self.batch = [] if self.active['mac'] == mac else [row]
            return True
        if self.mode:
            return False  # Never interrupt pairing, registration, or manual flashing.
        self.mode = 'preview'
        self.batch = [row]
        self.total, self.progress = 0, 0
        self.next_flash()
        return True

    def next_flash(self):
        if not self.batch:
            self.complete('Flash sequence complete. Radio results do not verify visible LEDs.')
            return
        self.active = self.batch.pop(0)
        self.phase = 'flashing'
        duration = 1000 if self.mode == 'preview' else 2000 if self.mode == 'flash_all' else 0
        self.request = self.emit('identify', mac=self.active['mac'], duration_ms=duration)
        self.deadline = self.clock() + 10 if duration else None
        self.message = f'Flashing cube #{self.active.get("cube_id") or "?"} · {self.active["mac"]}'

    def stop(self, then=None):
        if not self.connected:
            self.complete('Disconnected.')
            return
        if self.phase == 'registering' and self.active:
            self.db.result(self.active['mac'], False, 'Stopped; transmission may have reached cube')
        was_registration = self.mode in ('pair', 'repair') or isinstance(self.after_stop, tuple)
        self.after_stop = then
        if then is None and was_registration:
            self.notify('info', 'REGISTRATION STOPPED', 'Flashing is being stopped. Any registration already transmitted is not undone.')
        self.mode = self.mode or 'stop'
        self.phase = 'stopping'
        self.request = self.emit('stop')
        self.deadline = self.clock() + 5
        self.message = 'Stopping; restoring active cube to static white…'

    def skip(self):
        if self.mode not in ('pair', 'repair'):
            raise ValueError('Skip applies to interactive pairing')
        if self.active:
            self.skipped.add(self.active['mac'])
        self.stop(then='pair' if self.mode == 'pair' else None)

    def retry(self):
        if self.phase != 'paused' or not self.active:
            raise ValueError('No paused pairing to retry')
        row = self.db.get(self.active['mac'])
        if row['pending_uid']:
            self.register(row['pending_uid'])
        else:
            self.identify()

    def complete(self, message):
        self.mode = self.phase = ''
        self.request = self.active = self.deadline = None
        self.batch = []
        self.message = message
        self.log(message)

    def disconnected(self, reason):
        if self.phase == 'registering' and self.active:
            self.db.result(self.active['mac'], False, 'Serial connection lost; retry saved transaction')
        if self.mode in ('pair', 'repair') or self.after_stop:
            self.notify('error', 'REGISTRATION INTERRUPTED', reason)
        self.after_stop = None
        self.connected = self.reader_ok = False
        self.complete(reason)

    def event(self, e):
        kind = e.get('event')
        if kind == 'nfc_status':
            self.station['nfc_diagnostic'] = dict(e)
            self.reader_ok = bool(e.get('firmware_now')) and e.get('i2c_status') == 0 and e.get('nfc_polling', True)
            if not e.get('firmware_now') or e.get('i2c_status') != 0:
                self.notify('error', 'NFC READER NOT RESPONDING',
                            'The station radio is connected, but live communication with the PN532 has failed. No tag has been registered.')
            return
        if kind == 'nfc_poll_result':
            self.reader_ok = bool(e.get('enabled') and e.get('ready'))
            self.station['nfc_polling'] = bool(e.get('enabled'))
            if e.get('id') == self.nfc_poll_request:
                self.nfc_poll_request = None
                self.message = 'NFC scanning ready. Select a device and choose REGISTER DEVICE.' if self.reader_ok else 'NFC scanning could not start.'
            return
        if kind == 'radio' and e.get('mac'):
            t = self.telemetry.setdefault(e['mac'], {})
            t.update(delivery=e.get('status', 'unknown'), radio_at=self.clock(), packet_type=e.get('type'))
        if kind in ('registered', 'flash_done', 'stopped'):
            mac = e.get('mac') or (self.active['mac'] if self.active and e.get('id') == self.request else None)
            if mac:
                self.telemetry.setdefault(mac, {}).update(command='stop', command_at=self.clock())
        if kind == 'hello':
            if not e.get('id'):
                if self.connected:
                    self.disconnected('Station restarted; operation stopped.')
                    self.emit('hello')
                return
            if e.get('id') != self.hello_request:
                return
            self.hello_request = None
            self.station = dict(e)
            if e.get('mac'):
                try:
                    self.db.set_role(e['mac'], 'excluded')
                except ValueError:
                    pass
            if self.mode:
                self.disconnected('Station restarted; operation stopped.')
            self.connected = bool(e.get('radio_ok')) and e.get('protocol') == 1
            self.reader_ok = bool(e.get('nfc_ok')) and e.get('nfc_polling', True)
            self.tag_present = bool(e.get('tag_present', True))
            self.message = f'Station {e.get("mac")} · channel {e.get("channel")} · NFC {"ready" if self.reader_ok else "unavailable"}'
            if e.get('channel') != 2:
                self.connected = False
                self.message = 'Wrong radio channel; station must use channel 2.'
            if self.connected and e.get('nfc_ok') and e.get('nfc_polling') is False:
                self.message = 'Starting NFC scanning…'
                self.nfc_poll_request = self.emit('nfc_poll', enabled=True)
            return
        if kind == 'device':
            try:
                mac = hex_bytes(e['mac'], {6})
            except (KeyError, ValueError):
                return
            if int(mac[:2],16) & 1:
                return
            self.discovered[mac] = self.clock()
            if not self.db.excluded(mac) and mac != self.station.get('mac'):
                self.db.reserve(mac, source='discovered')
            self.choose()
            return
        if kind == 'tag_state':
            self.tag_present = bool(e.get('present'))
            if self.phase == 'identifying' and self.active:
                if self.tag_present:
                    self.notify('scan', f'CLEAR THE READER · NEOCORE #{self.active["cube_id"]}',
                                'Remove any tag first. Continuous flashing identifies the device to scan next.')
                else:
                    self.notify('scan', f'READY TO SCAN · NEOCORE #{self.active["cube_id"]} IS FLASHING',
                                f'{self.active["mac"]} · Hold its NFC tag on the reader. Keep it there until TAG DETECTED appears.')
            if not self.tag_present and self.phase == 'removal':
                self.phase = 'waiting'
                if self.mode == 'pair': self.choose()
                else: self.complete('Pairing complete.')
            return
        if kind == 'fatal':
            self.disconnected('Station radio fault. Reboot and reconnect.')
            return
        if kind == 'watchdog':
            self.disconnected('Station stopped after application heartbeat was lost. Reconnect.')
            return
        if e.get('id') != self.request:
            return  # Includes late ACK/results and stale scans from another target.
        if kind == 'tag' and self.phase == 'identifying':
            try:
                self.register(e['uid'])
            except ValueError as exc:
                self.phase = 'paused'
                self.message = str(exc)
                self.notify('error', 'TAG NOT REGISTERED', str(exc)+' · Flashing stopped. Use Retry or Skip.')
                self.emit('stop')  # Stop flashing, keep conflict visible until Retry/Skip.
                self.log(self.message)
        elif kind == 'registered' and self.phase == 'registering':
            if e.get('mac') != self.active['mac'] or e.get('cube_id') != self.active['cube_id']:
                return
            ack = e.get('acknowledged') is True
            self.db.result(self.active['mac'], ack, e.get('detail', ''))
            self.deadline = None
            self.progress += 1
            self.log(f'Cube #{self.active["cube_id"]}: {"acknowledged" if ack else "unconfirmed"}')
            if self.mode in ('pair', 'repair'):
                if ack:
                    self.notify('success', f'✓ NEOCORE #{self.active["cube_id"]} REGISTERED',
                                f'UID {self.active["pending_uid"] or self.active["uid"]} · Device acknowledged. Static lights requested. Remove the tag.')
                else:
                    self.notify('error', f'NEOCORE #{self.active["cube_id"]} NOT CONFIRMED',
                                'The tag was read, but the device did not acknowledge. Lights were commanded static. Retry the saved registration or Skip.')
            if self.mode == 'bulk':
                self.next_bulk()
            elif not ack:
                self.phase = 'paused'
                self.message = 'Registration unconfirmed. Retry or Skip; the saved ID/UID will be reused.'
            elif self.tag_present:
                self.phase = 'removal'
                self.message = 'Registered. Remove the NFC tag to continue.'
            elif self.mode == 'pair':
                self.phase = 'waiting'
                self.choose()
            else:
                self.complete('Pairing complete.')
        elif kind == 'flash_done' and self.phase == 'flashing':
            self.progress += 1
            self.next_flash()
        elif kind == 'stopped' and self.phase == 'stopping':
            then = self.after_stop
            self.after_stop = None
            self.complete('Stopped. Already transmitted registrations are not undone.')
            if isinstance(then, tuple) and then[0] == 'repair':
                self.repair(then[1], then[2] if len(then)>2 else None)
            elif isinstance(then, tuple) and then[0] == 'rename':
                self.rename(then[1], then[2])
            elif then == 'pair':
                self.mode, self.phase = 'pair', 'waiting'
                self.choose()
        elif kind == 'error':
            if self.phase == 'registering':
                self.db.result(self.active['mac'], False, e.get('detail', 'Station error'))
            self.phase, self.deadline = 'paused', None
            self.message = e.get('detail', 'Station error')
            if self.mode in ('pair', 'repair'):
                self.notify('error', 'REGISTRATION NEEDS ATTENTION', self.message)
            self.log(self.message)

    def tick(self):
        if not self.connected:
            return
        if self.deadline is not None and self.clock() >= self.deadline:
            self.stop()
            self.disconnected('Station response timed out. Reconnect before continuing.')
            return
        if self.phase not in ('registering', 'stopping') and self.clock() >= self.next_discovery:
            self.discover()
