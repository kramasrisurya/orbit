package com.orbit.app.data

import org.json.JSONObject

/**
 * Data classes for all WebSocket messages (both directions).
 */

data class PhoneMessage(
    val type: String,
    val payload: JSONObject,
    val timestamp: String,
    val seq: Int
)

data class PcMessage(
    val type: String,
    val payload: JSONObject,
    val timestamp: String,
    val seq: Int
)

// --- Specific payload types ---

data class ShakePayload(val count: Int)
data class NfcPayload(val mode: String)
data class RemotePayload(val action: String)
data class ClipboardPayload(val text: String)
data class GeoPayload(val status: String) // "left" | "returned"
data class ApprovalPayload(val granted: Boolean)
data class StatusPayload(val rssi: Int, val ssid: String)
data class NotificationPayload(val title: String, val body: String, val snapshot: String?)
data class DisplayPayload(val panel: String, val data: JSONObject)

// --- Connection state ---

enum class ConnectionState {
    CONNECTED,
    CONNECTING,
    DISCONNECTED
}
