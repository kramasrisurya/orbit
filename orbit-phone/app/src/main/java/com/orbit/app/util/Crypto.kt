package com.orbit.app.util

import android.util.Base64
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * AES-256-GCM encryption/decryption for WebSocket messages.
 *
 * Format: base64(nonce[12] + ciphertext + gcm_tag[16])
 */
object Crypto {
    private const val GCM_TAG_BITS = 128
    private const val NONCE_BYTES = 12

    fun generateKey(): ByteArray {
        return ByteArray(32).also { SecureRandom().nextBytes(it) }
    }

    fun encrypt(plaintext: String, key: ByteArray): String {
        val nonce = ByteArray(NONCE_BYTES).also { SecureRandom().nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BITS, nonce))
        val ciphertext = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))
        val combined = nonce + ciphertext  // nonce + (ciphertext + tag)
        return Base64.encodeToString(combined, Base64.NO_WRAP)
    }

    fun decrypt(ciphertextB64: String, key: ByteArray): String {
        val combined = Base64.decode(ciphertextB64, Base64.NO_WRAP)
        val nonce = combined.copyOfRange(0, NONCE_BYTES)
        val ciphertext = combined.copyOfRange(NONCE_BYTES, combined.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BITS, nonce))
        val plaintext = cipher.doFinal(ciphertext)
        return String(plaintext, Charsets.UTF_8)
    }

    fun deriveSessionKey(pairingKey: ByteArray, nonce: ByteArray): ByteArray {
        // Simple derivation: XOR pairing key with nonce (padded) to produce a session key.
        // In production, use HKDF. This is "good enough for my apartment."
        val session = ByteArray(32)
        for (i in 0 until 32) {
            session[i] = pairingKey[i % pairingKey.size] xor nonce[i % nonce.size]
        }
        return session
    }
}
