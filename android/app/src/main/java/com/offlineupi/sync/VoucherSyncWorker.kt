package com.offlineupi.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.offlineupi.data.AppDatabase
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Background WorkManager Worker:
 * Triggered automatically when internet connectivity is restored
 * to sync offline vouchers from the Room database to the cloud server.
 */
class VoucherSyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    override suspend fun doWork(): Result {
        val database = AppDatabase.getInstance(applicationContext)
        val pendingVouchers = database.voucherDao().getPendingSyncVouchers()

        if (pendingVouchers.isEmpty()) {
            return Result.success()
        }

        return try {
            val nowStr = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())
            for (voucher in pendingVouchers) {
                // In production, posts raw_payload to bank / central NPCI cloud gateway
                // For demo & offline sync simulation, we mark as synced
                database.voucherDao().updateSyncStatus(
                    voucherId = voucher.voucherId,
                    status = "COMPLETED",
                    syncedAt = nowStr
                )
            }
            Result.success()
        } catch (e: Exception) {
            Result.retry()
        }
    }
}

