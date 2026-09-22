"""Main show documents, images, radio frames and a reference renderer.

A show is edited as JSON (shows/mainshow.json, the console Show editor) and travels as a binary
image whose layout and rendering are defined by
zones/firmware/libraries/NctShow/src/NctShowEngine.h; the frames by NctShowProtocol.h. This module
mirrors both, console/web/lib/showengine.js mirrors the renderer and web/src/lib/show.ts mirrors
validate(). Change them together: run_firmware_tests.py renders generated vectors in C++ and
compares them with render() here.
"""
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / 'shows' / 'mainshow.json'
DEFAULT_HEADER = ROOT / 'flashing_station' / 'firmware' / 'neocore_usb' / 'DefaultShow.h'

FORMAT = 1
MAX_CUES = 128
MAX_LENGTH_MS = 3_600_000
LEVEL_MAX = 100
MAX_COLOURS = 3
U16 = 0xFFFF

HEADER = struct.Struct('<4sBBHI')              # magic, format, reserved, cueCount, lengthMs
CUE = struct.Struct('<IBBBB9sB3H')             # startMs, type, nColours, aux, reserved, colours, pad, params
MAX_IMAGE = HEADER.size + CUE.size * MAX_CUES

MAGIC, PROTO = b'NZ', 1
SHOW_ANNOUNCE, SHOW_CHUNK, SHOW_QUERY, SHOW_STATUS, SHOW_TIMECODE = 0x50, 0x51, 0x52, 0x53, 0x54
CHUNK_DATA = 200
ANNOUNCE_FORCE = 0x01
ANNOUNCE = struct.Struct('<2sBBIIHHBB')
CHUNK_HEADER = struct.Struct('<2sBBIHB')
QUERY = struct.Struct('<2sBBIH')
STATUS = struct.Struct('<2sBBIIIHIHHIBBBBBI16s')
TIMECODE = struct.Struct('<2sBBIIII')
SOURCES = {0: 'builtin', 1: 'nvs'}
ERRORS = {0: '', 1: 'update: out of memory', 2: 'update: CRC mismatch', 3: 'update: invalid show',
          4: 'update: NVS write failed', 5: 'update: timed out', 6: 'update: bad announce'}

assert HEADER.size == 12 and CUE.size == 24
assert ANNOUNCE.size == 18 and CHUNK_HEADER.size + CHUNK_DATA == 211 and QUERY.size == 10
assert STATUS.size == 55 and TIMECODE.size == 20

# Cue types: wire value, colour count (None = 1..3), parameter names in wire order.
TYPES = {
    'off': (0, 0, ()),
    'solid': (1, 1, ()),
    'fade': (2, 2, ('duration_ms',)),
    'blink': (3, 2, ('period_ms', 'on_ms')),
    'pulse': (4, 2, ('attack_ms', 'release_ms')),
    'cycle': (5, None, ('step_ms',)),
    'random': (6, 1, ('level_min', 'level_max', 'dur_min_ms', 'dur_max_ms', 'start_level')),
}
TYPE_NAMES = {code: name for name, (code, _, _) in TYPES.items()}
# Fanning (cube firmware v1.6.0+): per-cube offsets from the registered cube number. JSON:
#   "fan": {"mode": "sequential", "step_ms": S, "groups": N}   offset = ((cube - 1) % N) * S
#   "fan": {"mode": "scatter", "spread_ms": S}                  offset = scatter(cube) % (S + 1)
# Absent means no fanning (the image is then byte-identical to v1.5.0's).
FANNABLE = ('fade', 'blink', 'pulse', 'cycle')
FAN_MODES = {'sequential': 1, 'scatter': 2}
FAN_NAMES = {v: k for k, v in FAN_MODES.items()}


class ShowError(ValueError):
    """A show document or image that the cube firmware would refuse."""


def crc32(data, value=0):
    return zlib.crc32(data, value) & 0xFFFFFFFF


def _int(value, where, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ShowError(f'{where} must be a whole number from {low} to {high}')
    return value


def validate(doc):
    """Return a normalised copy of a show document, or raise ShowError naming the first problem."""
    if not isinstance(doc, dict):
        raise ShowError('show must be an object')
    if doc.get('format', FORMAT) != FORMAT:
        raise ShowError(f'unsupported show format {doc.get("format")!r}')
    length = _int(doc.get('length_ms'), 'length_ms', 1, MAX_LENGTH_MS)
    cues = doc.get('cues')
    if not isinstance(cues, list) or not 1 <= len(cues) <= MAX_CUES:
        raise ShowError(f'a show needs 1 to {MAX_CUES} cues')
    out, previous = [], None
    for i, cue in enumerate(cues):
        where = f'cue {i + 1}'
        if not isinstance(cue, dict):
            raise ShowError(f'{where} must be an object')
        start = _int(cue.get('start_ms'), f'{where} start_ms', 0, length - 1)
        if i == 0 and start != 0:
            raise ShowError('the first cue must start at 0')
        if previous is not None and start <= previous:
            raise ShowError(f'{where} must start after cue {i}')
        previous = start
        kind = cue.get('type')
        if kind not in TYPES:
            raise ShowError(f'{where} has unknown type {kind!r}')
        _, count, names = TYPES[kind]
        colours = cue.get('colours', [])
        if not isinstance(colours, list):
            raise ShowError(f'{where} colours must be a list')
        if count is None and not 1 <= len(colours) <= MAX_COLOURS:
            raise ShowError(f'{where} ({kind}) needs 1 to {MAX_COLOURS} colours')
        if count is not None and len(colours) != count:
            raise ShowError(f'{where} ({kind}) needs {count} colour{"s" if count != 1 else ""}')
        clean_colours = []
        for c, rgb in enumerate(colours):
            if not isinstance(rgb, list) or len(rgb) != 3:
                raise ShowError(f'{where} colour {c + 1} must be [r, g, b]')
            clean_colours.append([_int(v, f'{where} colour {c + 1}', 0, LEVEL_MAX) for v in rgb])
        params = cue.get('params', {}) or {}
        if not isinstance(params, dict) or set(params) != set(names):
            raise ShowError(f'{where} ({kind}) needs parameters {", ".join(names) or "none"}')
        p = {}
        for name in names:
            high = LEVEL_MAX if name in ('level_min', 'level_max', 'start_level') else U16
            low = 0 if name in ('level_min', 'level_max', 'start_level', 'on_ms') else 1
            p[name] = _int(params[name], f'{where} {name}', low, high)
        if kind == 'blink' and p['on_ms'] > p['period_ms']:
            raise ShowError(f'{where} on_ms cannot exceed period_ms')
        if kind == 'random':
            if p['level_min'] > p['level_max']:
                raise ShowError(f'{where} level_min cannot exceed level_max')
            if p['dur_min_ms'] > p['dur_max_ms']:
                raise ShowError(f'{where} dur_min_ms cannot exceed dur_max_ms')
        label = cue.get('label', '')
        if not isinstance(label, str):
            raise ShowError(f'{where} label must be text')
        clean = {'start_ms': start, 'label': label, 'type': kind, 'colours': clean_colours, 'params': p}
        fan = cue.get('fan')
        if fan not in (None, {}):
            if kind not in FANNABLE:
                raise ShowError(f'{where} ({kind}) cannot fan; only {", ".join(FANNABLE)} can')
            if not isinstance(fan, dict) or fan.get('mode') not in FAN_MODES:
                raise ShowError(f'{where} fan mode must be sequential or scatter')
            if fan['mode'] == 'sequential':
                if set(fan) != {'mode', 'step_ms', 'groups'}:
                    raise ShowError(f'{where} sequential fan needs step_ms and groups')
                clean['fan'] = {'mode': 'sequential', 'step_ms': _int(fan['step_ms'], f'{where} fan step_ms', 1, U16),
                                'groups': _int(fan['groups'], f'{where} fan groups', 1, 255)}
            else:
                if set(fan) != {'mode', 'spread_ms'}:
                    raise ShowError(f'{where} scatter fan needs spread_ms')
                clean['fan'] = {'mode': 'scatter', 'spread_ms': _int(fan['spread_ms'], f'{where} fan spread_ms', 1, U16)}
        out.append(clean)
    return {'format': FORMAT, 'length_ms': length, 'cues': out}


def pack(doc):
    """Binary image of a (validated) show document."""
    doc = validate(doc)
    parts = [HEADER.pack(b'NSHW', FORMAT, 0, len(doc['cues']), doc['length_ms'])]
    for cue in doc['cues']:
        code, _, _ = TYPES[cue['type']]
        p, aux, fan = cue['params'], 0, 0
        if cue['type'] == 'random':
            params = (p['level_min'] | p['level_max'] << 8, p['dur_min_ms'], p['dur_max_ms'])
            aux = p['start_level']
        else:
            params = (tuple(p[name] for name in TYPES[cue['type']][2]) + (0, 0, 0))[:3]
            if 'fan' in cue:
                f = cue['fan']
                fan = FAN_MODES[f['mode']]
                aux = f['groups'] if f['mode'] == 'sequential' else 0
                params = params[:2] + (f['step_ms'] if f['mode'] == 'sequential' else f['spread_ms'],)
        colours = bytes(v for rgb in cue['colours'] for v in rgb).ljust(9, b'\0')
        parts.append(CUE.pack(cue['start_ms'], code, len(cue['colours']), aux, fan, colours, 0, *params))
    return b''.join(parts)


def unpack(image):
    """Show document of a binary image (labels are not carried). Raises ShowError if invalid."""
    if len(image) < HEADER.size:
        raise ShowError('image too short')
    magic, fmt, reserved, count, length = HEADER.unpack_from(image)
    if magic != b'NSHW' or fmt != FORMAT or reserved:
        raise ShowError('not a show image')
    if not 1 <= count <= MAX_CUES or len(image) != HEADER.size + CUE.size * count:
        raise ShowError('image length does not match its cue count')
    cues = []
    for i in range(count):
        start, code, n, aux, res, colours, pad, p0, p1, p2 = CUE.unpack_from(image, HEADER.size + CUE.size * i)
        if code not in TYPE_NAMES or res not in (0, *FAN_NAMES) or pad or n > MAX_COLOURS or any(colours[3 * n:]):
            raise ShowError(f'cue {i + 1} is malformed')
        kind = TYPE_NAMES[code]
        names = TYPES[kind][2]
        if kind == 'random':
            params = {'level_min': p0 & 0xFF, 'level_max': p0 >> 8, 'dur_min_ms': p1, 'dur_max_ms': p2, 'start_level': aux}
        else:
            fan = None
            if res == FAN_MODES['sequential']:
                fan, aux, p2 = {'mode': 'sequential', 'step_ms': p2, 'groups': aux}, 0, 0
            elif res == FAN_MODES['scatter']:
                fan, p2 = {'mode': 'scatter', 'spread_ms': p2}, 0
            if aux or any((p0, p1, p2)[len(names):]):
                raise ShowError(f'cue {i + 1} is malformed')
            params = dict(zip(names, (p0, p1, p2)))
        cue = {'start_ms': start, 'label': '', 'type': kind,
               'colours': [list(colours[3 * c:3 * c + 3]) for c in range(n)], 'params': params}
        if kind != 'random' and fan:
            cue['fan'] = fan
        cues.append(cue)
    doc = validate({'format': FORMAT, 'length_ms': length, 'cues': cues})
    if pack(doc) != bytes(image):
        raise ShowError('image does not round-trip')
    return doc


def load(path=DEFAULT_PATH):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))


def dumps(doc):
    """Stable JSON text: one cue per line, so a git diff shows which cues changed."""
    doc = validate(doc)
    lines = ['{', f'  "format": {doc["format"]},', f'  "length_ms": {doc["length_ms"]},', '  "cues": [']
    for i, cue in enumerate(doc['cues']):
        comma = ',' if i < len(doc['cues']) - 1 else ''
        lines.append('    ' + json.dumps(cue, ensure_ascii=False, separators=(', ', ': ')) + comma)
    lines += ['  ]', '}', '']
    return '\n'.join(lines)


def save(doc, path=DEFAULT_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(dumps(doc), encoding='utf-8', newline='\n')
    tmp.replace(path)


def summary(doc):
    """Timeline for status displays: [(end_ms, label)] like zones/mainshow/app.py TIMELINE."""
    doc = validate(doc)
    cues = doc['cues']
    ends = [c['start_ms'] for c in cues[1:]] + [doc['length_ms']]
    return [(end, cue['label'] or cue['type']) for end, cue in zip(ends, cues)]


# ---------------------------------------------------------------- renderer (NctShowEngine.h)

def lerp8(a, b, elapsed, duration):
    if elapsed >= duration:
        return b
    diff = (b - a) * elapsed
    return a + (abs(diff) // duration) * (1 if diff >= 0 else -1)   # C truncation toward zero


def _fade(a, b, elapsed, duration):
    return tuple(lerp8(x, y, elapsed, duration) for x, y in zip(a, b))


def scatter(cube):
    return ((cube * 2654435761) & 0xFFFFFFFF) >> 16


def fan_offset(cue, cube):
    """This cube's offset for a cue in ms (nctshow::fanOffset)."""
    fan = cue.get('fan')
    if not cube or not fan:
        return 0
    if fan['mode'] == 'sequential':
        return ((cube - 1) % fan['groups']) * fan['step_ms']
    return scatter(cube) % (fan['spread_ms'] + 1)


class Player:
    """Renders a show image exactly like nctshow::Player. rng(lo, hi_exclusive) -> int."""

    def __init__(self, image, cube=0):
        self.doc = unpack(image) if isinstance(image, (bytes, bytearray)) else validate(image)
        self.length_ms = self.doc['length_ms']
        self.cube = cube  # registered cube number (0 = none): sets the fanning offsets
        self.restart()

    def restart(self):
        self._random_cue = -1
        self._from = self._to = self._start = 0
        self._duration = 1

    def cue_at(self, t):
        found = 0
        for i, cue in enumerate(self.doc['cues']):
            if cue['start_ms'] > t:
                break
            found = i
        return found

    def render(self, t, rng):
        """(r, g, b), or None once t reaches the show length."""
        if t >= self.length_ms:
            return None
        index = self.cue_at(t)
        cue = self.doc['cues'][index]
        local, p, c = t - cue['start_ms'], cue['params'], [tuple(x) for x in cue['colours']]
        kind = cue['type']
        offset = fan_offset(cue, self.cube)
        delayed = max(0, local - offset)  # one-shot effects wait; periodic ones shift phase
        if kind == 'off':
            return (0, 0, 0)
        if kind == 'solid':
            return c[0]
        if kind == 'fade':
            return _fade(c[0], c[1], delayed, p['duration_ms'])
        if kind == 'blink':
            period = p['period_ms']
            return c[0] if (local + period - offset % period) % period < p['on_ms'] else c[1]
        if kind == 'pulse':
            if delayed < p['attack_ms']:
                return _fade(c[0], c[1], delayed, p['attack_ms'])
            return _fade(c[1], c[0], delayed - p['attack_ms'], p['release_ms'])
        if kind == 'cycle':
            n, step_ms = len(c), p['step_ms']
            period = step_ms * n
            cycle = (local + period - offset % period) % period
            step = cycle // step_ms
            return _fade(c[step], c[(step + 1) % n], cycle - step * step_ms, step_ms)
        level = self._random_level(p, index, t, rng)
        return tuple(min(level, LEVEL_MAX) * v // 100 for v in c[0])

    def _random_level(self, p, index, t, rng):
        def transition():
            self._to = rng(p['level_min'], p['level_max'] + 1)
            self._start = t
            self._duration = rng(p['dur_min_ms'], p['dur_max_ms'] + 1)
        if self._random_cue != index:
            self._random_cue = index
            self._from = p['start_level']
            transition()
        elapsed = (t - self._start) & 0xFFFFFFFF
        if elapsed >= self._duration:
            self._from = self._to
            transition()
            elapsed = 0
        return lerp8(self._from, self._to, elapsed, self._duration)


class TestRng:
    """Deterministic rng shared with the C++ and JS vector tests."""

    def __init__(self):
        self.n = 0

    def __call__(self, lo, hi):
        self.n += 1
        return lo + (self.n * 7919) % (hi - lo)


def vector_doc():
    """A show using every cue type, short enough to sweep and long enough to need three chunks."""
    cues, t = [], 0
    specs = [('solid', [[10, 20, 30]], {}), ('off', [], {}),
             ('blink', [[90, 0, 5], [3, 4, 5]], {'period_ms': 70, 'on_ms': 25}),
             ('fade', [[0, 0, 0], [100, 51, 7]], {'duration_ms': 333}),
             ('fade', [[100, 60, 0], [1, 2, 3]], {'duration_ms': 900}),
             ('pulse', [[5, 5, 5], [97, 13, 60]], {'attack_ms': 45, 'release_ms': 140}),
             ('cycle', [[17, 17, 18], [11, 16, 18], [18, 12, 12]], {'step_ms': 110}),
             ('cycle', [[0, 100, 0], [100, 0, 100]], {'step_ms': 57}),
             ('cycle', [[42, 42, 42]], {'step_ms': 10}),
             ('random', [[81, 100, 23]], {'level_min': 12, 'level_max': 50, 'dur_min_ms': 30, 'dur_max_ms': 90, 'start_level': 20}),
             ('random', [[100, 100, 100]], {'level_min': 0, 'level_max': 100, 'dur_min_ms': 1, 'dur_max_ms': 40, 'start_level': 100}),
             ('blink', [[100, 100, 100], [20, 20, 20]], {'period_ms': 50, 'on_ms': 50})]
    for i in range(2):
        for kind, colours, params in specs:
            cue = {'start_ms': t, 'label': f'{kind} {i}', 'type': kind, 'colours': colours, 'params': params}
            if i == 1 and kind in FANNABLE:  # the second pass fans every fannable cue, both ways
                cue['fan'] = ({'mode': 'sequential', 'step_ms': 13 + len(cues), 'groups': 5} if len(cues) % 2 else
                              {'mode': 'scatter', 'spread_ms': 90 + len(cues)})
            cues.append(cue)
            t += 400 + 37 * len(cues)
    return {'format': 1, 'length_ms': t + 250, 'cues': cues}


VECTOR_CUBES = (0, 1, 7, 23, 138)


def vectors(doc, step=3, cube=0):
    """[(t, playing, r, g, b)] rendered with TestRng for one cube: the cross-engine vectors (C++, Python, JS)."""
    player, rng, rows = Player(doc, cube), TestRng(), []
    for t in list(range(0, doc['length_ms'], step)) + [doc['length_ms'], doc['length_ms'] + 1]:
        rgb = player.render(t, rng)
        rows.append((t, int(rgb is not None)) + tuple(rgb or (0, 0, 0)))
    return rows


VECTORS_PATH = ROOT / 'console' / 'web' / 'tests' / 'show_vectors.json'


def vectors_text():
    doc = vector_doc()
    return json.dumps(dict(doc=doc, crc=crc32(pack(doc)), cubes={str(c): vectors(doc, step=7, cube=c) for c in VECTOR_CUBES}),
                      separators=(',', ':')) + '\n'


# ---------------------------------------------------------------- radio frames (NctShowProtocol.h)

def announce(version, image, force=False):
    chunks = (len(image) + CHUNK_DATA - 1) // CHUNK_DATA
    return ANNOUNCE.pack(MAGIC, PROTO, SHOW_ANNOUNCE, version, crc32(image), len(image), chunks, CHUNK_DATA,
                         ANNOUNCE_FORCE if force else 0)


def chunks(version, image):
    out = []
    for index in range(0, len(image), CHUNK_DATA):
        data = image[index:index + CHUNK_DATA]
        out.append(CHUNK_HEADER.pack(MAGIC, PROTO, SHOW_CHUNK, version, index // CHUNK_DATA, len(data)) +
                   data.ljust(CHUNK_DATA, b'\0'))
    return out


def query(nonce, jitter_ms=2000):
    return QUERY.pack(MAGIC, PROTO, SHOW_QUERY, nonce & 0xFFFFFFFF, min(jitter_ms, 5000))


def timecode(show_id, t_ms, version=0, crc=0):
    return TIMECODE.pack(MAGIC, PROTO, SHOW_TIMECODE, show_id, t_ms, version, crc)


def frame_type(data):
    if len(data) < 4 or len(data) in (2, 24) or data[:2] != MAGIC or data[2] != PROTO:
        return 0
    sizes = {SHOW_ANNOUNCE: ANNOUNCE.size, SHOW_CHUNK: CHUNK_HEADER.size + CHUNK_DATA, SHOW_QUERY: QUERY.size,
             SHOW_STATUS: STATUS.size, SHOW_TIMECODE: TIMECODE.size}
    return data[3] if sizes.get(data[3]) == len(data) else 0


def parse_status(data):
    if frame_type(data) != SHOW_STATUS:
        raise ValueError('not a show status frame')
    (_, _, _, nonce, version, crc, length, staging_version, staging_chunks, staging_total, cube_id, source, error,
     zone, running, pending, uptime, fw) = STATUS.unpack(data)
    return {'nonce': nonce, 'version': version, 'crc': crc, 'length': length, 'staging_version': staging_version,
            'staging_chunks': staging_chunks, 'staging_total': staging_total, 'cube_id': cube_id,
            'source': SOURCES.get(source, str(source)), 'error': error, 'error_text': ERRORS.get(error, f'error {error}'),
            'zone': zone, 'show_running': bool(running), 'pending_commit': bool(pending), 'uptime_s': uptime,
            'fw': fw.rstrip(b'\0').decode('ascii', 'replace')}


# ---------------------------------------------------------------- compiled-in default

def header_text(doc):
    """DefaultShow.h: the cube's compiled-in show (used until a published show is stored in NVS)."""
    image = pack(doc)
    rows = [', '.join(f'0x{b:02x}' for b in image[i:i + 16]) for i in range(0, len(image), 16)]
    body = ',\n  '.join(rows)
    return ('#pragma once\n'
            '// GENERATED by `python pairing_station/showfile.py --header` from shows/mainshow.json.\n'
            '// Do not edit; the cube test fails if this is stale. This is the show a cube plays when\n'
            '// NVS holds no valid published show (version 0).\n'
            '#include <stdint.h>\n\n'
            f'static const uint32_t DEFAULT_SHOW_CRC = 0x{crc32(image):08x};\n'
            f'static const uint16_t DEFAULT_SHOW_SIZE = {len(image)};\n'
            f'static const uint8_t DEFAULT_SHOW[{len(image)}] = {{\n  {body}\n}};\n')


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--header']:  # also the JS vector file
        DEFAULT_HEADER.write_text(header_text(load()), encoding='utf-8', newline='\n')
        print(f'wrote {DEFAULT_HEADER}')
        VECTORS_PATH.write_text(vectors_text(), encoding='utf-8', newline='\n')
        print(f'wrote {VECTORS_PATH}')
    else:
        doc = load()
        image = pack(doc)
        print(f'{len(doc["cues"])} cues, {doc["length_ms"]} ms, image {len(image)} bytes, crc {crc32(image):08x}')
