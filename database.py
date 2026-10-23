"""
Backward-compatibility shim for database module.
Directs all database queries and transactions to the modular src.db layer.
Supports both PostgreSQL and SQLite fallback.
"""
from src.db import (
    get_connection,
    get_db_type,
    is_postgres_configured,
    init_db,
    reset_db,
    claim_packet_hash,
    get_accounts,
    get_transactions,
    get_offline_vouchers,
    create_voucher_record,
    claim_voucher_record,
    record_deposit,
    record_withdrawal,
    upsert_user_account,
    execute_offline_wallet_transfer,
    get_wallet_state,
    update_wallet_state,
    quarantine_wallet,
    record_fraud_attempt,
    execute_settlement,
    record_double_entry_transaction,
    audit_ledger_integrity
)

__all__ = [
    "get_connection",
    "get_db_type",
    "is_postgres_configured",
    "init_db",
    "reset_db",
    "claim_packet_hash",
    "get_accounts",
    "get_transactions",
    "get_offline_vouchers",
    "create_voucher_record",
    "claim_voucher_record",
    "record_deposit",
    "record_withdrawal",
    "upsert_user_account",
    "execute_offline_wallet_transfer",
    "get_wallet_state",
    "update_wallet_state",
    "quarantine_wallet",
    "record_fraud_attempt",
    "execute_settlement",
    "record_double_entry_transaction",
    "audit_ledger_integrity"
]
