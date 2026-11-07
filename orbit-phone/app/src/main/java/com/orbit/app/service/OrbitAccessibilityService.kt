package com.orbit.app.service

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.util.Base64
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityManager
import com.orbit.app.OrbitApp
import com.orbit.app.ui.ClipboardSyncActivity
import kotlinx.coroutines.*
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/**
 * ORBIT System-Wide Background Accessibility Service.
 *
 * Runs continuously in the background across ANY active app on Android.
 * Enables 100% automatic, seamless clipboard synchronization from phone to laptop:
 * Whenever text is copied anywhere on Android (Chrome, WhatsApp, Gmail, etc.),
 * it captures the clipboard and pushes it to Windows immediately without user intervention.
 */
class OrbitAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "OrbitAccessibility"
        var isRunning = false
            private set

        fun isAccessibilityServiceEnabled(context: Context): Boolean {
            val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as? AccessibilityManager ?: return false
            val enabled = am.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
            return enabled.any { it.resolveInfo?.serviceInfo?.packageName == context.packageName }
        }
    }

    private var lastSyncedText: String? = null
    private var lastSelectedText: String? = null
    private var lastActivityLaunch = 0L
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var overlayView: View? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        isRunning = true
        Log.i(TAG, "OrbitAccessibilityService connected — automatic clipboard monitor running")

        // Attach an active 1-pixel accessibility overlay window so the service retains window presence
        try {
            val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
            val view = View(this)
            val params = WindowManager.LayoutParams(
                1, 1,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                        WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                        WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT
            ).apply {
                gravity = Gravity.TOP or Gravity.START
            }
            wm.addView(view, params)
            overlayView = view
            Log.i(TAG, "Attached 1px accessibility overlay window for 24/7 background presence")
        } catch (e: Exception) {
            Log.w(TAG, "Overlay view init warning: ${e.message}")
        }

        serviceInfo = serviceInfo.apply {
            eventTypes = AccessibilityEvent.TYPE_VIEW_CLICKED or
                    AccessibilityEvent.TYPE_VIEW_LONG_CLICKED or
                    AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED or
                    AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED or
                    AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
                    AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            flags = AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS or
                    AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
        }

        try {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.addPrimaryClipChangedListener {
                triggerClipboardSyncActivity()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Listener error: ${e.message}")
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        try {
            when (event.eventType) {
                AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED -> {
                    val node = event.source
                    if (node != null && node.text != null) {
                        val full = node.text.toString()
                        val start = event.fromIndex
                        val end = event.toIndex
                        if (start in 0..end && end <= full.length && start != end) {
                            lastSelectedText = full.substring(start, end)
                        }
                    }
                }
                AccessibilityEvent.TYPE_VIEW_CLICKED,
                AccessibilityEvent.TYPE_VIEW_LONG_CLICKED -> {
                    if (isCopyEvent(event)) {
                        lastSelectedText?.let { sel ->
                            if (sel.isNotBlank()) {
                                syncTextToPc(sel)
                            }
                        }
                        triggerClipboardSyncActivity()
                    }
                }
                AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
                AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> {
                    val pkg = event.packageName?.toString() ?: ""
                    if (pkg.contains("systemui", ignoreCase = true) || pkg.contains("clipboard", ignoreCase = true)) {
                        val txt = event.text?.joinToString(" ") ?: ""
                        val desc = event.contentDescription?.toString() ?: ""
                        if (txt.contains("copi", ignoreCase = true) || desc.contains("copi", ignoreCase = true) ||
                            txt.contains("clipboard", ignoreCase = true) || desc.contains("clipboard", ignoreCase = true)) {
                            triggerClipboardSyncActivity()
                        }
                    }
                }
            }
        } catch (e: Exception) {
            // Safe guard
        }
    }

    private fun isCopyEvent(event: AccessibilityEvent): Boolean {
        val text = event.text?.joinToString(" ") ?: ""
        val desc = event.contentDescription?.toString() ?: ""
        if (text.contains("copy", ignoreCase = true) || desc.contains("copy", ignoreCase = true)) {
            return true
        }

        val source = event.source ?: return false
        try {
            val srcText = source.text?.toString() ?: ""
            val srcDesc = source.contentDescription?.toString() ?: ""
            val viewId = source.viewIdResourceName ?: ""
            if (srcText.contains("copy", ignoreCase = true) ||
                srcDesc.contains("copy", ignoreCase = true) ||
                viewId.contains("copy", ignoreCase = true)) {
                return true
            }

            for (i in 0 until source.childCount) {
                val child = source.getChild(i) ?: continue
                val cText = child.text?.toString() ?: ""
                val cDesc = child.contentDescription?.toString() ?: ""
                val cId = child.viewIdResourceName ?: ""
                val matched = cText.contains("copy", ignoreCase = true) ||
                        cDesc.contains("copy", ignoreCase = true) ||
                        cId.contains("copy", ignoreCase = true)
                child.recycle()
                if (matched) return true
            }
        } catch (e: Exception) {}
        return false
    }

    fun triggerClipboardSyncActivity() {
        val now = System.currentTimeMillis()
        if (now - lastActivityLaunch < 350L) return
        lastActivityLaunch = now

        try {
            val intent = Intent(this, ClipboardSyncActivity::class.java).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_NO_ANIMATION or
                    Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS
                )
            }
            startActivity(intent)
            Log.d(TAG, "Dispatched ClipboardSyncActivity to acquire foreground focus")
        } catch (e: Exception) {
            Log.w(TAG, "Could not start ClipboardSyncActivity: ${e.message}")
        }
    }

    override fun onInterrupt() {}

    private fun syncTextToPc(text: String) {
        if (text.isEmpty() || text == lastSyncedText) return
        lastSyncedText = text
        Log.i(TAG, "New clipboard detected on phone: ${text.take(30)}... (${text.length} chars)")

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
            serviceScope.launch {
                try {
                    val client = OkHttpClient()
                    val body = JSONObject().apply { put("text", text) }.toString()
                        .toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
                    val req = Request.Builder()
                        .url("http://$pcIp:8080/api/clipboard")
                        .post(body)
                        .build()
                    client.newCall(req).execute().close()
                    Log.i(TAG, "Auto-pushed clipboard directly to laptop via HTTP ($pcIp:8080)")
                } catch (e: Exception) {
                    Log.d(TAG, "HTTP push failed: ${e.message}")
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        isRunning = false
        overlayView?.let {
            try {
                val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
                wm.removeView(it)
            } catch (e: Exception) {}
        }
        overlayView = null
        serviceScope.cancel()
    }
}
