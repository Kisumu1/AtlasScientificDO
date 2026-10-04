'use strict';
const $ = id => document.getElementById(id);
let state, initialized = false, busy = false;
const fields = ['mode','transport','port','baud','i2c_address','interval_s','temperature_c','salinity_ppt','pressure_kpa'];
function connectionUI() {
  const i2c = $('transport').value === 'i2c';
  $('address-field').hidden = !i2c; $('baud-field').hidden = i2c;
  $('port-label').textContent = i2c ? 'I²C bus' : 'USB device (optional)';
  $('port').placeholder = i2c ? '/dev/i2c-6' : 'Choose automatically';
  $('port-help').textContent = i2c ? 'Navigator external I²C uses /dev/i2c-6. EZO-DO default address: 97 (0x61). Listing buses does not scan sensor addresses.' : 'Plug the carrier into the BlueOS Pi, then click Find & connect. Choose /dev/ttyUSB… or its stable /dev/serial/by-id/… entry. /dev/ttyAMA… is an onboard UART.';
}
function friendlyError(text) {
  if(/onboard UART/.test(text))return 'The selected port belongs to the Pi. Click Find & connect to choose your USB sensor.';
  if(/No matching devices|No such file|Errno 2/.test(text))return 'No sensor device was found. Connect the carrier to the Pi with a USB data cable, then try Find & connect again.';
  if(/Operation not permitted|Permission denied|Errno (1|13)\]/.test(text))return 'The extension cannot access this device. Check its Custom settings in BlueOS and restart the extension.';
  if(/exclusive|Resource busy|already open|Errno 16/.test(text))return 'Another program is using the sensor. Close its serial connection, then try again.';
  if(/not an Atlas|Not EZO-DO/.test(text))return 'The connected device is not an EZO dissolved oxygen sensor. Check that the EZO-DO circuit is fitted to the carrier.';
  if(/timeout|timed out|acknowledged without/i.test(text))return 'The sensor did not reply. Check its power, UART mode, and baud rate (normally 9600), then try again.';
  if(/No EZO-DO connected/.test(text))return 'USB devices were found, but none connected as an EZO-DO. Check the sensor circuit and connection settings, then try again.';
  if(/Invalid .*response|Missing or ambiguous|Expected mg|Oversized|outside.*range/.test(text))return 'The sensor sent an unreadable measurement. Check the cable and baud rate, then reconnect.';
  if(/EZO status: \*UV/.test(text))return 'The sensor reports low voltage. Check the carrier power and USB cable, then reconnect.';
  if(/EZO status:|EZO I2C command rejected/.test(text))return 'The sensor could not accept a command. Check the connection settings and try again. Technical details are available below.';
  if(/I2C.*no data|Empty I2C|Unexpected EZO I2C/.test(text))return 'The sensor did not respond on this I²C connection. Check the bus, address, wiring, and sensor mode.';
  if(/Failed to fetch|NetworkError|fetch failed/.test(text))return 'The dashboard cannot reach the extension. Check the BlueOS connection and restart the extension if needed.';
  return text;
}
function message(text = '') {
  $('message').hidden = !text; $('message').textContent = friendlyError(text);
  $('message-details').hidden = !text || friendlyError(text)===text; $('message-raw').textContent=text;
}
async function api(path, data) {
  const options = {signal: AbortSignal.timeout(path==='api/find'?120000:25000)};
  if (data !== undefined) Object.assign(options, {method:'POST',headers:{'Content-Type':'application/json','X-Atlas-Request':'1'},body:JSON.stringify(data)});
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Request failed');
  return value;
}
async function action(fn) {
  if (busy) return;
  busy = true; $('refresh').disabled=true; $('save').disabled=true; message();
  try { await fn(); await update(); } catch(e) {
    try{await update();}catch(_){}
    message(state?.error===e.message?'':e.message);
  }
  finally { busy = false; $('refresh').disabled=!!state?.recording; $('save').disabled=!!state?.recording; }
}
function chart() {
  const canvas = $('chart'), rect = canvas.getBoundingClientRect(), scale = devicePixelRatio || 1;
  if(!rect.width)return;
  canvas.width = rect.width * scale; canvas.height = rect.height * scale;
  const ctx = canvas.getContext('2d'); ctx.scale(scale,scale);
  const w = rect.width, h = rect.height, left = 52, top = 15, bottom = h-20;
  const points = state?.history || [], key = $('metric').value;
  if (!points.length) { ctx.fillStyle = '#91a9b7'; ctx.font = '13px system-ui'; ctx.textAlign='center'; ctx.fillText('Your readings will appear here',w/2,h/2); return; }
  let min = Math.min(...points.map(p=>p[key])), max = Math.max(...points.map(p=>p[key]));
  const pad = Math.max((max-min)*.15, key==='mg_l'?.2:2); min = Math.max(0,min-pad); max+=pad;
  ctx.font='11px system-ui';
  for(let i=0;i<5;i++) { const y=top+(bottom-top)*i/4;ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue('--line');ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w,y);ctx.stroke();ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--muted');ctx.fillText((max-(max-min)*i/4).toFixed(1),2,y+4); }
  const start=Date.parse(points[0].timestamp_utc), end=Date.parse(points.at(-1).timestamp_utc);
  ctx.beginPath(); let previous;
  points.forEach((p,i)=>{const t=Date.parse(p.timestamp_utc),x=left+(w-left-5)*(t-start)/Math.max(1000,end-start),y=bottom-(p[key]-min)/(max-min)*(bottom-top);if(i===0||t-previous>state.config.interval_s*2500)ctx.moveTo(x,y);else ctx.lineTo(x,y);previous=t;if(points.length===1){ctx.moveTo(x-2,y);ctx.lineTo(x+2,y);}});
  ctx.strokeStyle=state.config.mode==='demo'?'#a47500':getComputedStyle(document.documentElement).getPropertyValue('--accent');ctx.lineWidth=2;ctx.stroke();
  $('chart-start').textContent=new Date(start).toLocaleTimeString();$('chart-end').textContent=new Date(end).toLocaleTimeString();
}
function render(s) {
  state=s;
  if (!initialized) {fields.forEach(k=>$(k).value=s.config[k]);initialized=true;connectionUI();}
  const demo=s.config.mode==='demo', live=s.status==='connected'&&!s.stale;
  $('status').textContent=demo?'Demo':live?'Connected':s.status==='connecting'?'Connecting…':s.error?'Not connected':'Ready';
  $('status').className='badge '+(demo?'demo':live?'live':'');
  $('notice').className='notice '+(demo?'demo':s.error?'error':'');
  $('notice').textContent=demo?'Demo mode — these readings are simulated.':s.error?friendlyError(s.error):!s.config.port?'Click Find & connect to start.':live?'Receiving readings from your sensor.':'Waiting for the sensor. We will keep trying to connect.';
  $('error-details').hidden=!s.error;$('error-raw').textContent=s.error;
  $('mg').textContent=live?s.latest.mg_l.toFixed(2):'—';$('sat').textContent=live?s.latest.saturation_pct.toFixed(1):'—';
  $('freshness').textContent=s.latest?(s.stale?'Last reading is stale · ':'Updated ')+Math.round(s.age_s)+' seconds ago':'Waiting for a reading';
  $('ctx-temp').textContent=s.config.temperature_c+' °C';$('ctx-sal').textContent=s.config.salinity_ppt+' ppt';$('ctx-pressure').textContent=s.config.pressure_kpa+' kPa';
  $('cal-status').textContent=demo?'Not applicable':s.calibration_points===null?'Unknown':s.calibration_points===0?'Not calibrated':s.calibration_points+' point';
  $('identity').textContent=s.identity?'EZO-DO · '+s.config.port:'No sensor connected';
  $('record').disabled=!s.recording&&!live;$('record').textContent=s.recording?'Stop recording':'Start recording';
  $('record-state').textContent=s.log_error||(s.recording?'Recording '+(demo?'SIMULATED':'hardware')+' data onboard…':'Recording is stopped.');
  $('save').disabled=busy||s.recording;$('refresh').disabled=busy||s.recording;
  for(const id of ['cal-air','cal-zero'])$(id).disabled=demo||!live||s.recording;
  const container=$('sessions');container.replaceChildren();
  if(!s.sessions.length){const p=document.createElement('p');p.className='muted';p.textContent='No recordings yet.';container.append(p);}
  s.sessions.forEach(session=>{const row=document.createElement('div');row.className='session';const title=document.createElement('div');title.textContent=new Date(session.started).toLocaleString();const meta=document.createElement('small');meta.textContent=(session.mode==='demo'?'SIMULATED':'Hardware')+' · '+(session.stopped?'Completed':s.recording&&s.session===session.id?'Recording':'Interrupted');title.append(meta);const a=document.createElement('a');a.href='api/export?session='+encodeURIComponent(session.id);a.textContent='Download CSV';row.append(title,a);container.append(row);});
  $('cockpit-status').textContent=s.cockpit?.status==='connected'?'Cockpit is receiving sensor data.':'Add the data connection in Cockpit to use bottom-bar indicators.';
  chart();
}
async function update(){render(await api('api/state'));}
function formConfig(){return Object.fromEntries(fields.map(k=>[k,['mode','transport','port'].includes(k)?$(k).value.trim():Number($(k).value)]));}
async function findSensor(){
  if(!$('settings').checkValidity()){$('advanced').open=true;$('settings').reportValidity();return;}
  const button=$('refresh');button.textContent='Finding…';
  try{
    const result=await api('api/find',formConfig());
    $('port').value=result.port;$('mode').value='hardware';
    $('port-help').textContent='Connected to '+result.port+' — '+result.identity;
  }finally{button.textContent='Find & connect';}
}
async function refreshPorts(){const ports=await api('api/ports?transport='+$('transport').value);$('ports').replaceChildren();ports.forEach(p=>{const o=document.createElement('option');o.value=p.device;o.label=p.description;$('ports').append(o);});$('port-help').textContent=ports.length?ports.map(p=>p.device+' — '+p.description).join(' · '):'No matching devices found. Check the sensor connection, selected connection type, and the extension’s device permissions.';}
$('transport').addEventListener('change',()=>{$('port').value='';connectionUI();action(refreshPorts);});
$('settings').addEventListener('submit',e=>{e.preventDefault();action(async()=>{const config=formConfig();if(config.mode==='hardware'&&!config.port)throw new Error('Choose the sensor bus or serial device first');await api('api/config',config);});});
$('record').addEventListener('click',()=>action(()=>api('api/record',{enabled:!state.recording})));
$('refresh').addEventListener('click',()=>action(findSensor));
for(const kind of ['air','zero'])$('cal-'+kind).addEventListener('click',()=>{if(confirm(kind==='air'?'Apply air calibration now? Confirm the probe is prepared according to Atlas instructions, exposed to air, and readings are stable. This changes saved sensor calibration.':'Apply zero calibration now? Confirm the probe is in zero-oxygen solution and readings are stable. This changes saved sensor calibration.'))action(()=>api('api/calibrate',{kind,confirmed:true}));});
$('metric').addEventListener('change',chart);window.addEventListener('resize',chart);
$('trend').addEventListener('toggle',chart);
async function poll(){if(busy){setTimeout(poll,2000);return;}try{await update();}catch(e){$('status').textContent='Dashboard offline';$('mg').textContent='—';$('sat').textContent='—';$('notice').textContent='Cannot reach the extension. Check your connection to BlueOS.';for(const id of ['record','cal-air','cal-zero'])$(id).disabled=true;}finally{setTimeout(poll,2000);}}
poll();refreshPorts().catch(()=>{});

const cockpitStreamUrl = new URL('cockpit/ws', location.href);
cockpitStreamUrl.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
document.getElementById('cockpit-url').textContent = cockpitStreamUrl.href;
