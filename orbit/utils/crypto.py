"""
ORBIT cryptographic utilities.

- AES-256-GCM encrypt / decrypt
- HKDF session-key derivation
- Key storage at ~/ORBIT/key.bin (0600 permissions)
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

KEY_PATH = Path.home() / "ORBIT" / "key.bin"
NONCE_SIZE = 12  # 96-bit nonce for GCM


def generate_key() -> bytes:
    """Generate a random 256-bit key."""
    return secrets.token_bytes(32)


def save_key(key: bytes) -> None:
    """Persist the key to disk with restrictive permissions."""
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEY_PATH.write_bytes(key)
    os.chmod(KEY_PATH, 0o600)


def load_key() -> bytes | None:
    """Load the key from disk, or None if it doesn't exist."""
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    return None


def encrypt(data: bytes, key: bytes) -> bytes:
    """
    AES-256-GCM encrypt.
    Returns: nonce (12) + ciphertext + tag (16) — all concatenated.
    """
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(NONCE_SIZE)
    ct = aesgcm.encrypt(nonce, data, None)  # ct includes the 16-byte tag
    return nonce + ct


def decrypt(data: bytes, key: bytes) -> bytes:
    """
    AES-256-GCM decrypt.
    Expects: nonce (12) + ciphertext + tag (16).
    """
    aesgcm = AESGCM(key)
    nonce = data[:NONCE_SIZE]
    ct = data[NONCE_SIZE:]
    return aesgcm.decrypt(nonce, ct, None)


def derive_session_key(pairing_key: bytes, nonce: bytes) -> bytes:
    """
    Derive a per-session key from the pairing key + a random nonce
    using HKDF-SHA256.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=nonce,
        info=b"orbit-session",
    )
    return hkdf.derive(pairing_key)
