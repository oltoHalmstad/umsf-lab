# Fixed (structural) node A01–A03

The source of the fixed-node firmware is **not included** in this version of the archive.

The gateway accepts fixed-node data only in the format below. A compatible firmware must
broadcast a 55-byte `NodePacket` with magic `0x46534D55` over ESP-NOW on channel 1
(see `docs/PROTOCOL.md`, section 3):

```c
typedef struct __attribute__((packed)) {
  uint32_t magic;            // 0x46534D55 ("UMSF")
  char     node[4];          // "A01"
  uint32_t seq, uptimeS;
  uint16_t flags;            // F_SHOCK..F_SOS (bits 0-8), F_MQ_WARM (9), PIR warm-up (10)
  uint8_t  sensors;          // MPU, BMP, DS, MIC, MQ, PIR (bits 0-5)
  float    peakDev, tiltDeg;
  uint16_t sndPeak;
  float    mqV, mqBase, tempC, tempBase, pressHpa, pressJumpPa;
  uint16_t motionAgoS;
} NodePacket;
```

Zone names for `A01`–`A03` are set in `ZONES[]` in `firmware/gateway/src/main.cpp`.
