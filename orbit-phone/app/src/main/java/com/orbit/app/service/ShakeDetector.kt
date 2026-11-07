package com.orbit.app.service

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Base64
import android.util.Log
import com.orbit.app.data.PcConnection
import com.orbit.app.data.Prefs
import com.orbit.app.util.Constants
import kotlinx.coroutines.*
import org.json.JSONObject

/**
 * Detects phone shakes via the accelerometer and sends shake counts
 * over the WebSocket.
 *
 * A "shake" is: acceleration magnitude > threshold for > 100ms.
 * Shakes within a 2-second window are counted (1, 2, or 3).
 * Provides haptic feedback on each detected shake.
 */
class ShakeDetector(
    private val context: Context,
    private val pcConnection: PcConnection,
    private val prefs: Prefs
) : SensorEventListener {

    private val TAG = "ShakeDetector"
    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator

    private var accelerometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private var scope: CoroutineScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    // Shake counting within a window
    private var shakeCount = 0
    private var windowStart = 0L
    private var lastShakeTime = 0L
    private var isShaking = false

    // Sensitivity → threshold mapping (m/s²)
    private val threshold: Float
        get() = when (prefs.shakeSensitivity) {
            0 -> 20f  // low sensitivity (harder to trigger)
            1 -> Constants.SHAKE_THRESHOLD  // medium (15)
            2 -> 10f  // high sensitivity (easier to trigger)
            else -> Constants.SHAKE_THRESHOLD
        }

    fun start() {
        if (accelerometer == null) {
            Log.w(TAG, "No accelerometer — ShakeDetector disabled")
            return
        }
        sensorManager.registerListener(this, accelerometer!!, SensorManager.SENSOR_DELAY_GAME)
        Log.i(TAG, "ShakeDetector started (threshold=$threshold)")
    }

    fun stop() {
        sensorManager.unregisterListener(this)
        scope.cancel()
        Log.i(TAG, "ShakeDetector stopped")
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ACCELEROMETER) return
        val (x, y, z) = event.values

        // Gravity-compensated magnitude
        val magnitude = Math.sqrt(((x * x) + (y * y) + (z * z) - SensorManager.GRAVITY_EARTH * SensorManager.GRAVITY_EARTH).toDouble())

        val now = System.currentTimeMillis()

        if (magnitude > threshold) {
            if (!isShaking) {
                isShaking = true
                lastShakeTime = now
                onShakeDetected(now)
            }
        } else if (isShaking && now - lastShakeTime > 100) {
            isShaking = false
        }
    }

    private fun onShakeDetected(now: Long) {
        // Window management
        if (now - windowStart > Constants.SHAKE_WINDOW_MS) {
            // New window
            windowStart = now
            shakeCount = 0
        }
        shakeCount++
        Log.d(TAG, "Shake detected (count=$shakeCount)")
    }

    private fun vibrate() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(VibrationEffect.createOneShot(50, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(50)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Vibrate failed: ${e.message}")
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    // ------------------------------------------------------------------
    // Periodic flush of shake count at the end of each window
    // ------------------------------------------------------------------
    fun startWindowWatcher() {
        scope.launch {
            while (isActive) {
                delay(Constants.SHAKE_WINDOW_MS)
                if (shakeCount > 0) {
                    flushShakes()
                }
            }
        }
    }

    private fun flushShakes() {
        val count = shakeCount.coerceIn(1, 3)
        shakeCount = 0
        val key = prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) } ?: return
        val payload = JSONObject().apply { put("count", count) }
        pcConnection.send("shake", payload, key)
        Log.i(TAG, "Sent shake count=$count")
    }
}
