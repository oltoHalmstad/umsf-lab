"""Assemble UMSF_Firmware_Lab.ipynb from notebook/umsf_fw_lab.py, the cell texts below and a payload
built from the release tree (LZMA ZIP, Base85). Run from any directory: python scripts/build_notebook.py"""
from pathlib import Path
import base64, hashlib, io, json, lzma, tarfile, textwrap
import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

ROOT = Path(__file__).resolve().parents[1]


def build_payload() -> tuple[str, str, int]:
    files = [p for p in (ROOT / 'firmware').rglob('*')
             if p.is_file() and not {'build', '__pycache__', '.pio'} & set(p.relative_to(ROOT).parts)]
    files += [ROOT / 'lab/native_experiments.cpp', ROOT / 'provenance/source_sha256.json']
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:xz', preset=9 | lzma.PRESET_EXTREME) as archive:
        for p in sorted(files, key=lambda p: p.relative_to(ROOT).as_posix()):
            info = tarfile.TarInfo(p.relative_to(ROOT).as_posix())
            info.size, info.mode, info.mtime = p.stat().st_size, 0o644, 1791936000  # 2026-10-14, deterministic
            with p.open('rb') as handle:
                archive.addfile(info, handle)
    blob = buffer.getvalue()
    return hashlib.sha256(blob).hexdigest(), '\n'.join(textwrap.wrap(base64.b85encode(blob).decode(), 120)), len(blob)


def md(text):
    return new_markdown_cell(textwrap.dedent(text).strip())


def code(text, **metadata):
    cell = new_code_cell(textwrap.dedent(text).strip())
    cell.metadata.update(metadata)
    return cell


HEAD = 'from umsf_fw_lab import *  # shared runtime from Section 0; every cell is self-sufficient after setup\n'


def analysis(text):
    return code(HEAD + textwrap.dedent(text).strip())


def cells(payload_sha, payload_text, payload_bytes):
    lab_source = (ROOT / 'notebook/umsf_fw_lab.py').read_text()
    hidden = {'collapsed': True, 'jupyter': {'source_hidden': True}}
    return [
md("""
# UMSF Firmware Laboratory
### A self-contained, executable companion to the ESP32/BLE source release
**Notebook release 1.2.0 · Original firmware 1.0.0 · English · CPU only**

Explore the original portable C/C++ implementation through controlled experiments, protocol inspection and reproducible figures. All firmware source, test vectors and the new experiment harness are embedded in this notebook. No external dataset, account, device, broker, credentials or Google Drive mount is needed.

**Start:** Upload this `.ipynb` to [Google Colab](https://colab.research.google.com/), select a Python 3 CPU runtime, then **Runtime → Run all**. A Linux C/C++ compiler and `make` are required; these normally exist in Colab. Local use: Python 3.10+ with GCC/G++, make, NumPy, pandas, Matplotlib and IPython.

**Self-sufficient cells.** Section 0 writes a small verified runtime (`umsf_fw_lab.py`) next to the notebook. After it has run once, *every* analysis cell can be executed on its own, in any order, and again after **Runtime → Restart session**: each cell begins with `from umsf_fw_lab import *`, and the native builds, experiment CSVs and checks it needs are produced on first use and cached. Builds are incremental, so unchanged binaries are reused.

**Evidence boundary.** Native execution verifies software behavior under synthetic inputs. It does not compile the ESP32 images or validate BLE radio performance, MQTT/mTLS, sensors, real physiology, structural safety, or gas concentrations. Heart rate is null by default; a separate synthetic mode is explicitly flagged. SpO₂ stays null. All local thresholds are uncalibrated. `possible_impact_local` is an unverified composite, never attribution of a strike.

**Learning route:** reproducibility → native tests → binary protocol → BLE transport → personnel features → stationary events → button logic → link freshness → buffering and ACKs → export. Read each explanation before changing parameters. Every chart is also exported as PNG and SVG. The original source (including its localized embedded web pages and README) is archived verbatim; the notebook, laboratory interface and new documentation are English.
"""),
md(f"""
## 0. Setup — run once per runtime
Three cells prepare everything; nothing is downloaded except missing Python libraries.

1. **Embedded project** (collapsed): writes `umsf_fw_payload.py` – a {payload_bytes:,}-byte xz-compressed tar (Base85) with all original firmware files, the experiment harness and the source inventory; SHA-256 `{payload_sha[:16]}…`.
2. **Runtime module** (collapsed): writes `umsf_fw_lab.py` – dependency and compiler check, payload/hash verification, plotting conventions and cached native states. Expand it to read the code.
3. **Start**: imports the runtime. It verifies the payload and every original source hash and extracts the project once to `umsf_firmware_runs/project/` (later imports reuse the verified copy).

If a cell later reports `No module named 'umsf_fw_lab'`, the runtime files were removed (for example after **Disconnect and delete runtime**): run these three cells again.
"""),
code(f'%%writefile umsf_fw_payload.py\n# Embedded UMSF firmware project: xz-compressed tar, Base85 text. Generated by scripts/build_notebook.py.\n'
     f"PAYLOAD_SHA256 = '{payload_sha}'\nPAYLOAD = \"\"\"\n{payload_text}\n\"\"\"\n", tags=['embedded-payload'], **hidden),
code('%%writefile umsf_fw_lab.py\n' + lab_source, tags=['runtime-module'], **hidden),
code("""
import importlib, sys
if 'umsf_fw_lab' in sys.modules:       # re-running setup: reload a possibly edited runtime, clear caches
    importlib.reload(sys.modules['umsf_fw_lab'])
from umsf_fw_lab import *
status()
"""),
md("""
## 1. Runtime and visual conventions

The setup reports actual versions and uses deterministic synthetic inputs. Python draws the plots; compiled original C/C++ code computes feature windows, detectors, buffer actions and link states. No random sensor data are passed off as observations.
"""),
analysis("""
print(json.dumps(versions(), indent=2))
"""),
md("""
## 2. Architecture and evidence flow

Personnel and stationary nodes create distinct evidence streams. The gateway preserves source identity. MQTT PUBACK acknowledges broker receipt; only an application ACK following durable site commit authorizes release of held records. The diagram describes the intended hardware architecture, while this notebook exercises its portable software components.
"""),
analysis("""
fig,ax=newfig(figsize=(12,5));ax.set(xlim=(0,12),ylim=(0,5));ax.axis('off')
boxes=[(.2,3,'Personnel node\\nPPG · temperature · motion'),(.2,.6,'Stationary node\\nIMU · pressure · gas · sound'),(4.3,1.8,'BLE gateway\\nidentity · RAM · JSON'),(8.6,1.8,'Site agent\\ndurable storage · ACK')]
for x,y,label in boxes:
    ax.add_patch(FancyBboxPatch((x,y),3,1.1,boxstyle='round,pad=.12',facecolor='#E6F2F1',edgecolor=COLORS[0]))
    ax.text(x+1.5,y+.55,label,ha='center',va='center',fontsize=11)
for a,b in [((3.3,3.4),(4.2,2.6)),((3.3,1.2),(4.2,2.1)),((7.4,2.5),(8.5,2.5)),((8.5,1.8),(7.4,1.8))]:
    ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=16,color=COLORS[0]))
ax.text(7.95,2.85,'MQTT',ha='center');ax.text(7.95,1.4,'App ACK',ha='center')
ax.text(6,.25,'Native laboratory: codec, features, rules, queues and freshness — no hardware claims',ha='center',fontsize=11)
ax.set_title('From local evidence to acknowledged storage');savefig('01_architecture')
"""),
md("""
## 3. Build and execute the original host tests

The original test suite compiles the portable libraries with warnings treated as errors. A failed command stops execution. These are software tests, not measurements of physical accuracy. The complete compiler/test log is preserved.

*Optimization:* the Makefile is driven with parallel jobs (`make -j`), the shared protocol library used later is compiled at the same time, and an up-to-date build is reused after a kernel restart.
"""),
analysis("""
T = native_tests()
print(T.log[T.log.find('[PASS]'):])
groups=pd.Series([n.split('_')[0] for n in T.names]).value_counts().sort_values()
fig,ax=newfig(figsize=(9,5));groups.plot.barh(ax=ax,color=COLORS[0]);ax.set(xlabel='Passing original test cases',title='Native test coverage by test-name family');savefig('02_tests')
"""),
md("""
## 4. Compile the experiment harness

The added harness calls `PhysioWindow`, `StationDetector`, `SosButton`, `LinkMonitor` and `RecordBuffer` directly. It exports CSV traces from controlled inputs. The shared library exposes the original C CRC and BLE fragment functions to Python through `ctypes`; it is not a reimplementation.
"""),
analysis("""
X, L = experiments(), native_lib()
print('CSV traces:', ', '.join(sorted(p.name for p in OUT.glob('*.csv'))))
print('Native CRC-16 of "123456789":', hex(L.crc(b'123456789')))
print('Compiled original core and generated experiment CSVs.')
"""),
md("""
## 5. Protocol vectors and integrity

Nineteen supplied vectors include an intentionally corrupted packet. “Expected rejection” is a passing test outcome. The independent Python verifier checks decoded values against the supplied expected fields; the original native CRC is also checked against every vector.
"""),
analysis("""
V = vector_check(); vdf = V.vdf
print(V.log); display(vdf)
fig,ax=newfig(figsize=(11,7));ax.barh(vdf.name,vdf.bytes,color=[COLORS[0] if x else COLORS[3] for x in vdf.crc_valid])
ax.invert_yaxis();ax.set(xlabel='Serialized bytes',title='Supplied protocol vectors (red = intentional CRC failure)');savefig('03_vectors')
"""),
md("""
## 6. Where the bytes go

Full frames carry an 18-byte common header and a 2-byte CRC. COMPACT is a separate 20-byte layout. Header identity includes device, boot and sequence. CRC detects accidental corruption; it provides no authentication or confidentiality.
"""),
analysis("""
first = vector_check().first
layout=pd.DataFrame({'type':['PHYSIO','STATION','EVENT','STATUS','ACK','CONFIG'],
 'header':[18]*6,'payload':[30,32,12,16,8,8],'CRC':[2]*6}).set_index('type')
fig,ax=newfig();layout.plot.barh(stacked=True,ax=ax,color=COLORS[:3]);ax.set(xlabel='Bytes',title='Full-frame byte budget');ax.legend(loc='lower right');savefig('04_frame_budget')
fig,ax=newfig(figsize=(12,2.7));data=np.array(list(first))[None,:]
im=ax.imshow(data,cmap='viridis',aspect='auto',vmin=0,vmax=255)
for i,x in enumerate(first): ax.text(i,0,f'{x:02x}',ha='center',va='center',fontsize=7,color='white' if x<140 else 'black')
ax.axvline(17.5,color='red');ax.axvline(len(first)-2.5,color='red');ax.set(yticks=[],xlabel='Zero-based wire byte offset',title='PHYSIO example: hexadecimal bytes; red lines delimit header and CRC');savefig('05_wire_bytes')
"""),
md("""
## 7. Corruption experiment

Flip each individual bit in one valid frame and recompute its CRC using the compiled library. This finite experiment checks single-bit corruption of this packet only; it does not establish cryptographic security. An attacker can recompute an unkeyed CRC.
"""),
analysis("""
rejected = mutation_check()
fig,ax=newfig(figsize=(12,3));ax.imshow(np.array(rejected).reshape(-1,8).T,cmap='Greens',vmin=0,vmax=1,aspect='auto')
ax.set(xlabel='Byte offset',ylabel='Bit position',title=f'All {len(rejected)} single-bit mutations fail the CRC check');savefig('06_crc_mutations')
"""),
md("""
## 8. BLE fragmentation cost

For an ATT MTU M, the notification value budget is M−3 bytes. This implementation adds a 4-byte fragment header, leaving M−7 bytes per chunk. Native `umsf_frag_count` determines the counts. COMPACT uses its dedicated unfragmented path and is excluded here. The plots count notification value bytes, not radio airtime or total BLE overhead.
"""),
analysis("""
native = native_lib().native
mtus=np.arange(23,248)
lengths={'ACK':28,'EVENT':32,'PHYSIO':50,'STATION':52,'Maximum reassembly':512}
frag=pd.DataFrame({name:[native.umsf_frag_count(n,int(m)-3) for m in mtus] for name,n in lengths.items()},index=mtus)
fig,ax=newfig();frag.plot(ax=ax,drawstyle='steps-post');ax.set(xlabel='ATT MTU (bytes)',ylabel='Notifications per message',title='Native fragmentation counts');savefig('07_fragment_counts')
fig,ax=newfig();
for name in ['PHYSIO','STATION']:
    n=lengths[name];ax.plot(mtus,n/(n+4*frag[name]),label=name)
ax.set(xlabel='ATT MTU (bytes)',ylabel='Frame bytes / notification value bytes',ylim=(.7,1.02),title='Fragment-header efficiency');ax.legend();savefig('08_fragment_efficiency')
"""),
md("""
## 9. Inspect actual native fragments

At the default MTU 23, a 50-byte PHYSIO message becomes four notifications. Fragment order is intentionally reversed, then restored using the encoded fragment index. This transparent Python inspection is separate from the original native reassembly tests, which also exercise out-of-order reception, limits and timeout behavior.
"""),
analysis("""
L, first = native_lib(), vector_check().first
packets=[];att=20;count=L.native.umsf_frag_count(len(first),att)
for i in range(count):
    out=(L.ct.c_uint8*att)();n=L.native.umsf_frag_build(L.arr(first),len(first),7,i,att,out,att)
    packets.append(bytes(out[:n]))
shuffled=packets[::-1]
reconstructed=b''.join(p[4:] for p in sorted(shuffled,key=lambda p:p[2]))
assert reconstructed==first
fd=pd.DataFrame([{'arrival':i,'message_id':int.from_bytes(p[:2],'little'),'index':p[2],
 'count':p[3],'chunk_bytes':len(p)-4,'hex':p.hex()} for i,p in enumerate(shuffled)])
display(fd)
fig,ax=newfig();ax.bar(fd.arrival,fd.chunk_bytes,label='Frame chunk');ax.bar(fd.arrival,[4]*count,bottom=fd.chunk_bytes,label='Fragment header')
ax.set(xticks=fd.arrival,xlabel='Arrival order (reversed)',ylabel='Notification value bytes',title='Actual C-generated fragments at MTU 23');ax.legend();savefig('09_actual_fragments')
"""),
md("""
## 10. Personnel quality: two independent axes

A 10-second window expects 1,000 PPG samples and 250 IMU samples under default configuration. The harness sweeps received sample count and valid PPG fraction. Valid means contact present and neither channel saturated. Quality is a heuristic, not a calibrated probability of correctness. When no PPG samples exist and no missing-channel error is reported, the remaining complete channels can still produce quality 100: channel presence must be read alongside quality.
"""),
analysis("""
phys = experiments().phys
q=phys.query('motion_mg == 0').pivot(index='valid_fraction',columns='completeness',values='quality')
fig,ax=newfig(figsize=(11,5));im=ax.imshow(q,origin='lower',aspect='auto',extent=(-.025,1.025,-.05,1.05),vmin=0,vmax=100,cmap='viridis')
ax.set(xlabel='Received / expected PPG samples',ylabel='Valid / received PPG samples',title='Native heuristic quality (%) — motion-free windows');fig.colorbar(im,ax=ax,label='Quality (%)');savefig('10_quality_surface')
"""),
md("""
## 11. Motion penalty and threshold

Motion is computed as RMS of acceleration-magnitude deviation from 1g: sqrt(mean((|a|−1000 mg)²)). The motion-artifact condition is strictly greater than 150 mg, not greater-or-equal. When set, the internal quality score is halved. The sweep uses a constant acceleration deviation; it is not a human movement dataset.
"""),
analysis("""
phys = experiments().phys
fig,ax=newfig()
for motion,g in phys.query('valid_fraction == 1').groupby('motion_mg'):
    ax.plot(g.completeness,g.quality,label=f'{motion} mg',marker='.' if motion==200 else None)
ax.set(xlabel='PPG completeness',ylabel='Quality (%)',title='Native quality penalty across motion inputs');ax.legend(ncol=3);savefig('11_motion_quality')
fig,ax=newfig();m=phys.query('completeness == 1 and valid_fraction == 1')
ax.plot(m.motion_mg,m.motion_rms,'o-',label='Native motion RMS');ax.axvline(150,color=COLORS[3],ls='--',label='Artifact threshold (>150 mg)')
ax.set(xlabel='Injected magnitude deviation (mg)',ylabel='Reported RMS (mg)',title='Controlled acceleration input and output');ax.legend();savefig('12_motion_rms')
"""),
md("""
## 12. Artifact flags and missing values

Flags identify failure modes independently of numeric values. A null sentinel must become missing data, never zero or a normal reading. The fully missing case has quality 255 on the wire, meaning null. SpO₂ remains missing in every case. Synthetic HR is deliberately enabled only in its named case and carries its channel flag.
"""),
analysis("""
cases = experiments().cases
flag_names=['Motion','No contact','Saturation','Sample gap','Temp error','IMU error']
bits=((cases.artifacts.to_numpy()[:,None] & (1<<np.arange(6)))>0).astype(int)
fig,ax=newfig(figsize=(10,5));ax.imshow(bits,cmap='Oranges',vmin=0,vmax=1,aspect='auto')
ax.set(xticks=range(6),xticklabels=flag_names,yticks=range(len(cases)),yticklabels=cases['case'],title='Artifact flags from native feature windows');savefig('13_artifact_flags')
shown=cases.copy();shown['quality']=shown.quality.replace(255,np.nan)
shown['hr_bpm']=shown.hr.replace(65535,np.nan)/10;shown['spo2_pct']=shown.spo2.replace(65535,np.nan)/10
display(shown[['case','quality','hr_bpm','spo2_pct','channels','artifacts']])
fig,ax=newfig();ax.bar(shown['case'],shown.quality,color=COLORS[0]);ax.tick_params(axis='x',rotation=25)
ax.set(ylabel='Quality (%)',ylim=(0,110),title='Missing quality is a gap, not a zero score');savefig('14_quality_cases')
"""),
md("""
## 13. Synthetic HR is a test pattern

The documented deterministic helper generates 70–80 bpm in a repeated 11-step pattern. This chart visualizes that formula for illustration; it is not an estimator or a recording. The native experiment above separately confirms the synthetic channel flag. Default HR and every SpO₂ field stay null.
"""),
analysis("""
cases = experiments().cases
seq=np.arange(33);synthetic=(700+(seq%11)*10)/10
assert cases.loc[cases['case']=='synthetic_hr','hr'].iloc[0]==770
assert cases.loc[cases['case']!='synthetic_hr','hr'].eq(65535).all()
assert cases.spo2.eq(65535).all()
fig,ax=newfig();ax.step(seq,synthetic,where='mid',color=COLORS[3]);ax.set(xlabel='Synthetic sequence',ylabel='Test field (bpm)',title='Explicitly synthetic HR pattern — not physiological evidence');savefig('15_synthetic_hr')
"""),
md("""
## 14. A controlled stationary-node scenario

A 260-second experiment runs the original detector with 200 Hz acceleration. It injects a brief magnitude excursion, coincident sound/pressure changes, temporary tilt, PIR input, an SOS flag and an uncalibrated gas-voltage rise. Pressure is sampled at 20 Hz, gas at 10 Hz and microphone at 200 Hz in this laboratory. These are test stimulus rates, not a claim about real acquisition fidelity. Saved input traces are downsampled to 40 Hz for compact plotting; detector outputs are one-second windows.
"""),
analysis("""
inp = experiments().inp
fig,axs=newfig(4,1,figsize=(12,9),sharex=True)
for ax,col,label in zip(axs,['accel_z_mg','angle_deg','pressure_pa','gas_mv'],['Z acceleration (mg)','Mount angle (degrees)','Pressure (Pa)','Gas channel (mV)']):
    ax.plot(inp.time_s,inp[col]);ax.set_ylabel(label)
axs[0].set_title('Injected synthetic inputs');axs[-1].set_xlabel('Time (s)');savefig('16_station_inputs')
"""),
md("""
## 15. Impact and pressure response

The default magnitude-excursion threshold is 150 cg = 1.5g relative to gravity magnitude. The impact event closes after 50 ms without another above-threshold sample. The pressure rule compares recent values within a one-second window. This scenario tests event logic; it does not identify the cause of the disturbance.
"""),
analysis("""
st = experiments().st
fig,axs=newfig(2,1,sharex=True,figsize=(11,6))
axs[0].plot(st.time_s,st.peak_cg/100,'o-',label='Peak excursion');axs[0].axhline(1.5,ls='--',color=COLORS[3],label='Threshold')
axs[0].set(ylabel='Excursion (g)',title='Native stationary-window response');axs[0].legend()
axs[1].plot(st.time_s,st.pressure_delta_pa,'o-');axs[1].axhline(100,ls='--',color=COLORS[3])
axs[1].set(xlim=(27,35),xlabel='Time (s)',ylabel='Pressure change (Pa)');savefig('17_impact_pressure')
"""),
md("""
## 16. Tilt and attachment uncertainty

A baseline at (0,0,1g) makes tilt change interpretable relative to the initial mounting. A 12° rotation triggers the 5° default threshold. The tilt alarm clears below 80% of that threshold, but attachment uncertainty remains latched until recommissioning. Returning the numerical angle to zero does not establish that the mounting is verified.
"""),
analysis("""
st = experiments().st
fig,axs=newfig(2,1,sharex=True,figsize=(11,6))
axs[0].plot(st.time_s,st.tilt_delta_ddeg/10,label='Tilt change');axs[0].axhline(5,ls='--',color=COLORS[3]);axs[0].set(ylabel='Degrees',title='Tilt return does not clear attachment uncertainty')
for mask,label in [(32,'Tilt alarm'),(128,'Attachment uncertain')]:axs[1].step(st.time_s,(st['flags'].to_numpy()&mask)>0,label=label,where='post')
axs[1].set(xlim=(50,110),xlabel='Time (s)',ylabel='Flag state');axs[1].legend();savefig('18_tilt_attachment')
"""),
md("""
## 17. Gas warmup, baseline and hysteresis

The MQ channel is a voltage, not ppm and not a gas identity. Before 180 seconds, the baseline is null and gas alarm logic is locked out. After warmup, a rise of at least 300 mV sets the alarm; a rise below 150 mV clears it. The baseline stops adapting while the alarm is active. This synthetic sequence makes all three phases visible.
"""),
analysis("""
st = experiments().st
fig,axs=newfig(2,1,sharex=True,figsize=(12,7))
axs[0].plot(st.time_s,st.gas_mv,label='Window voltage');axs[0].plot(st.time_s,st.baseline_mv,label='Native baseline')
axs[0].fill_between(st.time_s,0,1700,where=st.time_s<=180,color='#CCCCCC',alpha=.3,label='Warmup interval')
axs[0].set(ylim=(800,1700),ylabel='mV',title='Uncalibrated gas channel: warmup and hysteresis');axs[0].legend(ncol=3)
axs[1].step(st.time_s,(st['flags'].to_numpy()&16)>0,label='Gas alarm',where='post');axs[1].step(st.time_s,(st.sensor_flags.to_numpy()&4)>0,label='Gas warm',where='post')
axs[1].set(xlabel='Time (s)',ylabel='Flag state');axs[1].legend();savefig('19_gas_hysteresis')
"""),
md("""
## 18. Presence hold and manual SOS

PIR presence is held for 30 seconds after the falling edge. It indicates channel activity, not a count or identity of people. The SOS trace here is a direct test input to the detector; debouncing and latching are examined separately below. `StationDetector.set_sos` sets a state flag; the node application owns SOS event emission.
"""),
analysis("""
X = experiments(); st, inp = X.st, X.inp
fig,axs=newfig(2,1,sharex=True,figsize=(11,6))
axs[0].plot(inp.time_s,inp.pir,label='Raw PIR input',alpha=.7);axs[0].step(st.time_s,(st['flags'].to_numpy()&1)>0,label='Held presence',where='post')
axs[0].set(ylabel='State',title='Native presence hold and SOS state');axs[0].legend()
axs[1].step(st.time_s,(st['flags'].to_numpy()&2)>0,where='post',color=COLORS[3]);axs[1].set(xlabel='Time (s)',ylabel='SOS state',xlim=(0,140));savefig('20_presence_sos')
"""),
md("""
## 19. Event chronology

The chart uses event timestamps returned by the original detector. A composite can be emitted later while retaining the initiating impact timestamp. The rule requires an impact and nearby sound or pressure evidence within two seconds; it does not establish what caused them. Events have different physical units, so raw values must not be compared on a single magnitude axis.
"""),
analysis("""
events = experiments().events
display(events)
order=list(dict.fromkeys(events.name));idx={name:i for i,name in enumerate(order)}
fig,ax=newfig(figsize=(12,6));scatter=ax.scatter(events.time_s,events.name.map(idx),c=events.level,cmap='plasma',vmin=0,vmax=3,s=80,edgecolors='white')
ax.set(yticks=range(len(order)),yticklabels=order,xlabel='Event timestamp (s)',title='Native event chronology');fig.colorbar(scatter,ax=ax,ticks=range(4),label='Severity code (0–3)');savefig('21_events')
"""),
md("""
## 20. Stationary flags and quality

The bitfield view separates simultaneous conditions. Quality is an availability heuristic averaged over five channel contributions; gas warmup alone changes this scenario from 80% to 100%. It does not measure the probability of an incident, nor guarantee that a mounted sensor retains structural meaning.
"""),
analysis("""
st = experiments().st
labels=['PIR presence','SOS','Impact','Loud sound','Gas alarm','Tilt alarm','Pressure transient','Attachment uncertain']
mat=((st['flags'].to_numpy()[None,:]&(1<<np.arange(8)[:,None]))>0)
fig,ax=newfig(figsize=(12,5));ax.imshow(mat,origin='upper',aspect='auto',cmap='Blues',extent=(.5,260.5,7.5,-.5),vmin=0,vmax=1)
ax.set(yticks=range(8),yticklabels=labels,xlabel='Window end (s)',title='Independent stationary state flags');savefig('22_station_flags')
fig,ax=newfig();ax.plot(st.time_s,st.quality);ax.axvline(180,ls='--',color=COLORS[3],label='Gas warmup ends')
ax.set(xlabel='Time (s)',ylabel='Quality (%)',ylim=(0,105),title='Channel availability is not incident confidence');ax.legend();savefig('23_station_quality')
"""),
md("""
## 21. Button debounce, latch and reset

The input bounces at 100–115 ms and becomes stable at 120 ms. A 30 ms stable press raises the latch at 150 ms. A second press begins at 1,000 ms; after debounce and a further three-second hold, reset occurs at 4,030 ms. The first press cannot reset the latch it just raised.
"""),
analysis("""
button = experiments().button
assert button.loc[button.action==1,'time_ms'].tolist()==[150]
assert button.loc[button.action==2,'time_ms'].tolist()==[4030]
fig,axs=newfig(2,1,figsize=(12,6))
for ax in axs:
    ax.step(button.time_ms,button.raw,label='Raw pressed',alpha=.6,where='post')
    ax.step(button.time_ms,button.active,label='SOS latched',where='post');ax.set_ylabel('State')
axs[0].set(title='Native SOS button state machine',xlim=(0,5000));axs[0].legend()
axs[1].set(xlim=(80,180),xlabel='Time (ms)',title='Debounce detail: stable input + 30 ms');savefig('24_button')
"""),
md("""
## 22. Lost links mean missing evidence

The native monitor marks stationary data lost after age >2,000 ms, and personnel data after age >25,000 ms. This test samples supervision every 100 ms, so loss is observed at the next supervision tick. A new frame restores the state. Link loss says nothing by itself about casualties or structural collapse.
"""),
analysis("""
link = experiments().link
fig,axs=newfig(2,1,sharex=True,figsize=(12,6))
for ax,col,label in zip(axs,['station_state','personnel_state'],['Stationary (2 s threshold)','Personnel (25 s threshold)']):
    ax.step(link.time_ms/1000,link[col],where='post');ax.set(yticks=[0,1,2],yticklabels=['Unknown','Up','Lost'],title=label)
axs[-1].set_xlabel('Time (s)');savefig('25_link_states')
fig,ax=newfig();ax.plot(link.time_ms/1000,link.station_age_ms/1000,label='Stationary age');ax.plot(link.time_ms/1000,link.personnel_age_ms/1000,label='Personnel age')
ax.axhline(2,ls=':',color=COLORS[0]);ax.axhline(25,ls=':',color=COLORS[1]);ax.set(xlabel='Time (s)',ylabel='Age of last received frame (s)',title='Freshness is separate from connectivity');ax.legend();savefig('26_link_age')
"""),
md("""
## 23. RAM retention and acknowledgements

A small eight-record buffer makes eviction easy to see. Sending does not free capacity. MQTT PUBACK is modeled as a no-op because release is an application-layer operation. Requeueing makes unacknowledged records eligible again. ACKs for the wrong source or boot do nothing. A matching cumulative ACK frees sequences at or below its watermark, including any not sent: the caller must only issue a safe watermark after durable commit and gap accounting.
"""),
analysis("""
buf = experiments().buf; display(buf)
fig,ax=newfig(figsize=(12,5))
for col in ['occupancy','evicted','acked']:ax.step(buf.step,buf[col],where='post',label=col)
for s in buf.loc[buf.operation.str.contains('ACK'),'step']:
    ax.axvline(s,color='gray',alpha=.2)
ax.set(xlabel='Operation index (see table)',ylabel='Records',title='Only matching application ACKs release held records');ax.legend();savefig('27_buffer_occupancy')
"""),
md("""
## 24. Priority and retry order

The urgent sequence 3 is sent first, followed by retained telemetry in age order. Retry sends the same held records again: downstream processing needs idempotency by (source, boot, sequence). The trace distinguishes transmissions from unique retained records.
"""),
analysis("""
buf = experiments().buf
sent=buf[buf.selected_seq>=0].copy();sent['attempt']=np.arange(len(sent))
fig,ax=newfig();ax.plot(sent.attempt,sent.selected_seq,'o-',color=COLORS[0]);ax.axvline(7.5,ls='--',color=COLORS[3],label='Retry batch')
ax.set(xlabel='Transmission attempt',ylabel='Selected sequence',title='Native priority selection followed by retransmission');ax.legend();savefig('28_send_order')
assert buf.loc[buf.operation=='MQTT_PUBACK_no_release','occupancy'].iloc[0]==8
assert buf.loc[buf.operation=='wrong_source_ACK','occupancy'].iloc[0]==8
assert buf.loc[buf.operation=='wrong_boot_ACK','occupancy'].iloc[0]==8
assert buf.iloc[-1].occupancy==0
"""),
md("""
## 25. An important priority boundary

Priority chooses the victim among existing records. It does not reject a lower-priority arrival. When all three slots contain urgent records, inserting telemetry evicts the oldest urgent record. The original firmware is preserved; this experiment documents its behavior instead of silently changing it. RAM contents also disappear on reset or power loss.
"""),
analysis("""
edge = experiments().edge; display(edge)
assert edge.retained.tolist()==[0,1,1,1]
fig,ax=newfig();ax.bar(edge.seq,edge.retained,color=[COLORS[3] if p==2 else COLORS[0] for p in edge.priority])
ax.set(xticks=edge.seq,yticks=[0,1],yticklabels=['Evicted','Retained'],xlabel='Sequence (1–3 urgent; 4 telemetry)',title='Priority is victim selection, not guaranteed urgent retention');savefig('29_eviction_boundary')
"""),
md("""
## 26. Capacity planning is a model

The following is an analytic illustration N/r, not a native stress test or a promise of loss-free buffering. It assumes a constant arrival rate and no ACKs. Event bursts, retransmission scheduling and shared-source traffic complicate real operation. A 32-record personnel buffer at one record per 10 seconds spans 320 seconds of arrivals; a 48-record gateway shared by three such streams spans 160 seconds.
"""),
analysis("""
rates=np.geomspace(.1,20,120)
fig,ax=newfig()
for n in [32,48,64]:ax.loglog(rates,n/rates,label=f'{n} records')
ax.scatter([.1,.3],[320,160],color=COLORS[3],s=70,zorder=5)
ax.set(xlabel='Aggregate arrival rate (records/s)',ylabel='Capacity / arrival rate (s)',title='Idealized buffer horizon without application ACKs');ax.legend();savefig('30_capacity_model')
"""),
md("""
## 27. Verification ledger and reproducible exports

This ledger records what this run actually exercised. The original 43-test suite contains more checks than the plotted scenarios. The added assertions focus on the notebook’s critical claims. The site-ACK parser is a limited field extractor, not a strict general-purpose JSON validator; passing its existing tests is not a security audit. Native verification does not validate the ESP32 builds, radio path or hardware. The ledger computes any check that has not run yet, so this cell is self-sufficient as well.
"""),
analysis("""
ledger = verification()
print(json.dumps(ledger, indent=2))
if ledger['figures'] < EXPECTED_FIGURES:
    print(f"Note: {EXPECTED_FIGURES-ledger['figures']} figure(s) not produced yet - run the remaining sections, then this cell again.")
"""),
md("""
## 28. Download the results

The export contains CSV traces, 30 PNG/SVG figures, build/test logs, version information and verification results. It is written to `umsf_firmware_runs/latest/UMSF_Firmware_Lab_results.zip`; in Colab, download it from the Files pane. This cell is self-sufficient: it refreshes the verification ledger itself and reports figure sections not yet executed. The full Zenodo release additionally includes original source, clean and executed notebooks, documentation and provenance.
"""),
analysis("""
ledger = verification()   # cached native checks + current figure count
files=[p for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='SHA256SUMS.txt']
(OUT/'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(OUT).as_posix()}\\n' for p in files))
latest=RUNS/'latest'; latest.mkdir(exist_ok=True)
result_zip=latest/'UMSF_Firmware_Lab_results.zip'
with zipfile.ZipFile(result_zip,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files+[OUT/'SHA256SUMS.txt']: z.write(p,p.relative_to(RUN).as_posix())
print(f"Figures: {ledger['figures']}/{EXPECTED_FIGURES} | original tests: {ledger['original_native_tests']['passed']}/{ledger['original_native_tests']['cases']} passed")
print(f'Results archive: {os.path.relpath(result_zip)} ({result_zip.stat().st_size:,} bytes)')
# Optional: in Colab, uncomment these two lines to open a browser download.
# from google.colab import files
# files.download(str(result_zip))
"""),
md("""
## Interpretation and next experiments

- Change one stimulus at a time in `lab/native_experiments.cpp` (in `umsf_firmware_runs/project/`), then re-run any experiment cell: the runtime rebuilds the harness only when a source is newer than its binary. Run Section 0 again to clear cached results. Compare event timing and flags before interpreting numeric magnitudes.
- Replace a synthetic trace with real sensor data only after specifying units, sampling gaps, calibration, consent and provenance. Never relabel these generated traces as measurements.
- Use `firmware/docs/TEST_PLAN.md` and the hardware commissioning checklist for future device validation. PlatformIO environments are preserved in `firmware/platformio.ini`; their build and flash commands belong to a separate hardware workflow.
- Preserve nulls and identity fields in downstream storage. Do not equate absent data with a safe state, quality with confidence, broker receipt with durable commit, or a local composite with causal attribution.

### Source map and reuse
`firmware/lib/umsf_proto` defines the byte protocol and fragmentation. `umsf_features` implements feature windows and local detectors. `umsf_buffer` implements volatile retention; `umsf_gwcore` implements freshness and ACK field extraction. The original tests and vectors remain in `firmware/test/host` and `firmware/test_vectors.json`. New experiments are in `lab/native_experiments.cpp`; the notebook runtime is `notebook/umsf_fw_lab.py`. The supplied MIT license and author metadata are preserved in the release. Cite `CITATION.cff`; no DOI has been invented. This notebook is an educational and reproducibility companion, not a certified monitoring system.
"""),
    ]


def main():
    sha, text, size = build_payload()
    nb = new_notebook(cells=cells(sha, text, size))
    nb.metadata = {'colab': {'name': 'UMSF_Firmware_Lab.ipynb', 'provenance': [], 'toc_visible': True},
                   'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                   'language_info': {'name': 'python', 'version': '3.12'}}
    for i, cell in enumerate(nb.cells):
        cell['id'] = f'umsf-fw-{i:02d}'
    nbformat.validate(nb)
    nbformat.write(nb, ROOT / 'UMSF_Firmware_Lab.ipynb')
    print(json.dumps({'cells': len(nb.cells), 'code_cells': sum(c.cell_type == 'code' for c in nb.cells),
                      'payload_bytes': size, 'payload_sha256': sha,
                      'notebook_bytes': (ROOT / 'UMSF_Firmware_Lab.ipynb').stat().st_size}, indent=2))


if __name__ == '__main__':
    main()
