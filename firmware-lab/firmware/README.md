# umsf-ble-firmware 1.0.0

**Прошивки ESP32 для збирання набору даних і об'єднання вузлів у Bluetooth-канал**
(персональний вузол, стаціонарний вузол стану будівлі, BLE-шлюз). Це проєкт P2 супровідного пакета до
статті *Evidence-Aware Multisensor Monitoring for Critical Infrastructure Incident Support*
(Torstensson, Prokopovych-Tkachenko, Adilzhanova, Tykhonenko, Beketova, Sydybayeva, 2026).

> **Не є сертифікованим засобом безпеки чи медичним виробом.** Прошивка нічим не керує: не зупиняє
> процесів, не вмикає вентиляцію, не відмикає приміщення й не перемикає живлення. Вона лише повідомляє.

## English abstract

ESP32 firmware for the UMSF evidence-aware monitoring pilot. A *personnel node* (MAX30102 PPG, DS18B20
contact temperature, MPU-6050 motion, help button, optional GSR) produces one 50-byte PHYSIO_FEATURE
frame per 10 s window. A *stationary building-state node* (MPU-6050 at 200 Hz ±16 g, BMP280, MQ-2,
microphone, PIR, SOS button) produces 1 s STATION_STATE frames, 200 ms 20-byte COMPACT packets and
immediate EVENT frames, and serves a local Ukrainian page at 192.168.4.1. A *BLE gateway* (NimBLE
central) connects to up to three enrolled nodes and merges their notifications into one ordered uplink
stream with per-source identity. Each frame goes through reassembly and a CRC check, the source identity
is bound to the authenticated link, and the record is published as JSON (schemas 1.0 / st-1.0 / ev-1.0,
with the raw `frame_hex`) over MQTT QoS 1 with mutually authenticated TLS. Records are released from the
node and gateway RAM buffers only by an application ACK issued after the site agent's durable commit.
All non-hardware logic is portable C/C++ in `lib/` and covered by host unit tests (43 test cases, all
passing with g++ 13). **The three ESP32 firmware images were not compiled and have not been tested on
hardware in this release.** HR is a flagged synthetic test field or null, SpO2 is always null, detector
thresholds are uncalibrated, and the local composite `possible_impact_local` is unverified. It never
attributes a strike.

## Межі доказовості (обов'язково прочитати)

| Що є | Чого немає |
|---|---|
| Портативні бібліотеки (`lib/`) зібрано g++/gcc і перевірено модульними тестами на хості: **43 тести, усі пройдено** | Жодну з трьох прошивок ESP32 **не скомпільовано** в цьому випуску: у середовищі збирання реєстр PlatformIO був недоступний |
| Код апаратного рівня написано під API NimBLE-Arduino 1.4.x, Arduino-ESP32 2.0.x та бібліотек датчиків; синтаксис перевірено лише проти власних заглушок API | Прошивки **не випробувано на апаратурі**: немає вимірювань часу, енергоспоживання, дальності чи співіснування BLE/Wi-Fi |
| Тестові вектори `test_vectors.json` згенеровано кодеком і незалежно перевірено Python-декодером, написаним за специфікацією | Фізіологічної валідності немає. ЧСС — синтетичне тестове поле (з прапорцем HR_SYNTHETIC) або null; SpO2 завжди null |
| Порогові правила детекторів, усі в одній структурі з `rule_version` | Пороги **не калібровано**. Канал MQ-2 — некалібрована напруга. Механічні значення не вимірюють пошкоджень. PIR і звук — лише ознаки *можливої* присутності |
| Захист «від вузла до вузла» (hop-by-hop): BLE LE Secure Connections + mTLS MQTT; шлюз є довіреною ланкою | Цільовий профіль COSE/CBOR **не реалізовано**. Метод генерації ключового потоку за патентом № 38233 **не реалізовано** |

Значення стенда Stage 2 (0,03 g; 0,4°; 1003,7 гПа; 15,3 g тощо) не калібровано. Вони не визначають
діапазон датчика чи енергію удару (розд. 3.8.3 статті). Втрата зв'язку означає «стан невідомий», а не
руйнування чи постраждалих.

## Структура

```
lib/umsf_proto/      C99: кадри, CRC-16/CCITT-FALSE, null-сентинели, фрагментація, COMPACT, текстовий рядок, JSON, час
lib/umsf_buffer/     C++17: RAM-буфер непідтверджених записів (вузол ≥30, шлюз ≥18), кумулятивний ACK, витіснення
lib/umsf_features/   C++17: ознаки PPG/IMU, детектори стаціонарного вузла, кнопка SOS, RuleConfig (rule_version)
lib/umsf_gwcore/     C++17: нагляд за зв'язком (link_loss/link_restored), розбір ACK сайт-агента, allowlist
src/personnel_node/  прошивка персонального вузла
src/stationary_node/ прошивка стаціонарного вузла + локальна сторінка (192.168.4.1)
src/gateway/         прошивка BLE-шлюзу + сторінка стану (192.168.4.1 або IP у мережі)
src/node_common/     спільний GATT-периферійний рівень вузлів (NimBLE)
src/common/          піни, UUID, лічильник boot_id у NVS, мінімальний драйвер MPU-6050
include/             secrets.example.h (скопіюйте в secrets.h)
test/host/           модульні тести + Makefile (g++, без PlatformIO)
test/test_native/    ті самі тести для `pio test -e native` (Unity)
tools/gen_vectors/   генератор test_vectors.json і examples/mqtt_samples.jsonl
tools/verify_vectors.py  незалежна перевірка векторів (Python, лише стандартна бібліотека)
hardware/            схеми під'єднання, BOM, чек-лист введення в експлуатацію (A.2)
docs/                ARCHITECTURE, BLE_PROTOCOL (+ копія PROTOCOL_v1.0), SECURITY, TEST_PLAN
```

## Тести на хості (без ESP32)

```sh
make -C test/host          # збирає lib/ і тести з -Wall -Wextra -Werror, запускає їх
make -C test/host vectors  # перегенеровує test_vectors.json і examples/mqtt_samples.jsonl
python3 tools/verify_vectors.py test_vectors.json
pio test -e native         # те саме через PlatformIO/Unity (у цьому випуску не запускалось)
```

Очікуваний результат: `43 test cases, 43 passed, 0 failed`.

## Збирання й прошивання (ESP32)

Потрібен PlatformIO з доступом до реєстру.

1. `cp include/secrets.example.h include/secrets.h` і заповніть: Wi-Fi, адресу брокера, PIN оператора,
   таблицю допущених вузлів (адреса BLE, passkey, зона).
2. Задайте унікальні `UMSF_DEVICE_ID` / `UMSF_PASSKEY` у `platformio.ini` для кожного вузла та
   `UMSF_GATEWAY_ID` / `UMSF_SITE_ID` для шлюзу.
3. Сертифікати шлюзу (`ca.pem`, `client.crt`, `client.key`) покладіть у `data/`, потім
   `pio run -e gateway -t uploadfs`.
4. Прошийте: `pio run -e personnel_node -t upload`, `pio run -e stationary_node -t upload`,
   `pio run -e gateway -t upload`.
5. Реєстрація вузла: тримайте кнопку (GPIO27) під час увімкнення вузла. Тоді шлюз виконає сполучення
   LE Secure Connections з passkey. Після цього вузол відхиляє незареєстровані центральні пристрої.
6. Монітор: `pio device monitor -b 115200`. Шлюз друкує рядки `RX,...` (формат Stage 1), вузли друкують
   `SLOT`, `ACKW`, `EVICT`.

### Прийняті версії бібліотек (не перевірено збиранням)

| Бібліотека | Версія | Примітка |
|---|---|---|
| platform espressif32 | 6.9.0 (Arduino-ESP32 2.0.17) | mbedTLS 2.28: лише TLS 1.2 (див. docs/SECURITY.md) |
| h2zero/NimBLE-Arduino | 1.4.3 | API зворотних викликів 1.4.x; версія 2.x несумісна |
| bertmelis/espMqttClient | 1.7.0 | публікація QoS 1 (PubSubClient підтримує лише QoS 0, тому не використовується) |
| SparkFun MAX3010x | 1.1.2 | MAX30102 через клас `MAX30105` |
| OneWire / DallasTemperature | 2.3.8 / 3.11.0 | |
| Adafruit BMP280 / Unified Sensor / BusIO | 2.6.8 / 1.1.14 / 1.16.1 | |
| MPU-6050 | — | власний мінімальний драйвер регістрів (`src/common/mpu6050_min.h`) |

## Протокол

Байтовий протокол, GATT, MQTT-топіки та параметри за замовчуванням описано в спільній специфікації
`docs/PROTOCOL_v1.0.md` (незмінна копія). Рішення, які специфікація залишила на розсуд реалізації,
зібрано в `docs/BLE_PROTOCOL.md`. Приклад рядка шлюзу, який точно відтворює запис зі статті:

```
RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM
```

## Ліцензія та цитування

Код поширюється за ліцензією MIT (`LICENSE`). Як цитувати: `CITATION.cff`. Метадані Zenodo: `.zenodo.json`.
