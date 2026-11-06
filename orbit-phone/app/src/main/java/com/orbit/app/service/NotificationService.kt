package com.orbit.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Base64
import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.orbit.app.ui.ApprovalScreen

/**
 * FCM message receiver. Shows local Android notifications for
 * push messages from the PC.
 */
class NotificationService : FirebaseMessagingService() {

    private val TAG = "NotificationService"

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        Log.d(TAG, "FCM message: ${message.notification?.body}")

        val title = message.notification?.title ?: message.data["title"] ?: "ORBIT"
        val body = message.notification?.body ?: message.data["body"] ?: ""
        val ntype = message.data["type"] ?: "ambient"
        val snapshotB64 = message.data["snapshot"]

        // Approval requests launch the full-screen activity
        if (ntype == "approval_request") {
            val action = message.data["action"] ?: ""
            val intent = Intent(this, ApprovalScreen::class.java).apply {
                putExtra("action", action)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(intent)
            return
        }

        showNotification(ntype, title, body, snapshotB64)
    }

    private fun showNotification(ntype: String, title: String, body: String, snapshotB64: String?) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        // Create a channel per notification type
        val channelId = "orbit_$ntype"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "ORBIT $ntype",
                when (ntype) {
                    "intruder_alert" -> NotificationManager.IMPORTANCE_HIGH
                    "approval_request" -> NotificationManager.IMPORTANCE_HIGH
                    else -> NotificationManager.IMPORTANCE_DEFAULT
                }
            )
            nm.createNotificationChannel(channel)
        }

        val builder = Notification.Builder(this, channelId)
            .setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setAutoCancel(true)
            .setPriority(Notification.PRIORITY_HIGH)

        // If there's a snapshot image, decode and attach as large icon
        if (!snapshotB64.isNullOrEmpty()) {
            try {
                val bytes = Base64.decode(snapshotB64, Base64.DEFAULT)
                val bitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                if (bitmap != null) {
                    builder.setLargeIcon(bitmap)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Failed to decode snapshot: ${e.message}")
            }
        }

        nm.notify(System.currentTimeMillis().toInt(), builder.build())
    }
}
