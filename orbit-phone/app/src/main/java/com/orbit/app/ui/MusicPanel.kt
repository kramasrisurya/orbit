package com.orbit.app.ui

import android.util.Base64
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orbit.app.OrbitApp
import org.json.JSONObject

/**
 * Music control panel.
 *
 * Mirrors the PC's music player state (fed via WebSocket `display_data`).
 * Shows: track title, artist, progress bar.
 * Controls: Previous, Play/Pause, Next, Volume slider.
 * Each button sends a `remote` command to the PC.
 *
 * Only active when the PC sends music display data.
 */
@Composable
fun MusicPanel(onBack: () -> Unit) {
    val app = OrbitApp.instance

    // These would be updated from the WebSocket display_data stream
    var trackTitle by remember { mutableStateOf("Not Playing") }
    var artist by remember { mutableStateOf("—") }
    var progress by remember { mutableFloatStateOf(0f) }
    var isPlaying by remember { mutableStateOf(false) }
    var volume by remember { mutableFloatStateOf(0.7f) }

    fun sendMusic(action: String) {
        val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) } ?: return
        app.pcConnection.send("remote", JSONObject().apply { put("action", action) }, key)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            TextButton(onClick = onBack) { Text("← Back") }
            Spacer(Modifier.weight(1f))
            Text("Music", fontSize = 20.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
        }

        Spacer(Modifier.height(32.dp))

        // Track info
        Text(trackTitle, fontSize = 22.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Medium)
        Text(artist, fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)

        Spacer(Modifier.height(24.dp))

        // Progress bar
        LinearProgressIndicator(
            progress = { progress },
            modifier = Modifier.fillMaxWidth().height(6.dp)
        )

        Spacer(Modifier.height(32.dp))

        // Transport controls
        Row(
            horizontalArrangement = Arrangement.spacedBy(24.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            TextButton(onClick = { sendMusic("prev") }) {
                Text("⏮", fontSize = 28.sp)
            }
            Button(
                onClick = {
                    isPlaying = !isPlaying
                    sendMusic(if (isPlaying) "play" else "pause")
                },
                modifier = Modifier.size(64.dp)
            ) {
                Text(if (isPlaying) "⏸" else "▶️", fontSize = 24.sp)
            }
            TextButton(onClick = { sendMusic("next") }) {
                Text("⏭", fontSize = 28.sp)
            }
        }

        Spacer(Modifier.height(32.dp))

        // Volume
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("🔊", fontSize = 18.sp)
            Slider(
                value = volume,
                onValueChange = {
                    volume = it
                    sendMusic("volume")
                },
                valueRange = 0f..1f,
                modifier = Modifier.weight(1f).padding(start = 8.dp)
            )
        }

        Spacer(Modifier.weight(1f))
    }
}
