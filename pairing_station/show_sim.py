"""A Python model of a v1.5.0 neocube's show receiver, for tests and the console's --simulate mode.

It follows neocore_usb.ino (onShowAnnounce / onShowChunk / finishStaging / commitStagedShow and the
status reply); zones/tests/test_NeocoreShow.cpp is the authority on the real firmware. It is not a
substitute for that test, only a stand-in cube for host-side tooling.
"""
import showfile

FW = 'v1.7.0-USB.1'


class FakeShowCube:
    def __init__(self, mac, cube_id=0, version=0, image=None, fw=FW):
        self.mac, self.cube_id, self.fw = mac, cube_id, fw
        self.image = image if image is not None else showfile.pack(showfile.load())
        self.version = version
        self.error = 0
        self.show_running = False
        self.zone = 0
        self.staging = None  # dict(version, crc, length, total, chunks{index: bytes})
        self.pending = False
        self.commits = 0
        self.live = None     # SHOW_LIVE (firmware v1.7.0+): dict(rgb, lease_ms, count) last shown for cube_id

    @property
    def crc(self):
        return showfile.crc32(self.image)

    def receive(self, data, broadcast=True):
        """Handle one frame; returns the status frames the cube would send back (to the sender)."""
        kind = showfile.frame_type(data)
        out = []
        if kind == showfile.SHOW_ANNOUNCE:
            _, _, _, version, crc, length, chunks, size, flags = showfile.ANNOUNCE.unpack(data)
            force = bool(flags & showfile.ANNOUNCE_FORCE) and not broadcast
            if not version or not length or length > showfile.MAX_IMAGE or size != showfile.CHUNK_DATA or \
                    chunks != (length + size - 1) // size:
                self.error = 6
            elif (version, crc) == (self.version, self.crc) or (version <= self.version and not force):
                pass
            elif self.staging and (self.staging['version'], self.staging['crc'], self.staging['length']) == (version, crc, length):
                pass
            elif self.pending and version < self.staging['version'] and not force:
                pass
            else:
                self.staging = dict(version=version, crc=crc, length=length, total=chunks, chunks={})
                self.pending = False
        elif kind == showfile.SHOW_CHUNK and self.staging and not self.pending:
            _, _, _, version, index, n = showfile.CHUNK_HEADER.unpack_from(data)
            s = self.staging
            expected = showfile.CHUNK_DATA if index + 1 < s['total'] else s['length'] - index * showfile.CHUNK_DATA
            if version == s['version'] and index < s['total'] and n == expected:
                s['chunks'].setdefault(index, data[showfile.CHUNK_HEADER.size:showfile.CHUNK_HEADER.size + n])
                if len(s['chunks']) == s['total']:
                    image = b''.join(s['chunks'][i] for i in range(s['total']))
                    if showfile.crc32(image) != s['crc']:
                        self.error, self.staging = 2, None
                    else:
                        try:
                            showfile.unpack(image)
                        except showfile.ShowError:
                            self.error, self.staging = 3, None
                        else:
                            s['image'] = image
                            self.pending = True
                            if not self.show_running:
                                out.append(self.commit())
        elif kind == showfile.SHOW_LIVE and broadcast:
            # Authoring mirror: a numbered cube not playing a show takes its entry (no reply).
            _, _, _, lease_ms, n = showfile.LIVE_HEADER.unpack_from(data)
            for i in range(n):
                cube, r, g, b = showfile.LIVE_ENTRY.unpack_from(data, showfile.LIVE_HEADER.size + i * showfile.LIVE_ENTRY.size)
                if self.cube_id and cube == self.cube_id and not self.show_running:
                    count = self.live['count'] + 1 if self.live else 1
                    self.live = dict(rgb=(r, g, b), lease_ms=lease_ms, count=count)
        elif kind == showfile.SHOW_QUERY:
            _, _, _, nonce, _ = showfile.QUERY.unpack(data)
            out.append(self.status(nonce))
        return out

    def commit(self):
        self.image, self.version = self.staging['image'], self.staging['version']
        self.staging, self.pending, self.error = None, False, 0
        self.commits += 1
        return self.status(0)

    def end_show(self):
        """The show ended (or was stopped); a pending image commits now."""
        self.show_running = False
        return [self.commit()] if self.pending else []

    def status(self, nonce):
        s = self.staging or {}
        return showfile.STATUS.pack(
            showfile.MAGIC, showfile.PROTO, showfile.SHOW_STATUS, nonce, self.version, self.crc, len(self.image),
            s.get('version', 0), len(s.get('chunks', ())), s.get('total', 0), self.cube_id, 1 if self.version else 0,
            self.error, self.zone, int(self.show_running), int(self.pending), 60, self.fw.encode().ljust(16, b'\0'))
