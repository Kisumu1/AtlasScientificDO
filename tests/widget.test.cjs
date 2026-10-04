// Run with node --test tests/widget.test.cjs; no browser or dependencies needed.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
test('widget clears stale readings, labels demo data, and handles an offline extension', async () => {
  const elements = Object.fromEntries(['mg', 'sat', 'source', 'status'].map(id => [id, {}]));
  const document = {getElementById: id => elements[id], body: {dataset: {}}};
  let now = 0, refresh;
  let data = {status:'connected', mode:'hardware', latest:{mg_l:8.74, saturation_pct:96.1}, stale:false, age_s:1, interval_s:2};
  const context = {document, performance:{now:()=>now}, AbortSignal,
    fetch:async () => {if (!data) throw Error('offline'); return {ok:true,json:async()=>data};},
    setInterval:fn=>{refresh=fn;}, setTimeout:()=>{}};
  runInNewContext(readFileSync('atlas/static/widget.js', 'utf8'), context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(elements.mg.textContent, '8.74');
  assert.equal(elements.sat.textContent, '96.1');
  now = 6000; refresh();
  assert.equal(elements.mg.textContent, '—');
  assert.equal(elements.status.textContent, 'Reading expired');
  data = {...data, mode:'demo'};
  await runInNewContext('poll()', context);
  assert.equal(elements.source.textContent, 'DEMO');
  assert.match(elements.status.textContent, /Simulated/);
  data = {...data, status:'disconnected'};
  await runInNewContext('poll()', context);
  assert.equal(elements.sat.textContent, '—');
  assert.equal(elements.status.textContent, 'Sensor disconnected');
  data = null;
  await runInNewContext('poll()', context);
  assert.equal(elements.mg.textContent, '—');
  assert.equal(elements.status.textContent, 'Extension unavailable');
});
