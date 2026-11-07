package com.orbit.app.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject
import com.orbit.app.util.Crypto
import android.util.Base64

/**
 * Manages the PC connection details (IP, port, pairing key) and
 * exposes connection state as a StateFlow.
 *
 * The actual WebSocket lives in WebSocketService; this class is the
 * single source of truth for *where* to connect and the pairing key.
 */
class PcConnection(context: Context) {
    private val prefs = Prefs(context.applicationContext)

    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState: StateFlow<ConnectionState> = _connectionState.asStateFlow()

    private val _rssi = MutableStateFlow(0)
    val rssi: StateFlow<Int> = _rssi.asStateFlow()

    data class UniversalControlState(
        val isLeaped: Boolean = false,
        val x: Float = 0.5f,
        val y: Float = 0.5f
    )

    private val _universalControl = MutableStateFlow(UniversalControlState())
    val universalControl: StateFlow<UniversalControlState> = _universalControl.asStateFlow()

    private val _lastClipboardText = MutableStateFlow("")
    val lastClipboardText: StateFlow<String> = _lastClipboardText.asStateFlow()

    private val _pendingBiometricToken = MutableStateFlow<String?>(null)
    val pendingBiometricToken: StateFlow<String?> = _pendingBiometricToken.asStateFlow()

    fun setPendingBiometricToken(token: String?) {
        _pendingBiometricToken.value = token
    }

    fun updateUniversalControl(action: String, x: Double, y: Double) {
        _universalControl.value = UniversalControlState(
            isLeaped = (action == "cursor_enter" || action == "cursor_move"),
            x = x.toFloat(),
            y = y.toFloat()
        )
    }

    fun updateClipboardText(text: String) {
        _lastClipboardText.value = text
    }

    fun sendMouseMove(dx: Int, dy: Int) {
        val key = pairingKeyBytes ?: return
        val payload = JSONObject().apply {
            put("dx", dx)
            put("dy", dy)
        }
        send("mouse_move", payload, key)
    }

    fun sendMouseClick(button: String = "left") {
        val key = pairingKeyBytes ?: return
        val payload = JSONObject().apply {
            put("button", button)
        }
        send("mouse_click", payload, key)
    }

    fun sendMouseScroll(dy: Int) {
        val key = pairingKeyBytes ?: return
        val payload = JSONObject().apply {
            put("dy", dy)
        }
        send("mouse_scroll", payload, key)
    }

    fun sendRemoteType(text: String) {
        val key = pairingKeyBytes ?: return
        val payload = JSONObject().apply {
            put("text", text)
        }
        send("remote_type", payload, key)
    }

    fun connect() {
        _connectionState.value = ConnectionState.CONNECTING
    }

    fun connected() {
        _connectionState.value = ConnectionState.CONNECTED
    }

    fun disconnect() {
        _connectionState.value = ConnectionState.DISCONNECTED
        _rssi.value = 0
    }

    fun reconnect() {
        disconnect()
        connect()
    }

    fun updateRssi(rssi: Int) {
        _rssi.value = rssi
    }

    val wsUrl: String
        get() = "ws://${prefs.pcIp}:${prefs.pcPort}"

    val pairingKeyBytes: ByteArray?
        get() {
            val keyB64 = prefs.pairingKey ?: return null
            return Base64.decode(keyB64, Base64.NO_WRAP)
        }

    fun send(type: String, payload: JSONObject, key: ByteArray) {
        // Delegates to WebSocketService via a registered sender
        sender?.invoke(type, payload, key)
    }

    // Registered by WebSocketService
    var sender: ((String, JSONObject, ByteArray) -> Unit)? = null
}
