// Korean for every front-end literal wrapped in t()/hint(), keyed by the English text. One file per area so
// edits do not collide; web/tests/i18n.test.js checks every t() literal has an entry and no entry is unused.
// Terminology follows the handover v2 Korean (존, 큐브, 동글, 등록, 플래시, 게시, 확인 응답, 전달됨, 검증됨).
// Protocol and hardware tokens (SET_ZONE, NFC, ACK, MAC, UID, CRC, versions) are never translated.
import common from './ko/common.js';
import shell from './ko/shell.js';
import devices from './ko/devices.js';
import sections from './ko/sections.js';
import show from './ko/show.js';
import workstation from './ko/workstation.js';
import flash from './ko/flash.js';
import panels from './ko/panels.js';

export default { ...common, ...shell, ...devices, ...sections, ...show, ...workstation, ...flash, ...panels };
