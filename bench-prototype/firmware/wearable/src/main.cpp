/*
  UMSF prototype - wearable node

  - Sensors: MAX30102 (finger PPG), MPU-6050 (motion, impact), DS18B20 (skin
    temperature), SOS button.
  - Heart rate is estimated on the node and broadcast over ESP-NOW once per
    second, and immediately when a status flag changes (SOS, impact, ...).
    Every gateway on the same Wi-Fi channel receives the broadcast.

  Heart rate pipeline (IR channel, 100 samples/s):
    finger detection -> automatic LED current adjustment -> baseline removal
    -> 2-pole low-pass (~5 Hz) -> adaptive-threshold peak detection
    -> interval checks (refractory period, motion gating, outlier rejection)
    -> median of the last 8 beat-to-beat intervals.
    The estimate is dropped if no interval has been accepted for 10 s.

  HR_SYNTHETIC = 1 sends a simulated heart rate. Such packets carry the
  W_HR_SYNTH flag and the dashboard labels the value as SIMULATED.

  Libraries: OneWire, DallasTemperature, Adafruit MPU6050, Adafruit Unified
  Sensor, SparkFun MAX3010x Pulse and Proximity Sensor Library.
*/

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include "MAX30105.h"

// ===== Node settings =====
#define NODE_ID      "W03"   // W01, W02, W03
#define ESPNOW_CH    1       // must match the gateway
#define HR_SYNTHETIC 0       // 1 = simulated heart rate, flagged in every packet
#define PPG_DEBUG    1       // 0 = TX log, 1 = PPG status every second, 2 = Serial Plotter

// ---------- Pins ----------
static const int I2C_SDA_PIN    = 21;
static const int I2C_SCL_PIN    = 22;
static const int DS18B20_PIN    = 4;
static const int BUTTON_PIN     = 27;
static const int STATUS_LED_PIN = 2;

// ---------- Timing ----------
static const uint32_t SEND_PERIOD_MS     = 1000;
static const uint32_t MIN_GAP_MS         = 100;
static const uint32_t TEMP_PERIOD_MS     = 1000;
static const uint32_t IMU_PERIOD_MS      = 10;
static const uint32_t BUTTON_DEBOUNCE_MS = 60;
static const uint32_t SOS_HOLD_MS        = 30000;
static const uint32_t IMPACT_HOLD_MS     = 30000;

// ---------- PPG ----------
// 400 Hz internal rate with 4x averaging -> 100 samples/s in the FIFO.
static const uint8_t  MAX_ADDR        = 0x57;
static const float    PPG_FS          = 100.0f;
static const uint8_t  LED_START       = 0x24;    // ~7 mA
static const uint8_t  LED_MIN         = 0x08;
static const uint8_t  LED_MAX         = 0x7F;    // ~25 mA

static const uint32_t FINGER_ON_IR    = 30000;
static const uint32_t FINGER_OFF_IR   = 20000;
static const uint32_t IR_TARGET_LOW   = 80000;
static const uint32_t IR_TARGET_HIGH  = 180000;
static const uint32_t IR_SATURATION   = 250000;  // 18-bit full scale is 262143

static const uint16_t SETTLE_SAMPLES  = 150;     // 1.5 s after finger placement / LED change
static const uint16_t MIN_IBI         = 30;      // 200 bpm, in samples
static const uint16_t MAX_IBI         = 200;     // 30 bpm
static const uint16_t BEAT_TIMEOUT    = 300;     // 3 s without a peak -> estimate dropped
static const uint16_t HR_HOLD_SAMPLES = 1000;    // 10 s without an accepted interval -> dropped
static const float    BEAT_THR_RATIO  = 0.5f;
static const float    PI_MIN          = 0.0005f;
static const float    PI_MAX          = 0.05f;
static const uint8_t  IBI_BUF         = 8;
static const uint8_t  IBI_MIN_FOR_HR  = 4;

// ---------- Motion / impact ----------
// Motion: change of the acceleration vector over 50 ms (offset-insensitive).
static const uint16_t MOTION_ARTIFACT_MG = 60;
static const uint32_t MOTION_GATE_MS     = 1000;
static const float    IMPACT_G           = 3.0f;   // |a| above this = impact / fall

// ---------- Packet ----------
enum : uint16_t {
  W_FINGER = 1<<0, W_HR_VALID = 1<<1, W_HR_SYNTH = 1<<2,
  W_MOTION = 1<<3, W_IMPACT = 1<<4, W_SOS = 1<<5
};
enum : uint8_t { WS_PPG = 1<<0, WS_IMU = 1<<1, WS_TEMP = 1<<2 };

typedef struct __attribute__((packed)) {
  uint32_t magic;
  char     node[4];
  uint32_t seq, uptimeS;
  uint16_t flags;
  uint8_t  sensors;
  uint8_t  hrBpm;        // 0 = no estimate
  uint8_t  beats;        // intervals in the HR median
  uint8_t  led;
  float    pi;           // perfusion index, %
  uint32_t irRaw;
  float    tempC;        // NAN if not available
  uint16_t motionMg;     // peak motion since the previous packet
  float    peakG;        // peak |a| since the previous packet
} WearPacket;
const uint32_t WEAR_MAGIC = 0x57534D55;   // "UMSW"

OneWire oneWire(DS18B20_PIN);
DallasTemperature tempSensor(&oneWire);
DeviceAddress tempAddr;
Adafruit_MPU6050 mpu;
MAX30105 max30102;

uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
bool hasTemp = false, hasMpu = false, hasMax = false;
uint8_t sensors = 0;

uint32_t seq = 0, lastSendMs = 0, lastTempMs = 0, ledOffMs = 0;
uint32_t untilSos = 0, untilImpact = 0;
uint16_t lastFlags = 0;
float tempC = NAN;

uint32_t lastButtonChangeMs = 0;
bool lastButtonState = HIGH, stableButtonState = HIGH;

uint32_t lastImuMs = 0, lastArtifactMs = 0;
uint8_t  imuDiv = 0;
uint16_t motionPeakMg = 0, motionDebugMg = 0;
float    peakG = 0;
float    prevAx = 0, prevAy = 0, prevAz = 0;
bool     havePrevAccel = false;

struct PpgState {
  bool     finger = false;
  uint8_t  led = LED_START;
  uint32_t n = 0;
  uint32_t lastIr = 0;
  uint32_t settleUntil = 0;
  uint32_t lastBeat = 0;
  uint32_t lastAcceptN = 0;
  float    dc = 0, lp1 = 0, lp2 = 0;
  float    prev1 = 0, prev2 = 0;
  float    env = 0;
  uint16_t ibi[IBI_BUF];
  uint8_t  ibiCount = 0, ibiHead = 0, rejects = 0;
  uint8_t  hr = 0;
  uint32_t overflows = 0;
  uint16_t peaks = 0, rejMotion = 0, rejPi = 0, rejOutlier = 0, rejLong = 0;
} ppg;

bool active(uint32_t until) {
  return until && (int32_t)(until - millis()) > 0;
}

// ---------- Motion ----------

bool motionRecent() {
  return lastArtifactMs && millis() - lastArtifactMs < MOTION_GATE_MS;
}

void pollMotion() {
  if (!hasMpu || millis() - lastImuMs < IMU_PERIOD_MS) return;
  lastImuMs = millis();

  sensors_event_t accel, gyro, temp;
  mpu.getEvent(&accel, &gyro, &temp);
  float ax = accel.acceleration.x / 9.80665f;
  float ay = accel.acceleration.y / 9.80665f;
  float az = accel.acceleration.z / 9.80665f;

  float mag = sqrtf(ax * ax + ay * ay + az * az);
  if (mag > peakG) peakG = mag;
  if (mag > IMPACT_G) untilImpact = millis() + IMPACT_HOLD_MS;

  if (++imuDiv < 5) return;          // motion metric every 50 ms
  imuDiv = 0;
  if (havePrevAccel) {
    float dx = ax - prevAx, dy = ay - prevAy, dz = az - prevAz;
    uint16_t mg = (uint16_t)min(65535.0f, sqrtf(dx * dx + dy * dy + dz * dz) * 1000.0f);
    if (mg > motionPeakMg) motionPeakMg = mg;
    if (mg > motionDebugMg) motionDebugMg = mg;
    if (mg > MOTION_ARTIFACT_MG) lastArtifactMs = millis();
  }
  prevAx = ax; prevAy = ay; prevAz = az;
  havePrevAccel = true;
}

// ---------- PPG processing ----------

void setLed(uint8_t level) {
  ppg.led = level;
  max30102.setPulseAmplitudeIR(level);
  max30102.setPulseAmplitudeRed(level);
}

void ppgResetDetector() {
  ppg.settleUntil = ppg.n + SETTLE_SAMPLES;
  ppg.lastBeat = 0;
  ppg.env = 0;
  ppg.ibiCount = ppg.ibiHead = ppg.rejects = 0;
  ppg.hr = 0;
}

uint16_t medianIbi() {
  uint16_t s[IBI_BUF];
  uint8_t k = ppg.ibiCount;
  for (uint8_t i = 0; i < k; i++) s[i] = ppg.ibi[i];
  for (uint8_t i = 1; i < k; i++) {
    uint16_t v = s[i];
    int8_t j = i - 1;
    while (j >= 0 && s[j] > v) { s[j + 1] = s[j]; j--; }
    s[j + 1] = v;
  }
  return (k & 1) ? s[k / 2] : (s[k / 2 - 1] + s[k / 2]) / 2;
}

void acceptInterval(uint16_t ibi) {
  if (ppg.ibiCount >= 3) {
    uint16_t m = medianIbi();
    if (abs((int)ibi - (int)m) > m * 0.3f) {
      ppg.rejOutlier++;
      if (++ppg.rejects >= 3) {
        ppg.ibiCount = ppg.ibiHead = ppg.rejects = 0;
        ppg.hr = 0;
      }
      return;
    }
  }
  ppg.rejects = 0;
  ppg.lastAcceptN = ppg.n;
  ppg.ibi[ppg.ibiHead] = ibi;
  ppg.ibiHead = (ppg.ibiHead + 1) % IBI_BUF;
  if (ppg.ibiCount < IBI_BUF) ppg.ibiCount++;
  if (ppg.ibiCount >= IBI_MIN_FOR_HR) ppg.hr = (uint8_t)lroundf(60.0f * PPG_FS / medianIbi());
}

void ppgAutoLevel() {
  bool saturated = ppg.dc > IR_SATURATION;
  bool outside = ppg.dc < IR_TARGET_LOW || ppg.dc > IR_TARGET_HIGH;
  if (!saturated && (!outside || ppg.hr)) return;

  float target = 0.5f * (IR_TARGET_LOW + IR_TARGET_HIGH);
  int level = constrain((int)lroundf(ppg.led * target / ppg.dc), LED_MIN, LED_MAX);
  if (level == ppg.led) return;

  ppg.dc *= (float)level / ppg.led;
  setLed(level);
  ppgResetDetector();
}

void processPpgSample(uint32_t ir) {
  ppg.n++;
  ppg.lastIr = ir;

  if (!ppg.finger) {
    if (ir < FINGER_ON_IR) return;
    ppg.finger = true;
    ppg.dc = ir;
    ppg.lp1 = ppg.lp2 = ppg.prev1 = ppg.prev2 = 0;
    ppgResetDetector();
  } else if (ir < FINGER_OFF_IR) {
    ppg.finger = false;
    ppg.hr = 0;
    setLed(LED_START);
    return;
  }

  if (ppg.n % 50 == 0) ppgAutoLevel();

  bool settling = ppg.n < ppg.settleUntil;
  ppg.dc += ((float)ir - ppg.dc) * (settling ? 0.05f : 0.0067f);
  float ac = ppg.dc - (float)ir;          // systolic peaks become positive
  ppg.lp1 += (ac - ppg.lp1) * 0.25f;
  ppg.lp2 += (ppg.lp1 - ppg.lp2) * 0.25f;
  float x = ppg.lp2;

  float thr = 0;
  bool beat = false;

  if (settling) {
    ppg.env = 0;
  } else {
    ppg.env *= 0.995f;
    if (x > ppg.env) ppg.env = x;
    thr = BEAT_THR_RATIO * ppg.env;

    float pi = ppg.env / ppg.dc;
    bool moving = motionRecent();
    bool piOk = pi > PI_MIN && pi < PI_MAX;

    uint16_t refractory = MIN_IBI;
    if (ppg.ibiCount >= 3) {
      uint16_t r = medianIbi() * 6 / 10;
      if (r > refractory) refractory = r;
    }

    bool isPeak = ppg.prev1 > ppg.prev2 && ppg.prev1 >= x && ppg.prev1 > thr;
    uint32_t peakN = ppg.n - 1;
    if (isPeak && (ppg.lastBeat == 0 || peakN - ppg.lastBeat >= refractory)) {
      ppg.peaks++;
      if (ppg.lastBeat) {
        uint32_t ibi = peakN - ppg.lastBeat;
        if (moving)              ppg.rejMotion++;
        else if (!piOk)          ppg.rejPi++;
        else if (ibi > MAX_IBI)  ppg.rejLong++;
        else                     acceptInterval((uint16_t)ibi);
      }
      ppg.lastBeat = peakN;
      beat = true;
    }

    if (ppg.lastBeat && ppg.n - ppg.lastBeat > BEAT_TIMEOUT) {
      ppg.lastBeat = 0;
      ppg.ibiCount = ppg.ibiHead = 0;
      ppg.hr = 0;
    }
    // Do not keep reporting an old value (e.g. during long movement).
    if (ppg.hr && ppg.n - ppg.lastAcceptN > HR_HOLD_SAMPLES) {
      ppg.ibiCount = ppg.ibiHead = 0;
      ppg.hr = 0;
    }
  }

  ppg.prev2 = ppg.prev1;
  ppg.prev1 = x;

#if PPG_DEBUG == 2
  Serial.printf("ppg:%.0f,thr:%.0f,beat:%.0f\n", x, thr, beat ? ppg.env : 0.0f);
#else
  (void)beat;
#endif
}

uint8_t maxReadReg(uint8_t reg) {
  Wire.beginTransmission(MAX_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0;
  if (Wire.requestFrom((uint8_t)MAX_ADDR, (uint8_t)1) != 1) return 0;
  return Wire.read();
}

void pollPpg() {
  if (!hasMax) return;

  uint8_t wr  = maxReadReg(0x04) & 0x1F;
  uint8_t ovf = maxReadReg(0x05) & 0x1F;
  uint8_t rd  = maxReadReg(0x06) & 0x1F;

  if (ovf) {
    max30102.clearFIFO();
    ppgResetDetector();
    ppg.overflows++;
    return;
  }

  uint8_t pending = (wr - rd) & 0x1F;
  while (pending) {
    uint8_t batch = min<uint8_t>(pending, 16);
    uint8_t buf[16 * 6];

    Wire.beginTransmission(MAX_ADDR);
    Wire.write(0x07);
    if (Wire.endTransmission(false) != 0) return;
    uint8_t len = batch * 6;
    if (Wire.requestFrom((uint8_t)MAX_ADDR, len) != len) return;
    for (uint8_t i = 0; i < len; i++) buf[i] = Wire.read();

    for (uint8_t i = 0; i < batch; i++) {
      const uint8_t* s = buf + i * 6;      // red: bytes 0-2, IR: bytes 3-5
      uint32_t ir = (((uint32_t)s[3] << 16) | ((uint32_t)s[4] << 8) | s[5]) & 0x3FFFF;
      processPpgSample(ir);
    }
    pending -= batch;
  }
}

// ---------- Setup helpers ----------

void setupSensors() {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);

  tempSensor.begin();
  hasTemp = tempSensor.getAddress(tempAddr, 0);
  if (hasTemp) {
    tempSensor.setResolution(tempAddr, 12);
    tempSensor.setWaitForConversion(false);
    tempSensor.requestTemperaturesByAddress(tempAddr);
    sensors |= WS_TEMP;
  }

  hasMpu = mpu.begin(0x68, &Wire);
  if (hasMpu) {
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);
    sensors |= WS_IMU;
  }

  hasMax = max30102.begin(Wire, I2C_SPEED_FAST);
  if (hasMax) {
    max30102.setup(LED_START, 4, 2, 400, 411, 4096);
    max30102.clearFIFO();
    sensors |= WS_PPG;
  }
}

void setupEspNow() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(ESPNOW_CH, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init FAILED");
    return;
  }
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = ESPNOW_CH;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
}

// ---------- Packet ----------

void readTemp() {
  if (!hasTemp) return;
  float c = tempSensor.getTempC(tempAddr);    // result of the previous request
  tempSensor.requestTemperaturesByAddress(tempAddr);
  if (c != DEVICE_DISCONNECTED_C && c > -55 && c < 125) tempC = c;
}

uint8_t currentHr() {
#if HR_SYNTHETIC
  // Slow 60 s oscillation around 74 bpm.
  return (uint8_t)lroundf(74.0f + 4.0f * sinf(millis() * (TWO_PI / 60000.0f)));
#else
  return ppg.hr;
#endif
}

uint16_t buildFlags() {
  uint16_t f = 0;
  if (ppg.finger) f |= W_FINGER;
#if HR_SYNTHETIC
  f |= W_HR_VALID | W_HR_SYNTH;
#else
  if (ppg.hr) f |= W_HR_VALID;
#endif
  if (motionRecent()) f |= W_MOTION;
  if (active(untilImpact)) f |= W_IMPACT;
  if (active(untilSos)) f |= W_SOS;
  return f;
}

void sendPacket(uint16_t flags) {
  WearPacket p = {};
  p.magic = WEAR_MAGIC;
  strncpy(p.node, NODE_ID, 3);
  p.seq = ++seq;
  p.uptimeS = millis() / 1000;
  p.flags = flags;
  p.sensors = sensors;
  p.hrBpm = currentHr();
  p.beats = ppg.ibiCount;
  p.led = ppg.led;
  p.pi = (ppg.finger && ppg.dc > 0) ? 100.0f * ppg.env / ppg.dc : 0.0f;
  p.irRaw = ppg.lastIr;
  p.tempC = tempC;
  p.motionMg = motionPeakMg;
  p.peakG = peakG;
  esp_now_send(BCAST, (uint8_t*)&p, sizeof(p));

#if PPG_DEBUG == 0
  Serial.printf("TX #%lu flags=0x%02X hr=%u%s T=%.2f motion=%u peak=%.2fg\n",
                (unsigned long)p.seq, flags, p.hrBpm, (flags & W_HR_SYNTH) ? "(sim)" : "",
                tempC, motionPeakMg, peakG);
#endif

  motionPeakMg = 0;
  peakG = 0;
  digitalWrite(STATUS_LED_PIN, HIGH);
  ledOffMs = millis() + 20;
}

void handleButton() {
  bool reading = digitalRead(BUTTON_PIN);
  if (reading != lastButtonState) {
    lastButtonChangeMs = millis();
    lastButtonState = reading;
  }
  if (millis() - lastButtonChangeMs > BUTTON_DEBOUNCE_MS && reading != stableButtonState) {
    stableButtonState = reading;
    if (stableButtonState == LOW) untilSos = millis() + SOS_HOLD_MS;
  }
}

void printPpgStatus() {
  static uint32_t last = 0;
  if (millis() - last < 1000) return;
  last = millis();
  float pi = (ppg.finger && ppg.dc > 0) ? 100.0f * ppg.env / ppg.dc : 0.0f;
  Serial.printf("PPG raw=%lu finger=%d led=0x%02X pi=%.2f%% peaks=%u rej[mot=%u pi=%u out=%u long=%u] "
                "beats=%u hr=%u motion=%umg ovf=%lu\n",
                (unsigned long)ppg.lastIr, ppg.finger, ppg.led, pi,
                ppg.peaks, ppg.rejMotion, ppg.rejPi, ppg.rejOutlier, ppg.rejLong,
                ppg.ibiCount, ppg.hr, motionDebugMg, (unsigned long)ppg.overflows);
  ppg.peaks = ppg.rejMotion = ppg.rejPi = ppg.rejOutlier = ppg.rejLong = 0;
  motionDebugMg = 0;
}

void setup() {
  pinMode(STATUS_LED_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  Serial.begin(115200);
  delay(800);
  Serial.printf("\nUMSF wearable %s starting\n", NODE_ID);

  setupSensors();
  setupEspNow();

  Serial.printf("MAX30102:%s MPU-6050:%s DS18B20:%s | MAC %s | channel %d%s\n",
                hasMax ? "OK" : "NOT FOUND", hasMpu ? "OK" : "NOT FOUND", hasTemp ? "OK" : "NOT FOUND",
                WiFi.macAddress().c_str(), ESPNOW_CH, HR_SYNTHETIC ? " | HR SIMULATED" : "");

  for (int i = 0; i < 3; i++) {
    digitalWrite(STATUS_LED_PIN, HIGH); delay(80);
    digitalWrite(STATUS_LED_PIN, LOW);  delay(80);
  }
  if (hasMax) max30102.clearFIFO();
}

void loop() {
  pollPpg();
  pollMotion();
  handleButton();

  uint32_t now = millis();
  if (now - lastTempMs >= TEMP_PERIOD_MS) {
    lastTempMs = now;
    readTemp();
  }

  uint16_t flags = buildFlags();
  bool periodic = now - lastSendMs >= SEND_PERIOD_MS;
  bool changed = flags != lastFlags && now - lastSendMs >= MIN_GAP_MS;
  if (periodic || changed) {
    lastSendMs = now;
    lastFlags = flags;
    sendPacket(flags);
  }

  if (ledOffMs && (int32_t)(millis() - ledOffMs) >= 0) {
    digitalWrite(STATUS_LED_PIN, LOW);
    ledOffMs = 0;
  }

#if PPG_DEBUG == 1
  printPpgStatus();
#endif

  delay(2);
}