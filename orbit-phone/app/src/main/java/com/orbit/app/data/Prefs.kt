package com.orbit.app.data

import android.content.Context
import android.content.SharedPreferences
import com.orbit.app.util.Constants

/**
 * SharedPreferences wrapper with typed getters/setters.
 */
class Prefs(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("orbit_prefs", Context.MODE_PRIVATE)

    // --- PC connection ---
    var pcIp: String
        get() = prefs.getString(Constants.PC_IP, "192.168.1.100") ?: "192.168.1.100"
        set(v) = prefs.edit().putString(Constants.PC_IP, v).apply()

    var pcPort: Int
        get() = prefs.getInt(Constants.PC_PORT, Constants.DEFAULT_WS_PORT)
        set(v) = prefs.edit().putInt(Constants.PC_PORT, v).apply()

    var pairingKey: String?
        get() = prefs.getString(Constants.PAIRING_KEY, null)
        set(v) = prefs.edit().putString(Constants.PAIRING_KEY, v).apply()

    // --- Geo fence ---
    var geoRadius: Int
        get() = prefs.getInt(Constants.GEO_RADIUS, 200)
        set(v) = prefs.edit().putInt(Constants.GEO_RADIUS, v).apply()

    // --- Shake sensitivity ---
    var shakeSensitivity: Int
        get() = prefs.getInt(Constants.SHAKE_SENSITIVITY, 1) // 0=low, 1=med, 2=high
        set(v) = prefs.edit().putInt(Constants.SHAKE_SENSITIVITY, v).apply()

    // --- Notification toggles ---
    var notifIntruder: Boolean
        get() = prefs.getBoolean(Constants.NOTIF_INTRUDER, true)
        set(v) = prefs.edit().putBoolean(Constants.NOTIF_INTRUDER, v).apply()

    var notifLocked: Boolean
        get() = prefs.getBoolean(Constants.NOTIF_LOCKED, true)
        set(v) = prefs.edit().putBoolean(Constants.NOTIF_LOCKED, v).apply()

    var notifPosture: Boolean
        get() = prefs.getBoolean(Constants.NOTIF_POSTURE, true)
        set(v) = prefs.edit().putBoolean(Constants.NOTIF_POSTURE, v).apply()

    var notifStress: Boolean
        get() = prefs.getBoolean(Constants.NOTIF_STRESS, true)
        set(v) = prefs.edit().putBoolean(Constants.NOTIF_STRESS, v).apply()

    var notifBreak: Boolean
        get() = prefs.getBoolean(Constants.NOTIF_BREAK, true)
        set(v) = prefs.edit().putBoolean(Constants.NOTIF_BREAK, v).apply()

    var notifMode: Boolean
        get() = prefs.getBoolean(Constants.NOTIF_MODE, true)
        set(v) = prefs.edit().putBoolean(Constants.NOTIF_MODE, v).apply()

    var notifApproval: Boolean
        get() = prefs.getBoolean(Constants.NOTIF_APPROVAL, true)
        set(v) = prefs.edit().putBoolean(Constants.NOTIF_APPROVAL, v).apply()

    var notifAmbient: Boolean
        get() = prefs.getBoolean(Constants.NOTIF_AMBIENT, true)
        set(v) = prefs.edit().putBoolean(Constants.NOTIF_AMBIENT, v).apply()

    fun isPaired(): Boolean = pairingKey != null

    fun clearPairing() {
        prefs.edit().remove(Constants.PAIRING_KEY).apply()
    }
}
