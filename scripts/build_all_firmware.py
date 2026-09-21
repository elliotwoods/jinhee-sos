#!/usr/bin/env python3
"""Build all maintained firmware and diagnostic targets; never upload."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
IDE_CLI = Path('/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli')
C3 = 'esp32:esp32:esp32c3:CDCOnBoot=cdc'
# Kept for a board that cannot read its flash reliably at the default 80 MHz. One pool
# central did exactly that: it boot-looped on `esp_image: Checksum failed` with the
# bootloader computing a DIFFERENT checksum on every boot, while the flash contents were
# provably byte-identical to the build. If that reappears, switch the pool central target
# to this and flash bootloader and app together - the speed lives in the bootloader header.
C3_SLOW_FLASH = 'esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashFreq=40'
SUPERMINI = 'esp32:esp32:nologo_esp32c3_super_mini:CDCOnBoot=cdc,PartitionScheme=no_ota'
XIAO = 'esp32:esp32:XIAO_ESP32C3:CDCOnBoot=default,PartitionScheme=no_ota,FlashSize=4M'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='List targets and output directories without compiling')
    options = parser.parse_args()
    sys.path.insert(0, str(ROOT/'flashing_station'))
    cube = load('cube_build', ROOT/'flashing_station/build.py')
    zones = load('zone_build', ROOT/'zones/flasher/zone_build.py')
    cli = str(IDE_CLI) if IDE_CLI.exists() else shutil.which('arduino-cli')
    if not cli and not options.dry_run:
        parser.error('Install Arduino IDE or arduino-cli with ESP32 core 3.3.11 first')

    def run(args, timeout):
        subprocess.run(args, check=True, timeout=timeout, cwd=ROOT)

    def compile_sketch(sketch, out, board, libraries=()):
        out.mkdir(parents=True, exist_ok=True)
        args = [cli, 'compile', '--fqbn', board]
        for library in libraries:
            args += ['--libraries', str(ROOT/library)]
        run(args + ['--build-path', str(out/'cache'), '--output-dir', str(out), str(ROOT/sketch)], 900)

    targets = [('Neocore USB', ROOT/'flashing_station/build', lambda: cube.build(run))]
    for name in zones.SKETCHES:
        targets.append((name, zones.build_dir(name), lambda name=name: zones.build(name, run)))
    for name, sketch, output, board, libraries in [
        ('Pairing station', 'pairing_station/firmware/pairing_station', 'pairing_station/build', C3,
         ('pairing_station/.arduino/libraries', 'zones/firmware/libraries')),
        ('Pool radio test', 'poolzone_test/firmware/PoolRadioTest', 'poolzone_test/build', SUPERMINI,
         ('zones/firmware/libraries',)),
        ('Pool central', 'zones/firmware/PoolCentral', 'zones/build/PoolCentral', C3, ('zones/firmware/libraries',)),
        # The TouchDesigner media bridge. Not a zone board (no PN532, no zcfg/zdb partitions),
        # so it is not a zone-flasher target and is built here instead. The board was rebuilt
        # with a different antenna and power supply; if it is not a plain ESP32-C3, this FQBN
        # is the only thing that needs changing.
        ('Preshow bridge', 'zones/firmware/PreshowBridge', 'zones/build/PreshowBridge', C3,
         ('zones/firmware/libraries',)),
        # Starts the cubes' main show (replaces the M5 Core2 show starter). Not a zone board either;
        # the Mainshow app (zones/mainshow) flashes this same build through zones/dbmanager/dongle.py.
        ('Mainshow controller', 'zones/firmware/MainshowController', 'zones/build/MainshowController', C3,
         ('zones/firmware/libraries', 'live files/libraries')),
        ('Registration console', 'registration_console', 'registration_console/build', C3, ()),
        ('Range test', 'rangetest/firmware/RangeTest', 'rangetest/build', XIAO, ('live files/libraries',)),
    ]:
        out = ROOT/output
        targets.append((name, out, lambda sketch=sketch, out=out, board=board, libraries=libraries:
                        compile_sketch(sketch, out, board, libraries)))

    failed = []
    for name, out, build in targets:
        print(f'\n=== {name} → {out.relative_to(ROOT)} ===', flush=True)
        if options.dry_run:
            continue
        try:
            build()
            print(f'PASS: {name}', flush=True)
        except Exception as exc:
            failed.append(name)
            print(f'FAIL: {name}: {exc}', file=sys.stderr, flush=True)
    if options.dry_run:
        print(f'\n{len(targets)} targets. Dry run; nothing compiled or uploaded.')
    elif failed:
        print('\nFailed targets: '+', '.join(failed), file=sys.stderr)
        return 1
    else:
        print(f'\nAll {len(targets)} firmware targets built successfully. No devices were uploaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
