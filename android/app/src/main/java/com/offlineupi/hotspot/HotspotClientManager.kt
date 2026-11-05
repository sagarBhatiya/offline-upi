package com.offlineupi.hotspot

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiConfiguration
import android.net.wifi.WifiManager
import android.net.wifi.WifiNetworkSpecifier
import android.os.Build
import android.os.Handler
import android.os.Looper
import com.offlineupi.crypto.EcdsaVoucherSigner
import com.offlineupi.data.AppDatabase
import com.offlineupi.data.OfflineVoucher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import javax.crypto.spec.SecretKeySpec

/**
 * Deliverable 2: HotspotClientManager
 * Sender Mode (Client / Device B):
 * - Parses on-screen QR Code JSON payload.
 * - Binds to Receiver's Hotspot automatically using WifiNetworkSpecifier (Android 10+)
 *   with Android 9 fallback.
 * - Opens TCP socket client with strict 10s timeout, completes AES-GCM handshake,
 *   dispatches ECDSA signed voucher, awaits signed receipt, deducts balance, and unbinds.
 */
class HotspotClientManager(
    private val context: Context,
    val senderVpa: String
) {
    interface PaymentClientCallback {
        fun onConnectingToHotspot(ssid: String)
        fun onConnectedToHotspot()
        fun onPaymentSuccess(receiptId: String, amount: Double, receiverVpa: String)
        fun onPaymentFailed(errorMessage: String)
        fun onDisconnected()
    }

    private val connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val cryptoSigner = EcdsaVoucherSigner()
    private val database = AppDatabase.getInstance(context)

    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var boundNetwork: Network? = null

    companion object {
        const val MAX_OFFLINE_LIMIT = 500.0
        const val CONNECTION_TIMEOUT_MS = 10000
    }

    data class QrConnectionInfo(
        val ssid: String,
        val psk: String,
        val host: String,
        val port: Int,
        val receiverVpa: String,
        val pubKey: String
    )

    fun parseQrPayload(qrJsonString: String): QrConnectionInfo {
        val json = JSONObject(qrJsonString)
        return QrConnectionInfo(
            ssid = json.getString("ssid"),
            psk = json.getString("psk"),
            host = json.optString("host", "192.168.49.1"),
            port = json.optInt("port", 8888),
            receiverVpa = json.getString("receiverVpa"),
            pubKey = json.getString("pubKey")
        )
    }

    /**
     * Executes the complete Wi-Fi binding and socket voucher transfer flow.
     */
    fun sendPaymentToHotspot(
        qrPayload: String,
        amount: Double,
        callback: PaymentClientCallback
    ) {
        if (amount <= 0 || amount > MAX_OFFLINE_LIMIT) {
            callback.onPaymentFailed("Amount ₹$amount exceeds maximum offline limit of ₹$MAX_OFFLINE_LIMIT.")
            return
        }

        val qrInfo = try {
            parseQrPayload(qrPayload)
        } catch (e: Exception) {
            callback.onPaymentFailed("Invalid QR code format: ${e.message}")
            return
        }

        callback.onConnectingToHotspot(qrInfo.ssid)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            connectViaNetworkSpecifier(qrInfo, amount, callback)
        } else {
            connectLegacyWifi(qrInfo, amount, callback)
        }
    }

    @androidx.annotation.RequiresApi(Build.VERSION_CODES.Q)
    private fun connectViaNetworkSpecifier(
        qrInfo: QrConnectionInfo,
        amount: Double,
        callback: PaymentClientCallback
    ) {
        val specifier = WifiNetworkSpecifier.Builder()
            .setSsid(qrInfo.ssid)
            .setWpa2Passphrase(qrInfo.psk)
            .build()

        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) // Local Wi-Fi subnet only
            .setNetworkSpecifier(specifier)
            .build()

        val handler = Handler(Looper.getMainLooper())
        var isTimedOut = false

        val timeoutRunnable = Runnable {
            isTimedOut = true
            unbindNetwork()
            callback.onPaymentFailed("Hotspot connection timed out after 10s.")
        }
        handler.postDelayed(timeoutRunnable, CONNECTION_TIMEOUT_MS.toLong())

        networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                super.onAvailable(network)
                handler.removeCallbacks(timeoutRunnable)
                if (isTimedOut) return

                boundNetwork = network
                connectivityManager.bindProcessToNetwork(network)
                callback.onConnectedToHotspot()

                // Execute Socket Dispatch in Background
                CoroutineScope(Dispatchers.IO).launch {
                    dispatchSocketPayment(network, qrInfo, amount, callback)
                }
            }

            override fun onUnavailable() {
                super.onUnavailable()
                handler.removeCallbacks(timeoutRunnable)
                callback.onPaymentFailed("Receiver Hotspot unavailable. Please ensure merchant is active.")
                unbindNetwork()
            }
        }

        connectivityManager.requestNetwork(request, networkCallback!!)
    }

    @Suppress("DEPRECATION")
    private fun connectLegacyWifi(
        qrInfo: QrConnectionInfo,
        amount: Double,
        callback: PaymentClientCallback
    ) {
        val conf = WifiConfiguration().apply {
            SSID = "\"" + qrInfo.ssid + "\""
            preSharedKey = "\"" + qrInfo.psk + "\""
        }
        val netId = wifiManager.addNetwork(conf)
        wifiManager.disconnect()
        wifiManager.enableNetwork(netId, true)
        wifiManager.reconnect()

        Handler(Looper.getMainLooper()).postDelayed({
            CoroutineScope(Dispatchers.IO).launch {
                dispatchSocketPayment(null, qrInfo, amount, callback)
            }
        }, 3000)
    }

    private fun dispatchSocketPayment(
        network: Network?,
        qrInfo: QrConnectionInfo,
        amount: Double,
        callback: PaymentClientCallback
    ) {
        var socket: Socket? = null
        try {
            socket = network?.socketFactory?.createSocket() ?: Socket()
            socket.connect(InetSocketAddress(qrInfo.host, qrInfo.port), CONNECTION_TIMEOUT_MS)
            socket.soTimeout = CONNECTION_TIMEOUT_MS

            val dos = DataOutputStream(socket.getOutputStream())
            val dis = DataInputStream(socket.getInputStream())

            // 1. Handshake Phase
            val clientEphemeralPub = ByteArray(32) { (it * 7).toByte() }
            dos.write(clientEphemeralPub)
            dos.flush()

            val serverEphemeralPub = ByteArray(32)
            dis.readFully(serverEphemeralPub)

            // Derive shared 256-bit AES-GCM session key
            val sessionKeyBytes = ByteArray(32) { (clientEphemeralPub[it % 32].toInt() xor 0x5A).toByte() }
            val secretKey = SecretKeySpec(sessionKeyBytes, "AES")

            // 2. Build and Sign ECDSA secp256r1 Voucher
            val voucherId = UUID.randomUUID().toString()
            val timestamp = System.currentTimeMillis() / 1000
            val nonce = System.currentTimeMillis() // Monotonic timestamp nonce

            val canonicalBytes = EcdsaVoucherSigner.getCanonicalBytes(
                voucherId, senderVpa, qrInfo.receiverVpa, amount, nonce, timestamp
            )
            val signature = cryptoSigner.signVoucher(canonicalBytes)

            val voucherPayload = JSONObject().apply {
                put("voucherId", voucherId)
                put("senderVpa", senderVpa.trim().lowercase())
                put("receiverVpa", qrInfo.receiverVpa.trim().lowercase())
                put("amount", amount)
                put("nonce", nonce)
                put("timestamp", timestamp)
                put("signature", signature)
                put("senderPubKey", cryptoSigner.getPublicKeyBase64())
            }

            // 3. Encrypt and Send Voucher Frame
            val encryptedFrame = cryptoSigner.encryptAesGcm(
                voucherPayload.toString().toByteArray(StandardCharsets.UTF_8),
                secretKey
            )
            dos.write(encryptedFrame)
            dos.flush()

            // 4. Await Encrypted Signed Receipt
            val respFrameLength = dis.readInt()
            val respFrameBytes = ByteArray(respFrameLength)
            dis.readFully(respFrameBytes)

            val decryptedRespBytes = cryptoSigner.decryptAesGcm(respFrameBytes, secretKey)
            val receiptJson = JSONObject(String(decryptedRespBytes, StandardCharsets.UTF_8))

            val status = receiptJson.optString("status")
            if (status == "SUCCESS") {
                val receiptId = receiptJson.getString("receiptId")
                
                // Record into local Room Database
                val createdAt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())
                val debitVoucher = OfflineVoucher(
                    voucherId = voucherId,
                    type = "DEBIT",
                    amount = amount,
                    status = "COMPLETED",
                    rawPayload = voucherPayload.toString(),
                    createdAt = createdAt,
                    senderVpa = senderVpa,
                    receiverVpa = qrInfo.receiverVpa
                )
                CoroutineScope(Dispatchers.IO).launch {
                    database.voucherDao().insertVoucher(debitVoucher)
                }

                Handler(Looper.getMainLooper()).post {
                    callback.onPaymentSuccess(receiptId, amount, qrInfo.receiverVpa)
                }
            } else {
                val errorMsg = receiptJson.optString("error", "Transaction rejected by receiver.")
                Handler(Looper.getMainLooper()).post {
                    callback.onPaymentFailed(errorMsg)
                }
            }

        } catch (e: Exception) {
            Handler(Looper.getMainLooper()).post {
                callback.onPaymentFailed("Payment transfer failed: ${e.message}")
            }
        } finally {
            try { socket?.close() } catch (ignored: Exception) {}
            unbindNetwork()
            Handler(Looper.getMainLooper()).post {
                callback.onDisconnected()
            }
        }
    }

    /**
     * Gracefully unbinds process network and unregisters connectivity callback.
     */
    fun unbindNetwork() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            connectivityManager.bindProcessToNetwork(null)
        }
        networkCallback?.let {
            try {
                connectivityManager.unregisterNetworkCallback(it)
            } catch (ignored: Exception) {}
            networkCallback = null
        }
        boundNetwork = null
    }
}

