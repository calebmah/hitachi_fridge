"""Cryptographic and wire-framing utilities for the Hitachi Fridge protocol.

Matches the exact cipher, padding, digest trailer, and dual-format response
behavior of `AESCryptUtils`, `UDPUtils`, `GsonRequestBodyCustomHitachiWebConverter`,
`GsonResponseBodyCustomHitachiWebConverter`, and `GsonResponseBodyCustomConverter`
in Hitachi Refrigerator app v1.6.0–v1.7.0, verified against captured MITM frames.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Static pre-authentication cipher parameters (`ConstantCo.<clinit>`,
# `GsonRequestBodyCustomHitachiWebConverter.<clinit>`, and
# `GsonResponseBodyCustomHitachiWebConverter.<clinit>`).
WEB_BOOTSTRAP_KEY: bytes = bytes.fromhex(
    "b8e76989a67babb17fd6ad50218c993c2593481c71bdf79f90942f3f9937c267"
)
WEB_BOOTSTRAP_IV: bytes = bytes.fromhex("c2462d1d35421ebf43b8619b93e98aa8")

# Static pre-login Appliance Cloud filter cipher key (`Constant.HTTP_ENCKEY`),
# used with `LEGACY_UDP_IV` on `ap_outer_ctrl_filter.cgi`.
APPLIANCE_FILTER_KEY: bytes = bytes.fromhex(
    "9c8990dbbc57cddb7487e79689f8b0f693745ab919f8acefd588091fdf2bd5d4"
)

# Shared static IV (`AESCryptUtils.<clinit>`), used for `ap_outer_ctrl_filter.cgi`
# and for legacy Local UDP fallback (`SHA256(dst + "hapiot")`) when `ckdn_device_key`
# has no entry for `dst`.
LEGACY_UDP_IV: bytes = bytes.fromhex("23939092abea944b46681d60498f4704")


def zero_pad_16(data: bytes) -> bytes:
    """Apply Android BouncyCastle-compatible `ZeroBytePadding` to 16-byte blocks.

    Android's `Cipher.getInstance("AES/CBC/ZeroBytePadding")` uses BouncyCastle's
    `PaddedBufferedBlockCipher` with `ZeroBytePadding`, which pads `1..16` zero bytes
    to the next 16-byte block boundary.
    """
    pad_len = 16 - (len(data) % 16)
    return data + (b"\x00" * pad_len)


def zero_pad_32(data: bytes) -> bytes:
    """Pad `data` with `0x00` to a 32-byte multiple (`AESCryptUtils.to32Bytes`), then 16-byte pad."""
    if not data:
        return zero_pad_16(data)
    rem = len(data) % 32
    padded_32 = data + (b"\x00" * (32 - rem)) if rem > 0 else data
    return zero_pad_16(padded_32)


def encrypt_aes_cbc_zero_pad(key: bytes, iv: bytes, plaintext: str) -> bytes:
    """Encrypt UTF-8 text using AES-256-CBC with BouncyCastle `ZeroBytePadding`."""
    padded = zero_pad_16(plaintext.encode("utf-8"))
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt_aes_cbc_zero_pad(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """Decrypt raw AES-256-CBC ciphertext bytes."""
    if not ciphertext or len(ciphertext) % 16 != 0:
        raise ValueError(
            f"Invalid AES-CBC ciphertext length: {len(ciphertext)} bytes"
        )
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def derive_legacy_udp_key(dst: str) -> bytes:
    """Derive legacy 32-byte UDP AES key `SHA256(dst + 'hapiot')`."""
    return hashlib.sha256(f"{dst}hapiot".encode("utf-8")).digest()


def encrypt_udp_packet(
    frame: str,
    device_key: bytes | None,
    device_iv: bytes | None,
    dst: str,
) -> bytes:
    """Encrypt a Local LAN UDP request frame (`UDPUtils.convertReqToBytes`).

    When per-device `device_key` and `device_iv` are present (`ckdn_device_key`),
    uses `AESCryptUtils.encrypt2`, appending `SHA256(plaintext_utf8)[0:16]`.
    Otherwise falls back to legacy `AESCryptUtils.encrypt(dst + 'hapiot', frame)`
    which calls `to32Bytes(frame)` before `AES/CBC/ZeroBytePadding`.
    """
    if device_key and device_iv:
        pt_bytes = frame.encode("utf-8")
        ciphertext = encrypt_aes_cbc_zero_pad(device_key, device_iv, frame)
        digest_trailer = hashlib.sha256(pt_bytes).digest()[:16]
        return ciphertext + digest_trailer

    legacy_key = derive_legacy_udp_key(dst)
    padded_legacy = zero_pad_32(frame.encode("utf-8"))
    cipher = Cipher(algorithms.AES(legacy_key), modes.CBC(LEGACY_UDP_IV))
    encryptor = cipher.encryptor()
    return encryptor.update(padded_legacy) + encryptor.finalize()


def decrypt_udp_packet(
    packet: bytes,
    device_key: bytes | None,
    device_iv: bytes | None,
    dst: str,
) -> dict[str, str]:
    """Decrypt a Local LAN UDP response datagram into a key-value dict.

    Matches `UDPUtils.convertResFromBytes`: splits decrypted UTF-8 text on `&`
    and stops at the first segment without `=`, cleanly discarding zero-padding
    and the trailing 16-byte SHA-256 trailer block.
    """
    if device_key and device_iv:
        raw = decrypt_aes_cbc_zero_pad(device_key, device_iv, packet)
    else:
        raw = decrypt_aes_cbc_zero_pad(derive_legacy_udp_key(dst), LEGACY_UDP_IV, packet)

    text = raw.decode("utf-8", errors="ignore")
    parsed: dict[str, str] = {}
    for segment in text.split("&"):
        if "=" not in segment:
            break
        key, val = segment.split("=", 1)
        parsed[key] = val
    return parsed


def serialize_query_map(params: dict[str, str]) -> str:
    """Serialize a request map as raw `KEY=VALUE&...` without URL encoding."""
    return "&".join(f"{key}={val}" for key, val in params.items())


def strip_hybrid_padding(decrypted_bytes: bytes) -> bytes:
    """Strip PKCS#7, ZeroBytePadding (`0x00`), and trailing control bytes (`<= 0x20`).

    Verified against live `kadenfan.hitachi.co.jp/my/api/` responses which zero-pad
    short payloads to 16 bytes and then append a 16-byte `0x10` PKCS#7 block, while
    Java's `String.trim()` in `GsonResponseBodyCustomHitachiWebConverter` strips all
    trailing bytes `<= 0x20`.
    """
    data = decrypted_bytes
    if data:
        last_byte = data[-1]
        if 1 <= last_byte <= 16 and len(data) >= last_byte:
            if all(b == last_byte for b in data[-last_byte:]):
                data = data[:-last_byte]
    # Truncate at first NUL byte (`ZeroBytePadding`) and trim ASCII control/space (`<= 0x20`)
    data = data.split(b"\x00", 1)[0]
    end = len(data)
    while end > 0 and data[end - 1] <= 0x20:
        end -= 1
    start = 0
    while start < end and data[start] <= 0x20:
        start += 1
    return data[start:end]


def parse_dual_response(decrypted_bytes: bytes) -> dict[str, Any]:
    """Parse Cloud HTTP plaintext response (either JSON or `K=V&...` pairs).

    Matches `GsonResponseBodyCustomConverter` and `GsonResponseBodyCustomHitachiWebConverter`.
    """
    cleaned_bytes = strip_hybrid_padding(decrypted_bytes)
    cleaned = cleaned_bytes.decode("utf-8", errors="strict")
    if not cleaned:
        return {}
    if cleaned.startswith("{"):
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object in Hitachi Cloud response")
        return parsed

    result: dict[str, Any] = {}
    for part in cleaned.split("&"):
        if "=" in part:
            key, val = part.split("=", 1)
            result[key] = val
    if not result:
        raise ValueError("Unrecognized Hitachi Cloud response payload")
    return result


def format_time_decimal_15(dt: datetime | None = None) -> str:
    """Format 15-char decimal timestamp for Cloud `CTRLINS` (`YYYYMMDDHHMMSSW`, 0=Sun..6=Sat).

    Matches `TimeUtils.getNowStringDex()`.
    """
    now = dt or datetime.now()
    weekday_sun0 = (now.weekday() + 1) % 7
    return (
        f"{now.year:04d}{now.month:02d}{now.day:02d}"
        f"{now.hour:02d}{now.minute:02d}{now.second:02d}{weekday_sun0:01d}"
    )


def format_time_hex_16(dt: datetime | None = None) -> str:
    """Format 16-char uppercase hex timestamp for Local UDP `CTRLINS`.

    Matches `TimeUtils.getNowStringHex()` (`%04X%02X%02X%02X%02X%02X%02X`).
    """
    now = dt or datetime.now()
    weekday_sun0 = (now.weekday() + 1) % 7
    return (
        f"{now.year:04X}{now.month:02X}{now.day:02X}"
        f"{now.hour:02X}{now.minute:02X}{now.second:02X}{weekday_sun0:02X}"
    )
