// gateway_page.h - local gateway status page (http://192.168.4.1 on the AP, or the STA address).
// Stage-1 style: status indicators, decoded table of newest records and the serialized CSV view.
// Fixes the Stage-1 "web refresh error" class of failure: the page never reloads itself; it polls
// a JSON endpoint with a timeout, shows the age of every record and node, and turns an explicit
// stale / no-connection indicator on instead of presenting old values as current.
#pragma once
#include <pgmspace.h>

static const char kGatewayPage[] PROGMEM = R"HTML(<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UMSF шлюз</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2330;--mut:#5d6675;--bad:#b3261e;--ok:#1e7a3c;--warn:#b26a00}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1e232b;--ink:#e8eaee;--mut:#9aa3b2}}
body{margin:0;font:14px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header,section{padding:10px 16px}h1{font-size:18px;margin:0}.mut{color:var(--mut)}
.pill{display:inline-block;padding:2px 8px;border-radius:10px;background:var(--card);margin:2px}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
#stale{display:none;margin:0 16px;padding:10px;border-radius:8px;background:#fdecea;color:var(--bad);font-weight:600}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--card)}td,th{padding:4px 6px;border-bottom:1px solid #8883;text-align:left;white-space:nowrap}
pre{background:var(--card);padding:8px;overflow-x:auto;font-size:12px}tr.old td{opacity:.5}
</style></head><body>
<header><h1>Шлюз <span id="gw">—</span> · майданчик <span id="site">—</span></h1>
<div id="st" class="mut">—</div></header>
<div id="stale">Оновлення не вдалося або дані застарілі — показані значення НЕ є поточним станом</div>
<section><b>Вузли</b><div id="nodes"></div>
<div class="mut">Легенда прапорців: T температура · P PPG · M рух · H синтетичний тестовий ЧСС · G GSR · S SOS.
Значення ЧСС з позначкою H — синтетичне тестове поле, не вимірювання.</div></section>
<section><b>Останні записи</b><div class="tw"><table><thead><tr><th>вік</th><th>тип</th><th>вузол</th><th>boot</th><th>seq</th>
<th>час вузла, мс</th><th>значення</th></tr></thead><tbody id="rows"></tbody></table></div></section>
<section><b>Серіалізований вигляд (CSV)</b> <a href="/records.csv">завантажити</a><pre id="csv"></pre></section>
<section class="mut">Не є сертифікованим засобом безпеки чи медичним виробом. Втрата зв'язку означає «стан невідомий».</section>
<script>
const $=id=>document.getElementById(id);let lastOk=0;const L={unknown:'невідомо',up:'на зв’язку',lost:'зв’язок втрачено'};
const ago=ms=>ms===null?'—':(ms<1000?'<1 с':Math.round(ms/1000)+' с');
async function tick(){const ac=new AbortController();const to=setTimeout(()=>ac.abort(),2500);
 try{const r=await fetch('/api/records',{signal:ac.signal,cache:'no-store'});if(!r.ok)throw 0;render(await r.json());lastOk=Date.now();$('stale').style.display='none';}
 catch(e){$('stale').style.display='block';$('st').textContent='помилка оновлення; останнє успішне: '+(lastOk?ago(Date.now()-lastOk)+' тому':'ніколи');}
 finally{clearTimeout(to);}}
function render(s){
 $('gw').textContent=s.gateway_id;$('site').textContent=s.site_id;
 $('st').innerHTML='MQTT: <span class="'+(s.mqtt?'ok':'bad')+'">'+(s.mqtt?'з’єднано':'немає')+'</span> · час: '+
  (s.clock_synced?'<span class="ok">синхронізовано</span>':'<span class="bad">не синхронізовано (записи чекають у буфері)</span>')+
  ' · буфер: '+s.buffered+' · витіснено: '+s.evicted_total+' · boot '+s.boot_id;
 $('nodes').innerHTML=s.nodes.map(n=>'<span class="pill">'+n.device_id+' ('+(n.source_class==2?'стаціонарний':'персональний')+'): <span class="'+
  (n.fresh?'ok':(n.link==='lost'?'bad':'warn'))+'">'+(n.fresh?L[n.link]:(n.link==='up'?'дані застарілі':L[n.link]))+'</span> · '+ago(n.age_ms)+'</span>').join('');
 $('rows').innerHTML=s.records.map(r=>{const f=r.line.split(',');const k={F:'F ознаки',S:'S стан',E:'E подія'}[f[3]]||f[3];
  return '<tr class="'+(r.age_ms>60000?'old':'')+'"><td>'+ago(r.age_ms)+'</td><td>'+k+'</td><td>'+(f[4]||'')+'</td><td>'+(f[5]||'')+'</td><td>'+(f[6]||'')+
  '</td><td>'+(f[7]||'')+'</td><td>'+f.slice(8).join(', ')+'</td></tr>'}).join('');
 $('csv').textContent=s.records.slice().reverse().map(r=>r.line).join('\n');}
setInterval(tick,2000);tick();
</script></body></html>)HTML";
