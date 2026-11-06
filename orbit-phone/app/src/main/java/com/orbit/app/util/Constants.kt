package com.orbit.app.util

import java.util.UUID

object Constants {
    const val ORBIT_BLE_SERVICE_UUID = "0000-ORBIT-0000-1000-8000-00805F9B34FB"
    const val ORBIT_BLE_CHARACTERISTIC_UUID = "0000-ORBIT-0001-1000-8000-00805F9B34FB"

    const val DEFAULT_WS_PORT = 8765
    const val BLE_BROADCAST_INTERVAL_MS = 3000L
    const val SHAKE_THRESHOLD = 15f
    const val SHAKE_WINDOW_MS = 2000L

    const val PC_IP = "pc_ip"
    const val PC_PORT = "pc_port"
    const val PAIRING_KEY = "pairing_key"
    const val GEO_RADIUS = "geo_radius"
    const val SHAKE_SENSITIVITY = "shake_sensitivity"

    const val NOTIF_INTRUDER = "notif_intruder"
    const val NOTIF_LOCKED = "notif_locked"
    const val NOTIF_POSTURE = "notif_posture"
    const val NOTIF_STRESS = "notif_stress"
    const val NOTIF_BREAK = "notif_break"
    const val NOTIF_MODE = "notif_mode"
    const val NOTIF_APPROVAL = "notif_approval"
    const val NOTIF_AMBIENT = "notif_ambient"
}
