package com.orbit.app.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.nfc.NdefMessage
import android.nfc.NdefRecord
import android.nfc.NfcAdapter
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Base64
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricPrompt
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import com.orbit.app.OrbitApp
import com.orbit.app.data.ConnectionState
import com.orbit.app.service.ShakeDetector
import com.orbit.app.service.WebSocketService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/**
 * ORBIT Mobile Companion Satellite.
 *
 * Dedicated mobile-native companion interface:
 *   - 100% Automatic Live Clipboard Bridge (bidirectional copy/paste)
 *   - 1-Tap File Transfer directly into Laptop's Windows Downloads folder
 *   - Universal Control: Smooth Touch Trackpad & Remote Typing
 *   - Live QR Pairing Scanner + 1-Tap LAN Auto-Pair
 *   - Workspace Modes & Remote Security controls
 */
class MainActivity : AppCompatActivity() {

    private lateinit var app: OrbitApp
    private lateinit var shakeDetector: ShakeDetector
    private var nfcAdapter: NfcAdapter? = null
    private var lastLocalClipboard: String? = null

    private val permissionsLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        android.util.Log.d("MainActivity", "Permissions result: $results")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        app = OrbitApp.instance

        // Request basic permissions gracefully on startup
        checkAndRequestPermissions()

        // Start WebSocket foreground service safely if already paired
        if (app.prefs.isPaired()) {
            try {
                val serviceIntent = Intent(this, WebSocketService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    startForegroundService(serviceIntent)
                } else {
                    startService(serviceIntent)
                }
            } catch (e: Exception) {
                android.util.Log.w("MainActivity", "Failed to start WebSocketService: ${e.message}")
            }
        }

        // Init shake detector safely (disabled by default to prevent accidental triggers on motion)
        try {
            shakeDetector = ShakeDetector(this, app.pcConnection, app.prefs)
        } catch (e: Exception) {
            android.util.Log.w("MainActivity", "Shake detector init failed: ${e.message}")
        }

        // Init NFC safely
        try {
            nfcAdapter = NfcAdapter.getDefaultAdapter(this)
        } catch (e: Exception) {
            android.util.Log.w("MainActivity", "NFC init failed: ${e.message}")
        }

        // Setup automatic local clipboard bridge listener (Phone -> Laptop)
        setupClipboardAutoBridge()
        handleCustomIntent(intent)

        setContent {
            val pcIp by remember { mutableStateOf(app.prefs.pcIp) }
            val connectionState by app.pcConnection.connectionState.collectAsState()
            val rssi by app.pcConnection.rssi.collectAsState()
            val lastClipboardText by app.pcConnection.lastClipboardText.collectAsState()
            var isPaired by remember { mutableStateOf(app.prefs.isPaired()) }

            var showPairDialog by remember { mutableStateOf(!isPaired) }
            var fileTransferStatus by remember { mutableStateOf<String?>(null) }
            var isUploadingFile by remember { mutableStateOf(false) }

            // Automatic bidirectional clipboard synchronization
            LaunchedEffect(lastClipboardText) {
                if (lastClipboardText.isNotEmpty() && lastClipboardText != lastLocalClipboard) {
                    copyToLocal(lastClipboardText)
                }
            }

            // High-frequency clipboard sync while app is active
            LaunchedEffect(Unit) {
                while (true) {
                    checkAndSyncClipboard()
                    kotlinx.coroutines.delay(500L)
                }
            }

            // Automatic file picker launcher -> Direct upload to Laptop Downloads
            val filePickerLauncher = rememberLauncherForActivityResult(
                contract = ActivityResultContracts.GetMultipleContents()
            ) { uris ->
                if (!uris.isNullOrEmpty()) {
                    isUploadingFile = true
                    fileTransferStatus = "Uploading ${uris.size} file(s) to Laptop Downloads…"
                    var completed = 0
                    uris.forEach { uri ->
                        uploadFileToLaptop(
                            context = this@MainActivity,
                            pcIp = app.prefs.pcIp,
                            uri = uri,
                            onSuccess = { name ->
                                completed++
                                fileTransferStatus = "✓ Saved '$name' to Laptop Downloads!"
                                Toast.makeText(this@MainActivity, "Saved '$name' to Laptop Downloads", Toast.LENGTH_SHORT).show()
                                if (completed >= uris.size) {
                                    isUploadingFile = false
                                }
                            },
                            onError = { err ->
                                isUploadingFile = false
                                fileTransferStatus = "Upload error: $err"
                                Toast.makeText(this@MainActivity, "File error: $err", Toast.LENGTH_LONG).show()
                            }
                        )
                    }
                }
            }

            val pendingBiometricToken by app.pcConnection.pendingBiometricToken.collectAsState()
            LaunchedEffect(pendingBiometricToken) {
                pendingBiometricToken?.let { token ->
                    showBiometricPrompt(token)
                }
            }

            OrbitSatelliteScreen(
                pcIp = pcIp,
                connectionState = connectionState,
                rssi = rssi,
                isPaired = isPaired,
                lastClipboardText = lastClipboardText,
                fileTransferStatus = fileTransferStatus,
                isUploadingFile = isUploadingFile,
                pendingBiometricToken = pendingBiometricToken,
                onVerifyFingerprint = { token -> showBiometricPrompt(token) },
                onCameraOff = { setCameraPaused(true) },
                onCameraOn = { setCameraPaused(false) },
                onOpenPairDialog = { showPairDialog = true },
                onSendFiles = { filePickerLauncher.launch("*/*") },
                onTrackpadMove = { dx, dy -> app.pcConnection.sendMouseMove(dx, dy) },
                onTrackpadClick = { btn -> app.pcConnection.sendMouseClick(btn) },
                onTrackpadScroll = { dy -> app.pcConnection.sendMouseScroll(dy) },
                onRemoteType = { text ->
                    app.pcConnection.sendRemoteType(text)
                },
                onSwitchMode = { mode -> sendNfc(mode) },
                onLock = { sendRemote("lock") },
                onOpenWebDashboard = {
                    try {
                        val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse("http://${app.prefs.pcIp}:8080"))
                        startActivity(browserIntent)
                    } catch (e: Exception) {
                        Toast.makeText(this@MainActivity, "Could not open browser: ${e.message}", Toast.LENGTH_SHORT).show()
                    }
                }
            )

            if (showPairDialog) {
                PairingQrDialog(
                    initialIp = app.prefs.pcIp,
                    onDismiss = { showPairDialog = false },
                    onPairSuccess = { ip, port, key ->
                        app.prefs.pcIp = ip
                        app.prefs.pcPort = port
                        app.prefs.pairingKey = key
                        isPaired = true
                        showPairDialog = false
                        // Start connection
                        startService(Intent(this@MainActivity, WebSocketService::class.java))
                        Toast.makeText(this@MainActivity, "✓ Paired successfully with Laptop!", Toast.LENGTH_SHORT).show()
                    }
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        handleCustomIntent(intent)
    }

    private fun handleCustomIntent(intent: Intent?) {
        val copyText = intent?.getStringExtra("copy_text")
        if (!copyText.isNullOrEmpty()) {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            lastLocalClipboard = null
            cm.setPrimaryClip(ClipData.newPlainText("ORBIT", copyText))
            checkAndSyncClipboard(force = true)
        }
    }

    override fun onResume() {
        super.onResume()
        checkAndSyncClipboard()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            checkAndSyncClipboard()
        }
    }

    private fun checkAndSyncClipboard(force: Boolean = false) {
        try {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val clip = cm.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val text = clip.getItemAt(0).text?.toString() ?: ""
                if (text.isNotEmpty() && (force || text != lastLocalClipboard)) {
                    lastLocalClipboard = text
                    app.pcConnection.updateClipboardText(text)
                    val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
                    if (key != null) {
                        val payload = JSONObject().apply { put("text", text) }
                        app.pcConnection.send("clipboard", payload, key)
                    }
                    val pcIp = app.prefs.pcIp
                    if (pcIp.isNotEmpty()) {
                        CoroutineScope(Dispatchers.IO).launch {
                            try {
                                val client = OkHttpClient()
                                val body = JSONObject().apply { put("text", text) }.toString()
                                    .toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
                                val req = Request.Builder()
                                    .url("http://$pcIp:8080/api/clipboard")
                                    .post(body)
                                    .build()
                                client.newCall(req).execute().close()
                            } catch (e: Exception) {
                                // Silent fallback
                            }
                        }
                    }
                    if (force) {
                        Toast.makeText(this, "✓ Synced clipboard to Laptop (${text.length} chars)", Toast.LENGTH_SHORT).show()
                    }
                }
            } else if (force) {
                Toast.makeText(this, "Phone clipboard is empty", Toast.LENGTH_SHORT).show()
            }
        } catch (e: Exception) {
            // Safe guard
        }
    }

    private fun showBiometricPrompt(token: String) {
        runOnUiThread {
            try {
                val executor = ContextCompat.getMainExecutor(this)
                val biometricPrompt = BiometricPrompt(
                    this,
                    executor,
                    object : BiometricPrompt.AuthenticationCallback() {
                        override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                            super.onAuthenticationSucceeded(result)
                            app.pcConnection.setPendingBiometricToken(null)
                            Toast.makeText(this@MainActivity, "✓ Fingerprint verified! Laptop enrollment approved.", Toast.LENGTH_LONG).show()

                            val key = app.prefs.pairingKey?.let { Base64.decode(it, Base64.NO_WRAP) }
                            if (key != null) {
                                val payload = JSONObject().apply { put("token", token) }
                                app.pcConnection.send("biometric_reenroll_approved", payload, key)
                            }

                            val pcIp = app.prefs.pcIp
                            if (pcIp.isNotEmpty()) {
                                CoroutineScope(Dispatchers.IO).launch {
                                    try {
                                        val client = OkHttpClient()
                                        val body = JSONObject().apply { put("token", token) }.toString()
                                            .toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
                                        val req = Request.Builder()
                                            .url("http://$pcIp:8080/api/enroll/approve")
                                            .post(body)
                                            .build()
                                        client.newCall(req).execute().close()
                                    } catch (e: Exception) {
                                        // Safe guard
                                    }
                                }
                            }
                        }

                        override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                            super.onAuthenticationError(errorCode, errString)
                            app.pcConnection.setPendingBiometricToken(null)
                            if (errorCode != BiometricPrompt.ERROR_USER_CANCELED &&
                                errorCode != BiometricPrompt.ERROR_NEGATIVE_BUTTON) {
                                Toast.makeText(this@MainActivity, "Biometric: $errString", Toast.LENGTH_SHORT).show()
                            }
                        }
                    }
                )

                val promptInfo = BiometricPrompt.PromptInfo.Builder()
                    .setTitle("Re-enroll Laptop Biometrics")
                    .setSubtitle("Scan fingerprint to authorize updating face biometrics on your laptop")
                    .setNegativeButtonText("Cancel")
                    .build()

                biometricPrompt.authenticate(promptInfo)
            } catch (e: Exception) {
                Toast.makeText(this@MainActivity, "Biometrics unavailable: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun setCameraPaused(paused: Boolean) {
        val action = if (paused) "pause_camera" else "resume_camera"
        sendRemote(action)
        val pcIp = app.prefs.pcIp
        if (pcIp.isNotEmpty()) {
            CoroutineScope(Dispatchers.IO).launch {
                try {
                    val client = OkHttpClient()
                    val body = JSONObject().apply { put("action", action) }.toString()
                        .toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
                    val req = Request.Builder()
                        .url("http://$pcIp:8080/api/command")
                        .post(body)
                        .build()
                    client.newCall(req).execute().close()
                } catch (e: Exception) {
                    // Safe guard
                }
            }
        }
        val msg = if (paused) "📷 Laptop Camera Paused" else "📷 Laptop Camera Resumed"
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }

    private fun setupClipboardAutoBridge() {
        try {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.addPrimaryClipChangedListener {
                checkAndSyncClipboard()
            }
        } catch (e: Exception) {
            // Safe guard
        }
    }

    private fun copyToLocal(text: String) {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        lastLocalClipboard = text
        cm.setPrimaryClip(ClipData.newPlainText("ORBIT", text))
        Toast.makeText(this, "Copied to Phone Clipboard", Toast.LENGTH_SHORT).show()
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

    private fun checkAndRequestPermissions() {
        try {
            val list = mutableListOf<String>()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    list.add(Manifest.permission.POST_NOTIFICATIONS)
                }
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                list.add(Manifest.permission.CAMERA)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                    list.add(Manifest.permission.BLUETOOTH_CONNECT)
                }
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_ADVERTISE) != PackageManager.PERMISSION_GRANTED) {
                    list.add(Manifest.permission.BLUETOOTH_ADVERTISE)
                }
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                list.add(Manifest.permission.ACCESS_FINE_LOCATION)
            }
            if (list.isNotEmpty()) {
                permissionsLauncher.launch(list.toTypedArray())
            }
        } catch (e: Exception) {
            android.util.Log.w("MainActivity", "checkAndRequestPermissions error: ${e.message}")
        }
    }

    override fun onDestroy() {
        try {
            if (::shakeDetector.isInitialized) {
                shakeDetector.stop()
            }
        } catch (e: Exception) {
            android.util.Log.w("MainActivity", "ShakeDetector stop error: ${e.message}")
        }
        super.onDestroy()
    }
}

// ---------------------------------------------------------------------------
// Network File Upload Helper (Direct to Laptop Downloads Folder)
// ---------------------------------------------------------------------------

private fun getFileName(context: Context, uri: Uri): String {
    var result: String? = null
    if (uri.scheme == "content") {
        val cursor = context.contentResolver.query(uri, null, null, null, null)
        try {
            if (cursor != null && cursor.moveToFirst()) {
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0) {
                    result = cursor.getString(index)
                }
            }
        } finally {
            cursor?.close()
        }
    }
    if (result == null) {
        result = uri.path
        val cut = result?.lastIndexOf('/') ?: -1
        if (cut != -1) {
            result = result?.substring(cut + 1)
        }
    }
    return result ?: "orbit_upload_${System.currentTimeMillis()}"
}

private fun uploadFileToLaptop(
    context: Context,
    pcIp: String,
    uri: Uri,
    onSuccess: (String) -> Unit,
    onError: (String) -> Unit
) {
    CoroutineScope(Dispatchers.IO).launch {
        try {
            val fileName = getFileName(context, uri)
            val inputStream = context.contentResolver.openInputStream(uri)
                ?: throw Exception("Could not read file")
            val bytes = inputStream.readBytes()
            inputStream.close()

            val mimeType = context.contentResolver.getType(uri) ?: "application/octet-stream"
            val mediaType = mimeType.toMediaTypeOrNull()

            val requestBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", fileName, bytes.toRequestBody(mediaType))
                .build()

            val request = Request.Builder()
                .url("http://$pcIp:8080/api/files/upload")
                .post(requestBody)
                .build()

            val client = OkHttpClient()
            client.newCall(request).execute().use { response ->
                if (response.isSuccessful) {
                    withContext(Dispatchers.Main) {
                        onSuccess(fileName)
                    }
                } else {
                    withContext(Dispatchers.Main) {
                        onError("Server rejected file (HTTP ${response.code})")
                    }
                }
            }
        } catch (e: Exception) {
            withContext(Dispatchers.Main) {
                onError(e.message ?: "Transfer error")
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Main Mobile Companion Satellite UI
// ---------------------------------------------------------------------------

@Composable
fun OrbitSatelliteScreen(
    pcIp: String,
    connectionState: ConnectionState,
    rssi: Int,
    isPaired: Boolean,
    lastClipboardText: String,
    fileTransferStatus: String?,
    isUploadingFile: Boolean,
    pendingBiometricToken: String? = null,
    onVerifyFingerprint: (String) -> Unit = {},
    onCameraOff: () -> Unit = {},
    onCameraOn: () -> Unit = {},
    onOpenPairDialog: () -> Unit,
    onSendFiles: () -> Unit,
    onTrackpadMove: (Int, Int) -> Unit,
    onTrackpadClick: (String) -> Unit,
    onTrackpadScroll: (Int) -> Unit,
    onRemoteType: (String) -> Unit,
    onSwitchMode: (String) -> Unit,
    onLock: () -> Unit,
    onOpenWebDashboard: () -> Unit
) {
    val connColor = when (connectionState) {
        ConnectionState.CONNECTED -> Color(0xFF34D399) // Emerald-400
        ConnectionState.CONNECTING -> Color(0xFFFBBF24) // Amber-400
        ConnectionState.DISCONNECTED -> Color(0xFFF43F5E) // Rose-500
    }
    val connLabel = when (connectionState) {
        ConnectionState.CONNECTED -> "Encrypted Bridge Active"
        ConnectionState.CONNECTING -> "Connecting to Laptop…"
        ConnectionState.DISCONNECTED -> if (isPaired) "Disconnected (Tap to Reconnect)" else "Unpaired"
    }

    var activeMode by remember { mutableStateOf("study") }
    var remoteInputText by remember { mutableStateOf("") }
    var lastTapTime by remember { mutableStateOf(0L) }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        val screenWidth = maxWidth
        val screenHeight = maxHeight

        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 16.dp)
        ) {
            // --- 1. Top Bar: Identity & Connection Badge ---
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(Color.White),
                    contentAlignment = Alignment.Center
                ) {
                    Text("Ø", color = Color.Black, fontSize = 22.sp, fontWeight = FontWeight.Black)
                }
                Spacer(Modifier.width(12.dp))
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("ORBIT", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.width(8.dp))
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(100.dp))
                                .background(Color(0x26FFFFFF))
                                .border(1.dp, Color(0x33FFFFFF), RoundedCornerShape(100.dp))
                                .padding(horizontal = 7.dp, vertical = 2.dp)
                        ) {
                            Text("MOBILE SATELLITE", color = Color(0xFFE4E4E7), fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                        }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 2.dp)) {
                        Box(
                            modifier = Modifier
                                .size(6.dp)
                                .clip(CircleShape)
                                .background(connColor)
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "$connLabel · $pcIp",
                            color = Color(0xFFA1A1AA),
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace
                        )
                    }
                }
                Spacer(Modifier.weight(1f))
                Button(
                    onClick = onOpenPairDialog,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF18181B), contentColor = Color.White),
                    border = BorderStroke(1.dp, Color(0x33FFFFFF)),
                    shape = RoundedCornerShape(10.dp),
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp)
                ) {
                    Text(if (isPaired) "Pairing" else "Scan QR", fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                }
            }

            Spacer(Modifier.height(14.dp))

            // --- 2. Top Prominent Workstation Quick Lock ---
            Button(
                onClick = onLock,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(46.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF261318), contentColor = Color(0xFFFDA4AF)),
                border = BorderStroke(1.dp, Color(0x66F43F5E)),
                shape = RoundedCornerShape(12.dp)
            ) {
                Text("🔒 Lock Laptop", fontSize = 13.sp, fontWeight = FontWeight.Bold)
            }

            Spacer(Modifier.height(10.dp))

            // Camera Hardware ON / OFF Controls
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Button(
                    onClick = onCameraOff,
                    modifier = Modifier.weight(1f).height(42.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1E1E24), contentColor = Color(0xFFFBBF24)),
                    border = BorderStroke(1.dp, Color(0x44FBBF24)),
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text("📷 Cam OFF", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
                Button(
                    onClick = onCameraOn,
                    modifier = Modifier.weight(1f).height(42.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF13221C), contentColor = Color(0xFF34D399)),
                    border = BorderStroke(1.dp, Color(0x4434D399)),
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text("📷 Cam ON", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            }

            // Biometric Authorization Banner (if pending from laptop)
            if (pendingBiometricToken != null) {
                Spacer(Modifier.height(10.dp))
                Button(
                    onClick = { onVerifyFingerprint(pendingBiometricToken) },
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF064E3B), contentColor = Color(0xFF6EE7B7)),
                    border = BorderStroke(1.dp, Color(0xFF10B981)),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Text("👆 Verify Fingerprint to Approve Face Re-enroll", fontSize = 11.sp, fontWeight = FontWeight.Bold)
                }
            }

            Spacer(Modifier.height(14.dp))



        // --- 3. 1-Tap Send Files Directly to Laptop Downloads ---
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(Color(0xFF09090B))
                .border(1.dp, Color(0x26FFFFFF), RoundedCornerShape(16.dp))
                .padding(16.dp)
        ) {
            Column(modifier = Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("📁 Send Files to Laptop", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.weight(1f))
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(100.dp))
                            .background(Color(0x26FFFFFF))
                            .padding(horizontal = 7.dp, vertical = 2.dp)
                    ) {
                        Text("AUTO-DOWNLOADS", color = Color(0xFFD4D4D8), fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                    }
                }
                Text(
                    "Select any file or photo. It uploads immediately and saves directly into your Windows Downloads folder without confirmations.",
                    color = Color(0xFFA1A1AA),
                    fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp, bottom = 12.dp)
                )

                Button(
                    onClick = onSendFiles,
                    enabled = !isUploadingFile,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(44.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Color.Black),
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text(
                        if (isUploadingFile) "Uploading to Laptop Downloads…" else "⚡ Choose File & Send to Laptop",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold
                    )
                }

                if (fileTransferStatus != null) {
                    Text(
                        fileTransferStatus,
                        color = Color(0xFF34D399),
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }
            }
        }

        Spacer(Modifier.height(14.dp))

        // --- 5. Universal Control Virtual Trackpad & Remote Typing ---
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(Color(0xFF09090B))
                .border(1.dp, Color(0x26FFFFFF), RoundedCornerShape(16.dp))
                .padding(16.dp)
        ) {
            Column(modifier = Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("🖱 Universal Trackpad & Keyboard", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.weight(1f))
                    Text("2D TOUCH SURFACE", color = Color(0xFF71717A), fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                }
                Text(
                    "1-Finger Move & Tap to Select · Double Tap to Open · 2-Finger Scroll · Right Click",
                    color = Color(0xFFA1A1AA),
                    fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp, bottom = 10.dp)
                )

                // Virtual Touchpad Surface with Precision Gestures
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(170.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(Color(0xFF121215))
                        .border(1.dp, Color(0x1FFFFFFF), RoundedCornerShape(12.dp))
                        .pointerInput(Unit) {
                            awaitEachGesture {
                                val down = awaitFirstDown(requireUnconsumed = false)
                                val startTime = System.currentTimeMillis()
                                var maxPointers = 1
                                var totalDist = 0f
                                var lastPos = down.position
                                var lastTwoFingerTime = 0L

                                while (true) {
                                    val event = awaitPointerEvent()
                                    val active = event.changes.filter { it.pressed }
                                    if (active.isEmpty()) break

                                    if (active.size > maxPointers) {
                                        maxPointers = active.size
                                    }

                                    if (active.size >= 2) {
                                        // 2-finger scroll
                                        lastTwoFingerTime = System.currentTimeMillis()
                                        val p0 = active[0]
                                        val p1 = active[1]
                                        val dy0 = p0.positionChange().y
                                        val dy1 = p1.positionChange().y
                                        val avgDy = (dy0 + dy1) / 2f
                                        totalDist += kotlin.math.abs(avgDy)

                                        p0.consume()
                                        p1.consume()

                                        val scrollAmount = (avgDy * 3.5f).toInt()
                                        if (scrollAmount != 0) {
                                            onTrackpadScroll(scrollAmount)
                                        }
                                        lastPos = (p0.position + p1.position) / 2f
                                    } else if (active.size == 1) {
                                        val p = active[0]
                                        // Cooldown: when lifting fingers after 2-finger scroll, prevent jump!
                                        if (System.currentTimeMillis() - lastTwoFingerTime < 250L) {
                                            lastPos = p.position
                                            p.consume()
                                        } else {
                                            val delta = p.position - lastPos
                                            lastPos = p.position
                                            val dist = delta.getDistance()
                                            totalDist += dist

                                            if (dist > 0.4f) {
                                                p.consume()
                                                val dx = (delta.x * 1.1f).toInt().coerceIn(-40, 40)
                                                val dy = (delta.y * 1.1f).toInt().coerceIn(-40, 40)
                                                if (dx != 0 || dy != 0) {
                                                    onTrackpadMove(dx, dy)
                                                }
                                            }
                                        }
                                    }
                                }

                                val duration = System.currentTimeMillis() - startTime
                                if (totalDist < 18f && duration < 350) {
                                    if (maxPointers >= 2) {
                                        // Two finger tap -> Right Click (context menu)
                                        onTrackpadClick("right")
                                    } else {
                                        val now = System.currentTimeMillis()
                                        if (now - lastTapTime < 320) {
                                            // Double tap -> Double Click!
                                            onTrackpadClick("double")
                                            lastTapTime = 0L
                                        } else {
                                            // Single tap -> Left Click / Select!
                                            lastTapTime = now
                                            onTrackpadClick("left")
                                        }
                                    }
                                } else if (totalDist < 15f && duration >= 450 && maxPointers == 1) {
                                    // Long press -> Right Click!
                                    onTrackpadClick("right")
                                }
                            }
                        },
                    contentAlignment = Alignment.Center
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            "TOUCHPAD · 1-FINGER MOVE & TAP · 2-FINGER SCROLL",
                            color = Color(0x66FFFFFF),
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold
                        )
                        Text(
                            "Tap to Select · Double Tap to Open · 2 Fingers to Scroll",
                            color = Color(0x33FFFFFF),
                            fontSize = 9.sp,
                            modifier = Modifier.padding(top = 4.dp)
                        )
                    }
                }

                Spacer(Modifier.height(10.dp))

                // Left & Right Mouse Buttons (▲ and ▼ buttons removed per request)
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Button(
                        onClick = { onTrackpadClick("left") },
                        modifier = Modifier
                            .weight(1f)
                            .height(44.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Color.Black),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text("Left Click", fontSize = 13.sp, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.width(10.dp))
                    Button(
                        onClick = { onTrackpadClick("right") },
                        modifier = Modifier
                            .weight(1f)
                            .height(44.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF27272A), contentColor = Color.White),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text("Right Click", fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                    }
                }

                Spacer(Modifier.height(10.dp))

                // Remote Typing to Laptop (Automatic Live Streaming Keystrokes)
                OutlinedTextField(
                    value = remoteInputText,
                    onValueChange = { newText ->
                        if (newText.length > remoteInputText.length) {
                            val added = newText.substring(remoteInputText.length)
                            onRemoteType(added)
                        } else if (newText.length < remoteInputText.length) {
                            val diff = remoteInputText.length - newText.length
                            repeat(diff) { onRemoteType("\b") }
                        }
                        remoteInputText = newText
                    },
                    placeholder = { Text("Live typing: keystrokes stream directly to laptop…", color = Color(0xFF52525B), fontSize = 12.sp) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(52.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedContainerColor = Color.Black,
                        unfocusedContainerColor = Color.Black,
                        focusedBorderColor = Color.White,
                        unfocusedBorderColor = Color(0x26FFFFFF),
                        focusedTextColor = Color.White,
                        unfocusedTextColor = Color(0xFFE4E4E7)
                    ),
                    shape = RoundedCornerShape(8.dp),
                    singleLine = true
                )
            }
        }

        Spacer(Modifier.height(14.dp))

        // --- 6. Mode Switcher Pill Bar ---
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(Color(0xFF09090B))
                .border(1.dp, Color(0x1AFFFFFF), RoundedCornerShape(12.dp))
                .padding(4.dp)
        ) {
            Row(modifier = Modifier.fillMaxWidth()) {
                val modes = listOf(
                    "study" to "📚 Study",
                    "entertainment" to "🎬 Entert.",
                    "coding" to "💻 Code",
                    "exam" to "🛡️ Exam"
                )
                modes.forEach { (key, label) ->
                    val isSelected = activeMode == key
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (isSelected) Color.White else Color.Transparent)
                            .clickable {
                                activeMode = key
                                onSwitchMode(key)
                            }
                            .padding(vertical = 8.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            label,
                            color = if (isSelected) Color.Black else Color(0xFFA1A1AA),
                            fontSize = 12.sp,
                            fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Medium
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(14.dp))

        // --- 7. Link to Web Ecosystem ---
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(Color(0xFF09090B))
                .border(1.dp, Color(0x26FFFFFF), RoundedCornerShape(14.dp))
                .clickable { onOpenWebDashboard() }
                .padding(14.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("Open Optical & Vector Dashboard", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                    Text("View live camera feed, SFace vector telemetry, and activity graphs", color = Color(0xFFA1A1AA), fontSize = 11.sp)
                }
                Spacer(Modifier.width(8.dp))
                Text("↗", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            }
        }

        Spacer(Modifier.height(20.dp))

        Text(
            "ORBIT COMPANION · HARDWARE CONTINUITY MESH",
            fontSize = 10.sp,
            color = Color(0xFF52525B),
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.align(Alignment.CenterHorizontally)
        )
    }


}
}

// ---------------------------------------------------------------------------
// QR Scanner & Pairing Dialog
// ---------------------------------------------------------------------------

@Composable
fun PairingQrDialog(
    initialIp: String,
    onDismiss: () -> Unit,
    onPairSuccess: (String, Int, String) -> Unit
) {
    val context = LocalContext.current
    val effectiveIp = if (initialIp.isNotBlank() && initialIp != "localhost") initialIp else "192.168.1.100"
    var ipInput by remember { mutableStateOf(effectiveIp) }
    var keyInput by remember { mutableStateOf("") }
    var isAutoPairing by remember { mutableStateOf(false) }
    var statusText by remember { mutableStateOf<String?>(null) }

    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasCameraPermission = granted
        if (!granted) {
            Toast.makeText(context, "Camera permission needed to scan QR. You can also use 1-Tap Auto Pair.", Toast.LENGTH_LONG).show()
        }
    }

    Dialog(onDismissRequest = onDismiss) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(20.dp))
                .background(Color(0xFF09090B))
                .border(1.dp, Color(0x33FFFFFF), RoundedCornerShape(20.dp))
                .padding(20.dp)
        ) {
            Column(modifier = Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Pair with Laptop", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.weight(1f))
                    IconButton(onClick = onDismiss, modifier = Modifier.size(24.dp)) {
                        Text("✕", color = Color(0xFFA1A1AA), fontSize = 14.sp)
                    }
                }
                Text(
                    "Scan the QR code from the laptop web dashboard (http://localhost:8080 -> 'Pair Device') or 1-tap auto-pair over Wi-Fi.",
                    color = Color(0xFFA1A1AA),
                    fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp, bottom = 12.dp)
                )

                // Camera Scanner or Permission Request
                if (hasCameraPermission) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(200.dp)
                            .clip(RoundedCornerShape(12.dp))
                            .border(1.dp, Color(0x3334D399), RoundedCornerShape(12.dp))
                    ) {
                        CameraQrScanner(
                            onQrDetected = { raw ->
                                try {
                                    val json = JSONObject(raw as String)
                                    val key = json.getString("key")
                                    val ip = json.optString("ip", ipInput)
                                    val port = json.optInt("port", 8765)
                                    onPairSuccess(ip, port, key)
                                } catch (e: Exception) {
                                    statusText = "Invalid QR code format"
                                }
                            },
                            modifier = Modifier.fillMaxSize()
                        )
                    }
                } else {
                    Button(
                        onClick = { cameraPermissionLauncher.launch(Manifest.permission.CAMERA) },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1E1E24), contentColor = Color.White),
                        shape = RoundedCornerShape(10.dp)
                    ) {
                        Text("📷 Enable Camera to Scan QR", fontSize = 12.sp)
                    }
                }

                Spacer(Modifier.height(14.dp))

                // 1-Tap Network Auto-Pair Button
                Button(
                    onClick = {
                        isAutoPairing = true
                        statusText = "Contacting http://$ipInput:8080/api/pairing_qr…"
                        CoroutineScope(Dispatchers.IO).launch {
                            try {
                                val client = OkHttpClient()
                                val req = Request.Builder()
                                    .url("http://$ipInput:8080/api/pairing_qr")
                                    .build()
                                client.newCall(req).execute().use { resp ->
                                    if (resp.isSuccessful) {
                                        val body = resp.body?.string() ?: ""
                                        val json = JSONObject(body)
                                        val key = json.optString("key", "")
                                        val ip = json.optString("ip", ipInput)
                                        val port = json.optInt("port", 8765)
                                        if (key.isNotEmpty()) {
                                            withContext(Dispatchers.Main) {
                                                isAutoPairing = false
                                                onPairSuccess(ip, port, key)
                                            }
                                        } else {
                                            withContext(Dispatchers.Main) {
                                                isAutoPairing = false
                                                statusText = "Laptop returned empty key. Please scan QR directly."
                                            }
                                        }
                                    } else {
                                        withContext(Dispatchers.Main) {
                                            isAutoPairing = false
                                            statusText = "Could not connect to laptop on port 8080"
                                        }
                                    }
                                }
                            } catch (e: Exception) {
                                withContext(Dispatchers.Main) {
                                    isAutoPairing = false
                                    statusText = "Connection error: ${e.message}"
                                }
                            }
                        }
                    },
                    enabled = !isAutoPairing,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Color.Black),
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text(if (isAutoPairing) "Auto-Pairing…" else "⚡ 1-Tap Local Wi-Fi Auto-Pair", fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }

                if (statusText != null) {
                    Text(
                        statusText!!,
                        color = Color(0xFFFBBF24),
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(top = 6.dp)
                    )
                }

                Spacer(Modifier.height(10.dp))

                // Manual IP input
                OutlinedTextField(
                    value = ipInput,
                    onValueChange = { ipInput = it },
                    label = { Text("Laptop LAN IP Address", color = Color(0xFFA1A1AA), fontSize = 11.sp) },
                    modifier = Modifier.fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedContainerColor = Color.Black,
                        unfocusedContainerColor = Color.Black,
                        focusedBorderColor = Color.White,
                        unfocusedBorderColor = Color(0x26FFFFFF),
                        focusedTextColor = Color.White,
                        unfocusedTextColor = Color.White
                    ),
                    shape = RoundedCornerShape(8.dp),
                    singleLine = true
                )
            }
        }
    }
}

// ---------------------------------------------------------------------------
// CameraX + ML Kit Barcode Analyzer View
// ---------------------------------------------------------------------------

@Composable
fun CameraQrScanner(
    onQrDetected: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val cameraProviderFuture = remember { ProcessCameraProvider.getInstance(context) }
    var scanned by remember { mutableStateOf(false) }

    AndroidView(
        factory = { ctx ->
            val previewView = PreviewView(ctx)
            val executor = ContextCompat.getMainExecutor(ctx)

            cameraProviderFuture.addListener({
                val cameraProvider = cameraProviderFuture.get()
                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }

                val options = BarcodeScannerOptions.Builder()
                    .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                    .build()
                val barcodeScanner = BarcodeScanning.getClient(options)

                val imageAnalysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()

                imageAnalysis.setAnalyzer(executor) { imageProxy ->
                    val mediaImage = imageProxy.image
                    if (mediaImage != null && !scanned) {
                        val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
                        barcodeScanner.process(image)
                            .addOnSuccessListener { barcodes ->
                                for (barcode in barcodes) {
                                    val raw = barcode.rawValue
                                    if (!raw.isNullOrEmpty() && !scanned) {
                                        scanned = true
                                        onQrDetected(raw)
                                        break
                                    }
                                }
                            }
                            .addOnCompleteListener {
                                imageProxy.close()
                            }
                    } else {
                        imageProxy.close()
                    }
                }

                try {
                    cameraProvider.unbindAll()
                    cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        CameraSelector.DEFAULT_BACK_CAMERA,
                        preview,
                        imageAnalysis
                    )
                } catch (e: Exception) {
                    // Safe guard
                }
            }, executor)

            previewView
        },
        modifier = modifier
    )
}
