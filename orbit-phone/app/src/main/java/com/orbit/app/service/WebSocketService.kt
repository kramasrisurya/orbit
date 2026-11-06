package com.orbit.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Base64
import android.util.Log
import com.orbit.app.data.ConnectionState
import com.orbit.app.data.PcConnection
import com.orbit.app.data.Prefs
import com.orbit.app.util.Constants
import com.orbit.app.util.Crypto
import kotlinx.coroutines.*
import org.json.JSONObject
import org.java_websocket.client.WebSocketClient
import org.java_websocket.handshake.ServerHandshake
import java.net.URI
import java.security.SecureRandom

/**
 * Foreground service that maintains the WebSocket connection to the PC.
 *
 * - Performs the AES handshake on connect
 * - Decrypts/parses incoming messages and dispatches them
 * - Encrypts outgoing messages
 * - Retries with exponential backoff on disconnect
 */
class WebSocketService : Service() {

    private val TAG = "WebSocketService"
    private val channelName = "orbit_ws"
    private var scope: CoroutineScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var wsClient: WebSocketClient? = null
    private var sessionKey: ByteArray? = null
    private var backoffMs = 5000L
    // Handshake state machine
    private var handshakeStage = 0  // 0=idle, 1=awaiting challenge, 2=awaiting confirm
    private var handshakeNonce: ByteArray = ByteArray(16)
    private var handshakeChallenge: String? = null

    private lateinit var pcConnection: PcConnection
    private lateinit var prefs: Prefs

    override fun onCreate() {
        super.onCreate()
        createChannel()
        pcConnection = (application as com.orbit.app.OrbitApp).pcConnection
        prefs = Prefs(applicationContext)
        // Register as the sender for PcConnection
        pcConnection.sender = { type, payload, key ->
            sendEncrypted(type, payload, key)
        }
        startForeground(NOTIF_ID, buildNotification("ORBIT — Connecting to PC…"))
        Log.i(TAG, "WebSocketService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        scope.launch { connectLoop() }
        return START_STICKY
    }

    // ------------------------------------------------------------------
    // Connection loop with exponential backoff
    // ------------------------------------------------------------------
    private suspend fun connectLoop() {
        while (isActive) {
            try {
                connect()
                // If we get here, the connection closed
                backoffMs = 5000L
            } catch (e: Exception) {
                Log.e(TAG, "Connection error: ${e.message}")
            }
            pcConnection.disconnect()
            updateNotification("ORBIT — Reconnecting…")
            delay(backoffMs)
            backoffMs = (backoffMs * 2).coerceAtMost(60000L)
        }
    }

    private fun connect() {
        val key = prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
        if (key == null) {
            Log.w(TAG, "No pairing key — cannot connect")
            pcConnection.disconnect()
            return
        }

        pcConnection.connect()
        updateNotification("ORBIT — Connecting to PC…")

        // Reset handshake state for this connection
        handshakeStage = 0
        sessionKey = null

        val uri = URI(pcConnection.wsUrl)
        wsClient = object : WebSocketClient(uri) {
            override fun onOpen(handshake: ServerHandshake?) {
                Log.i(TAG, "WS opened — sending nonce")
                // Stage 1: send random nonce
                handshakeNonce = ByteArray(16).also { SecureRandom().nextBytes(it) }
                handshakeStage = 1
                send(Base64.encodeToString(handshakeNonce, Base64.NO_WRAP))
            }

            override fun onMessage(message: String) {
                scope.launch { handleIncoming(message, key) }
            }

            override fun onClose(code: Int, reason: String?, remote: Boolean) {
                Log.i(TAG, "WS closed: $code $reason")
            }

            override fun onError(ex: Exception) {
                Log.e(TAG, "WS error: ${ex.message}")
            }
        }
        wsClient?.connect()
    }

    // ------------------------------------------------------------------
    // Message handling (handshake state machine + normal messages)
    // ------------------------------------------------------------------
    private suspend fun handleIncoming(raw: String, pairingKey: ByteArray) {
        val ws = wsClient ?: return
        try {
            when (handshakeStage) {
                1 -> {
                    // Stage 1: received encrypted challenge
                    // Derive session key from pairing key + our nonce
                    val sk = Crypto.deriveSessionKey(pairingKey, handshakeNonce)
                    sessionKey = sk
                    val challenge = Crypto.decrypt(raw, sk)
                    Log.i(TAG, "Handshake stage 1 OK — challenge: $challenge")
                    // Stage 2: echo the challenge back (encrypted)
                    handshakeChallenge = challenge
                    handshakeStage = 2
                    ws.send(Crypto.encrypt(challenge, sk))
                }
                2 -> {
                    // Stage 2: send device_id (plaintext) to complete handshake
                    handshakeStage = 3
                    val deviceId = android.provider.Settings.Secure.getString(
                        contentResolver, android.provider.Settings.Secure.ANDROID_ID
                    ) ?: "unknown"
                    ws.send(deviceId)
                    Log.i(TAG, "Handshake complete — device: $deviceId")
                    pcConnection.connected()
                    backoffMs = 5000L
                    updateNotification("ORBIT — Connected to PC")
                }
                else -> {
                    // Normal operation: decrypt and dispatch
                    val sk = sessionKey ?: return
                    val message = Crypto.decrypt(raw, sk)
                    val json = JSONObject(message)
                    val type = json.optString("type", "")
                    dispatch(type, json)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Handshake/message error (stage $handshakeStage): ${e.message}")
            if (handshakeStage < 3) {
                // Handshake failed — close and let the loop reconnect
                ws.close()
            }
        }
    }

    private fun dispatch(type: String, json: JSONObject) {
        when (type) {
            "notification" -> {
                val title = json.optString("title", "ORBIT")
                val body = json.optString("body", "")
                val snapshot = json.optString("snapshot", null)
                showNotification(title, body, snapshot)
            }
            "approval_request" -> {
                val action = json.optString("action", "")
                launchApprovalScreen(action)
            }
            "display_data" -> {
                val panel = json.optString("panel", "")
                // Update shared StateFlow for UI
                Log.d(TAG, "Display data for panel: $panel")
            }
            "clipboard" -> {
                val text = json.optString("text", "")
                setClipboard(text)
            }
            "ack" -> {
                Log.d(TAG, "ACK received")
            }
            else -> Log.d(TAG, "Unknown message type: $type")
        }
    }

    // ------------------------------------------------------------------
    // Outgoing
    // ------------------------------------------------------------------
    fun sendEncrypted(type: String, payload: JSONObject, key: ByteArray) {
        val ws = wsClient ?: return
        if (ws.isClosed) return
        val sessionKey = sessionKey ?: return
        val msg = JSONObject().apply {
            put("type", type)
            putAll(payload)
        }
        val encrypted = Crypto.encrypt(msg.toString(), sessionKey)
        ws.send(encrypted)
        Log.d(TAG, "Sent: $type")
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------
    private fun showNotification(title: String, body: String, snapshotB64: String?) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val notif = Notification.Builder(this, "orbit_notifications")
            .setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setAutoCancel(true)
            .build()
        nm.notify(System.currentTimeMillis().toInt(), notif)
    }

    private fun launchApprovalScreen(action: String) {
        val intent = Intent(this, com.orbit.app.ui.ApprovalScreen::class.java).apply {
            putExtra("action", action)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        startActivity(intent)
    }

    private fun setClipboard(text: String) {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
        cm.setPrimaryClip(android.content.ClipData.newPlainText("ORBIT", text))
        Log.d(TAG, "Clipboard set (${text.length} chars)")
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
                NotificationChannel(channelName, "ORBIT Connection", NotificationManager.IMPORTANCE_LOW),
                NotificationChannel("orbit_notifications", "ORBIT Alerts", NotificationManager.IMPORTANCE_HIGH)
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
