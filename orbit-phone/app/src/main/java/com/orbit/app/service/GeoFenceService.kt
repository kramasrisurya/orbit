package com.orbit.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.location.Geofence
import android.location.GeofencingClient
import android.location.GeofencingRequest
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
        startForeground(NOTIF_ID, buildNotification("ORBIT — GeoFence Active"))
        Log.i(TAG, "GeoFenceService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        scope.launch { setupGeofence() }
        return START_STICKY
    }

    private suspend fun setupGeofence() {
        try {
            geofencingClient = LocationServices.getGeofencingClient(this)
            fusedClient = LocationServices.getFusedLocationProviderClient(this)

            // Get current location as the geofence center
            val location = fusedClient!!.lastLocation.await()
            if (location == null) {
                Log.w(TAG, "No location available for geofence")
                return
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
            geofencingClient!!.addGeofences(request, intent)
                .addOnSuccessListener {
                    Log.i(TAG, "Geofence added at (${location.latitude}, ${location.longitude}) r=${prefs.geoRadius}m")
                }
                .addOnFailureListener { e ->
                    Log.e(TAG, "Failed to add geofence: ${e.message}")
                }
        } catch (e: Exception) {
            Log.e(TAG, "Geofence setup failed: ${e.message}")
        }
    }

    // Inner broadcast receiver for geofence transitions
    class GeofenceBroadcastReceiver : android.content.BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val result = GeofencingClient.getGeofencingEvent(intent)
                ?: return
            val pcConnection = (context.applicationContext as com.orbit.app.OrbitApp).pcConnection
            val key = (context.applicationContext as com.orbit.app.OrbitApp).prefs
                .pairingKey?.let { android.util.Base64.decode(it, android.util.Base64.NO_WRAP) }
                ?: return

            when (result.geofenceTransition) {
                Geofence.GEOFENCE_TRANSITION_EXIT -> {
                    Log.i(TAG, "Geofence EXIT — user left")
                    sendGeo(pcConnection, key, "left")
                }
                Geofence.GEOFENCE_TRANSITION_ENTER -> {
                    Log.i(TAG, "Geofence ENTER — user returned")
                    sendGeo(pcConnection, key, "returned")
                }
            }
        }

        private fun sendGeo(pc: PcConnection, key: ByteArray, status: String) {
            val payload = JSONObject().apply { put("status", status) }
            pc.send("geo", payload, key)
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
                channelName, "ORBIT GeoFence", NotificationManager.IMPORTANCE_LOW
            )
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
        Log.i(TAG, "GeoFenceService destroyed")
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val NOTIF_ID = 3
    }
}
