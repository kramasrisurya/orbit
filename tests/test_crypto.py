"""
Tests for cryptographic utilities and pairing manager.
"""

import pytest
from cryptography.exceptions import InvalidTag
from utils.crypto import (
    generate_key, encrypt, decrypt, derive_session_key
)
from phone.pairing import PairingManager


def test_generate_key():
    k1 = generate_key()
    k2 = generate_key()
    assert len(k1) == 32
    assert len(k2) == 32
    assert k1 != k2


def test_encrypt_decrypt_roundtrip():
    key = generate_key()
    plaintext = b"Hello ORBIT! Ambient local-first awareness"
    ciphertext = encrypt(plaintext, key)

    assert ciphertext != plaintext
    # 12 bytes nonce + len(plaintext) + 16 bytes tag
    assert len(ciphertext) == 12 + len(plaintext) + 16

    decrypted = decrypt(ciphertext, key)
    assert decrypted == plaintext


def test_decrypt_with_wrong_key_fails():
    key1 = generate_key()
    key2 = generate_key()
    plaintext = b"Sensitive payload"
    ciphertext = encrypt(plaintext, key1)

    with pytest.raises(InvalidTag):
        decrypt(ciphertext, key2)


def test_decrypt_tampered_ciphertext_fails():
    key = generate_key()
    plaintext = b"Sensitive command"
    ciphertext = bytearray(encrypt(plaintext, key))

    # Tamper with the ciphertext byte
    ciphertext[-5] ^= 0xFF

    with pytest.raises(InvalidTag):
        decrypt(bytes(ciphertext), key)


def test_derive_session_key():
    pairing_key = generate_key()
    nonce1 = generate_key()[:12]
    nonce2 = generate_key()[:12]

    session1 = derive_session_key(pairing_key, nonce1)
    session2 = derive_session_key(pairing_key, nonce2)

    assert len(session1) == 32
    assert len(session2) == 32
    assert session1 != session2


def test_pairing_manager_initiate_pairing(mock_config):
    pm = PairingManager(config=mock_config)
    qr_b64 = pm.initiate_pairing()

    assert isinstance(qr_b64, str)
    assert len(qr_b64) > 100
    assert pm.is_paired("device-test") is False

    pm.complete_pairing("device-test")
    assert pm.is_paired("device-test") is True
