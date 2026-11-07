package com.orbit.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.BluetoothLeAdvertiser
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.orbit.app.util.Constants
import kotlinx.coroutines.*

/**
 * Foreground service that broadcasts the ORBIT BLE service UUID
 * every `BLE_BROADCAST_INTERVAL_MS` so the PC can detect proximity.
 */
class BleService : Service() {

    private val TAG = "BleService"
    private val channelName = "orbit_ble"
    private var job: Job? = null
    private var advertiser: BluetoothLeAdvertiser? = null
    private var advertising = false

    override fun onCreate() {
        super.onCreate()
        createChannel()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIF_ID, buildNotification("ORBIT — Searching for PC"), android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
            } else {
                startForeground(NOTIF_ID, buildNotification("ORBIT — Searching for PC"))
            }
        } catch (e: Exception) {
            Log.w(TAG, "BleService startForeground error: ${e.message}")
        }
        Log.i(TAG, "BleService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startBroadcasting()
        return START_STICKY
    }

    private fun startBroadcasting() {
        job?.cancel()
        job = CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            val adapter = BluetoothAdapter.getDefaultAdapter() ?: return@launch
            if (adapter.isEnabled.not()) {
                Log.w(TAG, "Bluetooth disabled")
                return@launch
            }
            advertiser = adapter.bluetoothLeAdvertiser
            while (isActive) {
                try {
                    advertiseOnce(adapter.bluetoothLeAdvertiser)
                } catch (e: Exception) {
                    Log.e(TAG, "BLE advertise failed: ${e.message}")
                }
                delay(Constants.BLE_BROADCAST_INTERVAL_MS)
            }
        }
    }

    private val advertiseCallback = object : AdvertiseCallback() {
        override fun onStartSuccess(settingsInEffect: AdvertiseSettings?) {
            super.onStartSuccess(settingsInEffect)
            advertising = true
        }

        override fun onStartFailure(errorCode: Int) {
            super.onStartFailure(errorCode)
            advertising = false
            Log.w(TAG, "BLE advertising failed: $errorCode")
        }
    }

    private suspend fun advertiseOnce(advertiser: BluetoothLeAdvertiser?) {
        advertiser ?: return
        if (advertising) return

        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_POWER)
            .setConnectable(false)
            .setTimeout(3000)
            .build()

        val data = AdvertiseData.Builder()
            .setIncludeDeviceName(false)
            .apply {
                try {
                    addServiceUuid(android.os.ParcelUuid.fromString(Constants.ORBIT_BLE_SERVICE_UUID))
                } catch (e: Exception) {
                    Log.e(TAG, "Invalid BLE UUID: ${e.message}")
                }
            }
            .build()

        try {
            advertiser.startAdvertising(settings, data, advertiseCallback)
        } catch (e: Exception) {
            advertising = false
            Log.e(TAG, "startAdvertising threw: ${e.message}")
        }
    }

    override fun onDestroy() {
        job?.cancel()
        try {
            advertiser?.stopAdvertising(advertiseCallback)
        } catch (e: Exception) {
            // ignore
        }
        super.onDestroy()
        Log.i(TAG, "BleService destroyed")
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelName, "ORBIT BLE", NotificationManager.IMPORTANCE_LOW
            )
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        return Notification.Builder(this, channelName)
            .setContentTitle("ORBIT")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .build()
    }

    companion object {
        const val NOTIF_ID = 2
    }
}
