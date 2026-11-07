package com.orbit.app.util

import android.util.Base64
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * AES-256-GCM encryption/decryption and HKDF-SHA256 session key derivation
 * matching python's cryptography.hazmat HKDF and AESGCM.
 *
 * Format: base64(nonce[12] + ciphertext + gcm_tag[16])
 */
object Crypto {
    private const val GCM_TAG_BITS = 128
    private const val NONCE_BYTES = 12

    fun generateKey(): ByteArray {
        return ByteArray(32).also { SecureRandom().nextBytes(it) }
    }

    /**
     * HKDF-SHA256 matching Python:
     * HKDF(algorithm=hashes.SHA256(), length=32, salt=nonce, info=b"orbit-session").derive(pairing_key)
     */
    fun deriveSessionKey(pairingKey: ByteArray, nonce: ByteArray): ByteArray {
        // Step 1: Extract: PRK = HMAC-SHA256(salt=nonce, IKM=pairingKey)
        val macExtract = Mac.getInstance("HmacSHA256")
        macExtract.init(SecretKeySpec(nonce, "HmacSHA256"))
        val prk = macExtract.doFinal(pairingKey)

        // Step 2: Expand: OKM = HMAC-SHA256(PRK, info || 0x01)
        val macExpand = Mac.getInstance("HmacSHA256")
        macExpand.init(SecretKeySpec(prk, "HmacSHA256"))
        macExpand.update("orbit-session".toByteArray(Charsets.UTF_8))
        macExpand.update(1.toByte())
        return macExpand.doFinal()
    }

    fun encrypt(plaintext: String, key: ByteArray): String {
        val nonce = ByteArray(NONCE_BYTES).also { SecureRandom().nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BITS, nonce))
        val ciphertext = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))
        val combined = nonce + ciphertext
        return Base64.encodeToString(combined, Base64.NO_WRAP)
    }

    fun decrypt(ciphertextStr: String, key: ByteArray): String {
        val trimmed = ciphertextStr.trim()
        val raw = try {
            // First attempt Base64 decode
            val b64 = Base64.decode(trimmed, Base64.NO_WRAP)
            if (b64.isNotEmpty() && b64.size >= NONCE_BYTES + 16) b64 else decodeHex(trimmed)
        } catch (e: Exception) {
            decodeHex(trimmed)
        }
        if (raw.size < NONCE_BYTES + 16) {
            throw IllegalArgumentException("Ciphertext too short (${raw.size} bytes)")
        }
        val nonce = raw.copyOfRange(0, NONCE_BYTES)
        val ciphertext = raw.copyOfRange(NONCE_BYTES, raw.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BITS, nonce))
        val plaintext = cipher.doFinal(ciphertext)
        return String(plaintext, Charsets.UTF_8)
    }

    private fun decodeHex(hex: String): ByteArray {
        val s = hex.trim()
        val len = s.length
        val data = ByteArray(len / 2)
        var i = 0
        while (i < len) {
            data[i / 2] = ((Character.digit(s[i], 16) shl 4) + Character.digit(s[i + 1], 16)).toByte()
            i += 2
        }
        return data
    }
}
