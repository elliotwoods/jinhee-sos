"""Korean for the operator copy in uitext.py: the same keys, translatable fields only (tones and glyphs stay there).

The front end lays these over the English when the interface language is Korean (web/lib/i18n.js localCopy).
Protocol and hardware tokens (SET_ZONE, NFC, ACK, MAC, UID, CRC, versions) are never translated.
"""
LADDER = {'sent': '이 컴퓨터에서 전송함', 'delivered': '무선 전달 또는 기록됨 (애플리케이션 확인 응답 없음)',
          'acknowledged': '장치가 확인 응답함', 'verified': '다시 읽어 검증됨', 'failed': '실패'}

PANELS = {
    'flash': dict(title='큐브 플래시', what='켠 다음 큐브를 하나씩 USB에 꽂습니다. 각 큐브는 번들 펌웨어(이 큐브가 이미 이 빌드를 완료했으면 건너뜀)와 게시된 메인쇼를 받습니다. 큐브의 저장소(NVS)를 USB로 읽고, 오래되었거나 없거나 손상된 쇼는 다른 모든 값(번호, 태그, 보정)을 유지한 채 교체한 뒤 다시 읽어 확인하며, 재시작 후 큐브가 보고해야 합니다. USB 전용이며 무선으로는 아무것도 보내지 않습니다.',
                  check='펌웨어 건너뛰기는 이 MAC과 빌드에 대한 플래셔 자체 기록입니다. "Show written"은 세 가지로 검증됩니다: NVS 재읽기 일치, 쇼 이외에 바뀐 것 없음, 큐브의 "?" 응답이 NVS의 새 버전을 보고. 스위치는 콘솔을 시작할 때마다 꺼져 있습니다.'),
    'devices': dict(title='장치', what='USB에 연결된 장치와 무선으로 응답한 장치 전체를 역할별로 묶어 보여 줍니다.',
                    check='회색 무선 점은 이번 세션에 탐색 응답이 없었다는 뜻이며, 큐브가 꺼졌다는 뜻이 아닙니다.'),
    'cube.overview': dict(title='큐브', what='이 큐브의 번호, 태그, 등록 상태와 마지막으로 받은 표시 명령입니다.',
                          check='초록 등록 표시는 애플리케이션 ACK가 기록되었다는 뜻이며, 지금 큐브에 연결할 수 있다는 증거는 아닙니다.'),
    'cube.firmware': dict(title='펌웨어', what='이 큐브가 USB로 보고한 버전과 로컬 빌드를 비교합니다.',
                          check='버전 일치는 바이너리 해시 검증이 아닙니다. 응답이 없으면 최신이 아니라 미검증입니다.'),
    'register': dict(title='큐브 등록', what='큐브를 USB로 연결하면 식별되고, 번호가 없으면 32 초과의 가장 낮은 빈 번호를 받습니다(라벨에 새 번호를 적으세요). 등록 스테이션에서 NFC 태그를 기다리며 점멸하고, 큐브가 확인 응답하면 Sync 한 번으로 매핑을 업로드하고 존 데이터베이스를 게시합니다.',
                     check='등록됨은 큐브가 무선으로 확인 응답했다는 뜻입니다. 존은 게시된 데이터베이스를 받은 뒤에만 태그를 압니다. 자동 존 업데이트가 범위 내 존에 전달하며, 수동 방법은 Update all입니다.'),
    'station': dict(title='등록 스테이션', what='NFC 스테이션: 탐색, 등록, LED 테스트, 존 중계.',
                    check='NFC 준비와 무선 준비는 별개입니다. 등록에는 큐브의 애플리케이션 ACK가 필요합니다.'),
    'zone.monitor': dict(title='큐브 모니터', what='이 플레이트 위의 큐브와 플레이트가 보낸 명령입니다. 원형 표시는 마지막으로 명령한 색입니다.',
                         check='원형 표시와 실제 큐브를 비교하세요. "전달됨"은 무선 ACK이고, "확인 응답"은 큐브의 응답입니다.'),
    'zone.firmware': dict(title='펌웨어 및 데이터베이스', what='펌웨어 + 신원 + 데이터베이스를 플래시하거나 데이터베이스만 업데이트합니다.',
                          check='존은 더 새로운 데이터베이스 버전만 받습니다. 건너뛴 보드는 이미 최신입니다.'),
    'dongle': dict(title='ESP-NOW 동글', what='존 데이터베이스 업데이트와 상태 조회를 무선으로 중계합니다.',
                   check='Update all은 존이 범위 안에 있어야 합니다. 존은 새 버전과 CRC를 보고하여 확인합니다.'),
    'inventory': dict(title='인벤토리 및 데이터베이스', what='로컬 SQLite 인벤토리, 게시된 존 데이터베이스, 웹 동기화입니다.',
                      check='매핑은 Sync가 게시하고 존이 새 버전을 받은 뒤에만 존에 반영됩니다.'),
    'workstation': dict(title='Workstation', what='등록 프로토콜을 쓰는 모든 보드를 위한 하나의 패널: 등록 스테이션, ESP-NOW 동글, General Radio 또는 Workstation(NFC 리더, 등록 중계, 존 업데이트, 큐브 색상과 메인쇼, 풀 중앙을 통한 풀 램프, 브리지를 통한 TouchDesigner 큐). 보드의 hello가 보고하는 기능의 탭이 켜집니다.',
                        check='기존 스테이션은 태그 읽기와 중계만 하며 이전과 똑같이 둡니다. ALL 큐브 존 설정은 설치 전체의 색을 바꾸는 브로드캐스트입니다. 램프와 큐는 리스 방식이며 이 페이지가 유지를 멈추면 해제됩니다.'),
    'workstation.cubes': dict(title='큐브', what='큐브 하나(유니캐스트, 무선 확인)나 범위 내 모든 큐브(브로드캐스트, 확인 응답 없음)의 색을 바꾸고 메인쇼를 시작합니다. hello에 큐브 역할이 있을 때 표시됩니다.',
                              check='전달됨은 큐브의 무선이 응답했다는 뜻이며 색이 바뀌었다는 뜻이 아닙니다. 메인쇼 준비 상태인 큐브만 쇼를 시작합니다.'),
    'workstation.pool': dict(title='풀 램프', what='풀 중앙을 통해 풀 멤버 하나를 에뮬레이트된 슬라이더 라디오로 유지합니다(송신기당 슬롯 하나). hello에 풀 역할이 있을 때 표시됩니다.',
                             check='실제 풀 라디오도 함께 계속 동작합니다. 어느 라디오든 유지하는 동안 중앙이 해당 프레임을 켭니다.'),
    'workstation.preshow': dict(title='프리쇼 큐', what='다섯 번째 플레이트로서 미디어 브리지를 통해 TouchDesigner 큐를 올립니다. modern 모드에서는 끝까지 확인 응답됩니다. hello에 프리쇼 역할이 있을 때 표시됩니다.',
                                check='포인트 전환은 OFF 후 ON입니다. legacy 모드에서는 큐를 확인 응답할 수 없습니다.'),
    'pool.recording': dict(title='가이드 녹화', what='안내된 눈금마다 슬라이더를 옮기고 Reached this position을 누른 뒤 카운트다운 동안 고정합니다. 분석 결과가 필터 튜닝과 측정 제어점을 제안합니다.',
                           check='양 끝점은 항상 포함됩니다. 적용하면 측정 제어점이 교체되고 튜닝이 플래시에 저장될 수 있으니 이전 값을 먼저 기록하세요.'),
    'inventory.plan': dict(title='Sync가 옮길 내용', what='레코드별로 이 컴퓨터, 웹, 병합 후 결과를 보여 줍니다. 결정된 행은 양쪽 모두 바뀌어 최신 변경이 이긴 경우입니다.',
                           check='Check는 웹 비밀번호가 필요하며 아무것도 쓰지 않습니다. Sync는 여기서 진행 중인 작업이 없을 때만 다운로드를 적용합니다.'),
    'computer.intake': dict(title='USB 인테이크', what='지금부터 꽂는 보드를 자동 플래시합니다. 큐브는 번들 큐브 빌드를 받고, 식별된 존 보드는 그대로 업데이트되며, 과거 스케치는 선택한 존과 포인트를 받습니다.',
                            check='실행할 때마다 꺼진 상태로 시작합니다. 먼저 작업대에서 다른 ESP32 보드를 치우세요. USB 호환 보드라고 해서 역할이 증명되지는 않습니다. Stop after current는 진행 중인 쓰기를 마치게 합니다.'),
    'show': dict(title='쇼 제어', what='큐브를 메인쇼 준비 상태로 만들고 Mainshow controller로 메인쇼를 시작합니다.',
                 check='큐브는 아무것도 보고하지 않습니다. 시계는 큐브가 있어야 할 위치를 보여 줍니다.'),
    'pool.calibration': dict(title='풀 캘리브레이션', what='슬라이더 거리와 멤버 번호의 대응, 리스 방식 출력 강제 제어.',
                             check='콘솔이 핑을 멈추면 1.5초 후 강제 제어가 해제됩니다.'),
    'preshow.cue': dict(title='큐 테스트', what='리더 없이 이 플레이트를 통해 TouchDesigner 큐를 올립니다.',
                        check='legacy 모드에서는 큐를 확인 응답할 수 없습니다. 기존 브리지에서는 정상입니다.'),
    'rangetest': dict(title='범위 테스트', what='전시 공간과 뒷방 사이의 링크 품질.',
                      check='디스크에 아무것도 기록하지 않습니다.'),
    'pooltest': dict(title='풀 조명 테스트', what='풀 라디오 6개를 모두 에뮬레이트하여 조명을 점검합니다.',
                     check='먼저 실제 풀 라디오의 전원을 끄세요. 이 브리지는 그 ID 1-6을 사용합니다.'),
    'inventory.zonedb': dict(title='존 데이터베이스', what='게시된 큐브 데이터베이스(웹 할당 버전)와 각 존이 마지막으로 보고한 보유 버전.',
                             check='버전은 증가만 합니다. 이 컴퓨터보다 "앞선" 존은 다른 컴퓨터가 게시했다는 뜻입니다. 받아온 뒤 다시 게시하세요.'),
    'inventory.websync': dict(title='웹 동기화', what='로컬 인벤토리 변경을 업로드하고, 웹 변경을 다운로드하며, 존 데이터베이스를 게시하거나 받아옵니다.',
                              check='Sync는 결정을 묻지 않습니다. 최신 변경이 이기고 감사 기록됩니다. 하드웨어 작업 중에는 다운로드가 대기합니다.'),
    'bench': dict(title='벤치 도구', what='특정 보드가 USB에 있어야 하는 진단 도구입니다. 보드 신원이 안전을 보장합니다.',
                  check='조명·큐 테스트는 실제 출력에 영향을 줍니다. 끝나면 강제 제어를 끄세요.'),
    'settings': dict(title='설정', what='이 콘솔의 모양과 동작. 여기서는 하드웨어가 바뀌지 않습니다.',
                     check='테마는 브라우저별이고, 동작과 자동 업데이트 설정은 이 컴퓨터에 저장됩니다.'),
}

STATUS = {
    'registration.acknowledged': dict(label='등록됨 · ACK', tip='일치하는 애플리케이션 ACK가 도착했습니다. 플래시 저장이나 LED 출력을 증명하지는 않습니다.'),
    'registration.unconfirmed': dict(label='미확인', tip='결과가 불확실합니다. 같은 ID/UID로 재시도해도 안전합니다.'),
    'registration.pending': dict(label='등록 중', tip='큐브의 확인 응답을 기다리는 중입니다.'),
    'registration.not_transmitted': dict(label='저장됨 · 미전송', tip='이 컴퓨터가 아직 전송하지 않은 신뢰된 매핑입니다.'),
    'registration.awaiting_tag': dict(label='NFC 태그 필요', tip='번호가 있으며 스테이션에서 태그 스캔을 기다립니다.'),
    'registration.needs_number': dict(label='번호 필요', tip='번호가 없으면 장치가 존 데이터베이스에서 빠집니다.'),
    'registration.discovered': dict(label='미등록', tip='탐색에 응답했지만 저장된 정보가 없습니다.'),
    'delivery.delivered': dict(label='전달됨', tip='무선 확인만 받았습니다. 전달됨 ≠ 애플리케이션 확인 응답.'),
    'delivery.acknowledged': dict(label='확인 응답', tip='장치가 응답했습니다.'),
    'delivery.verified': dict(label='검증됨', tip='독립적으로 다시 읽었습니다.'),
    'delivery.unconfirmed': dict(label='무선 ACK 없음', tip='무선이 전달을 확인하지 않았습니다. 큐브가 꺼졌거나, 범위 밖이거나, 다른 채널일 수 있습니다.'),
    'firmware.current': dict(label='버전 일치', tip='보고된 버전이 로컬 빌드와 같습니다. 바이너리 해시 확인은 아닙니다.'),
    'firmware.different': dict(label='업데이트 필요', tip='보고된 버전이 로컬 빌드와 다릅니다.'),
    'firmware.unknown': dict(label='미검증', tip='"?"에 대한 일치 응답이 없습니다. 미검증은 최신과 같지 않습니다.'),
    'radio.recent': dict(label='응답 있음', tip='최근 10초 이내 탐색 응답이 있었습니다.'),
    'radio.stale': dict(label='응답 없음', tip='이번 세션에 탐색 응답이 없습니다. 회색 점이 큐브가 꺼졌다는 뜻은 아닙니다.'),
    'zonedb.current': dict(label='최신', tip='버전과 CRC가 게시된 데이터베이스와 일치합니다.'),
    'zonedb.behind': dict(label='구버전', tip='이전 버전입니다. USB 또는 무선으로 업데이트하세요.'),
    'zonedb.ahead': dict(label='더 새로움 / 다름', tip='버전이 더 높거나 같지만 내용이 다릅니다. 새로 게시해야만 해결됩니다.'),
    'zonedb.updating': dict(label='업데이트 중', tip='청크 준비 중입니다. 존은 60초 후 불완전한 업데이트를 폐기합니다.'),
    'zonedb.unpublished': dict(label='게시본 없음', tip='먼저 존 데이터베이스를 게시하세요(Sync).'),
    'nfc.ok': dict(label='NFC 스캔 중', tip='리더가 응답하고 폴링합니다.'),
    'nfc.warn': dict(label='NFC 저하', tip='리더는 응답하지만 스캔 명령이 I²C에서 실패합니다.'),
    'nfc.bad': dict(label='NFC 응답 없음', tip='PN532가 응답하지 않습니다. 플레이트의 무선은 계속 동작합니다.'),
    'usb.present': dict(label='USB', tip='인식되었으나 아직 식별되지 않았습니다.'),
    'usb.probing': dict(label='식별 중…', tip='보드에 정체를 묻는 중입니다(리셋 없음).'),
    'usb.session': dict(label='연결됨', tip='콘솔이 이 포트를 점유하고 있습니다.'),
    'usb.job': dict(label='작업 중', tip='작업이 이 포트를 사용 중입니다.'),
    'usb.foreign': dict(label='다른 앱이 점유', tip='다른 애플리케이션이 이 포트를 점유하고 있습니다.'),
    'usb.protected': dict(label='보호됨', tip='설치된 등록 스테이션의 신원입니다. 조회하거나 플래시하지 않습니다.'),
    'usb.idle': dict(label='식별됨', tip='식별되었으며 열린 세션이 없습니다.'),
    'sync.ok': dict(label='동기화됨', tip='웹과 최신 상태입니다.'),
    'sync.pending': dict(label='동기화 대기', tip='업로드하거나 다운로드할 변경이 있습니다.'),
    'sync.offline': dict(label='오프라인', tip='웹에 연결할 수 없어 로컬로 작업합니다.'),
    'sync.error': dict(label='동기화 문제', tip='웹이 응답하지 못했습니다.'),
}

_STATION = 'USB로 연결된 등록 스테이션.'
_RADIO = '쇼 프레임을 중계하는 연결된 Workstation(또는 General Radio).'
ACTIONS = {
    'flash.enable': dict(label='꽂는 대로 큐브 플래시', what='USB에 있는 모든 큐브(이미 꽂혀 있거나 나중에 꽂는 큐브)가 꽂을 때마다 한 번씩 USB로 펌웨어와 게시된 쇼를 받습니다.',
                         hazard='켜져 있는 동안 꽂는 모든 큐브의 펌웨어와 NVS에 씁니다.'),
    'flash.retry': dict(label='재시도 (펌웨어 다시 쓰기)', what='실패한 큐브를 다시 플래시합니다. 펌웨어가 최신이어도 다시 쓰고(Tk 플래셔의 Manual Retry), 이어서 쇼를 씁니다.',
                        hazard='앱 파티션에 쓰고 NVS의 쇼를 다시 쓸 수 있습니다.'),
    'cube.update_show': dict(label='USB로 쇼 업데이트', what='게시된 메인쇼를 USB로 이 큐브의 저장소(NVS)에 쓰고 다른 모든 값은 유지합니다. 다시 읽어 확인하고 큐브가 보고하는지 점검합니다. 펌웨어는 건드리지 않습니다.',
                             hazard='큐브의 NVS 파티션을 다시 쓰고 큐브를 재시작합니다. 이전 내용은 실행 폴더에 보관됩니다.',
                             needs='펌웨어 v1.5.0 이상으로 USB 식별된 큐브와 게시된 쇼.', disabled='이 보드에서 작업이 실행 중입니다.'),
    # --- zones: USB
    'zone.update_db_usb': dict(label='USB로 데이터베이스 업데이트', what='게시된 큐브 데이터베이스만 이 존 보드의 데이터베이스 슬롯에 씁니다. 펌웨어와 신원은 그대로입니다.',
                               hazard='플래시에 쓰고 보드를 재부팅합니다. 몇 초 동안 존이 동작하지 않습니다.',
                               needs='보드보다 새로운 게시 존 데이터베이스.', disabled='보드가 이미 게시된 데이터베이스를 가지고 있거나, 받을 게시본이 없거나, 작업이 진행 중입니다.'),
    'zone.flash': dict(label='펌웨어 + 신원 + 데이터베이스 플래시', what='필요하면 빌드한 뒤 존 펌웨어, 신원(종류, 포인트, 이름), 게시된 데이터베이스를 쓰고 부팅을 검증합니다.',
                       hazard='플래시에 쓰고 보드를 재부팅합니다. 존과 포인트를 신중히 선택하세요. 이 플레이트가 쇼에서 할 일이 정해집니다.',
                       needs='식별된 존 보드와 최신 존 빌드.', disabled='작업이 진행 중이거나, 빌드가 실패했거나, 인벤토리가 이 보드를 거부했습니다(강제 플래시 참고).'),
    'zone.flash_force': dict(label='강제 플래시 (덮어쓰기)', what='인벤토리에 큐브나 제외 장치(리더, 스테이션, 동글)로 기록된 보드를 플래시합니다.',
                             hazard='보드의 기존 용도를 덮어씁니다. 큐브는 LED 펌웨어를 잃고 등록이 해제됩니다. 길게 눌러 확인하세요.'),
    'zone.detect': dict(label='부트로더로 식별', what='ROM 부트로더로 보드의 플래시를 읽어 어떤 펌웨어와 신원을 가졌는지 확인합니다.',
                        hazard='보드를 부트로더로 리셋하고 끝나면 재부팅합니다.', needs='일반 조회에 응답하지 않은 USB 보드.'),
    'zone.check_report': dict(label='존 보고 읽기', what='시리얼 포트를 열고 존에 보고(?)를 요청합니다: 버전, 신원, 데이터베이스, 리더 상태.',
                              hazard='포트를 열면 일부 보드가 리셋될 수 있습니다.'),
    'zone.rxgain_usb': dict(label='RX gain 적용', what='PN532 리더 게인을 존에 저장하고 즉시 적용합니다.',
                            hazard='이 플레이트에서 태그를 읽는 거리가 바뀝니다. 보드에 저장됩니다.'),
    'zone.nfc_recover': dict(label='NFC 리더 복구', what='I²C 버스를 정리하고 존의 PN532를 다시 초기화합니다.',
                             hazard='리더가 잠시 오프라인이 됩니다. 플레이트 위의 태그를 다시 읽습니다.'),
    # --- zones: over the air
    'zones.update': dict(label='무선으로 데이터베이스 업데이트', what='게시된 데이터베이스를 이 존 하나에 보냅니다: 유니캐스트 안내 후, 새 버전과 CRC를 보고할 때까지 브로드캐스트 청크.',
                         hazard='전송 중 존이 데이터베이스 슬롯을 다시 씁니다. 동글을 범위 안에 두세요.', needs=_RADIO + ' 존이 구버전이어야 합니다.',
                         disabled='존이 이미 최신이거나 연결된 무선이 없습니다.'),
    'zones.update_all': dict(label='구버전 존 모두 업데이트', what='브로드캐스트 한 번으로 범위 내 모든 구버전 존을 게시된 데이터베이스로 올립니다.',
                             hazard='범위 내 모든 구버전 존이 데이터베이스를 다시 씁니다. 존은 버전 + CRC로 확인합니다.', needs=_RADIO,
                             disabled='연결된 무선이 없거나 구버전 존이 없습니다.'),
    'zones.reboot': dict(label='재부팅', what='이 존에 무선으로 ZONE_REBOOT를 보냅니다.', hazard='존이 재시작하며 몇 초 동안 태그를 놓칩니다.', needs=_RADIO),
    'zones.set_rx_gain': dict(label='RX gain 설정', what='새 리더 게인과 함께 ZONE_SET_CONFIG를 보냅니다.',
                              hazard='플레이트의 인식 거리가 바뀝니다. 존의 다음 설정 보고로만 확인됩니다.', needs=_RADIO),
    # --- cubes / pairing
    'cube.flash_firmware': dict(label='큐브 펌웨어 플래시', what='번들 큐브 펌웨어를 쓰고 검증한 뒤 부팅 메시지를 확인하고, 저장소의 쇼를 게시된 쇼로 맞춥니다.',
                                hazard='앱 파티션에 쓰고 큐브를 재부팅합니다. NVS(번호와 태그 등록)는 보존되며, 그 안의 쇼만 더 오래된 경우 교체됩니다.',
                                needs='USB에 연결된 큐브와 최신 큐브 빌드.', disabled='이 보드에서 작업이 진행 중입니다.'),
    'dongle.flash_force': dict(label='Workstation / 컨트롤러 펌웨어 강제 쓰기', what='인벤토리가 보호하는 보드(존, 큐브, 컨트롤러 또는 스테이션)에 Workstation 또는 Mainshow controller 펌웨어를 씁니다.',
                               hazard='보드의 기존 역할을 덮어씁니다: 존은 쇼에서 빠지고, 큐브는 LED 펌웨어를 잃습니다. 처음에는 전체 백업을 만듭니다. 길게 눌러 확인하세요.'),
    'dongle.flash': dict(label='Workstation / 컨트롤러 펌웨어 쓰기', what='여분의 ESP32-C3를 Workstation 또는 Mainshow controller로 만듭니다.',
                         hazard='보드의 기존 펌웨어를 교체합니다. 처음에는 전체 백업을 만듭니다.', needs='사용 중인 큐브가 아닌 여분 보드가 USB에 연결되어 있어야 합니다.'),
    'pairing.register': dict(label='등록 (태그 스캔)', what='이 큐브를 빨강/파랑으로 점멸시키고 스테이션에서 새 NFC 스캔을 기다린 뒤 번호와 태그를 보냅니다.',
                             hazard='다른 장치의 태그를 스캔하면 이 큐브로 이전됩니다.', needs='스테이션이 연결되고 NFC 리더가 준비되어야 합니다.',
                             disabled='스테이션이 연결되지 않았거나, 리더가 준비되지 않았거나, 다른 작업이 진행 중입니다.'),
    'register.restart': dict(label='처음부터 다시', what='USB로 연결된 큐브의 등록 절차를 다시 실행합니다: 번호, NFC 스캔, 동기화.',
                             hazard='큐브가 빨강/파랑으로 점멸하며 새 스캔을 기다립니다. 다른 장치의 태그를 스캔하면 이 큐브로 이전됩니다.', needs=_STATION),
    'register.retry': dict(label='재시도', what='실패한 단계를 재시도합니다: 스테이션이 이 큐브에서 일시 정지했다면 저장된 등록을 다시 보내고, 아니면 새 스캔을 위해 점멸시키거나 다시 동기화합니다.',
                           hazard='큐브가 매핑을 NVS에 저장합니다. 대기 중인 태그는 ACK로만 확정됩니다.', needs=_STATION),
    'pairing.transmit': dict(label='저장된 매핑 보내기', what='새 스캔 없이 이 큐브에 저장된 번호와 태그를 보냅니다.',
                             hazard='큐브가 매핑을 NVS에 저장합니다. 대기 중인 태그는 ACK로만 확정됩니다.', needs=_STATION),
    'pairing.transmit_originals': dict(label='원본 32개 전송', what='원본 32개 매핑을 각 큐브에 보냅니다.',
                                       hazard='범위 내 모든 원본 큐브의 번호/태그를 다시 씁니다. 변경된 원본은 거부됩니다.', needs=_STATION),
    'pairing.retry_unconfirmed': dict(label='미확인 재시도', what='아직 애플리케이션 ACK가 없는 저장된 등록을 모두 다시 전송합니다.',
                                      hazard='여러 큐브에 차례로 보냅니다.', needs=_STATION),
    'pairing.start_pair': dict(label='새 큐브 등록 (자동)', what='미등록 큐브를 탐색하고 차례로 점멸시키며 태그 스캔을 기다립니다.',
                               hazard='번호를 자동 할당합니다(32 초과의 가장 낮은 빈 번호, 2, 22, 39, 43 제외).', needs='스테이션 연결, NFC 리더 준비, 다른 작업 없음.'),
    'pairing.retry': dict(label='일시 정지 재시도', what='같은 큐브의 일시 정지된 등록을 이어서 진행합니다.', hazard='큐브가 다시 점멸하며 스캔을 기다립니다.', needs=_STATION),
    'station.nfc_recover': dict(label='NFC 리더 복구', what='등록 스테이션의 I²C 버스 정리 및 PN532 재초기화.',
                                hazard='리더가 잠시 오프라인이 됩니다. 작업 진행 중에는 거부됩니다.', needs=_STATION),
    'inventory.unregister': dict(label='등록 해제', what='로컬 인벤토리에서 이 장치의 번호와 태그를 해제합니다.',
                                 hazard='큐브 펌웨어는 다시 등록될 때까지 이전 매핑을 유지합니다. 길게 눌러 확인하세요.'),
    # --- show
    'mainshow.ready': dict(label='① 메인쇼 준비', what='이 큐브에 SET_ZONE 4: 네온으로 바뀌고 메인쇼 대상이 됩니다.',
                           hazard='큐브 색이 즉시 바뀝니다.', needs='Mainshow controller 또는 Workstation 연결.'),
    'mainshow.trigger': dict(label='② 메인쇼 시작', what='이 큐브에 새 showId를 다섯 번 보냅니다.',
                             hazard='큐브에서 쇼가 시작됩니다. 메인쇼 준비 상태인 큐브만 시작합니다.', needs='Mainshow controller 또는 Workstation 연결.'),
    'mainshow.idle': dict(label='정지 → 대기', what='SET_ZONE 0: 이 큐브의 쇼를 끝내고 대기 흰색으로 되돌립니다.', hazard='이 큐브에서 진행 중인 쇼를 중단합니다.'),
    'mainshow.trigger_all': dict(label='준비된 모든 큐브에서 메인쇼 시작', what='범위 내 메인쇼 준비 상태인 모든 큐브에 새 showId를 브로드캐스트합니다.',
                                 hazard='브로드캐스트이며 확인 응답이 없고 되돌릴 수 없습니다. 길게 눌러 확인하세요.'),
    'mainshow.led_test': dict(label='LED 테스트', what='컨트롤러 자체 LED를 켜거나 끕니다.', hazard='컨트롤러에서만 보입니다.'),
    'show.query': dict(label='큐브 조회', what='SHOW_QUERY 브로드캐스트: 범위 내 v1.5.0 이상의 모든 큐브가 2초 안에 보유한 쇼를 보고합니다.', hazard='무선 통신만 발생하며 큐브에는 아무 변화가 없습니다.', needs=_RADIO),
    'show.update': dict(label='업데이트', what='게시된 쇼를 이 큐브 하나에 보냅니다.', hazard='큐브가 새 쇼를 저장합니다. 큐브는 이전 버전으로 돌아가지 않습니다.', needs=_RADIO),
    'show.update_selected': dict(label='선택 항목 업데이트', what='체크한 큐브가 확인할 때까지 게시된 쇼를 보냅니다.',
                                 hazard='브로드캐스트입니다. 범위 내 이전 쇼를 가진 모든 큐브도 저장합니다(모든 큐브가 같은 쇼를 받음).',
                                 needs=_RADIO + ' 게시된 쇼.'),
    'show.update_all': dict(label='모두 업데이트', what='최근 응답한 모든 큐브가 확인할 때까지 게시된 쇼를 브로드캐스트합니다.',
                            hazard='범위 내 모든 큐브가 새 쇼를 저장합니다. 쇼 재생 중인 큐브는 쇼가 끝날 때 반영합니다.', needs=_RADIO + ' 게시된 쇼.'),
    'show.auto_update': dict(label='자동 업데이트', what='이동 점검 모드: 범위 내 이전 쇼를 가진 큐브를 자동으로 업데이트합니다.',
                             hazard='켜져 있는 동안 계속 전송합니다. 끝나면 끄세요.', needs=_RADIO),
    'show.push_config': dict(label='컨트롤러에 길이 보내기', what='Mainshow controller(mainshow-1.3.0 이상)에 게시된 쇼의 길이를 알려 타임코드 범위를 정합니다.',
                             hazard='컨트롤러가 쇼를 실행하는 시간이 바뀝니다.'),
    'show.revert': dict(label='되돌리기', what='편집기의 작업본을 게시된 쇼 또는 내장 기본 쇼로 바꿉니다.',
                        hazard='이 컴퓨터의 저장되지 않은 편집 내용이 사라집니다. 길게 눌러 확인하세요.'),
    'show.live': dict(label='실제 큐브에 미러링', what='켜져 있는 동안 미리보기 중인 각 큐브 번호의 재생 위치 색을 브로드캐스트하여(SHOW_LIVE, 초당 약 16회) 작업대 큐브가 편집기를 따라가게 합니다.',
                      hazard='번호가 미리보기 중인 범위 내 모든 큐브의 색이 바뀝니다. 각 색은 마지막 전송 0.6초 후 해제됩니다. 쇼 재생 중인 큐브는 무시합니다.',
                      needs='Workstation(또는 General Radio general-radio-1.2.0)과 펌웨어 v1.7.0-USB.1 큐브.'),
    'show.publish': dict(label='게시', what='작업본을 다음 쇼 버전으로 웹에 게시합니다.', hazard='업데이트하기 전까지 큐브는 바뀌지 않습니다.'),
    # --- general radio
    'radio.set_zone': dict(label='존 설정', what='Workstation으로 선택한 큐브에 유니캐스트 SET_ZONE ×3.',
                           hazard='큐브 색이 바뀝니다. 무선 ACK는 색이 바뀌었다는 증거가 아닙니다.', needs='Workstation 연결과 큐브 선택.'),
    'radio.set_zone_all': dict(label='ALL 큐브에 존 설정', what='수신하는 모든 큐브에 SET_ZONE 브로드캐스트.',
                               hazard='범위 내 설치 전체의 색이 바뀌며 확인 응답이 없습니다. 길게 눌러 확인하세요.'),
    'radio.show_start': dict(label='이 큐브에서 쇼 시작', what='선택한 큐브에 새 showId로 MSG_SHOW_START ×5.',
                             hazard='쇼가 시작됩니다. 메인쇼 준비 상태인 큐브만 시작합니다.', needs='Workstation 연결과 큐브 선택.'),
    'radio.show_start_all': dict(label='준비된 ALL 큐브에서 쇼 시작', what='범위 내 메인쇼 준비 상태인 모든 큐브에 MSG_SHOW_START 브로드캐스트.',
                                 hazard='브로드캐스트이며 확인 응답이 없고 되돌릴 수 없습니다. 길게 눌러 확인하세요.'),
    'radio.reader_flash': dict(label='태그를 읽으면 큐브 점멸', what='이 보드의 리더에 태그를 올릴 때마다 그 태그의 주인 큐브가 무선으로 2초간 파랑/빨강으로 점멸하여, 태그·인벤토리·무선이 모두 일치하는지 볼 수 있습니다.',
                               hazard='큐브에서 보이며 끝나면 대기 상태로 돌아갑니다. 보드가 유휴 상태일 때만 동작하며 페어링이나 등록 중에는 하지 않습니다.',
                               needs='NFC 리더가 동작하는 Workstation(또는 등록 스테이션).'),
    'radio.identify': dict(label='식별', what='선택한 큐브를 파랑/빨강으로 깜박여 찾을 수 있게 합니다.', hazard='큐브에서 보이며 끝나면 대기 상태로 돌아갑니다.', needs='Workstation 연결과 큐브 선택.'),
    'radio.transmit': dict(label='저장된 매핑 보내기', what='저장된 번호와 태그를 무선으로 선택한 큐브에 등록합니다(세 번 시도 후 큐브의 확인 응답).',
                           hazard='큐브가 매핑을 NVS에 저장합니다.', needs='Workstation 연결, 큐브에 저장된 태그가 있어야 합니다.'),
    'radio.pool': dict(label='풀 램프 유지', what='에뮬레이트된 슬라이더 라디오로 풀 중앙을 통해 풀 멤버 하나를 유지합니다.',
                       hazard='유지하는 동안 실제 풀 램프가 켜집니다. 이 페이지가 유지를 멈추면 해제됩니다.', needs='Workstation 연결, 풀 중앙이 범위 안에 있어야 합니다.'),
    'radio.preshow': dict(label='프리쇼 큐 올리기', what='미디어 브리지를 통해 프리쇼 포인트의 TouchDesigner 큐를 올립니다.',
                          hazard='현장 미디어가 작동합니다. 이 페이지가 유지하는 동안만 유지됩니다.', needs='Workstation 연결, 프리쇼 브리지가 범위 안에 있어야 합니다.'),
    'radio.led_test': dict(label='LED 테스트', what='보드의 WS2812 LED 8개를 순환 점등합니다.', hazard='동글에서만 보입니다.'),
    # --- pool / preshow plates, bench tools
    'pool.arm': dict(label='큐브 없이 출력 강제 제어', what='플레이트에 큐브가 없어도 슬라이더로 풀 조명을 제어합니다(보드의 리스 방식 호스트 강제 제어).',
                     hazard='실제 풀 램프가 켜집니다. 리스 방식: 콘솔이 0.35초마다 핑하며, 멈추면 1.5초 후 리스가 해제됩니다.', needs='USB에 연결되어 준비된 풀 라디오.'),
    'pool.cal_save': dict(label='적용 및 플래시 저장', what='캘리브레이션 제어점을 라디오의 플래시에 씁니다.', hazard='저장된 캘리브레이션을 교체합니다. 이전 값을 먼저 기록하세요.'),
    'pool.assign_radio_id': dict(label='라디오 ID 지정', what='이 풀 라디오에 새 라디오 ID(1-6)를 저장합니다.', hazard='같은 ID의 라디오 두 개는 같은 풀 슬롯을 두고 충돌합니다.'),
    'pool.flash_firmware': dict(label='풀 펌웨어 플래시', what='현재 PoolZone 펌웨어를 이 라디오에 씁니다.', hazard='플래시에 쓰고 재부팅합니다. 풀 라디오와 풀 중앙은 호환 세트입니다.'),
    'pool.record_start': dict(label='가이드 녹화 시작', what='페이지가 각 위치를 안내하는 동안 라디오가 원시 슬라이더 샘플을 스트리밍합니다.', hazard='녹화 중에는 플레이트가 평소처럼 조명을 제어하지 않습니다.'),
    'pool.record_apply': dict(label='녹화 적용', what='녹화의 권장 튜닝과, 선택 시 측정 제어점을 적용합니다.', hazard='튜닝과 제어점이 플래시에 저장될 수 있습니다.'),
    'preshow.arm': dict(label='큐 강제 제어', what='플레이트의 리스 방식 호스트 강제 제어를 시작하여 리더 없이 POINT 버튼으로 큐를 올릴 수 있게 합니다.',
                        hazard='1.5초 리스: 켜져 있는 동안 콘솔이 유지합니다. 끝나면 끄세요.', needs='USB에 연결된 프리쇼 플레이트.'),
    'preshow.cue': dict(label='큐', what='이 플레이트를 통해 TouchDesigner 큐를 올리거나 내립니다.', hazard='현장 미디어가 작동합니다.', needs='큐 강제 제어가 켜져 있어야 합니다.', disabled='먼저 큐 강제 제어를 켜세요.'),
    'bridge.test': dict(label='큐 테스트', what='브리지에서 TouchDesigner로 PRESHOW,n,ON|OFF를 직접 씁니다.', hazard='현장 미디어가 작동합니다.'),
    'central.recover': dict(label='I²C 복구', what='풀 중앙의 PCA9685 보드 두 개를 다시 초기화합니다.', hazard='풀 출력이 잠시 꺼졌다 다시 켜집니다.'),
    'pooltest.toggle': dict(label='멤버 전환', what='에뮬레이트된 라디오로 풀 멤버 하나를 켜거나 끕니다.', hazard='실제 풀 램프가 켜집니다.'),
    'pooltest.sequential': dict(label='순차 테스트', what='풀 멤버를 하나씩 차례로 켭니다.', hazard='실제 풀 램프가 켜집니다. 먼저 실제 풀 라디오의 전원을 끄세요.'),
    'pooltest.channel': dict(label='채널 적용', what='테스트 브리지의 ESP-NOW 채널을 바꿉니다.', hazard='조명이 하나라도 켜져 있으면 거부됩니다. 설치는 채널 2를 사용합니다.'),
    'monitor.zone': dict(label='존 설정', what='이 플레이트 위의 큐브에 SET_ZONE을 보냅니다.', hazard='큐브 색이 바뀝니다.'),
    'monitor.clear': dict(label='해제', what='이 플레이트 위의 큐브에 SET_ZONE 0을 보냅니다.', hazard='큐브가 대기 흰색으로 돌아갑니다.'),
    'usb.auto_cubes': dict(label='큐브 자동 플래시', what='지금부터 꽂는 모든 큐브가 차례로 번들 큐브 펌웨어와 게시된 쇼를 받습니다 (플래시 페이지의 스위치).',
                           hazard='꽂는 모든 큐브의 플래시에 씁니다. 먼저 작업대에서 다른 ESP32 보드를 치우세요. 실행할 때마다 꺼진 상태로 시작합니다.'),
    'usb.auto_zones': dict(label='존 자동 플래시', what='지금부터 꽂는 모든 존 보드가 그대로 업데이트되며, 과거 스케치는 선택한 존과 포인트를 받습니다.',
                           hazard='꽂는 모든 존 보드의 플래시에 씁니다. 실행할 때마다 꺼진 상태로 시작합니다.'),
    # --- safe but worth explaining
    'device.probe': dict(label='다시 조회', what='리셋 없이 보드에 정체를 다시 묻습니다.'),
    'sync.run': dict(label='Sync', what='로컬 인벤토리 변경을 업로드하고, 웹 변경을 다운로드하며, 존 데이터베이스를 게시하거나 받아옵니다.', hazard='최신 변경이 이깁니다. 결정은 감사 기록되고 보고됩니다.'),
    'zone.publish': dict(label='존 데이터베이스 게시', what='로컬 큐브 매핑을 다음 웹 할당 존 데이터베이스 버전으로 게시합니다.', hazard='존은 업데이트(USB 또는 무선)된 뒤에만 반영합니다.'),
}

GLOSSARY = {
    'pending_uid': '제안된 태그로 재시도할 수 있으며, 확정 태그가 아닙니다.',
    'uid': '확정된 NFC 태그.',
    'excluded': '리더, 스테이션 또는 동글: 절대 큐브가 아닙니다.',
    'reserved numbers': '2, 22, 39, 43은 자동으로 할당되지 않습니다.',
}


def as_dict():
    return dict(ladder=LADDER, panels=PANELS, status=STATUS, actions=ACTIONS, glossary=GLOSSARY)


# The English each Korean text was translated from, as a short hash per field, in uitext_ko_sources.json.
# tests/test_uitext.py fails when uitext.py rewords an English text whose Korean has not been revisited.
# After updating the Korean:  pairing_station/.venv/bin/python console/uitext_ko.py --stamp
SOURCES_FILE = __import__('pathlib').Path(__file__).with_name('uitext_ko_sources.json')


def english_digests():
    import hashlib
    import uitext
    out = {}
    for group in ('PANELS', 'STATUS', 'ACTIONS'):
        for key, entry in getattr(uitext, group).items():
            for field, text in entry.items():
                if field != 'tone':
                    out[f'{group.lower()}.{key}.{field}'] = hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]
    for group in ('LADDER', 'GLOSSARY'):
        for key, text in getattr(uitext, group).items():
            out[f'{group.lower()}.{key}'] = hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]
    return out


def stale():
    """Fields whose English changed (or appeared) since the Korean was last stamped."""
    import json
    try:
        stamped = json.loads(SOURCES_FILE.read_text(encoding='utf-8'))
    except FileNotFoundError:
        stamped = {}
    return sorted(k for k, v in english_digests().items() if stamped.get(k) != v)


if __name__ == '__main__':
    import json
    import sys
    sys.path.insert(0, str(SOURCES_FILE.parent))
    if sys.argv[1:] == ['--stamp']:
        SOURCES_FILE.write_text(json.dumps(english_digests(), indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
        print(f'stamped {SOURCES_FILE.name}')
    else:
        print('\n'.join(stale()) or 'every Korean text is current')
