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
