'use strict';
let snapshot = null, receivedAt = 0;
const element = id => document.getElementById(id);
function render() {
  const elapsed = (performance.now() - receivedAt) / 1000;
  const age = snapshot?.age_s == null ? null : snapshot.age_s + elapsed;
  const valid = snapshot && snapshot.status === 'connected' && !snapshot.stale &&
    age !== null && age <= Math.max(5, snapshot.interval_s * 2.5) &&
    Number.isFinite(snapshot.latest?.mg_l) && Number.isFinite(snapshot.latest?.saturation_pct);
  const demo = snapshot?.mode === 'demo';
  element('mg').textContent = valid ? snapshot.latest.mg_l.toFixed(2) : '—';
  element('sat').textContent = valid ? snapshot.latest.saturation_pct.toFixed(1) : '—';
  element('source').textContent = demo ? 'DEMO' : 'Atlas DO';
  document.body.dataset.state = !valid ? 'warning' : demo ? 'demo' : 'live';
  element('status').textContent = !snapshot ? 'Extension unavailable' : valid ?
    (demo ? 'Simulated · ' : '') + 'Updated ' + Math.floor(age) + 's ago' :
    snapshot.status === 'connected' ? 'Reading expired' : 'Sensor disconnected';
}
async function poll() {
  try {
    const response = await fetch('api/measurement', {signal: AbortSignal.timeout(5000), cache: 'no-store'});
    if (!response.ok) throw new Error('Extension unavailable');
    snapshot = await response.json(); receivedAt = performance.now();
  } catch (_) { snapshot = null; }
  render();
  setTimeout(poll, 2000);
}
setInterval(render, 500);
poll();
