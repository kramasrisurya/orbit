package com.orbit.app

import android.app.Application
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log
import com.orbit.app.data.PcConnection
import com.orbit.app.data.Prefs
import com.orbit.app.service.BleService
import com.orbit.app.service.WebSocketService

/**
 * ORBIT Application class.
 *
 * On create:
 *   - Initializes Firebase (if configured)
 *   - Loads saved PC connection details from SharedPreferences
 *   - Starts WebSocketService and BleService as foreground services
 */
class OrbitApp : Application() {

    companion object {
        const val TAG = "OrbitApp"
        lateinit var instance: OrbitApp
            private set
    }

    lateinit var pcConnection: PcConnection
        private set
    lateinit var prefs: Prefs
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this

        // Initialize preferences
        prefs = Prefs(this)

        // Initialize PC connection manager
        pcConnection = PcConnection(this)

        // Initialize Firebase (optional — falls back to WebSocket-only)
        initFirebase()

        // Start foreground services
        startServices()

        Log.i(TAG, "ORBIT app initialized")
    }

    private fun initFirebase() {
        try {
            // Firebase is auto-initialized if google-services.json is present.
            // If not, this is a no-op and notifications use WebSocket only.
            Log.d(TAG, "Firebase init attempted")
        } catch (e: Exception) {
            Log.w(TAG, "Firebase not available: ${e.message}")
        }
    }

    private fun startServices() {
        // Start WebSocket service
        startForegroundServiceSafely(WebSocketService::class.java)

        // Start BLE service
        startForegroundServiceSafely(BleService::class.java)
    }

    private fun startForegroundServiceSafely(serviceClass: Class<out android.app.Service>) {
        try {
            val intent = Intent(this, serviceClass)
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
            Log.d(TAG, "Started ${serviceClass.simpleName}")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start ${serviceClass.simpleName}: ${e.message}")
        }
    }
}
