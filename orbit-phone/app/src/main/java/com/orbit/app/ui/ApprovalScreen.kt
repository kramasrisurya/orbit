package com.orbit.app.ui

import android.app.Activity
import android.content.Context
import android.os.Bundle
import android.util.Base64
import android.widget.Toast
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.orbit.app.OrbitApp
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import org.json.JSONObject

/**
 * Full-screen, high-priority approval activity.
 *
 * Launched from NotificationService / WebSocketService on
 * `approval_request` messages.
 *
 * - Shows the action description
 * - 30-second countdown
 * - [Approve] → BiometricPrompt → sends {approval, granted: true}
 * - [Deny] → sends {approval, granted: false}
 * - Timeout → auto-denies
 * - Cannot be swiped away until a decision is made
 */
class ApprovalScreen : Activity() {

    private var decided = false
    private var action = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        action = intent.getStringExtra("action") ?: "Unknown action"

        setContent {
            MaterialTheme {
                ApprovalComposable(
                    action = action,
                    onApprove = { showBiometricPrompt() },
                    onDeny = { deny() }
                )
            }
        }
    }

    private fun showBiometricPrompt() {
        if (decided) return

        val biometricManager = BiometricManager.from(this)
        if (biometricManager.canAuthenticate(
                BiometricManager.Authenticators.BIOMETRIC_STRONG or
                BiometricManager.Authenticators.DEVICE_CREDENTIAL
            ) != BiometricManager.BIOMETRIC_SUCCESS
        ) {
            // No biometrics available — approve directly
            approve()
            return
        }

        val prompt = BiometricPrompt(
            this,
            ContextCompat.getExecutor(this),
            object : BiometricPrompt.Callback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    approve()
                }
                override fun onAuthenticationFailed() {
                    Toast.makeText(this@ApprovalScreen, "Authentication failed", Toast.LENGTH_SHORT).show()
                }
                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    Toast.makeText(this@ApprovalScreen, "Auth error: $errString", Toast.LENGTH_SHORT).show()
                }
            }
        )
        prompt.authenticate(
            BiometricPrompt.PromptOptions.Builder()
                .setTitle("ORBIT Approval")
                .setNegativeButtonText("Cancel")
                .build()
        )
    }

    private fun approve() {
        if (decided) return
        decided = true
        val app = OrbitApp.instance
        val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
        if (key != null) {
            app.pcConnection.send("approval", JSONObject().apply { put("granted", true) }, key)
        }
        finish()
    }

    private fun deny() {
        if (decided) return
        decided = true
        val app = OrbitApp.instance
        val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
        if (key != null) {
            app.pcConnection.send("approval", JSONObject().apply { put("granted", false) }, key)
        }
        finish()
    }

    override fun onBackPressed() {
        // Cannot swipe away until a decision is made
        if (!decided) {
            Toast.makeText(this, "Please approve or deny", Toast.LENGTH_SHORT).show()
            return
        }
        super.onBackPressed()
    }
}

// Helper for BiometricPrompt executor
object ContextCompat {
    fun getExecutor(activity: Activity): java.util.concurrent.Executor {
        return java.util.concurrent.Executors.newSingleThreadExecutor()
    }
}

// ---------------------------------------------------------------------------
// Compose UI
// ---------------------------------------------------------------------------

@Composable
fun ApprovalComposable(
    action: String,
    onApprove: () -> Unit,
    onDeny: () -> Unit
) {
    var secondsLeft by remember { mutableIntStateOf(30) }

    // Countdown
    LaunchedEffect(Unit) {
        while (secondsLeft > 0 && isActive) {
            delay(1000)
            secondsLeft--
        }
        // Timeout → auto-deny
        if (secondsLeft <= 0) {
            onDeny()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            "⚠️ Approval Required",
            fontSize = 24.sp,
            fontWeight = FontWeight.Bold,
            color = Color(0xFFF85149)
        )

        Spacer(Modifier.height(24.dp))

        // Action description
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = Color(0xFF1C2330),
            shape = MaterialTheme.shapes.medium
        ) {
            Text(
                text = action,
                modifier = Modifier.padding(20.dp),
                fontSize = 18.sp,
                textAlign = TextAlign.Center
            )
        }

        Spacer(Modifier.height(24.dp))

        // Countdown
        Text(
            "$secondsLeft seconds remaining",
            fontSize = 16.sp,
            color = if (secondsLeft <= 10) Color(0xFFF85149) else Color.Gray
        )

        Spacer(Modifier.height(32.dp))

        // Approve button
        Button(
            onClick = onApprove,
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp)
        ) {
            Text("✓ Approve", fontSize = 18.sp)
        }

        Spacer(Modifier.height(12.dp))

        // Deny button
        Button(
            onClick = onDeny,
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFF85149)),
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp)
        ) {
            Text("✗ Deny", fontSize = 18.sp)
        }
    }
}
