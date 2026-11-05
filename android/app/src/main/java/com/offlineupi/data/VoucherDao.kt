package com.offlineupi.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update

@Dao
interface VoucherDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertVoucher(voucher: OfflineVoucher): Long

    @Query("SELECT * FROM offline_vouchers WHERE voucher_id = :voucherId LIMIT 1")
    suspend fun getVoucherById(voucherId: String): OfflineVoucher?

    @Query("SELECT * FROM offline_vouchers WHERE status = 'PENDING_SYNC' ORDER BY id ASC")
    suspend fun getPendingSyncVouchers(): List<OfflineVoucher>

    @Query("UPDATE offline_vouchers SET status = :status, synced_at = :syncedAt WHERE voucher_id = :voucherId")
    suspend fun updateSyncStatus(voucherId: String, status: String, syncedAt: String)

    @Query("SELECT COUNT(*) FROM offline_vouchers WHERE sender_vpa = :senderVpa")
    suspend fun getVoucherCountForSender(senderVpa: String): Long

    @Query("SELECT * FROM offline_vouchers ORDER BY id DESC LIMIT :limit")
    suspend fun getRecentVouchers(limit: Int = 20): List<OfflineVoucher>
}

