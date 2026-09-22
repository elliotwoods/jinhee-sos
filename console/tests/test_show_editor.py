"""Show editor back end: the working copy, web publish/pull, cube updates through a relay, controller config."""
import copy
import sys
import unittest
from types import SimpleNamespace

import support  # noqa: F401
from support import simulated_hub, run_ticks
import paths
import commands
import commands_show  # noqa: F401
import showfile
from show_sim import FakeShowCube

sys.path.insert(0, str(paths.ROOT / 'pairing_station' / 'tests'))
from fake_web_inventory import FakeWebInventory  # noqa: E402
import web_client  # noqa: E402

CUBES = ['1C:DB:D4:F0:A8:30', 'AC:27:6E:80:00:D0']


class FakeRelay:
    """A General Radio that speaks show_send, with two v1.5.0 cubes in range."""
    kind = 'generalradio'

    def __init__(self, hub):
        self.hub = hub
        self.device = SimpleNamespace(id='relay')
        self.cubes = {mac: FakeShowCube(mac) for mac in CUBES}
        self.transport = SimpleNamespace(send=self.send)
        self.sent = []

    def show_relay(self):
        return True

    def send(self, message):
        self.sent.append(message)
        data = bytes.fromhex(message['hex'])
        broadcast = message['mac'] == 'FF:FF:FF:FF:FF:FF'
        self.hub.showedit.event(dict(event='show_sent', id=message['id'], mac=message['mac'], status='delivered'))
        for mac, cube in self.cubes.items():
            if broadcast or message['mac'] == mac:
                for reply in cube.receive(data, broadcast):
                    self.hub.showedit.event(dict(event='show_frame', mac=mac, rssi=-55, hex=reply.hex()))

    # the hub calls these on every session
    def pump(self):
        pass

    def tick(self, now):
        pass

    def snapshot(self):
        return {}


def token(hub, name, args):
    return dict(args)  # hardware commands run on click; only destructive ones need a confirming hold


class ShowEditorTests(unittest.TestCase):
    def setUp(self):
        self.hub = simulated_hub()
        self.editor = self.hub.showedit

    def edited(self):
        doc = copy.deepcopy(self.editor.draft)
        doc['cues'][0]['colours'] = [[40, 0, 0]]
        return doc

    def test_working_copy_is_validated_and_kept_in_the_database(self):
        self.assertEqual(self.editor.origin, 'default')
        self.assertEqual(self.editor.summary()['crc'], showfile.crc32(showfile.pack(showfile.load())))
        bad = self.edited()
        bad['cues'][1]['start_ms'] = 0
        with self.assertRaisesRegex(ValueError, 'must start after'):
            commands.run(self.hub, 'show.save', dict(doc=bad))
        commands.run(self.hub, 'show.save', dict(doc=self.edited()))
        self.assertEqual(self.editor.origin, 'draft')
        self.assertIn('[40,0,0]', self.hub.db.metadata('show_draft'))
        # A new editor on the same database resumes the working copy.
        from showedit import ShowEditor
        self.assertEqual(ShowEditor(self.hub).draft['cues'][0]['colours'], [[40, 0, 0]])
        commands.run(self.hub, 'show.revert', dict(source='default'))
        self.assertEqual(self.editor.draft, showfile.load())
        with self.assertRaisesRegex(ValueError, 'No show published'):
            commands.run(self.hub, 'show.revert', dict(source='published'))
        with self.assertRaisesRegex(ValueError, 'Not JSON'):
            commands.run(self.hub, 'show.import', dict(text='{'))
        run_ticks(self.hub, 3)
        snap = support.section(self.hub, 'showedit')
        self.assertEqual((snap['origin'], snap['summary']['cues'], snap['relay']['present']), ('default', 21, False))

    def test_publish_then_update_cubes_over_a_relay(self):
        server = FakeWebInventory()
        self.addCleanup(server.close)
        original = web_client.WebClient.__init__
        def local(this, *args, **kw):
            original(this, server.url, password=server.password, client='test')
        web_client.WebClient.__init__ = local
        self.addCleanup(setattr, web_client.WebClient, '__init__', original)
        web_client.save_password(server.password)
        commands.run(self.hub, 'show.save', dict(doc=self.edited()))
        job = commands.run(self.hub, 'show.publish', {})
        self.assertTrue(support.tick_until(self.hub, lambda: self.hub.jobs.jobs[job['job']].state in ('done', 'failed')))
        self.assertEqual(self.hub.jobs.jobs[job['job']].state, 'done', self.hub.jobs.jobs[job['job']].error)
        self.assertEqual(self.editor.registry.store.published()['version'], 1)
        # Updates need a relay.
        with self.assertRaisesRegex(ValueError, 'General Radio'):
            commands.run(self.hub, 'show.update_all', token(self.hub, 'show.update_all', {}))
        relay = FakeRelay(self.hub)
        self.hub.sessions['relay'] = relay
        commands.run(self.hub, 'show.query', token(self.hub, 'show.query', {}))
        self.assertEqual({c['mac'] for c in self.editor.registry.cube_rows()}, set(CUBES))
        self.assertTrue(all(c['state'] == 'behind' for c in self.editor.registry.cube_rows()))
        commands.run(self.hub, 'show.update_all', token(self.hub, 'show.update_all', {}))
        self.assertTrue(support.tick_until(self.hub, lambda: self.editor.registry.publication is None, timeout=20))
        image = showfile.pack(self.edited())
        self.assertTrue(all((c.version, c.image) == (1, image) for c in relay.cubes.values()))
        snap = support.section(self.hub, 'showedit')
        self.assertTrue(snap['draft_published'])
        self.assertTrue(all(c['state'] == 'current' for c in snap['cubes']))
        del self.hub.sessions['relay']

    def test_controller_config_only_for_timecode_firmware(self):
        requests = []
        old = SimpleNamespace(device=SimpleNamespace(id='ctl'), session=SimpleNamespace(
            info=dict(firmware='mainshow-1.2.0'), request=lambda cmd, **f: requests.append((cmd, f)), show_state=lambda: None))
        self.hub.show_session = lambda: old
        self.editor.registry.store.cache(dict(version=3, **self._doc_fields(self.edited())))
        with self.assertRaisesRegex(ValueError, 'no show timecode; it still starts the show'):
            self.editor.push_config()
        self.editor.tick(0)
        self.assertEqual(requests, [], 'an old controller is left alone')
        old.session.info = dict(firmware='mainshow-1.3.0', timecode=True, show_length_ms=298000)
        self.editor.tick(0)
        self.assertEqual(requests, [('show_config', dict(length_ms=298000, version=3, crc=showfile.crc32(showfile.pack(self.edited()))))])
        self.editor.tick(0)
        self.assertEqual(len(requests), 1, 'sent once per publication')

    def test_update_through_the_simulated_general_radio(self):
        """The real GeneralRadioSession + FakeGeneralRadio (general-radio-1.1.0) + a simulated v1.5.0 cube."""
        self.assertTrue(support.tick_until(self.hub, lambda: self.editor.relay() is not None, timeout=10))
        radio = self.editor.relay()
        self.editor.registry.store.cache(dict(version=4, **self._doc_fields(self.edited())))
        commands.run(self.hub, 'show.query', {})
        self.assertTrue(support.tick_until(self.hub, lambda: self.editor.registry.cube_rows(), timeout=5))
        cube_mac = self.editor.registry.cube_rows()[0]['mac']
        commands.run(self.hub, 'show.update_all', {})
        self.assertTrue(support.tick_until(self.hub, lambda: self.editor.registry.publication is None, timeout=30))
        self.assertIn('confirmed on 1 cube', self.editor.registry.message)
        rows = {c['mac']: c for c in self.editor.registry.cube_rows()}
        self.assertEqual((rows[cube_mac]['version'], rows[cube_mac]['state']), (4, 'current'))
        # A timecode-capable radio is told the published show's length once.
        self.assertTrue(support.tick_until(self.hub, lambda: radio.status.get('show_version') == 4, timeout=5))
        self.assertEqual(radio.status.get('show_length_ms'), self.edited()['length_ms'])

    def test_live_mirror_reaches_numbered_cubes_through_a_relay(self):
        entries = [[7, [10, 20, 30]], [8, [0, 100, 0]]]
        with self.assertRaisesRegex(ValueError, 'general-radio-1.2.0 and cubes with firmware v1.7.0-USB.1'):
            commands.run(self.hub, 'show.live', dict(entries=entries))
        relay = FakeRelay(self.hub)
        cube7, cube8 = relay.cubes.values()
        cube7.cube_id, cube8.cube_id = 7, 8
        self.hub.sessions['relay'] = relay
        self.addCleanup(self.hub.sessions.pop, 'relay', None)
        now = [100.0]
        self.editor.clock = lambda: now[0]
        result = commands.run(self.hub, 'show.live', dict(entries=entries))
        self.assertEqual(result, dict(sent=1, cubes=2))
        message = relay.sent[-1]
        self.assertEqual((message['cmd'], message['mac']), ('show_send', 'FF:FF:FF:FF:FF:FF'))
        self.assertEqual(showfile.frame_type(bytes.fromhex(message['hex'])), showfile.SHOW_LIVE)
        self.assertEqual((cube7.live['rgb'], cube7.live['lease_ms']), ((10, 20, 30), 600))
        self.assertEqual(cube8.live['rgb'], (0, 100, 0))
        # Fire-and-forget: the relay's show_sent is swallowed, not counted by the registry.
        self.assertEqual((self.editor.live_ids, self.editor.registry.send_failures), ({}, 0))
        # Rate limit: a call within 40 ms of the last send is dropped.
        now[0] += 0.02
        self.assertEqual(commands.run(self.hub, 'show.live', dict(entries=[[7, [1, 1, 1]]])), dict(sent=0, dropped=True))
        self.assertEqual((cube7.live['rgb'], len(relay.sent)), ((10, 20, 30), 1))
        now[0] += 0.05
        commands.run(self.hub, 'show.live', dict(entries=[[7, [1, 1, 1]]], lease_ms=300))
        self.assertEqual((cube7.live['rgb'], cube7.live['lease_ms'], cube8.live['rgb']), ((1, 1, 1), 300, (0, 100, 0)))
        self.assertTrue(self.editor.snapshot()['live']['active'])
        with self.assertRaisesRegex(ValueError, 'bad live entry'):
            now[0] += 1
            commands.run(self.hub, 'show.live', dict(entries=[[7, [101, 0, 0]]]))
        # A cube playing a show ignores it.
        cube7.show_running = True
        now[0] += 1
        commands.run(self.hub, 'show.live', dict(entries=[[7, [5, 5, 5]]]))
        self.assertEqual(cube7.live['rgb'], (1, 1, 1))

    def test_live_mirror_holds_during_a_show_update_or_a_running_show(self):
        relay = FakeRelay(self.hub)
        relay.cubes[CUBES[0]].cube_id = 3
        self.hub.sessions['relay'] = relay
        self.addCleanup(self.hub.sessions.pop, 'relay', None)
        self.editor.registry.publication = object()  # a show update in progress
        result = commands.run(self.hub, 'show.live', dict(entries=[[3, [9, 9, 9]]]))
        self.assertEqual(result['sent'], 0)
        self.assertIn('show update', result['held'])
        self.assertEqual((relay.sent, relay.cubes[CUBES[0]].live), ([], None))
        self.editor.registry.publication = None
        self.editor.controller_show_running = lambda: True
        self.assertIn('show is running', commands.run(self.hub, 'show.live', dict(entries=[[3, [9, 9, 9]]]))['held'])
        self.assertEqual(relay.sent, [])
        del self.editor.controller_show_running
        self.assertEqual(commands.run(self.hub, 'show.live', dict(entries=[[3, [9, 9, 9]]]))['sent'], 1)
        self.assertEqual(relay.cubes[CUBES[0]].live['rgb'], (9, 9, 9))

    def test_live_refusal_by_an_older_radio_is_swallowed_then_reported(self):
        relay = FakeRelay(self.hub)
        self.hub.sessions['relay'] = relay
        self.addCleanup(self.hub.sessions.pop, 'relay', None)

        def refuse(message):  # general-radio-1.1.0 does not know SHOW_LIVE
            relay.sent.append(message)
            self.hub.showedit.event(dict(event='error', id=message['id'], detail='unknown show frame'))
        relay.transport.send = refuse
        commands.run(self.hub, 'show.live', dict(entries=[[1, [1, 2, 3]]]))
        self.assertNotIn(relay.sent[0]['id'], self.editor.registry.requests)
        self.assertEqual(self.editor.snapshot()['live']['error'], 'unknown show frame')
        self.editor.live_last = None
        with self.assertRaisesRegex(ValueError, 'refused the live colours .*general-radio-1.2.0'):
            commands.run(self.hub, 'show.live', dict(entries=[[1, [1, 2, 3]]]))

    def test_live_through_the_simulated_general_radio(self):
        self.assertTrue(support.tick_until(self.hub, lambda: self.editor.relay() is not None, timeout=10))
        board = next(b for b in __import__('simulate').BOARDS.values() if hasattr(b, 'show_cubes'))
        cube = next(iter(board.show_cubes.values()))
        cube.cube_id = 12
        self.assertEqual(commands.run(self.hub, 'show.live', dict(entries=[[12, [4, 5, 6]]]))['sent'], 1)
        self.assertTrue(support.tick_until(self.hub, lambda: cube.live is not None, timeout=5))
        self.assertEqual(cube.live['rgb'], (4, 5, 6))
        self.assertTrue(support.tick_until(self.hub, lambda: not self.editor.live_ids, timeout=5))

    def _doc_fields(self, doc):
        import base64
        from show_registry import image_hash
        image = showfile.pack(doc)
        return dict(hash=image_hash(image), crc=showfile.crc32(image), length=len(image),
                    image_b64=base64.b64encode(image).decode(), source=doc)


if __name__ == '__main__':
    unittest.main()
