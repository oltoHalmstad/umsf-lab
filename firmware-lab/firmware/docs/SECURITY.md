# Security profile

## Implemented: hop-by-hop pilot profile (paper Sec. 3.3.2, 3.3.7, A.2)

| Hop | Protection | Where |
|---|---|---|
| node ↔ gateway | BLE LE Secure Connections pairing with passkey entry (MITM), bonding, encrypted link; ACK/CONFIG characteristics need an encrypted, authenticated link; no notifications before encryption | `src/node_common/node_link.h`, `src/gateway/main.cpp` |
| enrollment | node accepts new bonds only in enrollment mode (button held at power-up, or no bonds yet); unbonded centrals are disconnected afterwards; the gateway connects only to allowlisted addresses and binds each link to the enrolled `device_id` / `source_class` | same |
| gateway ↔ broker | MQTT over TLS with a client certificate (mutual authentication), QoS 1; certificates from LittleFS or `secrets.h`; **no insecure fallback**: missing credentials disable MQTT | `src/gateway/main.cpp` |
| integrity of frames | CRC-16/CCITT-FALSE. This detects corruption only. It is **not** authentication | `lib/umsf_proto` |
| advertising | name `UMSF-<id>` and manufacturer data `0xFFFF` + source class only; no physiological values | `node_link.h` |

**The gateway is a trusted endpoint.** It terminates BLE link security, sees plaintext records,
re-encodes them as JSON and forwards them over TLS. That is the paper's pilot transport profile: it
gives hop-by-hop protection, not end-to-end confidentiality (paper 3.3.2: "Link protection alone does
not provide end-to-end confidentiality when an intermediate service terminates the protected session").

## Known limitations and required work before live use

1. **TLS version.** The pinned core (espressif32 6.9.0 = Arduino-ESP32 2.0.17, mbedTLS 2.28) supports
   TLS 1.2 only. The shared spec asks for TLS 1.3 (paper ref. [32]: "an appropriate candidate"). With this
   core, configure the broker for TLS ≥ 1.2 with mutual authentication and strong ECDHE-AES-GCM suites.
   Moving to Arduino-ESP32 3.x (mbedTLS 3.x, TLS 1.3 when enabled in sdkconfig) also requires
   NimBLE-Arduino 2.x and a port of the BLE callback API. That port is not done.
2. **Static passkey.** Each node has a compile-time 6-digit passkey, also listed in the gateway
   enrollment table. Static passkeys are weaker than per-pairing random passkeys. Enroll in a controlled
   setting, then leave enrollment mode. Revocation means deleting the bond on both sides
   (`NimBLEDevice::deleteBond`) and removing the address from the allowlist. No revocation UI exists yet.
3. **Secrets at rest.** Wi-Fi password, TLS private key and passkeys are stored in flash and NVS without
   flash encryption. Enable ESP32 flash encryption and secure boot for anything beyond the bench.
4. **Local pages.** The soft-AP pages are protected by the WPA2 AP password. The stationary node's
   operator actions (SOS reset, tilt-baseline capture) also need a PIN. HTTP itself is unencrypted on the
   local AP.
5. **CONFIG.** Accepted only from the bonded gateway over an encrypted link, and logged. A protocol-level
   signature over CONFIG is not implemented.
6. **Replay/identity at the site.** The (site, device, boot, sequence) uniqueness, conflict quarantine and
   freshness checks are the site agent's job (P1). The gateway only drops exact duplicates still in its
   buffer.
7. **Device credentials.** A device-signing key and a separate data-encryption key (paper 3.3.2) are not
   present on the nodes.

## Not implemented (explicitly out of scope of release 1.0.0)

- **Target confidential profile**: deterministic CBOR + profiled COSE signing/encryption of records for the
  trusted analysis service, so that a relay can forward protected objects without reading physiology. Not
  implemented. No conformance is claimed.
- **Patent No. 38233 keystream-generation method**: **not implemented**. The available certificate is not
  enough to reproduce or evaluate it (paper 3.3.3). Nothing in this code base is an implementation of, or
  evidence for, that method.
- No claim is made that the ESP32's advertised cryptographic capability amounts to a complete secure
  implementation (paper 3.3.1).

## Safety boundary

The firmware actuates nothing. It does not stop processes, operate ventilation, unlock areas or switch
power (paper 3.3.5). The optional buzzer/LED only indicate local state. This is not a certified safety
device or medical device.

## Reporting

Report suspected vulnerabilities privately to the authors listed in `CITATION.cff` (via their affiliations); do not open public issues for them.
