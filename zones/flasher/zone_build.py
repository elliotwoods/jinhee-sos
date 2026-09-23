"""Reproducible zone firmware builds with a hash-checked manifest (mirrors flashing_station/build.py)."""
import csv
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # zones/flasher
ZONES = ROOT.parent                             # zones
WORKSPACE = ZONES.parent
if str(WORKSPACE / 'pairing_station') not in sys.path:
    sys.path.append(str(WORKSPACE / 'pairing_station'))
import hostos  # noqa: E402

CORE = hostos.esp32_core('3.3.11')
SUPERMINI = 'esp32:esp32:nologo_esp32c3_super_mini:CDCOnBoot=cdc,PartitionScheme=no_ota'
LIBRARIES = [WORKSPACE / 'live files/libraries', ZONES / 'firmware/libraries']
DATA_PARTITIONS = ('zcfg', 'zdb_a', 'zdb_b')

# Firmware sketches (zones/firmware/<name>) and the board they are built for.
SKETCHES = {'PreshowZone': SUPERMINI, 'TagPlateZone': SUPERMINI, 'DesertZone': SUPERMINI, 'PoolZone': SUPERMINI,
            'ResetZone': SUPERMINI}

# What the operator picks in the flasher. zone_type 1-4 match the neocube ZoneType enum; 5 (reset) is a plate
# kind only, the plate sends zone 0 (idle) to the cube. `params` are integers stored in zcfg (label, default
# shown, multiplier applied before storing).
PROFILES = {
    'preshow': dict(label='Preshow plate (media points 1-4)', sketch='PreshowZone', zone_type=1, points=(1, 2, 3, 4),
                    name='Preshow {point}', params=()),
    'preshow_exit': dict(label='Preshow exit / safety plate', sketch='TagPlateZone', zone_type=1, points=tuple(range(1, 9)),
                         name='Preshow Exit {point}', params=()),
    'mainshow': dict(label='Mainshow entrance plate', sketch='TagPlateZone', zone_type=4, points=tuple(range(1, 9)),
                     name='Mainshow {point}', params=()),
    'desert': dict(label='Desert plate (light panel)', sketch='DesertZone', zone_type=2, points=tuple(range(1, 9)),
                   name='Desert {point}', params=()),
    'pool': dict(label='Pool radio (slider)', sketch='PoolZone', zone_type=3, points=(1, 2, 3, 4, 5, 6),
                 name='Pool Radio {point}', params=(('Slider mm at member 1', 383.0, 10), ('Slider mm at member 23', 43.0, 10))),
    'reset': dict(label='Reset plate (cube → idle)', sketch='ResetZone', zone_type=5, points=tuple(range(1, 9)),
                  name='Reset {point}', params=()),
}
FIRMWARE_PREFIX = {'preshow-': 'PreshowZone', 'tagplate-': 'TagPlateZone', 'desert-': 'DesertZone', 'pool-': 'PoolZone',
                   'reset-': 'ResetZone'}


def profile_for(firmware, zone_type):
    """Profile key for a running NctZone firmware string + configured zone type, or None."""
    sketch = next((v for k, v in FIRMWARE_PREFIX.items() if (firmware or '').startswith(k)), None)
    matches = [k for k, p in PROFILES.items() if p['sketch'] == sketch and p['zone_type'] == zone_type]
    return matches[0] if matches else next((k for k, p in PROFILES.items() if p['sketch'] == sketch), None)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources(sketch):
    sketch = ZONES / 'firmware' / sketch
    files = sorted(sketch.glob('*.ino')) + sorted(sketch.glob('*.h')) + sorted(sketch.glob('*.csv')) + sorted((ZONES / 'firmware/libraries/NctZone/src').glob('*'))
    if sketch.name == 'PoolZone':
        files.append(Path(__file__))  # include build flags in the installed-source fingerprint
    return files


def source_hash(sketch):
    h = hashlib.sha256()
    for path in sources(sketch):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def firmware_version(sketch):
    text = (ZONES / 'firmware' / sketch / f'{sketch}.ino').read_text(encoding='utf-8')
    match = re.search(r'FIRMWARE_VERSION\s*=\s*"([^"]+)"', text)
    if not match:
        raise ValueError('Sketch has no FIRMWARE_VERSION')
    return match[1]


def parse_partitions(path):
    table = {}
    for row in csv.reader(line for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')):
        row = [c.strip() for c in row]
        table[row[0]] = dict(type=row[1], subtype=row[2], offset=int(row[3], 0), size=int(row[4], 0))
    for name in ('nvs', 'app0') + DATA_PARTITIONS:
        if name not in table:
            raise ValueError(f'Partition table is missing {name}')
    return table


def build_dir(name):
    return WORKSPACE / 'zones/build' / name


def build(name, run):
    """Build one sketch (a key of SKETCHES)."""
    fqbn = SKETCHES[name]
    cli = hostos.arduino_cli()
    if not cli:
        raise RuntimeError('Install Arduino IDE or arduino-cli and ESP32 core 3.3.11')
    before = source_hash(name)
    out = build_dir(name)
    out.mkdir(parents=True, exist_ok=True)
    args = [cli, 'compile', '--fqbn', fqbn, *hostos.arduino_build_args()]
    if name == 'PoolZone':
        # POOL_BUILD_ID goes in through the core's build_opt.h hook ("@{build.opt.path}" on every
        # compile line) from a file whose path never changes: a changing --build-property would make
        # arduino-cli wipe the whole build path on every source change. gcc does not track the
        # file as a dependency, so drop the compiled sketch whenever the ID changes.
        options = out / 'pool_build_opt.h'
        wanted = f'-DPOOL_BUILD_ID=h{before}\n'
        if not options.is_file() or options.read_text(encoding='utf-8') != wanted:
            shutil.rmtree(out / 'cache' / 'sketch', ignore_errors=True)
            options.write_text(wanted, encoding='utf-8', newline='\n')
        args += ['--build-property', f'build.opt.path={options}']
    for library in LIBRARIES:
        args += ['--libraries', str(library)]
    run(args + ['--build-path', str(out / 'cache'), '--output-dir', str(out), str(ZONES / 'firmware' / name)], timeout=900)
    options = json.loads((out / 'cache/build.options.json').read_text(encoding='utf-8'))
    if not all(hostos.same_folder(folder, CORE) for folder in options['hardwareFolders'].split(',')):
        raise RuntimeError('Build used an unexpected ESP32 core; select version 3.3.11')
    if source_hash(name) != before:
        raise RuntimeError('Source changed during build; rebuild before flashing')
    if name == 'PoolZone' and ('h' + before).encode() not in (out / f'{name}.ino.bin').read_bytes():
        raise RuntimeError('Build did not embed the expected POOL_BUILD_ID; delete zones/build/PoolZone/cache and rebuild')
    partitions = parse_partitions(out / 'cache/partitions.csv')
    shutil.copyfile(CORE / 'tools/partitions/boot_app0.bin', out / 'boot_app0.bin')
    sketch = name
    segments = []
    for offset, file in [(0x0, f'{sketch}.ino.bootloader.bin'), (0x8000, f'{sketch}.ino.partitions.bin'),
                         (partitions['otadata']['offset'], 'boot_app0.bin'), (partitions['app0']['offset'], f'{sketch}.ino.bin')]:
        segments.append(dict(offset=offset, file=file, sha256=digest(out / file), size=(out / file).stat().st_size))
    manifest = dict(sketch=name, version=firmware_version(name), fqbn=fqbn, core='3.3.11', esptool='5.3.1',
                    segments=segments, data={p: partitions[p] for p in DATA_PARTITIONS}, source_hash=before)
    manifest['build_hash'] = hashlib.sha256(json.dumps(segments, sort_keys=True).encode()).hexdigest()
    temp = out / 'manifest.json.tmp'
    temp.write_text(json.dumps(manifest, indent=2), encoding='utf-8', newline='\n')
    temp.replace(out / 'manifest.json')
    return manifest


def load_manifest(name):
    fqbn = SKETCHES[name]
    out = build_dir(name)
    path = out / 'manifest.json'
    if not path.exists():
        raise ValueError('No firmware build yet; choose Build firmware')
    m = json.loads(path.read_text(encoding='utf-8'))
    if m.get('sketch') != name or m['fqbn'] != fqbn:
        raise ValueError('Firmware target mismatch; rebuild')
    if m['source_hash'] != source_hash(name):
        raise ValueError('Firmware source changed since the last build; rebuild before flashing')
    for segment in m['segments']:
        if digest(out / segment['file']) != segment['sha256']:
            raise ValueError('Firmware checksum mismatch; rebuild')
    if m['build_hash'] != hashlib.sha256(json.dumps(m['segments'], sort_keys=True).encode()).hexdigest():
        raise ValueError('Build manifest checksum mismatch')
    return m


if __name__ == '__main__':
    import subprocess
    import sys
    for target in sys.argv[1:] or list(SKETCHES):
        m = build(target, lambda args, timeout: subprocess.run(args, check=True, timeout=timeout, capture_output=True))
        print(f'{target}: {m["version"]} build {m["build_hash"][:10]}, app {m["segments"][-1]["size"]} bytes')
