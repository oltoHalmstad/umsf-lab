// secrets.example.h - copy to include/secrets.h (git-ignored) and fill in real values.
// Never commit real credentials, passkeys or private keys. The values below are placeholders.
#pragma once

// ---------------- stationary node: local soft-AP page (192.168.4.1) ----------------
#define UMSF_AP_PASSWORD "change-me-ap-pass"   // WPA2, >= 8 characters
#define UMSF_OPERATOR_PIN "0000"               // required for operator SOS reset / commissioning

// ---------------- gateway: Wi-Fi station + local status AP ----------------
#define UMSF_WIFI_SSID "HEALTH-GW"
#define UMSF_WIFI_PASSWORD "change-me"
#define UMSF_GW_AP_PASSWORD "change-me-gw-ap"
#define UMSF_NTP_SERVER_1 "10.0.0.1"           // site NTP server (preferred over public pools)
#define UMSF_NTP_SERVER_2 "pool.ntp.org"

// ---------------- gateway: MQTT over TLS with client certificate ----------------
#define UMSF_MQTT_HOST "broker.site-a.local"
#define UMSF_MQTT_PORT 8883
#define UMSF_DATA_ORIGIN "synthetic_payload_physical_transport"  // label, not proof (paper 3.3.8)
#define UMSF_SCENARIO_ID nullptr                                  // e.g. "S0"; nullptr -> JSON null

// PEM strings used only if /ca.pem, /client.crt, /client.key are absent from LittleFS.
#define UMSF_CA_PEM ""
#define UMSF_CLIENT_CRT_PEM ""
#define UMSF_CLIENT_KEY_PEM ""

// ---------------- gateway: enrollment allowlist (max 3 active links) ----------------
// {device_id, BLE public address, source_class, passkey, zone_code, zone_id, attachment_verified}
// source_class: 1 personnel, 2 stationary. attachment_verified = mounting verified at commissioning.
#define UMSF_ENROLLED_NODES                                                     \
    {                                                                           \
        {"A01", "24:6f:28:00:00:01", 1, 123456, 1, "Z1", false},                \
        {"A02", "24:6f:28:00:00:02", 1, 223456, 1, "Z1", false},                \
        {"S01", "24:6f:28:00:00:11", 2, 654321, 1, "Z1", false},                \
    }
// Bench synthetic HR test field written to personnel nodes in CONFIG (0 = off, default).
#define UMSF_CONFIG_SYNTHETIC_HR 0
