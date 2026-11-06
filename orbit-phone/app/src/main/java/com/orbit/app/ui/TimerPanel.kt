package com.orbit.app.ui

import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Base64
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orbit.app.OrbitApp
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import org.json.JSONObject

/**
 * Focus timer panel.
 *
 * - Large circular countdown
 * - Duration selector: 15/25/45/60 min
 * - Start / Pause / Reset
 * - Phone is the source of truth for time
 * - On start: sends focus_start to PC
 * - On completion: vibrates 3× + notification + sends focus_end
 */
@Composable
fun TimerPanel(onBack: () -> Unit) {
    val app = OrbitApp.instance

    var selectedDuration by remember { mutableIntStateOf(25) }
    var remainingSec by remember { mutableIntStateOf(25 * 60) }
    var isRunning by remember { mutableStateOf(false) }
    var isPaused by remember { mutableStateOf(false) }

    // Countdown loop
    LaunchedEffect(isRunning, isPaused) {
        while (isRunning && !isPaused && isActive) {
            if (remainingSec > 0) {
                remainingSec--
                delay(1000)
            } else {
                // Timer complete
                isRunning = false
                onComplete()
                break
            }
        }
    }

    fun onComplete() {
        // Vibrate 3 times
        try {
            val vib = androidx.compose.ui.platform.LocalContext.current
                .getSystemService(android.content.Context.VIBRATOR_SERVICE) as Vibrator
            repeat(3) {
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                    vib.vibrate(VibrationEffect.createOneShot(200, VibrationEffect.DEFAULT_AMPLITUDE))
                }
                Thread.sleep(300)
            }
        } catch (e: Exception) { /* ignore */ }

        // Send focus_end to PC
        val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
        if (key != null) {
            app.pcConnection.send("remote", JSONObject().apply { put("action", "focus_end") }, key)
        }
    }

    fun startTimer() {
        val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
        if (key != null) {
            app.pcConnection.send(
                "remote",
                JSONObject().apply {
                    put("action", "focus_start")
                    put("duration", selectedDuration)
                },
                key
            )
        }
        isRunning = true
        isPaused = false
    }

    val progress = if (selectedDuration > 0)
        1f - (remainingSec.toFloat() / (selectedDuration * 60))
    else 0f

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            TextButton(onClick = onBack) { Text("← Back") }
            Spacer(Modifier.weight(1f))
            Text("Focus Timer", fontSize = 20.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
        }

        Spacer(Modifier.height(24.dp))

        // Circular progress
        Box(
            modifier = Modifier
                .size(220.dp)
                .clip(CircleShape)
                .background(Color(0xFF1C2330)),
            contentAlignment = Alignment.Center
        ) {
            // Progress ring (simplified as a colored arc via Canvas would be ideal)
            val mins = remainingSec / 60
            val secs = remainingSec % 60
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    "%02d:%02d".format(mins, secs),
                    fontSize = 48.sp,
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold
                )
                Text(
                    if (isRunning && !isPaused) "Focusing…"
                    else if (isPaused) "Paused"
                    else "Ready",
                    fontSize = 14.sp,
                    color = Color.Gray
                )
            }
        }

        Spacer(Modifier.height(24.dp))

        // Duration selector
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(15, 25, 45, 60).forEach { mins ->
                FilterChip(
                    selected = selectedDuration == mins,
                    onClick = {
                        if (!isRunning) {
                            selectedDuration = mins
                            remainingSec = mins * 60
                        }
                    },
                    enabled = !isRunning
                ) {
                    Text("${mins}m")
                }
            }
        }

        Spacer(Modifier.height(24.dp))

        // Controls
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (!isRunning) {
                Button(onClick = { startTimer() }) { Text("Start") }
            } else {
                if (isPaused) {
                    Button(onClick = { isPaused = false }) { Text("Resume") }
                } else {
                    OutlinedButton(onClick = { isPaused = true }) { Text("Pause") }
                }
            }
            OutlinedButton(onClick = {
                isRunning = false
                isPaused = false
                remainingSec = selectedDuration * 60
            }) { Text("Reset") }
        }

        Spacer(Modifier.weight(1f))
    }
}
