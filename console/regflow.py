"""Guided cube registration: USB → number → NFC scan → sync, one cube after another.

Switched on by the `auto_register` setting. Plugging in a cube (Hub.identified) starts the flow for it:
  1. usb     the cube was identified over USB and pinned (Hub.identified already reserved its row)
  2. number  a cube without a number gets the lowest free one above 32 (db.suggested_number, which skips the
             reserved numbers); the operator is told it is new so it goes on the label
  3. nfc     Controller.repair(mac) on the pairing station: the cube flashes, the operator scans its tag; the
             controller keeps every registration rule (request IDs, MAC/ID ACK match, tag takeover, audit)
  4. sync    one web Sync (inventory both ways, then the zone database publish) once the reader is clear
Pushing the published zone database to the zones stays a separate action.

Runs on the owner thread only (called from Hub.identified and Hub.tick) and never blocks. It never
retries a registration by itself: a failure waits for Retry or Restart.
"""
import paths  # noqa: F401

STEPS = ('usb', 'number', 'nfc', 'sync')
HISTORY = 20


class RegistrationFlow:
    def __init__(self, hub):
        self.hub = hub
        self.was_enabled = False
        self.history = []          # newest first: dict(mac, number, new, result, at)
        self.notice = None         # dict(id, text, tone): the UI shows each id once as a toast
        self.notices = 0
        self.clear()

    # ---------------------------------------------------------------- state
    def clear(self):
        self.mac = self.port = self.device_id = None
        self.step = 'idle'         # idle | number | nfc | sync | done | failed
        self.number = None
        self.number_new = None     # 'assigned' (new: write it on the label) | 'existing' | 'label' (typed by the operator)
        self.before = None
        self.wait = ''             # why the current step is waiting (not an error)
        self.error = ''            # why the flow stopped (step == 'failed'; failed_step says where)
        self.failed_step = None
        self.armed = False         # Controller.repair was called for this cube
        self.start_event = 0       # audit events after this id belong to this attempt
        self.sync_job = None
        self.sync_summary = ''
        self.sync_warning = ''
        self.unplugged = False
        self.started_at = None

    @property
    def enabled(self):
        return bool(self.hub.settings.get('auto_register'))

    @property
    def db(self):
        return self.hub.db

    def say(self, text, tone='info'):
        self.notices += 1
        self.notice = dict(id=self.notices, text=text, tone=tone)
        self.hub.log(text, 'ok' if tone == 'ok' else 'warn' if tone in ('warn', 'bad') else 'info', self.device_id,
                     source='register')
        self.hub.mark_dirty('register')

    def set_wait(self, text):
        if text != self.wait:
            self.wait = text
            self.hub.mark_dirty('register')

    def fail(self, text):
        self.failed_step = self.step if self.step in STEPS else self.failed_step
        self.step, self.error, self.wait = 'failed', text, ''
        self.say(f'Registration of {self.label()} stopped: {text}', 'bad')
        self.record('failed')

    def label(self):
        return f'#{self.number} ({self.mac})' if self.number is not None else str(self.mac)

    def record(self, result):
        entry = dict(mac=self.mac, number=self.number, new=self.number_new == 'assigned', result=result,
                     at=self.hub.wall(), detail=self.error or self.sync_summary)
        self.history = [h for h in self.history if h['mac'] != self.mac]
        self.history.insert(0, entry)
        del self.history[HISTORY:]
        self.hub.mark_dirty('register')

    # ---------------------------------------------------------------- entry points
    def cube_identified(self, device, before):
        """Hub.identified: a cube was identified over USB and pinned (its row already reserved)."""
        if not self.enabled:
            return
        if device.mac == self.mac and not self.unplugged:
            return   # the same cube re-probed (a session reopened): keep going where it is
        if device.mac == self.mac and self.step in ('number', 'nfc', 'sync'):
            self.port, self.device_id, self.unplugged = device.port, device.id, False   # plugged back in mid-flow
            self.set_wait('')
            self.hub.mark_dirty('register')
            return
        if self.mac and self.mac != device.mac and self.step in ('number', 'nfc', 'sync'):
            self.hub.log(f'Registration of {self.label()} interrupted by {device.mac} on {device.port}; '
                         'its saved mapping stays retryable', 'warn', device.id, source='register')
            self.record('interrupted')
        self.start(device, before)

    def start(self, device, before=None):
        self.clear()
        self.mac, self.port, self.device_id = device.mac, device.port, device.id
        self.before = before
        self.started_at = self.hub.wall()
        self.step = 'number'
        self.hub.mark_dirty('register')
        self.advance()

    def restart(self):
        device = self.pinned_device()
        if not device:
            raise ValueError('Plug in a cube over USB first')
        station = self.hub.station_session()
        if self.armed and station and station.controller.mode and \
                (station.controller.active or {}).get('mac') == self.mac:
            station.controller.stop()
        self.start(device, self.db.get(device.mac))

    def cancel(self):
        station = self.hub.station_session()
        if self.armed and station and station.controller.mode and \
                (station.controller.active or {}).get('mac') == self.mac:
            station.controller.stop()
        if self.step in ('number', 'nfc', 'sync'):
            self.error = 'Cancelled by the operator'
            self.failed_step = self.step
            self.step, self.wait = 'failed', ''
            self.record('cancelled')
        self.hub.mark_dirty('register')

    def renumber(self, number):
        """Use the number on the cube's physical label instead of the suggested one (before its tag is scanned)."""
        if not self.mac:
            raise ValueError('No cube in the registration workflow')
        if self.step not in ('nfc', 'failed') or (self.step == 'failed' and self.failed_step != 'nfc'):
            raise ValueError('The number can only be changed before the tag is scanned')
        number = int(number)
        station = self.hub.station_session()
        controller = station.controller if station else None
        if controller and controller.phase == 'registering':
            raise ValueError('The tag was already scanned; wait for the result')
        self.db.validate_number(self.mac, number)
        if controller and self.armed and controller.mode and (controller.active or {}).get('mac') == self.mac:
            controller.stop()
        self.db.rename(self.mac, number, fresh_scan=True)
        self.number, self.number_new = number, 'label'
        self.armed = False
        self.step, self.error, self.failed_step = 'nfc', '', None
        self.say(f'Number #{number} (from the label) set for {self.mac}', 'ok')
        self.hub.mark_dirty('inventory')
        return number

    def retry(self):
        """After a failed step: re-send the saved registration (station paused on this cube), re-arm the scan, or sync again."""
        if self.step != 'failed' or not self.mac:
            raise ValueError('Nothing to retry in the registration workflow')
        if self.failed_step == 'sync':
            return self.sync_now()
        if self.failed_step != 'nfc':
            return self.restart()
        station = self.hub.station_session()
        controller = station.controller if station else None
        self.start_event = self.last_event_id()
        self.step, self.error, self.failed_step, self.wait = 'nfc', '', None, ''
        if controller and controller.phase == 'paused' and (controller.active or {}).get('mac') == self.mac:
            controller.retry()     # the controller re-sends the saved tag, or flashes for a new scan
            self.armed = True
        else:
            self.armed = False     # armed again (a fresh scan) on the next tick
        self.hub.mark_dirty('register', 'station', 'inventory')
        self.advance()
        return True

    def sync_now(self):
        if self.step not in ('failed', 'done') or (self.step == 'failed' and self.failed_step != 'sync'):
            raise ValueError('Nothing to sync in the registration workflow')
        self.step, self.error, self.failed_step, self.sync_job = 'sync', '', None, None
        self.advance()

    # ---------------------------------------------------------------- tick
    def tick(self):
        enabled = self.enabled
        if enabled and not self.was_enabled and self.step == 'idle':
            device = self.pinned_device()
            if device:   # switched on with a cube already plugged in: register that one
                self.start(device, self.db.get(device.mac))
        if self.was_enabled and not enabled and self.step in ('number', 'nfc', 'sync'):
            self.cancel()
        self.was_enabled = enabled
        if self.mac and not self.unplugged and not self.device_present():
            self.unplugged = True
            self.hub.mark_dirty('register')
        if self.step in ('number', 'nfc', 'sync'):
            self.advance()

    def pinned_device(self):
        mac = self.hub.pinned_mac
        for device in self.hub.devices.values():
            if mac and device.mac == mac and device.role == 'cube':
                return device
        return None

    def device_key(self):
        return next((d.key for d in self.hub.devices.values() if d.mac == self.mac and d.role == 'cube'), None)

    def device_present(self):
        return any(d.mac == self.mac and d.role == 'cube' for d in self.hub.devices.values())

    def advance(self):
        for _ in range(4):   # each step may finish at once; stop when one waits
            step = self.step
            handler = {'number': self.step_number, 'nfc': self.step_nfc, 'sync': self.step_sync}.get(step)
            if handler is None:   # idle, done or failed: nothing to run
                return
            try:
                handler()
            except ValueError as exc:
                self.fail(str(exc))
            if self.step == step:
                return

    def step_number(self):
        row = self.db.get(self.mac)
        if not row:
            raise ValueError('The cube is not in the device database')
        if self.db.excluded(self.mac):
            raise ValueError('This device is excluded as a reader / base station, not a cube')
        if row['cube_id'] is None and self.hub.web_numbering():
            # This computer syncs with the web, so the web hands out the number (never two cubes on one number).
            self.hub.request_number(self.mac)
            error = self.hub.numbering['error']
            return self.set_wait(f'The web could not hand out a number ({error}); retrying. Or assign one by hand.' if error
                                 else 'Getting a new number from the web…')
        if row['cube_id'] is None:
            number = self.db.suggested_number()
            row = self.db.rename(self.mac, number, fresh_scan=True)
            self.number_new = 'assigned'
        elif self.before is None or self.before.get('cube_id') is None:
            self.number_new = 'assigned'   # reserve() just gave it the automatic number
        else:
            self.number_new = 'existing'
        self.number = row['cube_id']
        if self.number_new == 'assigned':
            self.say(f'New number #{self.number} assigned to {self.mac}. Write it on the cube\'s label.', 'ok')
        self.hub.mark_dirty('inventory', 'register')
        self.step = 'nfc'

    def step_nfc(self):
        station = self.hub.station_session()
        controller = station.controller if station else None
        if not self.armed:
            if self.unplugged:
                return self.set_wait('Plug the cube back in (it is powered over USB)')
            flashflow = getattr(self.hub, 'flashflow', None)
            if flashflow and flashflow.holds(self.mac, self.hub.devices.get(self.device_key())):
                return self.set_wait('Waiting for the Flash page to finish this cube')
            if not controller:
                return self.set_wait('Connect the pairing station')
            if not controller.connected:
                return self.set_wait('Waiting for the pairing station to connect')
            if not controller.reader_ok:
                return self.set_wait('The pairing link has no working NFC reader (plug in the pairing station)')
            if controller.mode and controller.mode != 'preview':
                return self.set_wait(f'The station is busy ({controller.mode}); waiting for it to finish')
            row = self.db.get(self.mac) or {}
            self.number = row.get('cube_id', self.number)
            self.start_event = self.last_event_id()
            controller.repair(self.mac)
            self.armed = True
            self.set_wait('')
            self.hub.mark_dirty('station', 'inventory', 'register')
            return
        result = self.registration_result()
        if result == 'acknowledged':
            row = self.db.get(self.mac)
            if not row or row['status'] != 'acknowledged' or not row['uid'] or row['cube_id'] != self.number:
                raise ValueError('The acknowledgment does not match the saved mapping')
            self.say(f'Cube #{self.number} registered with tag {row["uid"]} (acknowledged by the cube)', 'ok')
            self.step, self.wait = 'sync', ''
            self.hub.mark_dirty('register')
            return
        if result == 'unconfirmed':
            raise ValueError('The cube did not acknowledge; Retry sends the saved registration again')
        mine = controller and (controller.active or {}).get('mac') == self.mac
        after = controller and isinstance(controller.after_stop, tuple) and self.mac in controller.after_stop
        if controller and controller.mode == 'repair' and controller.phase == 'paused' and mine:
            raise ValueError(controller.message or 'The station paused the registration')
        if not controller or not (mine and controller.mode) and not after:
            raise ValueError('The registration was stopped before a tag was scanned')

    def step_sync(self):
        station = self.hub.station_session()
        controller = station.controller if station else None
        if controller and controller.mode and (controller.active or {}).get('mac') == self.mac:
            return self.set_wait('Remove the tag from the reader')
        if self.sync_job is None:
            if not self.hub.sync.get('password_known'):
                return self.set_wait('Sign in to sync (the Sync chip, top right)')
            if self.hub.sync.get('busy') or any(j.kind == 'sync' and j.state == 'running' for j in self.hub.jobs.jobs.values()):
                return self.set_wait('Another sync is running; waiting for it to finish')
            from jobs.sync import sync_job
            self.sync_job = sync_job(self.hub).id
            self.set_wait('Syncing inventory and publishing the zone database…')
            self.hub.mark_dirty('register')
            return
        job = self.hub.jobs.jobs.get(self.sync_job)
        if job is None or job.state in ('failed', 'cancelled'):
            raise ValueError('Sync failed: ' + ((job and job.error) or 'the job was lost') + '. Press Sync to try again')
        if job.state != 'done':
            return
        result = job.result or {}
        self.sync_summary = self.hub.sync.get('summary') or 'Synced'
        self.sync_warning = f'Zone database not published: {result["zone_error"]}' if result.get('zone_error') else ''
        self.step, self.wait = 'done', ''
        self.say(f'Cube #{self.number} registered and synced. Unplug it and plug in the next cube.'
                 + (f' ({self.sync_warning})' if self.sync_warning else ''), 'warn' if self.sync_warning else 'ok')
        self.record('registered')

    # ---------------------------------------------------------------- evidence
    def last_event_id(self):
        row = self.db.conn.execute('SELECT MAX(id) FROM events').fetchone()
        return row[0] or 0

    def registration_result(self):
        row = self.db.conn.execute(
            "SELECT action FROM events WHERE mac=? AND id>? AND action IN ('acknowledged','unconfirmed') ORDER BY id DESC LIMIT 1",
            (self.mac, self.start_event)).fetchone()
        return row[0] if row else None

    def usb_confirmation(self):
        """The cube's own USB line `REGISTERED Cube #N` after this attempt (extra evidence, never required)."""
        if not self.device_id:
            return None
        session = self.hub.sessions.get(self.device_id)
        flag = getattr(session, 'flags', {}).get('registered') if session else None
        if flag and self.started_at and flag.get('at', 0) >= self.started_at:
            return flag.get('number')
        return None

    def snapshot(self):
        return dict(enabled=self.enabled, step=self.step, mac=self.mac, port=self.port, device=self.device_id,
                    number=self.number, number_new=self.number_new, wait=self.wait, error=self.error,
                    failed_step=self.failed_step, armed=self.armed, unplugged=self.unplugged,
                    sync_job=self.sync_job, sync_summary=self.sync_summary, sync_warning=self.sync_warning,
                    usb_confirmed=self.usb_confirmation(), started_at=self.started_at, notice=self.notice,
                    history=list(self.history), steps=list(STEPS))
