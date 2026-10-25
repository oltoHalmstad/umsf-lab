/*
 * umsf_text.h - gateway text log line (spec 3), Stage-1 compatible.
 *
 * Physio:  RX,<gw_id>,<gw_ms>,F,<device_id>,<boot_id>,<seq>,<node_ms>,<temp_x100>,<ppg_ir>,<motion_mg>,<hr_x1>,<flags>
 * Station: RX,<gw_id>,<gw_ms>,S,<device_id>,<boot_id>,<seq>,<node_ms>,<vib_cg>,<tilt_ddeg>,<p_dhpa>,<temp_x100>,<gas_mv>,<sound>,<flags_hex>
 * Event:   RX,<gw_id>,<gw_ms>,E,<device_id>,<boot_id>,<seq>,<node_ms>,<event_type_name>,<level>,<value_x1000>
 * Missing values (null sentinels) are empty fields. Physio flag letters, in this order:
 * T temp, P PPG, M motion, H HR synthetic, G GSR, S SOS. hr_x1 = hr/10 rounded half up.
 * flags_hex = two uppercase hex digits.
 */
#ifndef UMSF_TEXT_H
#define UMSF_TEXT_H

#include "umsf_proto.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Returns number of characters written (excluding NUL), or -1 if the frame type has no
 * line format (STATUS/ACK/CONFIG) or the buffer is too small. */
int umsf_text_line(const char *gw_id, uint32_t gw_ms, const umsf_frame_t *f, char *out, size_t cap);

/* Physio flag letters for channel_flags into out (needs 7 bytes). */
char *umsf_text_flag_letters(uint8_t channel_flags, char *out);

#ifdef __cplusplus
}
#endif
#endif
