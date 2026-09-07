'use strict';
const $ = id => document.getElementById(id);
let state, initialized = false, busy = false;
const fields = ['mode','port','baud','interval_s','temperature_c','salinity_ppt','pressure_kpa'];
function message(text = '') { $('message').hidden = !text; $('message').textContent = text; }
async function api(path, data) {
  const options = {signal: AbortSignal.timeout(25000)};
  if (data !== undefined) Object.assign(options, {method:'POST',headers:{'Content-Type':'application/json','X-Atlas-Request':'1'},body:JSON.stringify(data)});
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Request failed');
  return value;
}
async function action(fn) {
  if (busy) return;
  busy = true; message();
  try { await fn(); await update(); } catch(e) { message(e.message); }
  finally { busy = false; }
}
function chart() {
  const canvas = $('chart'), rect = canvas.getBoundingClientRect(), scale = devicePixelRatio || 1;
  canvas.width = rect.width * scale; canvas.height = rect.height * scale;
  const ctx = canvas.getContext('2d'); ctx.scale(scale,scale);
  const w = rect.width, h = rect.height, left = 52, top = 15, bottom = h-20;
  const points = state?.history || [], key = $('metric').value;
  if (!points.length) { ctx.fillStyle = '#91a9b7'; ctx.font = '13px system-ui'; ctx.textAlign='center'; ctx.fillText('Your readings will appear here',w/2,h/2); return; }
  let min = Math.min(...points.map(p=>p[key])), max = Math.max(...points.map(p=>p[key]));
  const pad = Math.max((max-min)*.15, key==='mg_l'?.2:2); min = Math.max(0,min-pad); max+=pad;
  ctx.font='11px system-ui';
  for(let i=0;i<5;i++) { const y=top+(bottom-top)*i/4;ctx.strokeStyle='#263946';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w,y);ctx.stroke();ctx.fillStyle='#91a9b7';ctx.fillText((max-(max-min)*i/4).toFixed(1),2,y+4); }
  const start=Date.parse(points[0].timestamp_utc), end=Date.parse(points.at(-1).timestamp_utc);
  ctx.beginPath(); let previous;
  points.forEach((p,i)=>{const t=Date.parse(p.timestamp_utc),x=left+(w-left-5)*(t-start)/Math.max(1000,end-start),y=bottom-(p[key]-min)/(max-min)*(bottom-top);if(i===0||t-previous>state.config.interval_s*2500)ctx.moveTo(x,y);else ctx.lineTo(x,y);previous=t;if(points.length===1){ctx.moveTo(x-2,y);ctx.lineTo(x+2,y);}});
  ctx.strokeStyle=state.config.mode==='demo'?'#f2c76e':'#4fe0c1';ctx.lineWidth=2;ctx.stroke();
  $('chart-start').textContent=new Date(start).toLocaleTimeString();$('chart-end').textContent=new Date(end).toLocaleTimeString();
}
function render(s) {
  state=s;
  if (!initialized) {fields.forEach(k=>$(k).value=s.config[k]);initialized=true;}
  const demo=s.config.mode==='demo', live=s.status==='connected'&&!s.stale;
  $('status').textContent=demo?'DEMO · SIMULATED':live?'● SENSOR CONNECTED':s.status.toUpperCase();
  $('status').className='badge '+(demo?'demo':live?'live':'');
  $('notice').className='notice '+(demo?'demo':s.error?'error':'');
  $('notice').textContent=demo?'Demo mode — all readings are simulated. No hardware data is being collected.':s.error||(!s.config.port?'Choose your Atlas USB port below, check compensation values, then Save & connect.':live?'Receiving measurements from your EZO-DO.':'Waiting for the sensor. Connection attempts repeat automatically.');
  $('mg').textContent=live?s.latest.mg_l.toFixed(2):'—';$('sat').textContent=live?s.latest.saturation_pct.toFixed(1):'—';
  $('freshness').textContent=s.latest?(s.stale?'Last reading is stale · ':'Updated ')+Math.round(s.age_s)+' seconds ago':'Waiting for a reading';
  $('ctx-temp').textContent=s.config.temperature_c+' °C';$('ctx-sal').textContent=s.config.salinity_ppt+' ppt';$('ctx-pressure').textContent=s.config.pressure_kpa+' kPa';
  $('cal-status').textContent=demo?'Not applicable':s.calibration_points===null?'Unknown':s.calibration_points===0?'Not calibrated':s.calibration_points+' point';
  $('identity').textContent=s.identity||'No sensor identified';
  $('record').disabled=!s.recording&&!live;$('record').textContent=s.recording?'■ Stop recording':'● Start recording';
  $('record-state').textContent=s.log_error||(s.recording?'Recording '+(demo?'SIMULATED':'hardware')+' data onboard…':'Recording is stopped.');
  $('save').disabled=s.recording;
  for(const id of ['cal-air','cal-zero'])$(id).disabled=demo||!live||s.recording;
  const container=$('sessions');container.replaceChildren();
  if(!s.sessions.length){const p=document.createElement('p');p.className='muted';p.textContent='No recordings yet.';container.append(p);}
  s.sessions.forEach(session=>{const row=document.createElement('div');row.className='session';const title=document.createElement('div');title.textContent=new Date(session.started).toLocaleString();const meta=document.createElement('small');meta.textContent=(session.mode==='demo'?'SIMULATED':'Hardware')+' · '+(session.stopped?'Completed':s.recording&&s.session===session.id?'Recording':'Interrupted');title.append(meta);const a=document.createElement('a');a.href='api/export?session='+encodeURIComponent(session.id);a.textContent='Download CSV';row.append(title,a);container.append(row);});
  chart();
}
async function update(){render(await api('api/state'));}
async function refreshPorts(){const ports=await api('api/ports');$('ports').replaceChildren();ports.forEach(p=>{const o=document.createElement('option');o.value=p.device;o.label=p.description;$('ports').append(o);});$('port-help').textContent=ports.length?ports.map(p=>p.device+' — '+p.description).join(' · '):'No serial ports found. Check the cable and the extension’s USB device mapping.';}
$('settings').addEventListener('submit',e=>{e.preventDefault();action(async()=>{const config=Object.fromEntries(fields.map(k=>[k,['mode','port'].includes(k)?$(k).value.trim():Number($(k).value)]));if(config.mode==='hardware'&&!config.port)throw new Error('Choose the Atlas USB serial port first');await api('api/config',config);});});
$('record').addEventListener('click',()=>action(()=>api('api/record',{enabled:!state.recording})));
$('refresh').addEventListener('click',()=>action(refreshPorts));
for(const kind of ['air','zero'])$('cal-'+kind).addEventListener('click',()=>{if(confirm(kind==='air'?'Apply air calibration now? Confirm the probe is prepared according to Atlas instructions, exposed to air, and readings are stable. This changes saved sensor calibration.':'Apply zero calibration now? Confirm the probe is in zero-oxygen solution and readings are stable. This changes saved sensor calibration.'))action(()=>api('api/calibrate',{kind,confirmed:true}));});
$('metric').addEventListener('change',chart);window.addEventListener('resize',chart);
async function poll(){try{await update();}catch(e){$('status').textContent='DASHBOARD OFFLINE';$('mg').textContent='—';$('sat').textContent='—';$('notice').textContent='Cannot reach the onboard extension. Displayed history may be stale.';for(const id of ['record','cal-air','cal-zero'])$(id).disabled=true;}finally{setTimeout(poll,2000);}}
poll();refreshPorts().catch(()=>{});
