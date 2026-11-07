package com.orbit.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.orbit.app.ui.ApprovalScreen

/**
 * Local notification helper service for ORBIT alerts.
 */
class NotificationService : Service() {

    private val TAG = "NotificationService"

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        fun showNotification(context: Context, ntype: String, title: String, body: String) {
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val channelId = "orbit_$ntype"
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val channel = NotificationChannel(
                    channelId,
                    "ORBIT $ntype",
                    if (ntype == "intruder_alert" || ntype == "approval_request")
                        NotificationManager.IMPORTANCE_HIGH
                    else
                        NotificationManager.IMPORTANCE_DEFAULT
                )
                nm.createNotificationChannel(channel)
            }

            val builder = Notification.Builder(context, channelId)
                .setContentTitle(title)
                .setContentText(body)
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setAutoCancel(true)

            nm.notify(System.currentTimeMillis().toInt(), builder.build())
        }
    }
}
