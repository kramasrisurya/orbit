package com.orbit.app.ui

import android.content.Intent
import android.nfc.NdefMessage
import android.nfc.NdefRecord
import android.nfc.NfcAdapter
import android.os.Bundle
import android.util.Base64
import android.widget.Toast
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orbit.app.OrbitApp
import com.orbit.app.data.ConnectionState
import com.orbit.app.data.Prefs
import com.orbit.app.service.ShakeDetector
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Main ORBIT dashboard screen.
 *
 * Shows:
 *   - PC connection status (colored dot)
 *   - Current mode badge
 *   - BLE signal strength
 *   - Quick action buttons
 *   - Navigation to Remote Panel, Timer, Settings
 *   - Pair with PC (if not paired)
 *   - NFC tag reading (when screen is on)
 */
class MainActivity : androidx.appcompat.app.AppCompatActivity() {

    private lateinit var app: OrbitApp
    private lateinit var shakeDetector: com.orbit.app.service.ShakeDetector
    private var nfcAdapter: NfcAdapter? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        app = OrbitApp.instance

        // Init shake detector
        shakeDetector = ShakeDetector(this, app.pcConnection, app.prefs)
        shakeDetector.start()
        shakeDetector.startWindowWatcher()

        // Init NFC
        nfcAdapter = NfcAdapter.getDefaultAdapter(this)

        setContent {
            MaterialTheme {
                OrbitMainScreen(
                    connectionState = app.pcConnection.connectionState.value,
                    rssi = app.pcConnection.rssi.value,
                    isPaired = app.prefs.isPaired(),
                    onLock = { sendRemote("lock") },
                    onScreenshot = { sendRemote("screenshot") },
                    onNextApp = { sendRemote("next_app") },
                    onRemotePanel = { /* navigate to RemotePanel */ },
                    onTimer = { /* navigate to TimerPanel */ },
                    onSettings = { /* navigate to SettingsScreen */ },
                    onPair = { /* show QR scanning */ }
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleNfcIntent(intent)
    }

    private fun handleNfcIntent(intent: Intent) {
        if (intent.action != NfcAdapter.ACTION_NDEF_DISCOVERED) return
        val extras = intent.extras ?: return
        val rawMsgs = extras[NfcAdapter.EXTRA_NFCS] ?: return
        val msgs = rawMsgs as Array<NdefMessage>
        for (msg in msgs) {
            for (record in msg.records) {
                try {
                    val mode = String(record.payload, Charsets.UTF_8).trim()
                    if (mode.isNotEmpty()) {
                        sendNfc(mode)
                        Toast.makeText(this, "Switching to $mode Mode", Toast.LENGTH_SHORT).show()
                        return
                    }
                } catch (e: Exception) {
                    // Not a valid NDEF text record
                }
            }
        }
    }

    private fun sendRemote(action: String) {
        val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) } ?: return
        val payload = JSONObject().apply { put("action", action) }
        app.pcConnection.send("remote", payload, key)
    }

    private fun sendNfc(mode: String) {
        val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) } ?: return
        val payload = JSONObject().apply { put("mode", mode) }
        app.pcConnection.send("nfc", payload, key)
    }

    override fun onDestroy() {
        shakeDetector.stop()
        super.onDestroy()
    }
}

// ---------------------------------------------------------------------------
// Compose UI
// ---------------------------------------------------------------------------

@Composable
fun OrbitMainScreen(
    connectionState: ConnectionState,
    rssi: Int,
    isPaired: Boolean,
    onLock: () -> Unit,
    onScreenshot: () -> Unit,
    onNextApp: () -> Unit,
    onRemotePanel: () -> Unit,
    onTimer: () -> Unit,
    onSettings: () -> Unit,
    onPair: () -> Unit
) {
    val connColor = when (connectionState) {
        ConnectionState.CONNECTED -> Color(0xFF3FB950)
        ConnectionState.CONNECTING -> Color(0xFFD29922)
        ConnectionState.DISCONNECTED -> Color(0xFFF85149)
    }
    val connLabel = when (connectionState) {
        ConnectionState.CONNECTED -> "Connected"
        ConnectionState.CONNECTING -> "Connecting…"
        ConnectionState.DISCONNECTED -> "Disconnected"
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp)
    ) {
        // Header
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("ORBIT", fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            // Connection dot
            androidx.compose.foundation.Canvas(Modifier.size(12.dp)) {
                drawCircle(connColor)
            }
            Spacer(Modifier.width(8.dp))
            Text(connLabel, fontSize = 14.sp, color = connColor)
        }

        Spacer(Modifier.height(20.dp))

        // RSSI bar
        if (connectionState == ConnectionState.CONNECTED) {
            val bars = (rssi / -10).coerceIn(0, 5)
            Text("Signal: ${"▂▄▆█".repeat(bars)} (${rssi} dBm)", fontSize = 13.sp, color = Color.Gray)
            Spacer(Modifier.height(16.dp))
        }

        // Quick actions
        Text("Quick Actions", fontSize = 14.sp, color = Color.Gray)
        Spacer(Modifier.height(8.dp))
        Row {
            QuickActionButton("🔒 Lock", onLock, Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            QuickActionButton("📸 Screenshot", onScreenshot, Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            QuickActionButton("⬆ Next App", onNextApp, Modifier.weight(1f))
        }

        Spacer(Modifier.height(20.dp))

        // Navigation buttons
        Row {
            NavigationButton("🎛 Remote Panel", onRemotePanel, Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            NavigationButton("⏱ Timer", onTimer, Modifier.weight(1f))
        }
        Spacer(Modifier.height(8.dp))
        Row {
            NavigationButton("⚙ Settings", onSettings, Modifier.weight(1f))
            if (!isPaired) {
                Spacer(Modifier.width(8.dp))
                NavigationButton("📱 Pair with PC", onPair, Modifier.weight(1f))
            }
        }

        Spacer(Modifier.weight(1f))

        // Footer
        Text(
            "v1.0 · Local-First Ambient Awareness",
            fontSize = 12.sp,
            color = Color.Gray,
            modifier = Modifier.align(Alignment.CenterHorizontally)
        )
    }
}

@Composable
fun QuickActionButton(label: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    ElevatedButton(
        onClick = onClick,
        modifier = modifier
            .height(48.dp)
    ) {
        Text(label, fontSize = 13.sp)
    }
}

@Composable
fun NavigationButton(label: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier
            .height(44.dp)
    ) {
        Text(label, fontSize = 13.sp)
    }
}
