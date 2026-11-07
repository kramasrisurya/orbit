package com.orbit.app.service

import android.app.DownloadManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.IBinder
import android.util.Base64
import android.util.Log
import android.widget.Toast
import com.orbit.app.data.PcConnection
import com.orbit.app.data.Prefs
import com.orbit.app.util.Crypto
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Request
import org.java_websocket.client.WebSocketClient
import org.java_websocket.handshake.ServerHandshake
import org.json.JSONObject
import java.io.File
import java.net.URI
import java.security.SecureRandom

/**
 * Foreground service maintaining the high-speed WebSocket link to the PC.
 * - Bidirectional encrypted protocol
 * - Seamless automatic clipboard bridge
 * - Low-latency trackpad & typing
 * - Automatic direct file downloader into Phone Downloads folder
 */
class WebSocketService : Service() {

    private val TAG = "WebSocketService"
    private val channelName = "orbit_ws"
    private var scope: CoroutineScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var wsClient: WebSocketClient? = null
    private var sessionKey: ByteArray? = null
    private var backoffMs = 2000L
    private var connectJob: Job? = null

    // Handshake state
    private var handshakeStage = 0  // 0=idle, 1=awaiting challenge, 2=awaiting confirm, 3=connected
    private var handshakeNonce: ByteArray = ByteArray(16)
    private var lastReceivedClipboard: String? = null

    private lateinit var pcConnection: PcConnection
    private lateinit var prefs: Prefs

    override fun onCreate() {
        super.onCreate()
        createChannel()
        pcConnection = (application as com.orbit.app.OrbitApp).pcConnection
        prefs = Prefs(applicationContext)

        // Register as the active sender for PcConnection
        pcConnection.sender = { type, payload, key ->
            sendEncrypted(type, payload, key)
        }

        // Automatic Phone -> PC clipboard listener
        try {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
            cm.addPrimaryClipChangedListener {
                try {
                    val clip = cm.primaryClip
                    if (clip != null && clip.itemCount > 0) {
                        val text = clip.getItemAt(0).text?.toString() ?: ""
                        if (text.isNotEmpty() && text != lastReceivedClipboard) {
                            lastReceivedClipboard = text
                            pcConnection.updateClipboardText(text)
                            val key = prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
                            if (key != null) {
                                val payload = JSONObject().apply { put("text", text) }
                                sendEncrypted("clipboard", payload, key)
                                Log.i(TAG, "Synced phone clipboard to laptop (${text.length} chars)")
                            }
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Clipboard listener error: ${e.message}")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to register clipboard listener: ${e.message}")
        }

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(
                    NOTIF_ID,
                    buildNotification("ORBIT — Connecting to Laptop…"),
                    android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                )
            } else {
                startForeground(NOTIF_ID, buildNotification("ORBIT — Connecting to Laptop…"))
            }
        } catch (e: Exception) {
            Log.w(TAG, "startForeground warning: ${e.message}")
        }
        Log.i(TAG, "WebSocketService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (connectJob?.isActive != true) {
            connectJob = scope.launch { connectLoop() }
        }
        return START_STICKY
    }

    // ------------------------------------------------------------------
    // Resilient Connection Loop with Exponential Backoff
    // ------------------------------------------------------------------
    private suspend fun connectLoop() {
        while (scope.isActive) {
            val key = prefs.pairingKey?.let {
                try { Base64.decode(it, Base64.NO_WRAP) } catch (e: Exception) { null }
            }
            if (key == null || prefs.pcIp.isBlank()) {
                pcConnection.disconnect()
                delay(3000L)
                continue
            }

            val closeDeferred = CompletableDeferred<Unit>()

            try {
                pcConnection.connect()
                updateNotification("ORBIT — Connecting to Laptop (${prefs.pcIp})…")
                handshakeStage = 0
                sessionKey = null

                val uri = URI(pcConnection.wsUrl)
                wsClient = object : WebSocketClient(uri) {
                    override fun onOpen(handshake: ServerHandshake?) {
                        Log.i(TAG, "WS connected to $uri — starting handshake")
                        // Send nonce to begin Stage 1
                        handshakeNonce = ByteArray(16).also { SecureRandom().nextBytes(it) }
                        handshakeStage = 1
                        send(Base64.encodeToString(handshakeNonce, Base64.NO_WRAP))
                    }

                    override fun onMessage(message: String) {
                        scope.launch { handleIncoming(message, key) }
                    }

                    override fun onClose(code: Int, reason: String?, remote: Boolean) {
                        Log.i(TAG, "WS closed: code=$code, reason=$reason, remote=$remote")
                        pcConnection.disconnect()
                        updateNotification("ORBIT — Reconnecting…")
                        if (!closeDeferred.isCompleted) {
                            closeDeferred.complete(Unit)
                        }
                    }

                    override fun onError(ex: Exception) {
                        Log.w(TAG, "WS error: ${ex.message}")
                        if (!closeDeferred.isCompleted) {
                            closeDeferred.complete(Unit)
                        }
                    }
                }

                wsClient?.connect()

                // Wait until this connection closes before attempting reconnection
                closeDeferred.await()
                backoffMs = 2000L
            } catch (e: Exception) {
                Log.e(TAG, "Connection error: ${e.message}")
            }

            pcConnection.disconnect()
            delay(backoffMs)
            backoffMs = (backoffMs * 1.5).toLong().coerceAtMost(15000L)
        }
    }

    // ------------------------------------------------------------------
    // Handshake & Incoming Message Handling
    // ------------------------------------------------------------------
    private suspend fun handleIncoming(raw: String, pairingKey: ByteArray) {
        val ws = wsClient ?: return
        try {
            when (handshakeStage) {
                1 -> {
                    // Stage 1: Received challenge from laptop
                    val sk = Crypto.deriveSessionKey(pairingKey, handshakeNonce)
                    sessionKey = sk
                    val challenge = Crypto.decrypt(raw, sk)
                    Log.i(TAG, "Handshake stage 1 OK — challenge received: $challenge")

                    // Echo challenge back (encrypted with session key)
                    ws.send(Crypto.encrypt(challenge, sk))

                    // Send device ID immediately to complete laptop's expectation
                    val deviceId = android.provider.Settings.Secure.getString(
                        contentResolver, android.provider.Settings.Secure.ANDROID_ID
                    ) ?: "orbit_android_satellite"
                    ws.send(deviceId)

                    handshakeStage = 2
                }
                2 -> {
                    // Stage 2: Laptop confirmed handshake
                    val plaintext = try {
                        Crypto.decrypt(raw, sessionKey ?: pairingKey)
                    } catch (e: Exception) {
                        raw
                    }
                    val json = JSONObject(plaintext)
                    val type = json.optString("type", "")
                    if (type == "handshake_ok" || type.isNotEmpty()) {
                        handshakeStage = 3
                        pcConnection.connected()
                        updateNotification("ORBIT — Connected to Laptop")
                        Log.i(TAG, "Handshake complete — CONNECTED TO LAPTOP!")
                        if (type != "handshake_ok") {
                            dispatch(type, json)
                        }
                    }
                }
                else -> {
                    // Normal operational messages (AES-256-GCM encrypted)
                    val sk = sessionKey ?: pairingKey
                    val plaintext = try {
                        Crypto.decrypt(raw, sk)
                    } catch (e: Exception) {
                        raw
                    }
                    val json = JSONObject(plaintext)
                    val type = json.optString("type", "")
                    Log.i(TAG, "Incoming WS operational message: type=$type, raw_len=${raw.length}")
                    dispatch(type, json)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Message/handshake error (stage $handshakeStage): ${e.message}")
            if (handshakeStage < 3) {
                ws.close()
            }
        }
    }

    private fun dispatch(type: String, json: JSONObject) {
        Log.i(TAG, "Dispatching incoming message: type=$type")
        when (type) {
            "clipboard" -> {
                val text = json.optString("text", "")
                if (text.isNotEmpty()) {
                    setClipboard(text)
                }
            }
            "file_incoming" -> {
                val filename = json.optString("filename", "orbit_file")
                val url = json.optString("url", "")
                if (url.isNotEmpty()) {
                    downloadFileToPhone(filename, url)
                }
            }
            "universal_control" -> {
                val action = json.optString("action", "")
                val x = json.optDouble("x", 0.5)
                val y = json.optDouble("y", 0.5)
                pcConnection.updateUniversalControl(action, x, y)
            }
            "notification", "intruder_alert" -> {
                val title = json.optString("title", "⚠️ Laptop Alert")
                val body = json.optString("body", "Activity detected on your laptop")
                val notifType = json.optString("type", if (type == "intruder_alert") "intruder_alert" else "")
                val snapshotB64 = json.optString("snapshot", "")
                val filename = json.optString("filename", "intruder_${System.currentTimeMillis()}.jpg")
                showEnhancedNotification(title, body, notifType, snapshotB64, filename)
            }
            "approval_request" -> {
                val action = json.optString("action", "")
                launchApprovalScreen(action)
            }
            "biometric_reenroll_request" -> {
                val token = json.optString("token", "")
                Log.i(TAG, "Biometric re-enrollment request from laptop (token: $token)")
                pcConnection.setPendingBiometricToken(token)
                try {
                    val authIntent = Intent(this, com.orbit.app.ui.BiometricAuthActivity::class.java).apply {
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS)
                        putExtra("token", token)
                    }
                    startActivity(authIntent)
                } catch (e: Exception) {
                    Log.w(TAG, "Failed to launch BiometricAuthActivity: ${e.message}")
                }
            }
            "ack" -> Log.d(TAG, "ACK received")
            else -> Log.d(TAG, "Incoming type: $type")
        }
    }

    // ------------------------------------------------------------------
    // Direct Laptop -> Phone File Downloader
    // ------------------------------------------------------------------
    private fun downloadFileToPhone(filename: String, fileUrl: String) {
        try {
            val uri = Uri.parse(fileUrl)
            val request = DownloadManager.Request(uri)
                .setTitle(filename)
                .setDescription("Received from Laptop via ORBIT")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
                .setAllowedOverMetered(true)
                .setAllowedOverRoaming(true)

            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            dm.enqueue(request)
            CoroutineScope(Dispatchers.Main).launch {
                Toast.makeText(this@WebSocketService, "Incoming: '$filename' saved to Downloads!", Toast.LENGTH_LONG).show()
            }
            Log.i(TAG, "Download enqueued via DownloadManager for $filename")
        } catch (e: Exception) {
            Log.w(TAG, "DownloadManager failed, using OkHttp fallback: ${e.message}")
            downloadViaOkHttp(filename, fileUrl)
        }
    }

    private fun downloadViaOkHttp(filename: String, fileUrl: String) {
        scope.launch(Dispatchers.IO) {
            try {
                val client = OkHttpClient()
                val req = Request.Builder().url(fileUrl).build()
                client.newCall(req).execute().use { resp ->
                    if (resp.isSuccessful) {
                        val body = resp.body ?: return@use
                        val targetDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                        targetDir.mkdirs()
                        val target = File(targetDir, filename)
                        target.outputStream().use { out ->
                            body.byteStream().copyTo(out)
                        }
                        withContext(Dispatchers.Main) {
                            Toast.makeText(this@WebSocketService, "✓ Saved '$filename' to Downloads", Toast.LENGTH_LONG).show()
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "OkHttp fallback download error: ${e.message}")
            }
        }
    }

    // ------------------------------------------------------------------
    // Outgoing encrypted message
    // ------------------------------------------------------------------
    fun sendEncrypted(type: String, payload: JSONObject, key: ByteArray) {
        val ws = wsClient ?: return
        if (ws.isClosed || !ws.isOpen) return
        val currentKey = sessionKey ?: key
        try {
            val msg = JSONObject().apply {
                put("type", type)
                val keys = payload.keys()
                while (keys.hasNext()) {
                    val k = keys.next()
                    put(k, payload.get(k))
                }
            }
            val encrypted = Crypto.encrypt(msg.toString(), currentKey)
            ws.send(encrypted)
            Log.d(TAG, "Sent $type")
        } catch (e: Exception) {
            Log.e(TAG, "sendEncrypted error: ${e.message}")
        }
    }

    private fun setClipboard(text: String) {
        lastReceivedClipboard = text
        pcConnection.updateClipboardText(text)
        try {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
            cm.setPrimaryClip(android.content.ClipData.newPlainText("ORBIT", text))
            Log.d(TAG, "Android clipboard updated (${text.length} chars)")
        } catch (e: Exception) {
            Log.w(TAG, "Clipboard update warning: ${e.message}")
        }
    }

    private fun showEnhancedNotification(
        title: String,
        body: String,
        notifType: String,
        snapshotB64: String,
        filename: String
    ) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        var bitmap: Bitmap? = null

        if (snapshotB64.isNotEmpty()) {
            try {
                val imageBytes = Base64.decode(snapshotB64, Base64.DEFAULT)
                bitmap = BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)

                // Save snapshot directly into Phone's Downloads folder
                val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                downloadsDir.mkdirs()
                val targetFile = File(downloadsDir, filename)
                targetFile.writeBytes(imageBytes)
                MediaScannerConnection.scanFile(
                    this,
                    arrayOf(targetFile.absolutePath),
                    arrayOf("image/jpeg"),
                    null
                )
                Log.i(TAG, "Saved intruder snapshot to phone Downloads: ${targetFile.absolutePath}")
            } catch (e: Exception) {
                Log.w(TAG, "Failed to decode/save snapshot: ${e.message}")
            }
        }

        val channelId = if (notifType == "intruder_alert") "orbit_security_alerts" else "orbit_notifications"
        val openIntent = Intent(this, com.orbit.app.ui.MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notifBuilder = Notification.Builder(this, channelId)
            .setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setShowWhen(true)

        if (bitmap != null) {
            notifBuilder.setStyle(
                Notification.BigPictureStyle()
                    .bigPicture(bitmap)
                    .setBigContentTitle(title)
                    .setSummaryText(body)
            )
            notifBuilder.setLargeIcon(bitmap)
        } else {
            notifBuilder.setStyle(Notification.BigTextStyle().bigText(body))
        }

        val notifId = if (notifType == "intruder_alert") 9999 else System.currentTimeMillis().toInt()
        nm.notify(notifId, notifBuilder.build())

        // Immediate toast feedback on main thread
        CoroutineScope(Dispatchers.Main).launch {
            Toast.makeText(
                this@WebSocketService,
                "⚠️ $title: $body" + if (bitmap != null) " (Photo saved to Downloads)" else "",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    private fun launchApprovalScreen(action: String) {
        val intent = Intent(this, com.orbit.app.ui.ApprovalScreen::class.java).apply {
            putExtra("action", action)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        startActivity(intent)
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIF_ID, buildNotification(text))
    }

    private fun buildNotification(text: String): Notification {
        return Notification.Builder(this, channelName)
            .setContentTitle("ORBIT")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .build()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channels = listOf(
                NotificationChannel(channelName, "ORBIT Link", NotificationManager.IMPORTANCE_LOW),
                NotificationChannel("orbit_notifications", "ORBIT Transfers", NotificationManager.IMPORTANCE_HIGH),
                NotificationChannel("orbit_security_alerts", "ORBIT Security & Intruder Alerts", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "High-priority alerts with photos when someone else uses your laptop"
                    enableVibration(true)
                    vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 600)
                    lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                }
            )
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            channels.forEach { nm.createNotificationChannel(it) }
        }
    }

    override fun onDestroy() {
        scope.cancel()
        wsClient?.close()
        super.onDestroy()
        Log.i(TAG, "WebSocketService destroyed")
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val NOTIF_ID = 1
    }
}
