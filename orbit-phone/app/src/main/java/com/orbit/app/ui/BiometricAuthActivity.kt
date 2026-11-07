package com.orbit.app.ui

import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import com.orbit.app.OrbitApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/**
 * System-wide transparent activity that pops up the native Android BiometricPrompt
 * immediately over ANY active application or home screen when the laptop requests
 * biometric authentication for face re-enrollment.
 */
class BiometricAuthActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "BiometricAuthActivity"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val token = intent.getStringExtra("token") ?: ""
        if (token.isEmpty()) {
            finish()
            return
        }

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("ORBIT Workstation")
            .setSubtitle("Scan fingerprint to authorize face biometrics re-enrollment")
            .setNegativeButtonText("Cancel")
            .build()

        val executor = ContextCompat.getMainExecutor(this)
        val biometricPrompt = BiometricPrompt(
            this,
            executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    super.onAuthenticationSucceeded(result)
                    Log.i(TAG, "Fingerprint verification SUCCEEDED for token: $token")
                    Toast.makeText(this@BiometricAuthActivity, "✓ Fingerprint verified! Laptop enrollment approved.", Toast.LENGTH_LONG).show()

                    val app = OrbitApp.instance
                    app.pcConnection.setPendingBiometricToken(null)

                    // 1. WebSocket Push
                    val key = app.prefs.pairingKey?.let {
                        try { Base64.decode(it, Base64.NO_WRAP) } catch (e: Exception) { null }
                    }
                    if (key != null) {
                        val payload = JSONObject().apply { put("token", token) }
                        app.pcConnection.send("biometric_reenroll_approved", payload, key)
                    }

                    // 2. Direct HTTP Fallback Push
                    val pcIp = app.prefs.pcIp
                    if (pcIp.isNotEmpty()) {
                        CoroutineScope(Dispatchers.IO).launch {
                            try {
                                val client = OkHttpClient()
                                val body = JSONObject().apply { put("token", token) }.toString()
                                    .toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
                                val req = Request.Builder()
                                    .url("http://$pcIp:8080/api/enroll/approve")
                                    .post(body)
                                    .build()
                                client.newCall(req).execute().close()
                            } catch (e: Exception) {
                                Log.w(TAG, "HTTP approval fallback error: ${e.message}")
                            }
                        }
                    }

                    finish()
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    super.onAuthenticationError(errorCode, errString)
                    Log.w(TAG, "Biometric error ($errorCode): $errString")
                    finish()
                }

                override fun onAuthenticationFailed() {
                    super.onAuthenticationFailed()
                    Log.w(TAG, "Biometric authentication failed")
                }
            }
        )

        biometricPrompt.authenticate(promptInfo)
    }
}
