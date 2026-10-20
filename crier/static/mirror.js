let access = '';
const $ = id => document.getElementById(id);
async function api(path='', method='GET', body) {
  const response = await fetch('/api/mirror'+path, {method, headers:{Authorization:'Bearer '+access,'Content-Type':'application/json'}, ...(body ? {body:JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
  return data;
}
function button(label, action) { const b=document.createElement('button'); b.textContent=label; b.onclick=()=>run(action); return b; }
async function run(action) { try { await action(); } catch(e) { $('message').textContent=e.message; } }
async function refresh() {
  const state=await api(); $('desk').hidden=false;
  $('message').textContent=state.configured?'Receiver configured. Pairing is separate from Discord.':'Set CRIER_MIRROR_ALPACA_KEY and CRIER_MIRROR_ALPACA_SECRET on this PC, then restart.';
  $('pairs').replaceChildren();
  for (const pair of state.pairs) {
    const row=document.createElement('p'); row.textContent=pair.name+' • '+pair.environment.toUpperCase()+' • '+(pair.revoked?'Revoked':pair.enabled?'Following':'Paused')+' ';
    if (!pair.revoked) {
      row.append(button(pair.enabled?'Pause':'Follow automatically',async()=>{await api('/pairs/'+pair.id,'PUT',{enabled:!pair.enabled});await refresh();}));
      row.append(button('Revoke pairing',async()=>{await api('/pairs/'+pair.id,'DELETE');await refresh();}));
    }
    $('pairs').append(row);
  }
  $('events').replaceChildren();
  for(const event of state.events) { const data=JSON.parse(event.payload); const p=document.createElement('p'); p.textContent=`${data.side.toUpperCase()} ${data.quantity} ${data.symbol} @ $${data.price} • ${event.state} • ${event.note}`; $('events').append(p); }
}
$('unlock').onclick=()=>run(async()=>{access=$('access').value;$('access').value='';await refresh();});
$('pair').onclick=()=>run(async()=>{const pair=await api('/pairs','POST',{name:$('name').value});$('pairing').value=JSON.stringify({url:location.origin,token:pair.token,environment:pair.environment});await refresh();});
$('refresh').onclick=()=>run(refresh);
$('reconcile').onclick=()=>run(async()=>{await api('/reconcile','POST');await refresh();});
