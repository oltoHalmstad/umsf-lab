// Socket-free JavaScript/DOM smoke test; this does not claim browser layout validation.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const project = path.resolve(__dirname, '..');
const input = process.argv[2] || path.join(project, 'interactive_dashboard.html');
const source = fs.readFileSync(input, 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];
class Element {
  constructor(tag='div') { this.tag=tag;this.value='';this.children=[];this.style={};this.attrs={};this.events={};this.textContent=''; }
  append(child) { this.children.push(child);if(this.tag==='select'&&!this.value)this.value=child.value; }
  replaceChildren(...children) { this.children=children; }
  setAttribute(key,value) { this.attrs[key]=value; }
  addEventListener(key,fn) { this.events[key]=fn; }
}
const ids={};
for(const id of ['node','channel','time','timeLabel','status','chart','summary','events']) ids[id]=new Element(['node','channel'].includes(id)?'select':'div');
ids.time.value='15';
const context={document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)},window:{},console};
vm.createContext(context);vm.runInContext(source,context);
const data=vm.runInContext('D',context);
let cases=0;
for(const node of data.nodes) for(const channel of Object.keys(data.fields)) for(let t=0;t<=30;t+=.5) {
  ids.node.value=node;ids.channel.value=channel;ids.time.value=String(t);ids.time.events.input();
  const got=context.window.UMSF_REPLAY_STATE;
  assert.equal(got.node,node);assert.equal(got.channel,channel);assert.equal(got.minute,t);
  const expected=data.records.filter(r=>r.node===node&&r.s<=t*60&&r.arrival<=t*60&&r[channel]!==null&&Number.isFinite(r[channel])).length;
  assert.equal(got.samples,expected);
  assert.ok(!ids.chart.children.some(e=>/NaN|Infinity/.test(JSON.stringify(e.attrs))));
  if(t===0) assert.equal(got.samples,0);
  if(t===30&&node==='SA1') assert.equal(got.status,'unknown');
  if(t===30&&node==='SB2') assert.equal(got.status,'current');
  cases++;
}
const result={status:'PASS',control_combinations:cases,method:'JavaScript executed with a minimal DOM test adapter',browser_visual_rendering_tested:false,checks:['All nodes/channels/cutoffs execute','No future arrivals displayed','No invalid SVG coordinates','Initial empty evidence','SA1 final unknown / SB2 final current']};
console.log(JSON.stringify(result,null,2));
if(fs.existsSync(path.join(project,'results')))fs.writeFileSync(path.join(project,'results/dashboard_logic_validation.json'),JSON.stringify(result,null,2)+'\n');
