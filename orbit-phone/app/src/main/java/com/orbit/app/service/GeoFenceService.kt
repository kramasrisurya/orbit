package com.orbit.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.google.android.gms.location.*
import com.orbit.app.data.PcConnection
import com.orbit.app.data.Prefs
import com.orbit.app.util.Constants
import kotlinx.coroutines.*
import org.json.JSONObject

/**
 * Foreground service that monitors a geofence around the home location.
 * Sends "geo" events over WebSocket when the user leaves/returns.
 */
class GeoFenceService : Service() {

    private val TAG = "GeoFenceService"
    private val channelName = "orbit_geo"
    private var scope: CoroutineScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var geofencingClient: GeofencingClient? = null
    private var fusedClient: FusedLocationProviderClient? = null

    private lateinit var pcConnection: PcConnection
    private lateinit var prefs: Prefs

    override fun onCreate() {
        super.onCreate()
        createChannel()
        pcConnection = (application as com.orbit.app.OrbitApp).pcConnection
        prefs = Prefs(applicationContext)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIF_ID, buildNotification("ORBIT — GeoFence Active"), android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            } else {
                startForeground(NOTIF_ID, buildNotification("ORBIT — GeoFence Active"))
            }
        } catch (e: Exception) {
            Log.w(TAG, "GeoFenceService startForeground error: ${e.message}")
        }
        Log.i(TAG, "GeoFenceService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        setupGeofence()
        return START_STICKY
    }

    private fun setupGeofence() {
        try {
            geofencingClient = LocationServices.getGeofencingClient(this)
            fusedClient = LocationServices.getFusedLocationProviderClient(this)

            fusedClient?.lastLocation?.addOnSuccessListener { location ->
                if (location == null) {
                    Log.w(TAG, "No location available for geofence")
                    return@addOnSuccessListener
                }

                val geofence = Geofence.Builder()
                    .setRequestId("orbit_home")
                    .setCircularRegion(
                        location.latitude,
                        location.longitude,
                        prefs.geoRadius.toFloat()
                    )
                    .setExpirationDuration(Geofence.NEVER_EXPIRE)
                    .setTransitionTypes(
                        Geofence.GEOFENCE_TRANSITION_EXIT or
                        Geofence.GEOFENCE_TRANSITION_ENTER
                    )
                    .build()

                val request = GeofencingRequest.Builder()
                    .addGeofence(geofence)
                    .setInitialTrigger(GeofencingRequest.INITIAL_TRIGGER_ENTER)
                    .build()

                val intent = Intent(this, GeofenceBroadcastReceiver::class.java)
                val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
                } else {
                    PendingIntent.FLAG_UPDATE_CURRENT
                }
                val pendingIntent = PendingIntent.getBroadcast(this, 0, intent, flags)

                try {
                    geofencingClient?.addGeofences(request, pendingIntent)
                        ?.addOnSuccessListener {
                            Log.i(TAG, "Geofence registered at (${location.latitude}, ${location.longitude})")
                        }
                        ?.addOnFailureListener { e ->
                            Log.e(TAG, "Failed to add geofence: ${e.message}")
                        }
                } catch (se: SecurityException) {
                    Log.e(TAG, "Permission missing for geofence: ${se.message}")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Geofence setup failed: ${e.message}")
        }
    }

    // Inner broadcast receiver for geofence transitions
    class GeofenceBroadcastReceiver : android.content.BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val result = GeofencingEvent.fromIntent(intent) ?: return
            val pcConnection = (context.applicationContext as com.orbit.app.OrbitApp).pcConnection
            val key = (context.applicationContext as com.orbit.app.OrbitApp).prefs
                .pairingKey?.let { android.util.Base64.decode(it, android.util.Base64.NO_WRAP) }
                ?: return

            when (result.geofenceTransition) {
                Geofence.GEOFENCE_TRANSITION_EXIT -> {
                    Log.i("GeoFenceReceiver", "Geofence EXIT — user left")
                    sendGeo(pcConnection, key, "left")
                }
                Geofence.GEOFENCE_TRANSITION_ENTER -> {
                    Log.i("GeoFenceReceiver", "Geofence ENTER — user returned")
                    sendGeo(pcConnection, key, "returned")
                }
            }
        }

        private fun sendGeo(pcConnection: PcConnection, key: ByteArray, status: String) {
            val payload = JSONObject().apply {
                put("type", "geo")
                put("status", status)
                put("ts", System.currentTimeMillis())
            }
            pcConnection.send("geo", payload, key)
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

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelName,
                "ORBIT GeoFence",
                NotificationManager.IMPORTANCE_LOW
            )
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val NOTIF_ID = 2
    }
}
