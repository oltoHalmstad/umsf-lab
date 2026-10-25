// station_page.h - local page of the stationary node (soft-AP http://192.168.4.1), Ukrainian UI.
// Polls /api/state; never presents stale data as current (explicit age and stale banner).
#pragma once
#include <pgmspace.h>

static const char kStationPage[] PROGMEM = R"HTML(<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UMSF стаціонарний вузол</title>
<style>
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2330;--mut:#5d6675;--warn:#b26a00;--bad:#b3261e;--ok:#1e7a3c}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1e232b;--ink:#e8eaee;--mut:#9aa3b2}}
body{margin:0;font:15px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:12px 16px}h1{font-size:18px;margin:0}small,.mut{color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;padding:0 16px}
.card{background:var(--card);border-radius:10px;padding:10px 12px}.v{font-size:24px;font-weight:600}
.alarm{outline:3px solid var(--bad)}.warn{outline:3px solid var(--warn)}
.banner{margin:8px 16px;padding:10px 12px;border-radius:8px;font-weight:600;display:none}
#stale{background:#fdecea;color:var(--bad)}#impact{background:#fff4e5;color:var(--warn)}#sos{background:var(--bad);color:#fff;font-size:18px}
section{padding:8px 16px}ul{padding-left:18px;margin:4px 0}input,button{font:inherit;padding:6px 10px}
</style></head><body>
<header><h1>Вузол стану будівлі <span id="dev">—</span></h1>
<small>Зона: <span id="zone">—</span> · BLE: <span id="ble">—</span> · буфер: <span id="buf">—</span> · оновлено: <span id="age">—</span></small></header>
<div id="stale" class="banner">Дані застарілі або немає зв'язку з вузлом — поточний стан НЕВІДОМИЙ</div>
<div id="sos" class="banner">SOS — ручний сигнал тривоги активний</div>
<div id="impact" class="banner">Можливий удар — не верифіковано (локальна ознака, не встановлює причину)</div>
<div class="grid">
<div class="card" id="c_vib"><small>Удар / вібрація</small><div class="v" id="vib">—</div><small>g, пік |a|−1g за 1 с</small></div>
<div class="card" id="c_tilt"><small>Нахил вузла</small><div class="v" id="tilt">—</div><small>° · зміна від базового: <span id="tiltd">—</span></small></div>
<div class="card" id="c_p"><small>Атмосферний тиск</small><div class="v" id="p">—</div><small>гПа</small></div>
<div class="card"><small>Температура</small><div class="v" id="t">—</div><small>°C (повітря біля вузла)</small></div>
<div class="card" id="c_gas"><small>Газовий канал MQ-2</small><div class="v" id="gas">—</div><small>В, некалібрований сигнал · <span id="warm">—</span></small></div>
<div class="card" id="c_snd"><small>Звук</small><div class="v" id="snd">—</div><small>індекс (розмах АЦП)</small></div>
<div class="card" id="c_pir"><small>Рух / присутність (PIR)</small><div class="v" id="pir">—</div><small>утримання 30 с</small></div>
<div class="card" id="c_sos"><small>SOS</small><div class="v" id="sosv">—</div><small>кнопка на вузлі</small></div>
</div>
<section><b>Ознаки можливої присутності</b>
<div class="mut">Рух (PIR), звукова активність і ручний SOS лише вказують на можливу присутність людини. Вони не вимірюють пульс,
дихання, свідомість чи стан здоров'я; їх відсутність не виключає присутності людини.</div>
<ul id="pres"></ul></section>
<section><b>Журнал подій</b><ul id="log"></ul></section>
<section><b>Оператор</b><br><input id="pin" type="password" placeholder="PIN" size="6">
<button onclick="post('/api/sos_reset')">Скинути SOS (оператор)</button>
<button onclick="post('/api/commission')">Зафіксувати базове положення</button> <span id="msg" class="mut"></span>
<div class="mut">Базове положення фіксується лише після перевіреного кріплення вузла. Без нього нахил і кріплення вважаються невизначеними.</div></section>
<section class="mut">Не є сертифікованим засобом безпеки чи медичним виробом. Пороги та значення не калібровані.
Втрата зв'язку означає «стан невідомий», а не руйнування чи постраждалих.</section>
<script>
const N={sos:'SOS',sos_reset:'скидання SOS',impact_excursion:'механічний сплеск',loud_sound:'гучний звук',
gas_channel_alarm:'тривога газового каналу',tilt_change:'зміна нахилу',pressure_transient:'перепад тиску',presence:'присутність (PIR)',
possible_impact_local:'можливий удар — не верифіковано',buffer_eviction:'витіснення з буфера',help_request:'запит допомоги'};
const $=id=>document.getElementById(id);let lastOk=0;
const f=(v,u)=>v===null||v===undefined?'—':v+(u||'');
function ago(ms){return ms<1000?'щойно':Math.round(ms/1000)+' с тому'}
async function tick(){
 const ac=new AbortController();const to=setTimeout(()=>ac.abort(),2500);
 try{const r=await fetch('/api/state',{signal:ac.signal,cache:'no-store'});const s=await r.json();lastOk=Date.now();render(s);}
 catch(e){$('stale').style.display='block';$('age').textContent=lastOk?ago(Date.now()-lastOk)+' (помилка оновлення)':'немає даних';}
 finally{clearTimeout(to);}
}
function render(s){
 const c=s.cards||{},fl=c.flags||0,stale=s.state_age_ms===null||s.state_age_ms>3000;
 $('stale').style.display=stale?'block':'none';
 $('dev').textContent=s.device_id;$('ble').textContent=s.ble_ready?'з’єднано':'немає';$('buf').textContent=s.buffered;
 $('age').textContent=s.state_age_ms===null?'немає даних':ago(s.state_age_ms);$('zone').textContent=s.zone||'—';
 $('vib').textContent=f(c.vib_peak_g);$('tilt').textContent=f(c.tilt_deg);$('tiltd').textContent=c.tilt_baseline?f(c.tilt_delta_deg,'°'):'немає базового (кріплення невизначене)';
 $('p').textContent=f(c.pressure_hpa);$('t').textContent=f(c.temp_c);$('gas').textContent=f(c.gas_v);
 $('warm').textContent=c.gas_warm?'прогрітий':'прогрів — тривоги заблоковані';$('snd').textContent=f(c.sound_index);
 const pir=(c.sensor_flags&16)?((fl&1)?'виявлено':'не виявлено'):'невідомо';$('pir').textContent=pir;
 $('sosv').textContent=c.sos?'АКТИВНИЙ':'немає';$('sos').style.display=c.sos?'block':'none';
 $('c_vib').className='card'+((fl&4)?' warn':'');$('c_tilt').className='card'+((fl&32)?' alarm':((fl&128)?' warn':''));
 $('c_p').className='card'+((fl&64)?' warn':'');$('c_gas').className='card'+((fl&16)?' alarm':'');
 $('c_snd').className='card'+((fl&8)?' warn':'');$('c_sos').className='card'+(c.sos?' alarm':'');
 const ev=s.events||[];$('impact').style.display=ev.some(e=>e.type==='possible_impact_local'&&e.age_ms<60000)?'block':'none';
 $('log').innerHTML=ev.map(e=>'<li>'+ago(e.age_ms)+': '+(N[e.type]||e.type)+' ('+e.value+')'+(e.operator?' — дія оператора':'')+'</li>').join('')||'<li class="mut">подій немає</li>';
 const p=[];if((fl&1)&&(c.sensor_flags&16))p.push('рух (PIR)');if(fl&8)p.push('звукова активність');if(c.sos)p.push('ручний SOS');
 $('pres').innerHTML=p.length?p.map(x=>'<li>'+x+'</li>').join(''):'<li class="mut">ознак не зафіксовано (це не означає відсутність людей)</li>';
}
async function post(u){const b=new URLSearchParams({pin:$('pin').value});
 try{const r=await fetch(u,{method:'POST',body:b});$('msg').textContent=r.ok?'виконано':'відмовлено ('+r.status+')';}catch(e){$('msg').textContent='помилка зв’язку';}}
setInterval(tick,1000);tick();
</script></body></html>)HTML";
