package com.offlineupi.data

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Encrypted Offline Voucher Database Entity:
 * Tracks offline voucher double-entry states (DEBIT/CREDIT)
 * and cloud synchronization statuses (COMPLETED, PENDING_SYNC, QUARANTINED).
 */
@Entity(
    tableName = "offline_vouchers",
    indices = [Index(value = ["voucher_id"], unique = true)]
)
data class OfflineVoucher(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    @ColumnInfo(name = "voucher_id")
    val voucherId: String,

    @ColumnInfo(name = "type")
    val type: String, // "DEBIT" or "CREDIT"

    @ColumnInfo(name = "amount")
    val amount: Double,

    @ColumnInfo(name = "status")
    val status: String, // "COMPLETED", "PENDING_SYNC", "QUARANTINED"

    @ColumnInfo(name = "raw_payload")
    val rawPayload: String,

    @ColumnInfo(name = "created_at")
    val createdAt: String,

    @ColumnInfo(name = "synced_at")
    val syncedAt: String? = null,

    @ColumnInfo(name = "sender_vpa")
    val senderVpa: String = "",

    @ColumnInfo(name = "receiver_vpa")
    val receiverVpa: String = ""
)

