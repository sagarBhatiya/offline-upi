package com.offlineupi.service

import android.content.Context
import androidx.work.Constraints
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.offlineupi.crypto.EcdsaVoucherSigner
import com.offlineupi.data.AppDatabase
import com.offlineupi.data.OfflineVoucher
import com.offlineupi.hotspot.HotspotClientManager
import com.offlineupi.hotspot.HotspotServerManager
import com.offlineupi.sync.VoucherSyncWorker

/**
 * Deliverable 3: OfflinePaymentService
 * Orchestrator linking the local network manager, cryptography engine,
 * Room database, and WorkManager background reconciliation.
 */
class OfflinePaymentService(private val context: Context) {

    private val database = AppDatabase.getInstance(context)
    private val signer = EcdsaVoucherSigner()
    private var serverManager: HotspotServerManager? = null
    private var clientManager: HotspotClientManager? = null

    /**
     * Initializes Receiver Mode: starts Hotspot and TCP Socket Server.
     */
    fun startReceiver(
        receiverVpa: String,
        port: Int = 8888,
        listener: HotspotServerManager.HotspotServerListener
    ) {
        stopReceiver()
        serverManager = HotspotServerManager(context, receiverVpa, port).apply {
            this.listener = object : HotspotServerManager.HotspotServerListener {
                override fun onHotspotStarted(qrPayloadJson: String) {
                    listener.onHotspotStarted(qrPayloadJson)
                }

                override fun onHotspotFailed(error: String) {
                    listener.onHotspotFailed(error)
                }

                override fun onPaymentReceived(voucher: OfflineVoucher, senderVpa: String, amount: Double) {
                    listener.onPaymentReceived(voucher, senderVpa, amount)
                    scheduleBackgroundVoucherSync()
                }

                override fun onPaymentRejected(error: String, rawPayload: String) {
                    listener.onPaymentRejected(error, rawPayload)
                }

                override fun onHotspotStopped() {
                    listener.onHotspotStopped()
                }
            }
            startHotspot()
        }
    }

    /**
     * Stops Receiver Mode and releases hotspot & ports.
     */
    fun stopReceiver() {
        serverManager?.stopHotspot()
        serverManager = null
    }

    /**
     * Initiates Sender Mode: binds Wi-Fi and executes socket transfer.
     */
    fun sendOfflinePayment(
        senderVpa: String,
        qrPayload: String,
        amount: Double,
        callback: HotspotClientManager.PaymentClientCallback
    ) {
        clientManager = HotspotClientManager(context, senderVpa)
        clientManager?.sendPaymentToHotspot(qrPayload, amount, object : HotspotClientManager.PaymentClientCallback {
            override fun onConnectingToHotspot(ssid: String) {
                callback.onConnectingToHotspot(ssid)
            }

            override fun onConnectedToHotspot() {
                callback.onConnectedToHotspot()
            }

            override fun onPaymentSuccess(receiptId: String, amount: Double, receiverVpa: String) {
                callback.onPaymentSuccess(receiptId, amount, receiverVpa)
                scheduleBackgroundVoucherSync()
            }

            override fun onPaymentFailed(errorMessage: String) {
                callback.onPaymentFailed(errorMessage)
            }

            override fun onDisconnected() {
                callback.onDisconnected()
            }
        })
    }

    /**
     * Schedules a background WorkManager job to synchronize offline vouchers
     * as soon as internet connectivity (NetworkType.CONNECTED) becomes available.
     */
    fun scheduleBackgroundVoucherSync() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val syncRequest = OneTimeWorkRequestBuilder<VoucherSyncWorker>()
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(context).enqueue(syncRequest)
    }

    suspend fun getRecentTransactions(limit: Int = 20): List<OfflineVoucher> {
        return database.voucherDao().getRecentVouchers(limit)
    }
}

