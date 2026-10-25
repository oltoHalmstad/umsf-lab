/*
  UMSF gateway AG1

  - Receives ESP-NOW broadcasts from fixed (structural) nodes and wearable nodes.
  - Runs a Wi-Fi access point with a local monitoring dashboard.
    Connect to "UMSF_AG1" (password umsf12345) and open http://192.168.4.1
  - Several gateways can run at once: nodes broadcast, so every gateway on the
    same channel receives the same packets.
  - Serial output: EVENT lines and one "W," CSV line per wearable packet,
    suitable for logging measurement sessions.
*/
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <esp_now.h>

#define ESPNOW_CH 1
static const char* GATEWAY_ID  = "AG1";
static const char* AP_SSID     = "UMSF_AG1";
static const char* AP_PASSWORD = "umsf12345";
static const uint32_t OFFLINE_MS = 5000;
static const uint8_t  HR_LOW  = 45;     // heart rate outside this range raises a warning
static const uint8_t  HR_HIGH = 130;

struct NameMap { const char* id; const char* name; };
static const NameMap ZONES[] = {
  {"A01", "Workshop 1 · north wing"},
  {"A02", "Finished goods warehouse"},
  {"A03", "Administration building"},
};
static const NameMap PEOPLE[] = {
  {"W01", "Responder 1"},
  {"W02", "Responder 2"},
  {"W03", "Responder 3"},
};

// ----- Fixed node packet (must match the fixed node firmware) -----
enum : uint16_t {
  F_SHOCK = 1<<0, F_TILT = 1<<1, F_LOUD = 1<<2, F_PRESSURE = 1<<3, F_GAS = 1<<4,
  F_HEAT = 1<<5, F_MOTION = 1<<6, F_VOICE = 1<<7, F_SOS = 1<<8, F_MQ_WARM = 1<<9
};
const uint16_t EVENT_MASK = 0x01FF;

typedef struct __attribute__((packed)) {
  uint32_t magic;
  char     node[4];
  uint32_t seq, uptimeS;
  uint16_t flags;
  uint8_t  sensors;
  float    peakDev, tiltDeg;
  uint16_t sndPeak;
  float    mqV, mqBase, tempC, tempBase, pressHpa, pressJumpPa;
  uint16_t motionAgoS;
} NodePacket;
const uint32_t NODE_MAGIC = 0x46534D55;   // "UMSF"

// ----- Wearable packet (must match the wearable firmware) -----
enum : uint16_t {
  W_FINGER = 1<<0, W_HR_VALID = 1<<1, W_HR_SYNTH = 1<<2, W_MOTION = 1<<3,
  W_IMPACT = 1<<4, W_SOS = 1<<5,
  W_HR_ABN = 1<<8                          // set by the gateway
};
const uint16_t W_LATCH_MASK = W_IMPACT | W_SOS | W_HR_ABN;

typedef struct __attribute__((packed)) {
  uint32_t magic;
  char     node[4];
  uint32_t seq, uptimeS;
  uint16_t flags;
  uint8_t  sensors;
  uint8_t  hrBpm;
  uint8_t  beats;
  uint8_t  led;
  float    pi;
  uint32_t irRaw;
  float    tempC;
  uint16_t motionMg;
  float    peakG;
} WearPacket;
const uint32_t WEAR_MAGIC = 0x57534D55;   // "UMSW"

// ----- State -----
struct NodeState {
  bool used = false, online = false;
  char id[4] = {0};
  NodePacket last = {};
  uint32_t lastSeen = 0, packets = 0, lost = 0;
  uint16_t latched = 0, prevFlags = 0;
  float maxDev = 0, maxPj = 0, maxT = -1000, maxMq = 0;
};

struct WearState {
  bool used = false, online = false;
  char id[4] = {0};
  WearPacket last = {};
  uint32_t lastSeen = 0, packets = 0, lost = 0;
  uint16_t latched = 0, prevFlags = 0;
  float impactG = 0;
  uint8_t hrMin = 0, hrMax = 0;
};

NodeState nodes[6];
WearState people[6];

struct Event { uint32_t ms; char node[4]; uint8_t kind; float value; };
const int MAX_EVENTS = 40;
Event events[MAX_EVENTS];
int evCount = 0, evHead = 0;
enum { EV_ONLINE = 20, EV_OFFLINE = 21, EV_RESET = 22, EV_W_SOS = 30, EV_W_IMPACT = 31, EV_W_HR = 32 };

// ESP-NOW callback runs in the Wi-Fi task: copy raw bytes, process in loop()
struct RawPkt { uint8_t len; uint8_t data[64]; };
const int QN = 16;
RawPkt q[QN];
volatile int qHead = 0, qTail = 0;
portMUX_TYPE qMux = portMUX_INITIALIZER_UNLOCKED;

WebServer server(80);
extern const char PAGE[];

template <size_t N>
const char* lookup(const NameMap (&m)[N], const char* id, const char* fallback) {
  for (auto& e : m) if (strcmp(e.id, id) == 0) return e.name;
  return fallback;
}

template <typename T, size_t N>
T* findSlot(T (&arr)[N], const char* id) {
  for (auto& s : arr) if (s.used && strcmp(s.id, id) == 0) return &s;
  for (auto& s : arr) if (!s.used) {
    s = T();
    s.used = true;
    strncpy(s.id, id, 3); s.id[3] = 0;
    return &s;
  }
  return nullptr;
}

void addEvent(const char* node, uint8_t kind, float value) {
  Event& e = events[evHead];
  e.ms = millis();
  strncpy(e.node, node, 3); e.node[3] = 0;
  e.kind = kind; e.value = value;
  evHead = (evHead + 1) % MAX_EVENTS;
  if (evCount < MAX_EVENTS) evCount++;
  Serial.printf("EVENT,%s,%u,%.2f\n", e.node, kind, value);
}

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
#else
void onRecv(const uint8_t* mac, const uint8_t* data, int len) {
#endif
  if (len < 8 || len > (int)sizeof(RawPkt::data)) return;
  portENTER_CRITICAL(&qMux);
  int next = (qHead + 1) % QN;
  if (next != qTail) {
    q[qHead].len = len;
    memcpy(q[qHead].data, data, len);
    qHead = next;
  }
  portEXIT_CRITICAL(&qMux);
}

float nodeEventValue(const NodePacket& p, int bit) {
  switch (bit) {
    case 0: return p.peakDev;
    case 1: return p.tiltDeg;
    case 2: return p.sndPeak;
    case 3: return p.pressJumpPa;
    case 4: return p.mqV;
    case 5: return p.tempC;
  }
  return NAN;
}

void processNode(NodePacket p) {
  p.node[3] = 0;
  NodeState* n = findSlot(nodes, p.node);
  if (!n) return;
  if (!n->online) { n->online = true; addEvent(n->id, EV_ONLINE, NAN); }
  if (n->packets > 0 && p.seq > n->last.seq + 1) n->lost += p.seq - n->last.seq - 1;

  uint16_t ev = p.flags & EVENT_MASK;
  uint16_t rising = ev & ~n->prevFlags;
  for (int b = 0; b < 9; b++) if (rising & (1 << b)) addEvent(n->id, b, nodeEventValue(p, b));
  n->prevFlags = ev;
  n->latched |= ev & ~(F_MOTION | F_VOICE);

  if (p.peakDev > n->maxDev) n->maxDev = p.peakDev;
  if (p.pressJumpPa > n->maxPj) n->maxPj = p.pressJumpPa;
  if (!isnan(p.tempC) && p.tempC > n->maxT) n->maxT = p.tempC;
  if (!(p.flags & F_MQ_WARM) && p.mqV > n->maxMq) n->maxMq = p.mqV;

  n->last = p;
  n->lastSeen = millis();
  n->packets++;
}

void processWear(WearPacket p) {
  p.node[3] = 0;
  WearState* w = findSlot(people, p.node);
  if (!w) return;
  if (!w->online) { w->online = true; addEvent(w->id, EV_ONLINE, NAN); }
  if (w->packets > 0 && p.seq > w->last.seq + 1) w->lost += p.seq - w->last.seq - 1;

  bool hrValid = (p.flags & W_HR_VALID) && p.hrBpm > 0;
  if (hrValid && (p.hrBpm < HR_LOW || p.hrBpm > HR_HIGH)) p.flags |= W_HR_ABN;

  uint16_t rising = p.flags & ~w->prevFlags;
  if (rising & W_SOS)    addEvent(w->id, EV_W_SOS, NAN);
  if (rising & W_IMPACT) addEvent(w->id, EV_W_IMPACT, p.peakG);
  if (rising & W_HR_ABN) addEvent(w->id, EV_W_HR, p.hrBpm);
  w->prevFlags = p.flags;
  w->latched |= p.flags & W_LATCH_MASK;

  if ((p.flags & W_IMPACT) && p.peakG > w->impactG) w->impactG = p.peakG;
  if (hrValid) {
    if (!w->hrMin || p.hrBpm < w->hrMin) w->hrMin = p.hrBpm;
    if (p.hrBpm > w->hrMax) w->hrMax = p.hrBpm;
  }

  w->last = p;
  w->lastSeen = millis();
  w->packets++;

  // W,id,seq,node_uptime_s,hr_bpm,flags,temp_c,motion_mg,peak_g,pi_pct
  Serial.printf("W,%s,%lu,%lu,%u,0x%03X,%.2f,%u,%.2f,%.2f\n", w->id, (unsigned long)p.seq,
                (unsigned long)p.uptimeS, p.hrBpm, p.flags, p.tempC, p.motionMg, p.peakG, p.pi);
}

void dispatch(const RawPkt& r) {
  uint32_t magic;
  memcpy(&magic, r.data, 4);
  if (magic == NODE_MAGIC && r.len == sizeof(NodePacket)) {
    NodePacket p;
    memcpy(&p, r.data, sizeof(p));
    processNode(p);
  } else if (magic == WEAR_MAGIC && r.len == sizeof(WearPacket)) {
    WearPacket p;
    memcpy(&p, r.data, sizeof(p));
    processWear(p);
  }
}

void checkOffline() {
  uint32_t now = millis();
  for (auto& n : nodes) {
    if (n.used && n.online && now - n.lastSeen > OFFLINE_MS) {
      n.online = false; n.prevFlags = 0;
      addEvent(n.id, EV_OFFLINE, NAN);
    }
  }
  for (auto& w : people) {
    if (w.used && w.online && now - w.lastSeen > OFFLINE_MS) {
      w.online = false; w.prevFlags = 0;
      addEvent(w.id, EV_OFFLINE, NAN);
    }
  }
}

String num(float v, int d = 2) {
  if (isnan(v) || isinf(v) || v < -500) return "null";
  return String(v, d);
}

void handleApi() {
  uint32_t now = millis();
  String j;
  j.reserve(9000);
  auto kv = [&](const char* k, const String& v) { j += ",\""; j += k; j += "\":"; j += v; };

  j += "{\"gw\":\""; j += GATEWAY_ID; j += "\"";
  kv("up", String(now));
  kv("hrLo", String(HR_LOW));
  kv("hrHi", String(HR_HIGH));

  j += ",\"nodes\":[";
  bool first = true;
  for (auto& n : nodes) {
    if (!n.used) continue;
    if (!first) j += ",";
    first = false;
    const NodePacket& p = n.last;
    j += "{\"id\":\""; j += n.id; j += "\"";
    j += ",\"zone\":\""; j += lookup(ZONES, n.id, "Unassigned zone"); j += "\"";
    kv("online", n.online ? "true" : "false");
    kv("age", String(now - n.lastSeen));
    kv("pk", String(n.packets));
    kv("lost", String(n.lost));
    kv("upS", String(p.uptimeS));
    kv("flags", String(p.flags));
    kv("latched", String(n.latched));
    kv("sensors", String(p.sensors));
    kv("pg", num(p.peakDev));
    kv("tilt", num(p.tiltDeg, 1));
    kv("snd", String(p.sndPeak));
    kv("mq", num(p.mqV));
    kv("mqb", num(p.mqBase));
    kv("t", num(p.tempC, 1));
    kv("tb", num(p.tempBase, 1));
    kv("p", num(p.pressHpa, 1));
    kv("pj", num(p.pressJumpPa, 0));
    kv("mot", String(p.motionAgoS));
    j += ",\"mx\":{\"g\":"; j += num(n.maxDev);
    j += ",\"pj\":"; j += num(n.maxPj, 0);
    j += ",\"t\":"; j += num(n.maxT, 1);
    j += ",\"mq\":"; j += num(n.maxMq);
    j += "}}";
  }

  j += "],\"people\":[";
  first = true;
  for (auto& w : people) {
    if (!w.used) continue;
    if (!first) j += ",";
    first = false;
    const WearPacket& p = w.last;
    j += "{\"id\":\""; j += w.id; j += "\"";
    j += ",\"name\":\""; j += lookup(PEOPLE, w.id, w.id); j += "\"";
    kv("online", w.online ? "true" : "false");
    kv("age", String(now - w.lastSeen));
    kv("pk", String(w.packets));
    kv("lost", String(w.lost));
    kv("upS", String(p.uptimeS));
    kv("flags", String(p.flags));
    kv("latched", String(w.latched));
    kv("sensors", String(p.sensors));
    kv("hr", String(p.hrBpm));
    kv("beats", String(p.beats));
    kv("pi", num(p.pi));
    kv("t", num(p.tempC, 1));
    kv("mot", String(p.motionMg));
    j += ",\"mx\":{\"g\":"; j += num(w.impactG, 1);
    j += ",\"hrMin\":"; j += w.hrMin;
    j += ",\"hrMax\":"; j += w.hrMax;
    j += "}}";
  }

  j += "],\"events\":[";
  for (int i = 0; i < evCount; i++) {
    const Event& e = events[(evHead - 1 - i + MAX_EVENTS) % MAX_EVENTS];
    if (i) j += ",";
    j += "{\"ago\":"; j += now - e.ms;
    j += ",\"n\":\""; j += e.node;
    j += "\",\"k\":"; j += e.kind;
    j += ",\"v\":"; j += num(e.value);
    j += "}";
  }
  j += "]}";
  server.send(200, "application/json", j);
}

void handleReset() {
  for (auto& n : nodes) {
    if (!n.used) continue;
    n.latched = 0; n.maxDev = 0; n.maxPj = 0; n.maxT = -1000; n.maxMq = 0;
  }
  for (auto& w : people) {
    if (!w.used) continue;
    w.latched = 0; w.impactG = 0; w.hrMin = 0; w.hrMax = 0;
  }
  evCount = 0; evHead = 0;
  addEvent(GATEWAY_ID, EV_RESET, NAN);
  server.send(200, "application/json", "{\"ok\":true}");
}

void handleRoot() { server.send(200, "text/html; charset=utf-8", PAGE); }

void setup() {
  Serial.begin(115200);
  delay(500);
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_SSID, AP_PASSWORD, ESPNOW_CH);
  Serial.printf("\nUMSF gateway %s | Wi-Fi %s | http://%s | channel %d\n", GATEWAY_ID, AP_SSID,
                WiFi.softAPIP().toString().c_str(), ESPNOW_CH);
  if (esp_now_init() != ESP_OK) Serial.println("ESP-NOW init FAILED");
  esp_now_register_recv_cb(onRecv);

  server.on("/", handleRoot);
  server.on("/api", handleApi);
  server.on("/reset", HTTP_POST, handleReset);
  server.begin();
}

void loop() {
  server.handleClient();
  while (true) {
    RawPkt r;
    bool have = false;
    portENTER_CRITICAL(&qMux);
    if (qTail != qHead) { r = q[qTail]; qTail = (qTail + 1) % QN; have = true; }
    portEXIT_CRITICAL(&qMux);
    if (!have) break;
    dispatch(r);
  }
  static uint32_t tChk = 0;
  if (millis() - tChk > 500) { tChk = millis(); checkOffline(); }
  delay(2);
}

// ===================== Dashboard =====================
const char PAGE[] = R"HTML(<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UMSF · Site monitoring</title>
<style>
:root{--bg:#0a0f16;--pn:#111925;--ln:#1e2a3a;--tx:#e2eaf3;--mu:#8093a8;--ok:#22c55e;--wa:#f59e0b;--cr:#ef4444;--li:#38bdf8;--off:#4b5563}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 22px;border-bottom:1px solid var(--ln)}
.brand b{font-size:17px;letter-spacing:.4px}.brand small{display:block;color:var(--mu)}
.hdr{text-align:right;color:var(--mu);font-size:13px}#clock{font-size:22px;color:var(--tx);font-variant-numeric:tabular-nums}
main{padding:18px 22px;display:grid;gap:16px;grid-template-columns:minmax(0,2fr) minmax(0,1fr)}
@media(max-width:960px){main{grid-template-columns:1fr}}
.banner{grid-column:1/-1;display:flex;gap:18px;align-items:center;padding:20px 24px;border-radius:14px;border:1px solid var(--ln);background:var(--pn);transition:background .3s}
.banner .dot{flex:none;width:20px;height:20px;border-radius:50%;background:var(--mu)}
.banner.ok .dot{background:var(--ok)}
.banner.warn{background:#241a08;border-color:#6b4a0f}.banner.warn .dot{background:var(--wa);animation:pw 1.6s infinite}
.banner.crit{background:#2a0d10;border-color:#7f1d1d}.banner.crit .dot{background:var(--cr);animation:pc 1s infinite}
@keyframes pc{0%{box-shadow:0 0 0 0 rgba(239,68,68,.75)}100%{box-shadow:0 0 0 20px rgba(239,68,68,0)}}
@keyframes pw{0%{box-shadow:0 0 0 0 rgba(245,158,11,.7)}100%{box-shadow:0 0 0 20px rgba(245,158,11,0)}}
.banner h1{margin:0;font-size:24px}.banner p{margin:4px 0 0;color:var(--mu)}
#colmain{display:flex;flex-direction:column;gap:16px;min-width:0}
.sec{margin:4px 0 -4px;font-size:12px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;color:var(--mu)}
.pn{background:var(--pn);border:1px solid var(--ln);border-radius:14px;padding:16px 18px}
.pn h2{margin:0 0 12px;font-size:12px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;color:var(--mu)}
.nh{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:12px}
.nh b{font-size:18px}.nh small{display:block;color:var(--mu)}
.badge{padding:4px 12px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.b-ok{background:#0f2f1c;color:#4ade80}.b-warn{background:#3a2a08;color:#fbbf24}.b-crit{background:#3b0f12;color:#f87171}
.people{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.pc{background:var(--pn);border:1px solid var(--ln);border-radius:14px;padding:14px 16px}
.pc.warn{border-color:#6b4a0f}.pc.crit{border-color:#7f1d1d;background:#1c0d11}.pc.off{opacity:.65}
.pulse{display:flex;align-items:baseline;gap:6px}
.pulse b{font-size:42px;font-variant-numeric:tabular-nums;line-height:1.1}.pulse small{color:var(--mu)}
.heart{color:#f87171;font-size:20px}
.sim{margin-left:4px;padding:2px 7px;border-radius:5px;background:#3a2a08;color:#fbbf24;font-size:10px;font-weight:700;letter-spacing:.6px;align-self:center}
.ps{font-size:11px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;margin-top:2px}
.ps.ok{color:#4ade80}.ps.warn{color:#fbbf24}.ps.off{color:var(--mu)}.ps.sim{color:#fbbf24}
.pc canvas{display:block;width:100%;height:40px;margin-top:8px}
.mini{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.mini div{border:1px solid var(--ln);border-radius:8px;padding:6px 8px;font-size:11px;color:var(--mu)}
.mini b{display:block;color:var(--tx);font-size:15px}
.mini .crit{border-color:#7f1d1d}.mini .crit b{color:#f87171}.mini .life b{color:#7dd3fc}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(205px,1fr));gap:10px}
.t{border:1px solid var(--ln);border-left:4px solid var(--ok);border-radius:10px;padding:11px 12px;background:#0d151f;transition:background .3s}
.t.warn{border-left-color:var(--wa)}.t.crit{border-left-color:var(--cr);background:#1c0d11}
.t.life{border-left-color:var(--li);background:#0b1a26}.t.off{border-left-color:var(--off);opacity:.6}
.t .l{font-size:12px;color:var(--mu)}
.t .v{font-size:26px;font-weight:700;margin:2px 0;font-variant-numeric:tabular-nums}
.t .v small{font-size:13px;color:var(--mu);font-weight:400;margin-left:3px}
.t .s{font-size:11px;font-weight:700;letter-spacing:.6px}
.t.ok .s{color:#4ade80}.t.warn .s{color:#fbbf24}.t.crit .s{color:#f87171}.t.life .s{color:#7dd3fc}.t.off .s{color:var(--mu)}
.t .d{font-size:12px;color:var(--mu);margin-top:4px}
.t canvas{display:block;width:100%;height:34px;margin-top:8px}
.offline{margin-bottom:12px;padding:10px 12px;border-radius:8px;background:#3b0f12;color:#fca5a5;font-weight:600}
.side{display:flex;flex-direction:column;gap:16px;min-width:0}
.life{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
.li{text-align:center;padding:12px 6px;border-radius:10px;border:1px solid var(--ln);color:var(--mu);font-size:12px}
.li b{display:block;font-size:22px;margin-bottom:2px}
.li.on{border-color:var(--li);color:#7dd3fc;background:#0b1a26}.li.sos{border-color:var(--cr);color:#fca5a5;background:#2a0d10}
.as p{margin:0 0 10px}.as p:last-child{margin:0}
.ev{list-style:none;margin:0;padding:0;max-height:380px;overflow:auto}
.ev li{display:grid;grid-template-columns:66px 1fr;gap:8px;padding:8px 0;border-bottom:1px solid var(--ln)}
.ev time{color:var(--mu);font-variant-numeric:tabular-nums;font-size:12px;padding-top:1px}
.ev .k{font-weight:600}.ev .k.crit{color:#f87171}.ev .k.warn{color:#fbbf24}.ev .k.life{color:#7dd3fc}.ev .k.ok{color:#4ade80}
.ev small{color:var(--mu)}
button{width:100%;margin-top:12px;background:#1f2c3b;color:var(--tx);border:1px solid #2c3d52;border-radius:8px;padding:10px 14px;font-weight:600;cursor:pointer}
button:hover{background:#2a3b50}
.muted{color:var(--mu)}.foot{margin-top:12px;font-size:12px;color:var(--mu)}
</style></head><body>
<header><div class="brand"><b>UMSF · Strike impact monitoring</b><small>Gateway AG1 · local network UMSF_AG1 · works without internet</small></div>
<div class="hdr"><div id="clock">--:--:--</div><span id="gw">connecting…</span></div></header>
<main>
<section class="banner" id="banner"><div class="dot"></div><div><h1 id="bt">Connecting to gateway…</h1><p id="bs"></p></div></section>
<div id="colmain">
<h2 class="sec">Personnel</h2><div class="people" id="people"></div>
<h2 class="sec">Structural monitoring</h2><div id="nodes" style="display:flex;flex-direction:column;gap:16px"></div>
</div>
<div class="side">
<section class="pn"><h2>Signs of life</h2><div class="life" id="life"></div><div id="lifec"></div></section>
<section class="pn as"><h2>Situation assessment</h2><div id="assess"></div></section>
<section class="pn"><h2>Event log</h2><ul class="ev" id="ev"></ul><button onclick="resetAll()">Reset alarms</button></section>
</div></main>
<script>
const F={SHOCK:1,TILT:2,LOUD:4,PRESS:8,GAS:16,HEAT:32,MOTION:64,VOICE:128,SOS:256,MQW:512,PIRW:1024};
const S={MPU:1,BMP:2,DS:4,MIC:8,MQ:16,PIR:32};
const W={FINGER:1,HRV:2,SYN:4,MOV:8,IMPACT:16,SOS:32,HRABN:256};
const WS={PPG:1,IMU:2,TEMP:4};
const EV={0:['Structural shock','crit'],1:['Node displaced','warn'],2:['Loud sound','warn'],3:['Pressure jump','crit'],
4:['Smoke or gas','crit'],5:['Temperature rise','crit'],6:['Movement in zone','life'],7:['Voice or knocking','life'],
8:['SOS at fixed node','crit'],20:['Node online','ok'],21:['Link lost','crit'],22:['Alarms reset by operator','ok'],
30:['SOS from person','crit'],31:['Impact or fall','crit'],32:['Heart rate out of range','warn']};
const COL={ok:'#22c55e',warn:'#f59e0b',crit:'#ef4444',life:'#38bdf8',off:'#4b5563'};
const HMAX=60,hist={},names={},$=id=>document.getElementById(id);
const f=(v,d=1)=>v==null||isNaN(v)?'—':Number(v).toFixed(d);
function ago(ms){const s=Math.round(ms/1000);if(s<60)return s+' s';const m=Math.floor(s/60);if(m<60)return m+' min';return Math.floor(m/60)+' h '+(m%60)+' min'}
function clock(ms){return new Date(Date.now()-ms).toLocaleTimeString('en-GB',{hour12:false})}
setInterval(()=>$('clock').textContent=clock(0),1000);
function evVal(k,v){if(v==null)return'';switch(k){case 0:case 31:return f(v,1)+' g';case 1:return f(v,1)+'°';case 2:return'level '+f(v,0);
case 3:return f(v,0)+' Pa';case 4:return f(v,2)+' V';case 5:return f(v,1)+' °C';case 32:return f(v,0)+' bpm'}return''}
function sev(n){const L=n.latched;if(!n.online&&L)return'crit';if(L&(F.SHOCK|F.PRESS|F.SOS|F.GAS|F.HEAT))return'crit';
if(!n.online||(L&(F.TILT|F.LOUD)))return'warn';return'ok'}
function sevP(p){const L=p.latched;if(!p.online&&L)return'crit';if(L&(W.SOS|W.IMPACT))return'crit';
if(!p.online||(L&W.HRABN))return'warn';return'ok'}
const badge=s=>s==='crit'?'ALARM':s==='warn'?'ATTENTION':'NORMAL';
function hrState(p){const C=p.flags;
if(!(p.sensors&WS.PPG))return['No PPG sensor','off'];
if(C&W.SYN)return['Simulated value, not measured','sim'];
if(C&W.HRV)return[C&W.MOV?'Measured · holding during motion':'Measured · '+p.beats+' beats','ok'];
if(!(C&W.FINGER))return['Sensor not on finger','off'];
if(C&W.MOV)return['Motion · reading paused','warn'];
return['Acquiring pulse…','warn']}
function personCard(p){const sv=sevP(p),L=p.latched,C=p.flags,hs=hrState(p),showHr=(C&W.HRV)&&p.hr>0;
let h=`<div class="pc ${p.online?sv:'off'}"><div class="nh"><div><b>${p.name}</b><small>Wearable ${p.id}</small></div><span class="badge b-${sv}">${badge(sv)}</span></div>`;
if(!p.online)h+=`<div class="offline">No link for ${ago(p.age)}</div>`;
h+=`<div class="pulse"><span class="heart">♥</span><b>${showHr?p.hr:'—'}</b><small>bpm</small>${C&W.SYN?'<span class="sim">SIMULATED</span>':''}</div>`;
h+=`<div class="ps ${hs[1]}">${hs[0]}</div><canvas data-p="${p.id}"></canvas>`;
h+=`<div class="mini"><div><span>Skin temperature</span><b>${p.sensors&WS.TEMP?f(p.t,1)+' °C':'—'}</b></div>`;
h+=`<div class="${C&W.MOV?'life':''}"><span>Activity</span><b>${!(p.sensors&WS.IMU)?'—':C&W.MOV?'Moving':'Still'}</b></div>`;
h+=`<div class="${L&W.IMPACT?'crit':''}"><span>Impact / fall</span><b>${L&W.IMPACT?f(p.mx.g,1)+' g':'None'}</b></div>`;
h+=`<div class="${L&W.SOS?'crit':''}"><span>SOS</span><b>${L&W.SOS?'CALLING':'—'}</b></div></div>`;
h+=`<div class="foot">Packets ${p.pk} · lost ${p.lost} · updated ${ago(p.age)} ago</div></div>`;return h}
function tiles(n){
const L=n.latched,C=n.flags,has=b=>n.sensors&b,now=b=>C&b,was=b=>L&b,T=[];
const off=l=>({l,v:'—',u:'',st:'off',s:'NO SENSOR',d:'Sensor is not connected to this node'});
if(!has(S.MPU)){T.push(off('Shock and vibration'));T.push(off('Node position'))}else{
T.push({l:'Shock and vibration',v:f(n.pg,2),u:'g',k:'g',st:was(F.SHOCK)?'crit':'ok',
s:now(F.SHOCK)?'SHOCK NOW':was(F.SHOCK)?'SHOCK RECORDED':'NORMAL',
d:was(F.SHOCK)?`Peak load ${f(n.mx.g,1)} g — strong impact on the structure near the node`:'Structure is steady, no vibration'});
T.push({l:'Node position',v:f(n.tilt,1),u:'°',st:was(F.TILT)?'warn':'ok',s:was(F.TILT)?'NODE DISPLACED':'IN PLACE',
d:was(F.TILT)?'The node has tilted from its initial position — the wall or floor may be deformed':'Deviation from the initial position is within limits'})}
if(!has(S.BMP))T.push(off('Air pressure'));else
T.push({l:'Air pressure',v:f(n.p,1),u:'hPa',k:'p',st:was(F.PRESS)?'crit':'ok',
s:now(F.PRESS)?'BLAST WAVE':was(F.PRESS)?'PRESSURE JUMP RECORDED':'NORMAL',
d:was(F.PRESS)?`Sudden change of ${f(n.mx.pj,0)} Pa — typical sign of a blast wave`:`No sudden changes (fluctuation ${f(n.pj,0)} Pa)`});
T.push({l:'Sound',v:f(n.snd,0),u:'',k:'snd',st:was(F.LOUD)?'warn':now(F.VOICE)?'life':'ok',
s:now(F.LOUD)?'VERY LOUD':now(F.VOICE)?'VOICE / KNOCKING':was(F.LOUD)?'LOUD SOUND RECORDED':'QUIET',
d:now(F.VOICE)?'Repeated sounds — possibly voices or people knocking':was(F.LOUD)?'Explosion-level sound recorded':'No unusual sounds'});
if(now(F.MQW))T.push({l:'Smoke and gas',v:f(n.mq,2),u:'V',k:'mq',st:'off',s:'WARMING UP',d:'Sensor is reaching operating mode, about 1.5 min'});
else{const r=n.mqb>0.05?n.mx.mq/n.mqb:0;T.push({l:'Smoke and gas',v:f(n.mq,2),u:'V',k:'mq',st:was(F.GAS)?'crit':'ok',
s:now(F.GAS)?'SMOKE / GAS NOW':was(F.GAS)?'SMOKE / GAS RECORDED':'CLEAR',
d:was(F.GAS)?`Level rose ${f(r,1)}× above background — possible fire or gas leak`:`Air is clear, background ${f(n.mqb,2)} V`})}
if(!has(S.DS))T.push(off('Temperature'));else{const dt=n.t-n.tb;
T.push({l:'Temperature',v:f(n.t,1),u:'°C',k:'t',st:was(F.HEAT)?'crit':'ok',s:now(F.HEAT)?'HEATING':was(F.HEAT)?'HEATING RECORDED':'NORMAL',
d:was(F.HEAT)?`Temperature reached ${f(n.mx.t,1)} °C — possible fire nearby`:`Background ${f(n.tb,1)} °C, change ${dt>=0?'+':''}${f(dt,1)} °C`})}
if(!has(S.PIR))T.push(off('Movement'));
else if(now(F.PIRW))T.push({l:'Movement',v:'…',u:'',st:'off',s:'CALIBRATING',d:'Motion sensor is calibrating after power-up'});
else T.push({l:'Movement',v:now(F.MOTION)?'yes':'no',u:'',st:now(F.MOTION)?'life':'ok',s:now(F.MOTION)?'PERSON IN ZONE':'NO MOVEMENT',
d:now(F.MOTION)?'Sensor detects a moving warm body':n.mot<65535?`Last movement ${ago(n.mot*1000)} ago`:'No movement since power-up'});
T.push({l:'SOS button',v:was(F.SOS)?'SOS':'—',u:'',st:was(F.SOS)?'crit':'ok',s:was(F.SOS)?'HELP REQUESTED':'NOT PRESSED',
d:was(F.SOS)?'Someone pressed the SOS button on this node':'No calls for help'});
return T}
function spark(cv,a,col){const r=devicePixelRatio||1,w=cv.clientWidth,h=cv.clientHeight;cv.width=w*r;cv.height=h*r;
const c=cv.getContext('2d');c.scale(r,r);if(a.length<2)return;let lo=Math.min(...a),hi=Math.max(...a);if(hi-lo<1e-3){hi+=.5;lo-=.5}
const x=i=>(i+HMAX-a.length)/(HMAX-1)*w,y=v=>h-2-(v-lo)/(hi-lo)*(h-4);
c.beginPath();a.forEach((v,i)=>i?c.lineTo(x(i),y(v)):c.moveTo(x(i),y(v)));c.strokeStyle=col;c.lineWidth=1.6;c.stroke();
c.lineTo(x(a.length-1),h);c.lineTo(x(0),h);c.closePath();c.globalAlpha=.13;c.fillStyle=col;c.fill()}
function render(d){
$('gw').textContent=`Gateway ${d.gw} · up ${ago(d.up)} · ${d.people.length} wearable · ${d.nodes.length} fixed`;
d.nodes.forEach(n=>names[n.id]=n.zone);d.people.forEach(p=>names[p.id]=p.name);
d.nodes.forEach(n=>{if(!n.online)return;const h=hist[n.id]||(hist[n.id]={g:[],p:[],snd:[],mq:[],t:[]});
const push=(k,v)=>{if(v==null)return;h[k].push(v);if(h[k].length>HMAX)h[k].shift()};
push('g',n.pg);push('p',n.p);push('snd',n.snd);push('mq',n.mq);push('t',n.t)});
d.people.forEach(p=>{if(!p.online||!(p.flags&W.HRV)||!p.hr)return;const h=hist['P'+p.id]||(hist['P'+p.id]=[]);
h.push(p.hr);if(h.length>HMAX)h.shift()});
$('people').innerHTML=d.people.length?d.people.map(personCard).join('')
:'<section class="pn"><p class="muted" style="margin:0">No wearable has reported yet. Check that the wearables are powered and on channel 1.</p></section>';
let html='';
if(!d.nodes.length)html='<section class="pn"><p class="muted" style="margin:0">No fixed node has reported yet. Check that the nodes are powered and on channel 1.</p></section>';
d.nodes.forEach(n=>{const sv=sev(n);
html+=`<section class="pn"><div class="nh"><div><b>Node ${n.id}</b><small>${n.zone}</small></div><span class="badge b-${sv}">${badge(sv)}</span></div>`;
if(!n.online)html+=`<div class="offline">No link for ${ago(n.age)} — the node may be damaged. Showing the last received data.</div>`;
html+='<div class="tiles">'+tiles(n).map(t=>`<div class="t ${t.st}"><div class="l">${t.l}</div><div class="v">${t.v}<small>${t.u}</small></div><div class="s">${t.s}</div><div class="d">${t.d}</div>${t.k?`<canvas data-n="${n.id}" data-k="${t.k}" data-c="${t.st}"></canvas>`:''}</div>`).join('')+'</div>';
html+=`<div class="foot">Packets: ${n.pk} · lost: ${n.lost} · data ${ago(n.age)} old · node uptime ${ago(n.upS*1000)}</div></section>`});
$('nodes').innerHTML=html;
document.querySelectorAll('canvas[data-k]').forEach(cv=>spark(cv,(hist[cv.dataset.n]||{})[cv.dataset.k]||[],COL[cv.dataset.c]));
document.querySelectorAll('canvas[data-p]').forEach(cv=>spark(cv,hist['P'+cv.dataset.p]||[],'#f87171'));
side(d)}
function side(d){
let mot=false,voi=false,sos=false,inc=false,worst='ok',withHr=0;const lines=[],bad=[],rank={ok:0,warn:1,crit:2};
d.people.forEach(p=>{const sv=sevP(p),L=p.latched;if(rank[sv]>rank[worst])worst=sv;if(sv!=='ok')bad.push(p.name);
if(p.online&&(p.flags&W.HRV)&&p.hr)withHr++;if(L&W.SOS)sos=true;
const z=`<b>${p.name}</b> (${p.id})`;
if(L&W.SOS)lines.push(`${z}: SOS pressed — the person needs assistance.`);
if(L&W.IMPACT)lines.push(`${z}: impact or fall detected (${f(p.mx.g,1)} g). Check on the person.`);
if(L&W.HRABN)lines.push(`${z}: heart rate left the ${d.hrLo}–${d.hrHi} bpm range (recorded ${p.mx.hrMin}–${p.mx.hrMax} bpm).`);
if(!p.online)lines.push(`${z}: link lost ${ago(p.age)} ago. ${L?'Lost after an alarm — locate the person first.':'Check the wearable battery.'}`)});
d.nodes.forEach(n=>{const sv=sev(n),L=n.latched;if(rank[sv]>rank[worst])worst=sv;if(sv!=='ok')bad.push(n.zone);
if(n.online&&(n.flags&F.MOTION))mot=true;if(n.online&&(n.flags&F.VOICE))voi=true;if(L&F.SOS)sos=true;if(L&(F.SHOCK|F.PRESS))inc=true;
const z=`<b>${n.zone}</b> (node ${n.id})`;
if(L&(F.SHOCK|F.PRESS)){const p=[];if(L&F.SHOCK)p.push(`shock ${f(n.mx.g,1)} g`);if(L&F.PRESS)p.push(`pressure jump ${f(n.mx.pj,0)} Pa`);
lines.push(`${z}: impact recorded — ${p.join(', ')}. Likely a hit or an explosion nearby.`)}
if(L&F.TILT)lines.push(`${z}: node tilted by ${f(n.tilt,1)}°, the structure may be deformed — enter with caution.`);
if(L&(F.GAS|F.HEAT))lines.push(`${z}: signs of fire — ${[(L&F.GAS)?'smoke or gas':'',(L&F.HEAT)?`heating up to ${f(n.mx.t,1)} °C`:''].filter(Boolean).join(' and ')}.`);
if(L&F.SOS)lines.push(`${z}: SOS pressed at the node — someone in the zone needs help.`);
if(!n.online)lines.push(`${z}: link lost ${ago(n.age)} ago. ${L?'Lost after an alarm — the node was probably destroyed.':'Check the node power supply.'}`)});
const b=$('banner'),total=d.nodes.length+d.people.length;b.className='banner '+(total?worst:'');
if(!total){$('bt').textContent='Waiting for data';$('bs').textContent='The gateway is running, no node has reported yet'}
else if(worst==='crit'){$('bt').textContent='ALARM: strike consequences detected';$('bs').textContent='Affected: '+bad.join(', ')}
else if(worst==='warn'){$('bt').textContent='Attention: abnormal situation';$('bs').textContent='Needs checking: '+bad.join(', ')}
else{$('bt').textContent='All clear';$('bs').textContent=`All ${total} nodes online · no threats detected`}
$('life').innerHTML=`<div class="li ${mot?'on':''}"><b>${mot?'●':'○'}</b>Movement</div><div class="li ${voi?'on':''}"><b>${voi?'●':'○'}</b>Voice / knocking</div><div class="li ${sos?'sos':''}"><b>${sos?'●':'○'}</b>SOS</div>`;
let lc=sos?'<b style="color:#fca5a5">Someone is calling for help.</b>'
:(mot||voi)?`<b style="color:#7dd3fc">People are likely present in the zone.</b> ${mot?'Motion is detected. ':''}${voi?'Repeated sounds are heard.':''}`
:inc?'No signs of presence yet. The motion sensor needs line of sight — people under debris may not be visible; the node keeps listening for sounds.'
:'<span class="muted">No one is currently seen or heard in the monitored zones.</span>';
if(d.people.length)lc+=`<p class="muted" style="margin:10px 0 0">Wearables with a pulse reading: ${withHr} of ${d.people.length}</p>`;
$('lifec').innerHTML=lc;
$('assess').innerHTML=lines.length?lines.map(l=>`<p>${l}</p>`).join(''):'<p class="muted">No threats detected. Nodes monitor shocks, blast waves, signs of fire, and the condition of personnel.</p>';
$('ev').innerHTML=d.events.length?d.events.map(e=>{const m=EV[e.k]||['Event '+e.k,'ok'];
return`<li><time>${clock(e.ago)}</time><div><span class="k ${m[1]}">${m[0]}</span> <small>· ${names[e.n]||e.n} ${evVal(e.k,e.v)}</small></div></li>`}).join('')
:'<li><div class="muted" style="grid-column:1/-1">No events yet</div></li>'}
async function tick(){try{const r=await fetch('/api',{cache:'no-store'});render(await r.json())}
catch(e){$('banner').className='banner warn';$('bt').textContent='No connection to the gateway';$('bs').textContent='Check the Wi-Fi connection to UMSF_AG1'}}
async function resetAll(){if(!confirm('Reset all alarms and clear the event log?'))return;await fetch('/reset',{method:'POST'});tick()}
tick();setInterval(tick,1000);
</script></body></html>)HTML";