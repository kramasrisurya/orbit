package com.orbit.app.ui

import android.app.Activity
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.view.Gravity
import android.view.WindowManager
import android.widget.Toast
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
 * Invisible 1-frame foreground activity that briefly acquires window focus
 * to read Android's system clipboard without being blocked by Android 10+ background
 * clipboard security restrictions, then immediately finishes without animation.
 */
class ClipboardSyncActivity : Activity() {

    companion object {
        private const val TAG = "ClipboardSyncActivity"
        private var lastSyncedText: String? = null
    }

    private var hasSynced = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Make window 1x1 pixel and completely transparent at top-left
        window.attributes = window.attributes.apply {
            width = 1
            height = 1
            gravity = Gravity.TOP or Gravity.START
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && !hasSynced) {
            hasSynced = true
            readAndSyncClipboard()
            finish()
            overridePendingTransition(0, 0)
        }
    }

    override fun onResume() {
        super.onResume()
        if (!hasSynced) {
            window.decorView.post {
                if (!hasSynced) {
                    hasSynced = true
                    readAndSyncClipboard()
                    finish()
                    overridePendingTransition(0, 0)
                }
            }
        }
    }

    private fun readAndSyncClipboard() {
        try {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val clip = cm.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val item = clip.getItemAt(0)
                val text = item.text?.toString() ?: item.coerceToText(this)?.toString() ?: ""
                if (text.isNotEmpty() && text != lastSyncedText) {
                    lastSyncedText = text
                    Log.i(TAG, "Read system clipboard: ${text.take(30)}... (${text.length} chars)")

                    val app = OrbitApp.instance
                    app.pcConnection.updateClipboardText(text)

                    // 1. WebSocket Push
                    val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
                    if (key != null) {
                        val payload = JSONObject().apply { put("text", text) }
                        app.pcConnection.send("clipboard", payload, key)
                    }

                    // 2. Direct HTTP Push to Laptop
                    val pcIp = app.prefs.pcIp
                    if (pcIp.isNotEmpty()) {
                        CoroutineScope(Dispatchers.IO).launch {
                            try {
                                val client = OkHttpClient()
                                val body = JSONObject().apply { put("text", text) }.toString()
                                    .toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
                                val req = Request.Builder()
                                    .url("http://$pcIp:8080/api/clipboard")
                                    .post(body)
                                    .build()
                                client.newCall(req).execute().close()
                                Log.i(TAG, "Pushed clipboard to laptop via HTTP ($pcIp:8080)")
                            } catch (e: Exception) {
                                Log.e(TAG, "HTTP push failed: ${e.message}")
                            }
                        }
                    }

                    Toast.makeText(this, "✓ Synced phone clipboard to Laptop (${text.length} chars)", Toast.LENGTH_SHORT).show()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to read system clipboard: ${e.message}")
        }
    }
}
