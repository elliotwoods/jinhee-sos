"""Reproducible local Arduino build; only publish a manifest after success."""
import hashlib
import json
import shutil
from core import ROOT, WORKSPACE, VERSION, FQBN, SHOW_LIBRARY, digest, source_digest, atomic_json
import hostos

def build(run):
    cli = hostos.arduino_cli()
    if not cli: raise RuntimeError('Install Arduino IDE or arduino-cli and ESP32 core 3.3.11')
    source_hash = source_digest()
    out = ROOT/'build'; out.mkdir(exist_ok=True)
    run([cli,'compile','--fqbn',FQBN,*hostos.arduino_build_args(),'--libraries',str(WORKSPACE/'live files/libraries'),'--library',str(SHOW_LIBRARY),
         '--build-path',str(out/'cache'),'--output-dir',str(out),str(ROOT/'firmware/neocore_usb')], timeout=600)
    core = hostos.esp32_core('3.3.11')
    options = json.loads((out/'cache/build.options.json').read_text(encoding='utf-8'))
    if not all(hostos.same_folder(folder,core) for folder in options['hardwareFolders'].split(',')):
        raise RuntimeError('Build used an unexpected ESP32 core; select version 3.3.11')
    if source_hash != source_digest():
        raise RuntimeError('Source changed during build; rebuild before flashing')
    # Match the selected board's upload recipe; leave NVS (0x9000–0xdfff) untouched.
    shutil.copyfile(core/'tools/partitions/boot_app0.bin', out/'boot_app0.bin')
    segments=[]
    for offset,name in [(0,'neocore_usb.ino.bootloader.bin'),(0x8000,'neocore_usb.ino.partitions.bin'),
                        (0xe000,'boot_app0.bin'),(0x10000,'neocore_usb.ino.bin')]:
        segments.append(dict(offset=offset,file=name,sha256=digest(out/name),size=(out/name).stat().st_size))
    m=dict(version=VERSION,fqbn=FQBN,core='3.3.11',esptool='5.3.1',segments=segments,
           source_hash=source_hash)
    m['build_hash']=hashlib.sha256(json.dumps(segments,sort_keys=True).encode()).hexdigest()
    atomic_json(out/'manifest.json',m)
    return m

if __name__=='__main__':
    import subprocess
    def run(args, timeout): subprocess.run(args,check=True,timeout=timeout)
    print(json.dumps(build(run),indent=2))
