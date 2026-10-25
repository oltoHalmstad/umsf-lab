# Evidence boundaries and known implementation behavior

| Claim | Evidence in this release | Limit |
|---|---|---|
| Portable source compiles | GCC/G++ host build log | Not an ESP32 build |
| Existing tests pass | 43 tests, 475 checks | Finite software coverage |
| Supplied vectors behave as expected | Independent verifier; native CRC | Not exhaustive protocol fuzzing |
| Notebook is standalone | Only notebook supplied in a fresh process | Standard Python packages and compiler are runtime dependencies |
| All cells execute, sequentially and each alone | Executed notebook; per-cell fresh-kernel check in validation JSON | Hosted Colab service/frontend not directly tested |
| Feature/rule outputs reproducible | Native harness and CSV inputs/outputs | Synthetic stimuli, uncalibrated thresholds |
| Source retained | Per-file SHA-256 and original archive | Original limitations retained |

## Behavior that affects interpretation

- No PPG samples and no explicit PPG error may leave quality at 100 when other channels are complete. Read channel flags and counts, not quality alone.
- Motion RMS measures deviation of acceleration magnitude from gravity, not orientation-invariant movement intensity in a clinical sense.
- Stationary quality averages channel availability and IMU completeness/saturation. Warmup completion changes the score without establishing sensor calibration.
- Returning tilt to baseline clears the alarm but leaves attachment uncertainty latched.
- `StationDetector.set_sos` changes a state flag. SOS event emission is the responsibility of application code; this harness does not invent such events.
- Impact timestamps may precede the time a closed event is emitted. Composite event times inherit the initiating impact time.
- Pressure history has finite storage in addition to its time window. The harness uses 20 Hz pressure sampling, not arbitrary sampling rates.
- Event queue capacity is 16; the harness drains it continuously. It does not test overload loss of local events.
- Full record buffers evict the oldest lowest-priority existing entry; lower-priority incoming data can evict urgent data when all existing entries are urgent.
- Identity deduplication compares source, boot and sequence, not payload equality.
- A cumulative ACK releases matching sequences even if unsent. The upstream durable-commit protocol must account for gaps before advancing the watermark.
- The ACK parser extracts fields with a limited scanner; it does not validate an entire JSON document. No production security audit is claimed.
- CRC is not authentication. BLE/mTLS behavior, credentials and provisioning are outside the native laboratory. COSE and the patent keystream method mentioned in the original project are not implemented.
- RAM retention does not survive reboot or power loss. Duplicate delivery and eviction must be handled explicitly downstream.

None of the synthetic traces is a patient, building, gas-exposure or incident dataset.
