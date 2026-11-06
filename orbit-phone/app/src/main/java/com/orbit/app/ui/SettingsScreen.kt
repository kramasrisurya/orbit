package com.orbit.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orbit.app.OrbitApp
import com.orbit.app.data.Prefs

/**
 * Settings screen.
 *
 * - PC IP address
 * - PC WebSocket port
 * - Geo-fence radius slider
 * - Shake sensitivity slider
 * - 8 notification toggles
 * - Save / Re-pair / About
 */
@Composable
fun SettingsScreen(onBack: () -> Unit, onRePair: () -> Unit) {
    val app = OrbitApp.instance
    val prefs: Prefs = app.prefs

    // Local editable state
    var ip by remember { mutableStateOf(prefs.pcIp) }
    var port by remember { mutableStateOf(prefs.pcPort.toString()) }
    var geoRadius by remember { mutableFloatStateOf(prefs.geoRadius.toFloat()) }
    var shakeSens by remember { mutableIntStateOf(prefs.shakeSensitivity) }

    // Notification toggles
    var nIntruder by remember { mutableStateOf(prefs.notifIntruder) }
    var nLocked by remember { mutableStateOf(prefs.notifLocked) }
    var nPosture by remember { mutableStateOf(prefs.notifPosture) }
    var nStress by remember { mutableStateOf(prefs.notifStress) }
    var nBreak by remember { mutableStateOf(prefs.notifBreak) }
    var nMode by remember { mutableStateOf(prefs.notifMode) }
    var nApproval by remember { mutableStateOf(prefs.notifApproval) }
    var nAmbient by remember { mutableStateOf(prefs.notifAmbient) }

    var saved by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp)
            .verticalScroll(rememberScrollState())
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            TextButton(onClick = onBack) { Text("← Back") }
            Spacer(Modifier.weight(1f))
            Text("Settings", fontSize = 20.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
        }

        Spacer(Modifier.height(16.dp))

        // --- Connection ---
        SectionHeader("PC Connection")

        OutlinedTextField(
            value = ip,
            onValueChange = { ip = it },
            label = { Text("IP Address") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = port,
            onValueChange = { port = it.filter { c -> c.isDigit() } },
            label = { Text("WebSocket Port") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(16.dp))

        // --- Geo fence ---
        SectionHeader("Geo-Fence")
        Text("Radius: ${geoRadius.toInt()} m", fontSize = 14.sp)
        Slider(
            value = geoRadius,
            onValueChange = { geoRadius = it },
            valueRange = 50f..500f,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(16.dp))

        // --- Shake sensitivity ---
        SectionHeader("Shake Sensitivity")
        val sensLabel = listOf("Low", "Medium", "High")[shakeSens.coerceIn(0, 2)]
        Text("Sensitivity: $sensLabel", fontSize = 14.sp)
        Slider(
            value = shakeSens.toFloat(),
            onValueChange = { shakeSens = it.toInt().coerceIn(0, 2) },
            valueRange = 0f..2f,
            steps = 1,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(16.dp))

        // --- Notifications ---
        SectionHeader("Notifications")
        ToggleRow("Intruder Alert", nIntruder) { nIntruder = it }
        ToggleRow("PC Locked", nLocked) { nLocked = it }
        ToggleRow("Posture", nPosture) { nPosture = it }
        ToggleRow("Stress", nStress) { nStress = it }
        ToggleRow("Break Reminder", nBreak) { nBreak = it }
        ToggleRow("Mode Changed", nMode) { nMode = it }
        ToggleRow("Approval Request", nApproval) { nApproval = it }
        ToggleRow("Ambient", nAmbient) { nAmbient = it }

        Spacer(Modifier.height(24.dp))

        // --- Save ---
        Button(
            onClick = {
                prefs.pcIp = ip
                prefs.pcPort = port.toIntOrNull() ?: 8765
                prefs.geoRadius = geoRadius.toInt()
                prefs.shakeSensitivity = shakeSens
                prefs.notifIntruder = nIntruder
                prefs.notifLocked = nLocked
                prefs.notifPosture = nPosture
                prefs.notifStress = nStress
                prefs.notifBreak = nBreak
                prefs.notifMode = nMode
                prefs.notifApproval = nApproval
                prefs.notifAmbient = nAmbient
                // Reconnect if IP/port changed
                app.pcConnection.reconnect()
                saved = true
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text(if (saved) "✓ Saved" else "Save")
        }

        Spacer(Modifier.height(12.dp))

        OutlinedButton(
            onClick = {
                prefs.clearPairing()
                onRePair()
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Re-pair with PC")
        }

        Spacer(Modifier.height(32.dp))

        // --- About ---
        SectionHeader("About")
        Text("ORBIT v1.0", fontSize = 14.sp)
        Text("Local-first ambient awareness system.", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun SectionHeader(text: String) {
    Text(
        text = text,
        fontSize = 13.sp,
        fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(bottom = 8.dp)
    )
}

@Composable
fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label, fontSize = 15.sp, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
