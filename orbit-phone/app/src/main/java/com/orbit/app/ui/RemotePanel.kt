package com.orbit.app.ui

import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Base64
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orbit.app.OrbitApp
import org.json.JSONObject

/**
 * Remote control panel — 8 buttons in a 2×4 grid.
 *
 * Row 1: Lock, Screenshot, Vol +, Vol -
 * Row 2: Mute, Play, Pause, Next App
 */
@Composable
fun RemotePanel(onBack: () -> Unit) {
    val app = OrbitApp.instance

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp)
    ) {
        // Header
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("← Back") }
            Spacer(Modifier.weight(1f))
            Text("Remote Panel", fontSize = 20.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
        }

        Spacer(Modifier.height(20.dp))

        // Row 1
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            RemoteButton("🔒\nLock", "lock", onBack, Modifier.weight(1f))
            RemoteButton("📸\nShot", "screenshot", onBack, Modifier.weight(1f))
            RemoteButton("🔊+\nVol+", "vol_up", onBack, Modifier.weight(1f))
            RemoteButton("🔊-\nVol-", "vol_down", onBack, Modifier.weight(1f))
        }

        Spacer(Modifier.height(12.dp))

        // Row 2
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            RemoteButton("🔇\nMute", "mute", onBack, Modifier.weight(1f))
            RemoteButton("▶️\nPlay", "play", onBack, Modifier.weight(1f))
            RemoteButton("⏸\nPause", "pause", onBack, Modifier.weight(1f))
            RemoteButton("⬆\nNext", "next_app", onBack, Modifier.weight(1f))
        }

        Spacer(Modifier.weight(1f))
    }
}

@Composable
fun RemoteButton(label: String, action: String, onBack: () -> Unit, modifier: Modifier) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val app = OrbitApp.instance

    ElevatedButton(
        onClick = {
            // Haptic feedback
            try {
                val vib = context.getSystemService(android.content.Context.VIBRATOR_SERVICE) as Vibrator
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                    vib.vibrate(VibrationEffect.createOneShot(30, VibrationEffect.DEFAULT_AMPLITUDE))
                }
            } catch (e: Exception) { /* ignore */ }

            // Send remote command
            val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
            if (key != null) {
                val payload = JSONObject().apply { put("action", action) }
                app.pcConnection.send("remote", payload, key)
            }
        },
        modifier = modifier
            .height(80.dp)
    ) {
        Text(label, fontSize = 12.sp)
    }
}
