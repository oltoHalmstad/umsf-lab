"""Host-side protection demonstration for Study A (Ed25519 signature + AES-GCM), optional.

Requires the optional ``cryptography`` package. Keys are derived deterministically from the
seed: they are DEMONSTRATION credentials only, not operational provisioning, and the nonce
policy (device prefix + per-device counter) is a demo policy. The checks establish expected
host-side behaviour for four specified perturbation classes (1,000 cases each): ciphertext
alteration, retained-signature modification, replay, and 180 s delivery against a 120 s
freshness rule. They say nothing about key compromise, malicious enrolled devices, firmware
or BLE attacks, or power interruption.
"""

from __future__ import annotations

import hashlib
import json
import random
import struct

from ..timeutil import to_epoch

FRESHNESS_S = 120
N_NEGATIVE = 1000


def available() -> bool:
    """True if the optional ``cryptography`` primitives import and work in this interpreter."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        Ed25519PrivateKey.from_private_bytes(bytes(32))
        AESGCM(bytes(32))
        return True
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:  # ImportError, or a broken binary wheel (e.g. pyo3 PanicException)
        return False


class DemoProtector:
    def __init__(self, seed: int, devices: list[str]):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self.sign_keys = {d: Ed25519PrivateKey.from_private_bytes(
            hashlib.sha256(f"umsf-demo-sign|{seed}|{d}".encode()).digest()) for d in devices}
        self.verify_keys = {d: k.public_key() for d, k in self.sign_keys.items()}
        self.aead = AESGCM(hashlib.sha256(f"umsf-demo-aead|{seed}".encode()).digest())
        self.counters = {d: 0 for d in devices}
        self.prefix = {d: i for i, d in enumerate(sorted(devices))}

    @staticmethod
    def canonical(rec: dict) -> bytes:
        return json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()

    def seal(self, rec: dict, signature: bytes | None = None) -> dict:
        dev = rec["device_id"]
        body = self.canonical(rec)
        sig = signature if signature is not None else self.sign_keys[dev].sign(body)
        self.counters[dev] += 1
        nonce = struct.pack(">IQ", self.prefix[dev], self.counters[dev])  # unique per key in this demo
        aad = f"{dev}|{rec['day']}|{rec['minute']}".encode()
        ct = self.aead.encrypt(nonce, struct.pack(">H", len(sig)) + sig + body, aad)
        return {"device_id": dev, "aad": aad, "nonce": nonce, "ct": ct}


class DemoVerifier:
    def __init__(self, protector: DemoProtector):
        self.p = protector
        self.seen: set = set()

    def accept(self, env: dict, received_at_epoch: float) -> tuple[bool, str]:
        from cryptography.exceptions import InvalidSignature, InvalidTag

        try:
            pt = self.p.aead.decrypt(env["nonce"], env["ct"], env["aad"])
        except InvalidTag:
            return False, "aead_authentication_failed"
        (n,) = struct.unpack(">H", pt[:2])
        sig, body = pt[2:2 + n], pt[2 + n:]
        try:
            self.p.verify_keys[env["device_id"]].verify(sig, body)
        except (InvalidSignature, KeyError):
            return False, "signature_invalid"
        rec = json.loads(body)
        if received_at_epoch - to_epoch(rec["measured_at"]) > FRESHNESS_S:
            return False, "stale_beyond_freshness"
        ident = (rec["device_id"], rec["day"], rec["minute"])
        if ident in self.seen:
            return False, "replay"
        self.seen.add(ident)
        return True, "accepted"


def run_protection_demo(records: list[dict], seed: int) -> dict:
    if not available():
        return {"available": False, "note": "optional 'cryptography' package not installed; demo skipped"}
    rng = random.Random(seed + 1)
    prot = DemoProtector(seed, sorted({r["device_id"] for r in records}))
    ver = DemoVerifier(prot)
    envs, ok = [], 0
    for r in records:
        env = prot.seal(r)
        envs.append(env)
        good, _ = ver.accept(env, to_epoch(r["measured_at"]) + rng.uniform(0.5, 5.0))
        ok += good
    res = {"available": True, "algorithms": "Ed25519 signature inside AES-256-GCM", "freshness_s": FRESHNESS_S,
           "ordinary_records": len(records), "ordinary_verified": ok,
           "note": "demonstration keys and nonce state; not operational provisioning", "negative": {}}
    picks = rng.sample(range(len(records)), N_NEGATIVE)

    def tally(name, reason, gen):
        rejected = sum(1 for good, why in gen if not good and why == reason)
        res["negative"][name] = {"cases": N_NEGATIVE, "rejected": rejected, "expected_reason": reason}

    def altered():
        for i in picks:
            e = dict(envs[i])
            ct = bytearray(e["ct"])
            ct[rng.randrange(len(ct))] ^= 1 << rng.randrange(8)
            e["ct"] = bytes(ct)
            yield ver.accept(e, to_epoch(records[i]["measured_at"]) + 2)

    def retained_sig():
        for i in picks:
            r = records[i]
            sig = prot.sign_keys[r["device_id"]].sign(prot.canonical(r))
            forged = dict(r, hr_bpm=(r["hr_bpm"] or 70.0) + 1.0)
            yield DemoVerifier(prot).accept(prot.seal(forged, signature=sig), to_epoch(r["measured_at"]) + 2)

    def replay():
        for i in picks:
            yield ver.accept(envs[i], to_epoch(records[i]["measured_at"]) + 3)

    def delayed():
        fresh = DemoVerifier(prot)
        for i in picks:
            yield fresh.accept(prot.seal(records[i]), to_epoch(records[i]["measured_at"]) + 180)

    tally("ciphertext_alteration", "aead_authentication_failed", altered())
    tally("retained_signature_modification", "signature_invalid", retained_sig())
    tally("replay", "replay", replay())
    tally("delivery_180s_vs_120s_freshness", "stale_beyond_freshness", delayed())
    return res
