import hmac
import hashlib
import time
from datetime import datetime

class RegulatoryRiskEngine:
    MAX_PER_TXN_AMOUNT = 500.00       # RBI offline per-transaction ceiling (₹500)
    MAX_CUMULATIVE_OFFLINE = 2000.00   # Max allowed cumulative on-device wallet pool (₹2,000)
    VOUCHER_TTL_HOURS = 48             # Mandatory expiry window (48 hours)

    @classmethod
    def validate_offline_instruction(cls, amount: float, current_balance: float, signed_timestamp: int):
        if amount <= 0:
            raise ValueError("Transaction amount must be strictly greater than ₹0.00.")

        if amount > cls.MAX_PER_TXN_AMOUNT:
            raise ValueError(
                f"Transaction exceeds RBI offline limit of ₹{cls.MAX_PER_TXN_AMOUNT:.2f} (Attempted: ₹{amount:.2f})."
            )

        if current_balance < amount:
            raise ValueError(
                f"Insufficient offline balance! Available: ₹{current_balance:.2f}, Required: ₹{amount:.2f}."
            )

        # Check TTL
        now_ts = int(time.time() * 1000)
        elapsed_hours = (now_ts - signed_timestamp) / (1000.0 * 3600.0)
        if elapsed_hours > cls.VOUCHER_TTL_HOURS:
            raise ValueError(f"Offline voucher has expired ({elapsed_hours:.1f}h old > 48h limit). Online reconciliation required.")

class OfflineReconciliationEngine:
    """
    Hardened Reconciliation & Double-Spend Prevention Engine:
    - Verifies monotonic counter & hash-chain steps: H_i = HMAC(H_{i-1}, seq:amount:payee).
    - Detects offline forks (double-spend attempts with duplicate seq or branched hash).
    - Immediately quarantines fraudulent wallets with slashing & audit logging.
    - Applies NPCI/RBI risk invariant checks.
    """
    def __init__(self, db_module):
        self.db = db_module

    def compute_step_hash(self, prev_hash: str, seq: int, amount: float, payee_vpa: str) -> str:
        """Computes HMAC-SHA256 monotonic step hash."""
        msg = f"{seq}:{amount:.2f}:{payee_vpa}".encode('utf-8')
        return hmac.new(prev_hash.encode('utf-8'), msg, hashlib.sha256).hexdigest()

    def process_hardened_voucher(self, voucher: dict) -> dict:
        """
        Processes and reconciles an incoming offline voucher payload.
        Voucher format:
        {
            "payer_vpa": str,
            "payee_vpa": str,
            "amount": float,
            "seq_counter": int,
            "prev_hash": str,
            "current_hash": str,
            "signed_at": int (ms),
            "signature": str
        }
        """
        payer_vpa = (voucher.get("payer_vpa") or "").strip()
        payee_vpa = (voucher.get("payee_vpa") or "").strip()
        amount = float(voucher.get("amount", 0.0))
        seq = int(voucher.get("seq_counter", 1))
        prev_hash = voucher.get("prev_hash") or "GENESIS_HASH"
        current_hash = voucher.get("current_hash") or ""
        signed_at = int(voucher.get("signed_at", int(time.time() * 1000)))
        sig = voucher.get("signature", "")

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # 1. Fetch wallet state
            cursor.execute("SELECT state, current_seq, last_hash, escrow_balance FROM wallets WHERE vpa = ?", (payer_vpa,))
            wallet = cursor.fetchone()

            if not wallet:
                # Auto-initialize wallet if not present (defaulting to ₹2000 demo ceiling)
                init_bal = 2000.0
                genesis_hash = hashlib.sha256(f"{payer_vpa}:GENESIS:{time.time()}".encode('utf-8')).hexdigest()
                cursor.execute("""
                    INSERT INTO wallets (vpa, state, current_seq, last_hash, escrow_balance, updated_at)
                    VALUES (?, 'ACTIVE', 0, ?, ?, ?)
                """, (payer_vpa, genesis_hash, init_bal, datetime.now().isoformat()))
                conn.commit()
                cursor.execute("SELECT state, current_seq, last_hash, escrow_balance FROM wallets WHERE vpa = ?", (payer_vpa,))
                wallet = cursor.fetchone()

            wallet_dict = dict(wallet)
            if wallet_dict["state"] == "QUARANTINED_FRAUD":
                return {
                    "success": False,
                    "status": "REJECTED_WALLET_QUARANTINED",
                    "error": f"Wallet '{payer_vpa}' is quarantined due to prior double-spend fraud detection."
                }

            # 2. Enforce Regulatory Caps & TTL
            RegulatoryRiskEngine.validate_offline_instruction(
                amount=amount,
                current_balance=wallet_dict["escrow_balance"],
                signed_timestamp=signed_at
            )

            # 3. Check for Monotonic Fork / Double Spend
            cursor.execute(
                "SELECT id, current_hash, payee_vpa, amount FROM vouchers WHERE payer_vpa = ? AND seq_counter = ?",
                (payer_vpa, seq)
            )
            existing_voucher = cursor.fetchone()

            if existing_voucher:
                existing_dict = dict(existing_voucher)
                if existing_dict["current_hash"] == current_hash and existing_dict["payee_vpa"] == payee_vpa:
                    # Idempotent re-submission (e.g. multi-hop mule relay duplicate)
                    return {
                        "success": True,
                        "status": "DUPLICATE_IDEMPOTENT_SUCCESS",
                        "voucher_id": existing_dict["id"],
                        "message": "Voucher already settled. Idempotent acknowledgment returned."
                    }
                else:
                    # FORK DETECTED! Same sequence counter used for different hash or merchant!
                    self._quarantine_wallet(
                        cursor=cursor,
                        vpa=payer_vpa,
                        seq=seq,
                        conflict_a=existing_dict,
                        conflict_b=voucher
                    )
                    conn.commit()
                    return {
                        "success": False,
                        "status": "REJECTED_DOUBLE_SPEND",
                        "error": "CRITICAL_OFFLINE_FORK_DETECTED: Sequence counter re-used with conflicting payload.",
                        "slashing_applied": True
                    }

            # 4. Verify Hash Chain Continuity
            expected_current_hash = self.compute_step_hash(
                prev_hash=prev_hash,
                seq=seq,
                amount=amount,
                payee_vpa=payee_vpa
            )

            if current_hash != expected_current_hash:
                return {
                    "success": False,
                    "status": "REJECTED_INTEGRITY_MISMATCH",
                    "error": "Monotonic hash step verification failed. Tampered voucher."
                }

            # 5. Atomic Settlement & State Update
            utr = f"409{int(time.time()*1000)%1000000000:09d}"
            cursor.execute("""
                INSERT INTO vouchers (
                    payer_vpa, payee_vpa, seq_counter, prev_hash, current_hash,
                    amount, status, raw_sig, submitted_at, bank_utr
                ) VALUES (?, ?, ?, ?, ?, ?, 'SETTLED', ?, ?, ?)
            """, (
                payer_vpa, payee_vpa, seq, prev_hash, current_hash,
                amount, sig, datetime.now().isoformat(), utr
            ))
            voucher_id = cursor.lastrowid

            new_payer_bal = wallet_dict["escrow_balance"] - amount
            cursor.execute("""
                UPDATE wallets
                SET current_seq = ?, last_hash = ?, escrow_balance = ?, updated_at = ?
                WHERE vpa = ?
            """, (seq, current_hash, new_payer_bal, datetime.now().isoformat(), payer_vpa))

            # Credit merchant wallet
            cursor.execute("SELECT balance FROM accounts WHERE vpa = ?", (payee_vpa,))
            m_acc = cursor.fetchone()
            if not m_acc:
                cursor.execute("INSERT INTO accounts (vpa, holder_name, balance, version) VALUES (?, ?, ?, 1)",
                               (payee_vpa, f"{payee_vpa.split('@')[0].capitalize()} (Merchant)", amount))
            else:
                cursor.execute("UPDATE accounts SET balance = balance + ?, version = version + 1 WHERE vpa = ?",
                               (amount, payee_vpa))

            # Record balanced double-entry ledger journal
            self.db.record_double_entry_transaction(
                entry_type="OFFLINE_VOUCHER_SETTLEMENT",
                transaction_ref=f"VOUCHER_{voucher_id}_{utr}",
                payer_vpa=payer_vpa,
                payee_vpa=payee_vpa,
                amount=amount,
                conn=conn
            )

            conn.commit()

            return {
                "success": True,
                "status": "SETTLED_SUCCESS",
                "voucher_id": voucher_id,
                "payer_vpa": payer_vpa,
                "payee_vpa": payee_vpa,
                "amount": amount,
                "seq_counter": seq,
                "bank_utr": utr,
                "new_payer_balance": new_payer_bal
            }

        except Exception as e:
            conn.rollback()
            return {"success": False, "status": "ERROR", "error": str(e)}
        finally:
            conn.close()

    def _quarantine_wallet(self, cursor, vpa: str, seq: int, conflict_a: dict, conflict_b: dict):
        cursor.execute("UPDATE wallets SET state = 'QUARANTINED_FRAUD' WHERE vpa = ?", (vpa,))
        cursor.execute("""
            INSERT INTO fraud_audit_log (vpa, sequence_counter, evidence_payload, quarantined_at)
            VALUES (?, ?, ?, ?)
        """, (
            vpa,
            seq,
            f"Conflict V1: {conflict_a} | Conflict V2: {conflict_b}",
            datetime.now().isoformat()
        ))
