// The guided registration's stepper (panels/RegisterSection.js), pure so node --test can check it.

// Where each step stands: done | current | waiting | failed | todo.
export function stepStates(r) {
  const steps = r.steps || ['usb', 'number', 'nfc', 'sync'];
  const at = !r.mac ? -1 : r.step === 'done' ? steps.length : steps.indexOf(r.step === 'failed' ? r.failed_step : r.step);
  const out = {};
  steps.forEach((s, i) => {
    out[s] = !r.mac || i > at ? 'todo' : i < at ? 'done' : r.step === 'failed' ? 'failed' : r.wait ? 'waiting' : 'current';
  });
  return out;
}
