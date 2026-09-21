"""Zone database updates over an unreliable link: packet loss, dongle drop-outs, zones leaving range.

SimZone follows NctZoneLink.cpp (onAnnounce / onChunk / finishStaging / staging timeout) as used by the
deployed 2.x zone firmware; the protocol bytes come from zonedb.py, the same definitions the host
firmware tests check against the real library.
"""
import base64
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Database  # noqa: E402
from zone_registry import ZoneRegistry  # noqa: E402
import zonedb  # noqa: E402

STAGING_TIMEOUT = 60
STATION = dict(zones=1, channel=2)


class SimZone:
    def __init__(self, mac, version, records):
        self.mac, self.version, self.records = mac, version, list(records)
        self.crc = zonedb.crc32(zonedb.pack_records(self.records))
        self.staging = None
        self.replies = []

    def status(self):
        s = self.staging
        frame = zonedb.STATUS.pack(b'NZ', 1, zonedb.ZONE_STATUS, 0, 2, 1, b'Desert 1'.ljust(16, b'\0'),
                                   b'desert-2.2.0'.ljust(16, b'\0'), self.version, len(self.records), self.crc,
                                   s['version'] if s else 0, len(s['chunks']) if s else 0, s['total'] if s else 0,
                                   100, 0, 0, 0, 0, 2, 1, 1)
        return frame.hex()

    def receive(self, data, now, broadcast):
        kind = zonedb.frame_kind(data)
        if kind == zonedb.ZONE_QUERY:
            self.replies.append(self.status())
        elif kind == zonedb.DB_ANNOUNCE:
            _, _, _, version, count, chunks, per, flags, crc = zonedb.ANNOUNCE.unpack(data)
            self.replies.append(self.status())
            force = bool(flags & zonedb.ANNOUNCE_FORCE) and not broadcast
            if (version, crc, count) == (self.version, self.crc, len(self.records)):
                return
            if not (version > self.version or force):
                return
            s = self.staging
            if s and (s['version'], s['crc'], s['count']) == (version, crc, count):
                s['last'] = now  # same announce: progress kept
                return
            if s and not force and version < s['version']:
                return
            self.staging = dict(version=version, crc=crc, count=count, total=chunks, per=per, chunks={}, last=now)
        elif kind == zonedb.DB_CHUNK and self.staging:
            _, _, _, version, index, n = zonedb.CHUNK_HEADER.unpack_from(data)
            s = self.staging
            if version != s['version'] or index >= s['total']:
                return
            s['last'] = now
            s['chunks'].setdefault(index, data[zonedb.CHUNK_HEADER.size:])
            if len(s['chunks']) == s['total']:
                body = b''.join(s['chunks'][i] for i in range(s['total']))
                self.staging = None
                if zonedb.crc32(body) == s['crc']:
                    self.version, self.records, self.crc = s['version'], zonedb.unpack_records(body), s['crc']
                self.replies.append(self.status())

    def tick(self, now):
        if self.staging and now - self.staging['last'] > STAGING_TIMEOUT:
            self.staging = None


class LinkFaultTests(unittest.TestCase):
    ZONE = '30:ED:A0:5B:1D:3C'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'devices.sqlite3')
        self.now, self.wall = 1000.0, 1_700_000_000.0
        self.sent = []
        self.registry = ZoneRegistry(self.db, self.sent.append, lambda _: None, lambda: self.now, lambda: self.wall,
                                     auto_refresh=True)
        records = self.registry.store.records()
        p = zonedb.Publication(14, records)
        self.registry.store.cache(dict(version=14, hash=zonedb.content_hash(records), count=p.count, crc=p.crc,
                                       records_b64=base64.b64encode(p.body).decode(), published_at='', published_by=''))
        self.target = p
        self.zone = SimZone(self.ZONE, 12, records[:-5])  # an old 2.2.0 zone on a legacy database
        self.rng = random.Random(7)
        self.loss, self.in_range, self.dongle = 0.0, True, True

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def step(self, dt=0.1):
        """One app poll: relay what the registry sent (with loss), deliver zone replies (with loss)."""
        self.now += dt
        self.wall += dt
        self.zone.tick(self.now)
        for message in self.sent:
            if not self.dongle:
                continue  # USB gone: no zone_sent either
            delivered = self.in_range and self.rng.random() >= self.loss
            if delivered and message['mac'] in (self.ZONE, 'FF:FF:FF:FF:FF:FF'):
                self.zone.receive(bytes.fromhex(message['hex']), self.now, message['mac'] != self.ZONE)
            # Broadcasts always report "delivered"; unicast only when the zone ACKed at the MAC layer.
            status = 'delivered' if message['mac'] != self.ZONE or delivered else 'unconfirmed'
            self.registry.event(dict(event='zone_sent', id=message['id'], status=status))
        self.sent.clear()
        for reply in self.zone.replies:
            if self.dongle and self.in_range and self.rng.random() >= self.loss:
                self.registry.event(dict(event='zone_frame', mac=self.ZONE, hex=reply))
        self.zone.replies.clear()
        self.registry.tick(self.dongle, STATION)

    def run_until(self, done, seconds):
        for _ in range(int(seconds / 0.1)):
            self.step()
            if done():
                return True
        return False

    def zone_current(self):
        return (self.zone.version, self.zone.crc) == (self.target.version, self.target.crc)

    def test_update_selected_survives_heavy_packet_loss(self):
        self.loss = 0.4
        self.run_until(lambda: self.registry.zone_rows(), 10)
        self.registry.update(self.ZONE)
        self.assertTrue(self.run_until(lambda: not self.registry.publication, 45))
        self.assertTrue(self.zone_current())
        self.assertIn('confirmed', self.registry.message)
        self.assertEqual(self.zone.records, self.target.records)

    def test_dongle_drop_mid_update_then_resume_keeps_zone_progress(self):
        self.run_until(lambda: self.registry.zone_rows(), 5)
        self.registry.update(self.ZONE)
        self.run_until(lambda: self.zone.staging and len(self.zone.staging['chunks']) >= 2, 10)
        received = len(self.zone.staging['chunks'])
        self.assertLess(received, self.target.chunk_count)
        self.dongle = False  # USB unplugged / dongle silent: the app reports disconnected
        self.step()
        self.assertIsNone(self.registry.publication)
        self.assertIn('disconnected', self.registry.message)
        self.run_until(lambda: False, 20)  # 20 s later (inside the zone's 60 s staging window)
        self.dongle = True
        self.assertEqual(len(self.zone.staging['chunks']), received)  # zone kept its progress
        self.registry.update(self.ZONE)
        self.assertTrue(self.run_until(lambda: not self.registry.publication, 45))
        self.assertTrue(self.zone_current())

    def test_zone_leaves_range_mid_update(self):
        self.run_until(lambda: self.registry.zone_rows(), 5)
        self.registry.update(self.ZONE)
        self.run_until(lambda: self.zone.staging and len(self.zone.staging['chunks']) >= 2, 10)
        self.in_range = False
        self.assertTrue(self.run_until(lambda: not self.registry.publication, ZoneRegistry.WALK_TIMEOUT + 5))
        self.assertIn('timed out', self.registry.message)
        self.assertEqual(self.zone.version, 12)  # nothing half-committed
        self.run_until(lambda: False, STAGING_TIMEOUT + 5)
        self.assertIsNone(self.zone.staging)  # the zone discards the partial update itself
        self.assertEqual(self.registry.zone_rows()[0]['state'], 'behind')

    def test_walkaround_retries_after_outages_until_current(self):
        self.loss = 0.25
        self.registry.set_walkaround(True)
        self.run_until(lambda: self.registry.walk_run, 10)
        self.in_range = False  # walked away mid-update
        self.run_until(lambda: not self.registry.publication, ZoneRegistry.WALK_TIMEOUT + 5)
        self.assertEqual(self.zone.version, 12)
        self.in_range = True  # walked back: after the backoff, walkaround finishes the job by itself
        self.assertTrue(self.run_until(self.zone_current, ZoneRegistry.WALK_BACKOFF + 60))
        self.run_until(lambda: not self.registry.publication, 10)
        self.assertEqual(self.registry.zone_rows()[0]['state'], 'current')

    def test_zone_on_newer_version_is_never_rolled_back(self):
        self.zone = SimZone(self.ZONE, 20, self.target.records[:3])
        self.registry.set_walkaround(True)
        self.run_until(lambda: False, 30)
        self.assertEqual(self.registry.zone_rows()[0]['state'], 'ahead')
        self.assertFalse(self.registry.walk_run)
        self.assertEqual(self.zone.version, 20)


if __name__ == '__main__':
    unittest.main()
