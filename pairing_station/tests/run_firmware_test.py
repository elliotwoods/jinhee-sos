#!/usr/bin/env python3
import pathlib
import re
import subprocess
import sys
import tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'scripts'))
import host_cxx
packet=lambda s: re.sub(r'\s+','',re.search(r'struct Packet\s*\{(.*?)\};',s,re.S)[1])
assert packet((ROOT/'firmware/pairing_station/pairing_station.ino').read_text(encoding='utf-8'))==packet((ROOT.parent/'ForKimchi.ino').read_text(encoding='utf-8'))
for source in ['neocore_cube/neocore_cube_1.3.ino', 'neocore_cube_OTA/neocore_cube_OTA.ino', 'neocore_cube_OTA_1.4/neocore_cube_OTA_1.4.ino']:
    assert packet((ROOT/'firmware/pairing_station/pairing_station.ino').read_text(encoding='utf-8')) == packet((ROOT.parent/'live files'/source).read_text(encoding='utf-8')), source
with tempfile.TemporaryDirectory(prefix='pairing-fw-tests-') as directory:
    directory=pathlib.Path(directory)
    for name in ['WiFi.h','esp_now.h','esp_wifi.h','Wire.h','Adafruit_PN532.h','freertos/FreeRTOS.h','freertos/queue.h']:
        path=directory/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('#include "firmware_stubs.h"\n',encoding='utf-8')
    binary=host_cxx.executable(directory/'test')
    subprocess.run([host_cxx.compiler(),'-std=c++17','-I'+str(directory),'-I'+str(ROOT/'tests'),'-I'+str(ROOT.parent/'zones/firmware/libraries/NctZone/src'),
                    '-I'+str(ROOT/'.arduino/libraries/ArduinoJson/src'),str(ROOT/'tests/firmware_test.cpp'),
                    '-o',binary],check=True)
    subprocess.run([binary],check=True)
