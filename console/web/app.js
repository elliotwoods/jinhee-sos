import { html, render } from './lib/html.js';
import { useState, useEffect } from 'preact/hooks';
import { api, ready } from './api.js';
import { state, applyPull, touch, section } from './store.js';
import { install as installRouter, navigate } from './router.js';
import { installDocHighlights } from './lib/dochl.js';
import { useSections, useUI } from './lib/hooks.js';
import { onNotify, notify } from './lib/notify.js';
import { Toasts } from './components/basics.js';
import { TopBar } from './components/TopBar.js';
import { Rail } from './components/Rail.js';
import { Attention, Jobs } from './components/Attention.js';
import { Timeline } from './components/Timeline.js';
import { StatusBar } from './components/StatusBar.js';
import { applyTheme, storedTheme } from './lib/theme.js';
import { findDevice } from './panels/common.js';
import { CubePanel } from './panels/CubePanel.js';
import { PairingStationPanel } from './panels/PairingStationPanel.js';
import { ZonePanel } from './panels/ZonePanel.js';
import { GeneralRadioPanel } from './panels/GeneralRadioPanel.js';
import { MainshowPanel, PoolCentralPanel, PoolTestBridgePanel, PreshowBridgePanel, RangeTestPanel, UnknownBoardPanel, ThisComputerPanel } from './panels/others.js';
import { InventorySection } from './panels/InventorySection.js';
import { ShowSection } from './panels/ShowSection.js';
import { ShowEditorSection } from './panels/ShowEditor.js';
import { RegisterSection, RegisterNotices } from './panels/RegisterSection.js';
import { BenchSection, SettingsSection, RadioCubePanel, RadioZonePanel } from './panels/sections.js';
import { run } from './api.js';

const PANELS = { cube: CubePanel, station: PairingStationPanel, generalradio: GeneralRadioPanel, zone: ZonePanel, mainshow: MainshowPanel, poolcentral: PoolCentralPanel,
  pooltest: PoolTestBridgePanel, preshowbridge: PreshowBridgePanel, rangetest: RangeTestPanel };

function Main() {
  useSections(['ui', 'devices']);
  const ui = useUI();
  const r = ui.route;
  if (r.section === 'register') return html`<${RegisterSection} />`;
  if (r.section === 'inventory') return html`<${InventorySection} />`;
  if (r.section === 'show') return html`<${ShowSection} />`;
  if (r.section === 'showedit') return html`<${ShowEditorSection} />`;
  if (r.section === 'bench') return html`<${BenchSection} />`;
  if (r.section === 'settings') return html`<${SettingsSection} />`;
  if (!r.device || r.device === 'computer') return html`<${ThisComputerPanel} />`;
  if (r.device.startsWith('cube:')) return html`<${RadioCubePanel} mac=${r.device.slice(5)} />`;
  if (r.device.startsWith('zone:')) return html`<${RadioZonePanel} mac=${r.device.slice(5)} />`;
  const device = findDevice(r.device);
  if (!device) return html`<div><h1 class="title">Not attached</h1><div class="subtitle">${r.device} is not on USB right now. <a href="#/devices">Back to devices</a></div></div>`;
  const Panel = (device.state === 'present' || device.state === 'probing') && !device.role ? UnknownBoardPanel : (PANELS[device.role] || UnknownBoardPanel);
  return html`<${Panel} key=${device.id} device=${device} />`;
}

function App() {
  const [dock, setDock] = useState(state.ui.doc.active ? !!state.ui.doc.dock : true);
  const [side, setSide] = useState(false);
  const [toasts, setToasts] = useState([]);
  useEffect(() => onNotify(setToasts), []);
  useEffect(() => {
    const key = (e) => {
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
      if (e.key === 'Escape') { if (typing) { document.activeElement.blur(); return; } run('device.stop', {}).then(() => notify('Stop sent to every device', 'warn')).catch((x) => notify(x.message, 'bad')); }
      if (typing) return;
      if (e.key === '/') { e.preventDefault(); document.getElementById('search')?.focus(); }
      if ((e.metaKey || e.ctrlKey) && '123456'.includes(e.key)) { e.preventDefault(); navigate('#/' + ['devices', 'register', 'inventory', 'show', 'showedit', 'bench'][Number(e.key) - 1]); }
      if (e.key === '?') navigate('#/settings');
      if (e.key === 'j' || e.key === 'k') {
        const items = [...document.querySelectorAll('.rail-item')]; const i = items.findIndex((el) => el.getAttribute('aria-current') === 'true');
        const next = items[Math.max(0, Math.min(items.length - 1, i + (e.key === 'j' ? 1 : -1)))]; next && next.click();
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);
  return html`<div class=${'layout' + (dock ? ' dock-open' : '') + (side ? ' side-open' : '')}>
    <${TopBar} onToggleDock=${() => setDock(!dock)} dockOpen=${dock} onToggleSide=${() => setSide(!side)} sideOpen=${side} /><${Rail} />
    <main class="main"><${Main} /></main>
    <aside class="side"><${Attention} /><${Jobs} /></aside>
    <${Timeline} open=${dock} onToggle=${() => setDock(!dock)} />
    <${StatusBar} />
    <${Toasts} items=${toasts} /><${RegisterNotices} /></div>`;
}

let polling = false;
async function poll() {
  if (polling) return; polling = true;
  try { applyPull(await api.pull(state.versions, state.seq)); } catch (e) { state.connected = false; state.errors += 1; touch('link'); } finally { polling = false; }
}

async function boot() {
  state.ui.theme = applyTheme(storedTheme());
  await ready();
  window.nct = { wake: () => poll(), notify: (text, tone) => notify(text, tone), state, api };
  let copy = null;
  for (let i = 0; i < 40 && !copy; i++) {
    try { const c = await api.getCopy(); if (c && c.copy) copy = c; } catch (e) { /* backend booting */ }
    if (!copy) await new Promise((r) => setTimeout(r, 500));
  }
  if (copy) { state.copy = copy.copy; state.commands = copy.commands; }
  installRouter();
  if (state.ui.doc.theme) state.ui.theme = applyTheme(state.ui.doc.theme, { persist: false });
  render(html`<${App} />`, document.getElementById('app'));
  installDocHighlights();
  await poll();
  const timer = setInterval(poll, 200);
  // A documentation still (?still=1) stops polling after a few seconds so headless Chrome's virtual-time budget
  // reaches the end of its clock and the capture completes; the page then shows the last snapshot it pulled.
  if (state.ui.doc.still) setTimeout(() => clearInterval(timer), 5000);
}

boot();
