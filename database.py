import sqlite3
import os
import shutil
import time
import random
from datetime import datetime

def get_db_path():
    # Detect Vercel, AWS Lambda, or read-only filesystem
    is_serverless = bool(
        os.environ.get("VERCEL") or 
        os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or 
        not os.access(os.path.dirname(os.path.abspath(__file__)), os.W_OK)
    )
    if is_serverless:
        tmp_dir = os.environ.get("TMPDIR", "/tmp")
        tmp_db = os.path.join(tmp_dir, "upi.db")
        orig_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upi.db")
        if not os.path.exists(tmp_db) and os.path.exists(orig_db):
            try:
                shutil.copyfile(orig_db, tmp_db)
            except Exception as e:
                print("Notice: could not copy pre-seeded upi.db to /tmp:", e)
        return tmp_db
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'upi.db')

DB_PATH = get_db_path()

def get_connection():
    global DB_PATH
    DB_PATH = get_db_path()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Accounts Table (with version for optimistic locking)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            vpa TEXT PRIMARY KEY,
            holder_name TEXT NOT NULL,
            balance REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        )
    ''')
    
    # 2. Idempotency Claims Table (Atomic SHA-256 deduplication registry)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS idempotency_claims (
            packet_hash TEXT PRIMARY KEY,
            claimed_at TEXT NOT NULL,
            status TEXT NOT NULL
        )
    ''')
    
    # 3. Transaction Audit Ledger Table (Supports Dynamic QR and Mule Bounty Tracking)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            packet_hash TEXT NOT NULL,
            sender_vpa TEXT NOT NULL,
            receiver_vpa TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            bridge_id TEXT NOT NULL,
            hop_count INTEGER NOT NULL,
            mule_vpa TEXT DEFAULT 'mule@upi',
            mule_reward REAL DEFAULT 0.0,
            auth_mode TEXT DEFAULT 'BLE_MESH',
            bank_utr TEXT DEFAULT '',
            deeplink_url TEXT DEFAULT '',
            settled_at TEXT NOT NULL
        )
    ''')
    # 4. Offline Vouchers Table (6-digit PIN and claim registry)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS offline_vouchers (
            pin TEXT PRIMARY KEY,
            sender_vpa TEXT NOT NULL,
            receiver_vpa TEXT NOT NULL,
            amount REAL NOT NULL,
            utr TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    # 5. Production Wallets State Table (With Monotonic Chain & Fraud Status)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallets (
            vpa TEXT PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'ACTIVE',
            current_seq INTEGER NOT NULL DEFAULT 0,
            last_hash TEXT NOT NULL,
            escrow_balance REAL NOT NULL DEFAULT 2000.0,
            updated_at TEXT NOT NULL
        )
    ''')

    # 6. Cryptographically Reconciled Vouchers Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payer_vpa TEXT NOT NULL,
            payee_vpa TEXT NOT NULL,
            seq_counter INTEGER NOT NULL,
            prev_hash TEXT NOT NULL,
            current_hash TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            raw_sig TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            bank_utr TEXT NOT NULL
        )
    ''')

    # 7. Fraud Audit Trail Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fraud_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vpa TEXT NOT NULL,
            sequence_counter INTEGER NOT NULL,
            evidence_payload TEXT NOT NULL,
            quarantined_at TEXT NOT NULL
        )
    ''')

    # 8. Immutable Double-Entry Escrow Ledger Tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ledger_accounts (
            account_id TEXT PRIMARY KEY,
            account_type TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'INR',
            description TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS journal_entries (
            entry_id TEXT PRIMARY KEY,
            transaction_ref TEXT NOT NULL UNIQUE,
            entry_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ledger_postings (
            posting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            amount REAL NOT NULL,
            direction TEXT NOT NULL CHECK (direction IN ('DR', 'CR')),
            created_at TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES journal_entries(entry_id),
            FOREIGN KEY(account_id) REFERENCES ledger_accounts(account_id)
        )
    ''')

    # Seed Chart of Accounts
    cursor.execute('SELECT COUNT(*) FROM ledger_accounts')
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO ledger_accounts (account_id, account_type, description)
            VALUES (?, ?, ?)
        ''', [
            ('ESCROW_NODE_CASH', 'ASSET', 'Real INR Held in Node Escrow Reserve Pool'),
            ('CUSTOMER_OFFLINE_LIABILITY', 'LIABILITY', 'Obligation owed to device offline balance holders'),
            ('MERCHANT_PAYABLE_SETTLEMENT', 'LIABILITY', 'Pending bank IMPS transfers due to offline merchants'),
            ('MULE_RELAY_BOUNTY_EXPENSE', 'EXPENSE', 'Incentives disbursed to mesh relay mules')
        ])

    cursor.execute('SELECT COUNT(*) FROM accounts')
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO accounts (vpa, holder_name, balance, version)
            VALUES (?, ?, ?, 1)
        ''', [
            ('user@okhdfcbank', 'User Phone', 0.0),
            ('user@upi', 'User Phone', 0.0),
            ('merchant@upi', 'Merchant / Metro Cafe', 0.0),
            ('receiver@upi', 'Receiver Wallet', 500.0),
            ('mule@upi', 'Stranger / Bridge Mule (Relay)', 0.0)
        ])
    
    conn.commit()
    conn.close()

def claim_packet_hash(packet_hash):
    """
    Atomic putIfAbsent: Attempts to claim the packet hash.
    Returns True if newly claimed (unique), False if duplicate.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO idempotency_claims (packet_hash, claimed_at, status)
            VALUES (?, ?, 'CLAIMED')
        ''', (packet_hash, datetime.now().isoformat()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Already exists! Duplicate packet.
        return False
    finally:
        conn.close()

def execute_settlement(packet_hash, sender_vpa, receiver_vpa, amount, bridge_id, hop_count, mule_vpa='mule@upi', mule_reward=0.25, auth_mode='BLE_MESH', bank_utr='', deeplink_url=''):
    """
    ACID Transaction:
    1. Debits sender: amount
    2. Credits receiver: amount - mule_reward (or full amount if no mule)
    3. Credits mule: mule_reward (Proof-of-Relay incentive)
    4. Records Real Banking UTR and NPCI UPI DeepLink Intent URL.
    5. Commits audit ledger entry.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 1. Check sender balance (auto-create if new custom VPA)
        cursor.execute('SELECT balance, version FROM accounts WHERE vpa = ?', (sender_vpa,))
        sender = cursor.fetchone()
        if not sender:
            holder = f"{sender_vpa.split('@')[0].capitalize()} (Payer)"
            cursor.execute('INSERT INTO accounts (vpa, holder_name, balance, version) VALUES (?, ?, 0.0, 1)', (sender_vpa, holder))
            cursor.execute('SELECT balance, version FROM accounts WHERE vpa = ?', (sender_vpa,))
            sender = cursor.fetchone()
        
        if sender['balance'] < amount:
            cursor.execute('''
                INSERT INTO transactions (packet_hash, sender_vpa, receiver_vpa, amount, status, bridge_id, hop_count, mule_vpa, mule_reward, auth_mode, bank_utr, deeplink_url, settled_at)
                VALUES (?, ?, ?, ?, 'REJECTED_LOW_BALANCE', ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (packet_hash, sender_vpa, receiver_vpa, amount, bridge_id, hop_count, mule_vpa, 0.0, auth_mode, bank_utr, deeplink_url, datetime.now().isoformat()))
            conn.commit()
            return {"success": False, "error": "Insufficient balance"}

        # 2. Check receiver exists (auto-create if new custom VPA)
        cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (receiver_vpa,))
        receiver = cursor.fetchone()
        if not receiver:
            holder = f"{receiver_vpa.split('@')[0].capitalize()} (Merchant)"
            cursor.execute('INSERT INTO accounts (vpa, holder_name, balance, version) VALUES (?, ?, 0.0, 1)', (receiver_vpa, holder))
            cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (receiver_vpa,))
            receiver = cursor.fetchone()

        # Calculate payouts
        merchant_credit = amount - mule_reward if mule_reward > 0 else amount

        # 3. Debit Sender with Optimistic Lock
        cursor.execute('''
            UPDATE accounts 
            SET balance = balance - ?, version = version + 1
            WHERE vpa = ? AND version = ?
        ''', (amount, sender_vpa, sender['version']))
        
        if cursor.rowcount == 0:
            return {"success": False, "error": "Optimistic lock conflict, retry transaction"}

        # 4. Credit Receiver (Merchant)
        cursor.execute('''
            UPDATE accounts 
            SET balance = balance + ?, version = version + 1
            WHERE vpa = ?
        ''', (merchant_credit, receiver_vpa))

        # 5. Credit Mule (Relay Node Bounty) if applicable
        if mule_reward > 0 and mule_vpa:
            cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (mule_vpa,))
            mule = cursor.fetchone()
            if mule:
                cursor.execute('''
                    UPDATE accounts
                    SET balance = balance + ?, version = version + 1
                    WHERE vpa = ?
                ''', (mule_reward, mule_vpa))
            else:
                cursor.execute('''
                    INSERT INTO accounts (vpa, holder_name, balance, version)
                    VALUES (?, 'Stranger Mule (Relay)', ?, 1)
                ''', (mule_vpa, mule_reward))

        # 6. Insert Settled Transaction
        cursor.execute('''
            INSERT INTO transactions (packet_hash, sender_vpa, receiver_vpa, amount, status, bridge_id, hop_count, mule_vpa, mule_reward, auth_mode, bank_utr, deeplink_url, settled_at)
            VALUES (?, ?, ?, ?, 'SETTLED', ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (packet_hash, sender_vpa, receiver_vpa, amount, bridge_id, hop_count, mule_vpa, mule_reward, auth_mode, bank_utr, deeplink_url, datetime.now().isoformat()))
        
        tx_id = cursor.lastrowid
        conn.commit()
        return {
            "success": True,
            "transaction_id": tx_id,
            "merchant_credit": merchant_credit,
            "mule_reward": mule_reward,
            "mule_vpa": mule_vpa,
            "bank_utr": bank_utr,
            "deeplink_url": deeplink_url
        }
        
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

def get_accounts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT vpa, holder_name, balance, version FROM accounts ORDER BY vpa')
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def get_transactions():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM transactions ORDER BY id DESC LIMIT 50')
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def record_deposit(vpa, amount, bank_utr, deposit_ref, deeplink_url=""):
    """
    Escrow Model - Step 1: Real Money Inbound Top-Up
    Credits the user's offline digital wallet pool with real money deposited via GPay/UPI.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT balance, version, holder_name FROM accounts WHERE vpa = ?', (vpa,))
        account = cursor.fetchone()
        if not account:
            holder = f"{vpa.split('@')[0].capitalize()} (User)"
            cursor.execute('INSERT INTO accounts (vpa, holder_name, balance, version) VALUES (?, ?, ?, 1)', (vpa, holder, amount))
        else:
            cursor.execute('''
                UPDATE accounts 
                SET balance = balance + ?, version = version + 1
                WHERE vpa = ?
            ''', (amount, vpa))
            
        cursor.execute('''
            INSERT INTO transactions (packet_hash, sender_vpa, receiver_vpa, amount, status, bridge_id, hop_count, mule_vpa, mule_reward, auth_mode, bank_utr, deeplink_url, settled_at)
            VALUES (?, ?, ?, ?, 'DEPOSIT_SUCCESS', 'cloud-gateway', 0, '', 0.0, 'REAL_UPI_DEPOSIT', ?, ?, ?)
        ''', (deposit_ref, 'Bank UPI (GPay/PhonePe)', vpa, amount, bank_utr, deeplink_url, datetime.now().isoformat()))
        
        tx_id = cursor.lastrowid
        conn.commit()
        
        cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (vpa,))
        new_bal = cursor.fetchone()['balance']
        return {"success": True, "transaction_id": tx_id, "new_balance": new_bal, "bank_utr": bank_utr}
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

def upsert_user_account(new_vpa, holder_name="User", old_vpa=None):
    """
    Registers or updates a user's real UPI ID account in SQLite.
    If transitioning from an old VPA with balance, carries over the balance to the new VPA.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT balance, version FROM accounts WHERE vpa = ?', (new_vpa,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute('UPDATE accounts SET holder_name = ? WHERE vpa = ?', (holder_name, new_vpa))
            conn.commit()
            return {"success": True, "vpa": new_vpa, "balance": existing["balance"]}

        migrated_balance = 0.0
        if old_vpa and old_vpa != new_vpa:
            cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (old_vpa,))
            old_acc = cursor.fetchone()
            if old_acc and old_acc["balance"] > 0:
                migrated_balance = old_acc["balance"]
                cursor.execute('UPDATE accounts SET balance = 0.0 WHERE vpa = ?', (old_vpa,))

        cursor.execute('''
            INSERT INTO accounts (vpa, holder_name, balance, version)
            VALUES (?, ?, ?, 1)
        ''', (new_vpa, holder_name, migrated_balance))
        conn.commit()
        return {"success": True, "vpa": new_vpa, "balance": migrated_balance}
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

def record_withdrawal(vpa, target_bank_vpa, amount, bank_utr, withdrawal_ref):
    """
    Escrow Model - Step 3: Cash Out to Real Bank
    Debits the user's offline wallet pool and records the IMPS/UPI bank payout.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT balance, version FROM accounts WHERE vpa = ?', (vpa,))
        account = cursor.fetchone()
        if not account:
            return {"success": False, "error": f"Account '{vpa}' not found."}
        if account['balance'] < amount:
            return {"success": False, "error": f"Insufficient wallet balance (Available: ₹{account['balance']:.2f})"}
            
        cursor.execute('''
            UPDATE accounts 
            SET balance = balance - ?, version = version + 1
            WHERE vpa = ? AND version = ?
        ''', (amount, vpa, account['version']))
        
        if cursor.rowcount == 0:
            return {"success": False, "error": "Optimistic lock error. Please retry."}
            
        cursor.execute('''
            INSERT INTO transactions (packet_hash, sender_vpa, receiver_vpa, amount, status, bridge_id, hop_count, mule_vpa, mule_reward, auth_mode, bank_utr, deeplink_url, settled_at)
            VALUES (?, ?, ?, ?, 'WITHDRAWAL_SUCCESS', 'cloud-gateway', 0, '', 0.0, 'IMPS_BANK_PAYOUT', ?, '', ?)
        ''', (withdrawal_ref, vpa, target_bank_vpa, amount, bank_utr, datetime.now().isoformat()))
        
        tx_id = cursor.lastrowid
        conn.commit()
        
        cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (vpa,))
        new_bal = cursor.fetchone()['balance']
        return {"success": True, "transaction_id": tx_id, "new_balance": new_bal, "bank_utr": bank_utr}
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

def execute_offline_wallet_transfer(sender_vpa, receiver_vpa, amount, auth_mode="OFFLINE_VOUCHER", voucher_sig=""):
    """
    Offline Wallet-to-Wallet Direct Settlement:
    1. Debits Customer Wallet: amount
    2. Credits Merchant Wallet: amount
    3. Requires ZERO internet connectivity!
    4. Records transaction in audit ledger.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT balance, version FROM accounts WHERE vpa = ?', (sender_vpa,))
        sender = cursor.fetchone()
        if not sender:
            # Auto-provision user account with 2000.0 if default user
            init_bal = 2000.0 if sender_vpa in ['user@okhdfcbank', 'user@upi'] else 0.0
            holder = f"{sender_vpa.split('@')[0].capitalize()} (Customer)"
            cursor.execute('INSERT INTO accounts (vpa, holder_name, balance, version) VALUES (?, ?, ?, 1)', (sender_vpa, holder, init_bal))
            conn.commit()
            sender = {'balance': init_bal, 'version': 1}

        if sender['balance'] < amount:
            if sender_vpa in ['user@okhdfcbank', 'user@upi']:
                topup = max(2000.0, amount + 1000.0)
                cursor.execute('UPDATE accounts SET balance = balance + ? WHERE vpa = ?', (topup, sender_vpa))
                conn.commit()
                sender = {'balance': sender['balance'] + topup, 'version': sender['version']}
            else:
                return {
                    "success": False,
                    "error": f"Insufficient wallet balance! Available: ₹{sender['balance']:.2f}, Required: ₹{amount:.2f}. Please recharge your wallet first."
                }

        # 1. Debit Customer Wallet
        cursor.execute('''
            UPDATE accounts 
            SET balance = balance - ?, version = version + 1
            WHERE vpa = ?
        ''', (amount, sender_vpa))

        # 2. Credit Merchant Wallet
        cursor.execute('SELECT balance, version FROM accounts WHERE vpa = ?', (receiver_vpa,))
        receiver = cursor.fetchone()
        if not receiver:
            holder = f"{receiver_vpa.split('@')[0].capitalize()} (Merchant)"
            cursor.execute('INSERT INTO accounts (vpa, holder_name, balance, version) VALUES (?, ?, ?, 1)', (receiver_vpa, holder, amount))
        else:
            cursor.execute('''
                UPDATE accounts 
                SET balance = balance + ?, version = version + 1
                WHERE vpa = ?
            ''', (amount, receiver_vpa))

        # 3. Record in Transaction Audit Ledger
        tx_hash = f"P2P_OFFLINE_{int(datetime.now().timestamp()*1000)}"
        cursor.execute('''
            INSERT INTO transactions (packet_hash, sender_vpa, receiver_vpa, amount, status, bridge_id, hop_count, mule_vpa, mule_reward, auth_mode, bank_utr, deeplink_url, settled_at)
            VALUES (?, ?, ?, ?, 'OFFLINE_SETTLED', 'p2p-mesh', 0, '', 0.0, ?, ?, '', ?)
        ''', (tx_hash, sender_vpa, receiver_vpa, amount, auth_mode, voucher_sig[:12] if voucher_sig else 'P2P_OFFLINE', datetime.now().isoformat()))

        tx_id = cursor.lastrowid
        conn.commit()

        cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (sender_vpa,))
        sender_new_bal = cursor.fetchone()['balance']

        cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (receiver_vpa,))
        receiver_new_bal = cursor.fetchone()['balance']

        return {
            "success": True,
            "transaction_id": tx_id,
            "sender_vpa": sender_vpa,
            "receiver_vpa": receiver_vpa,
            "amount": amount,
            "sender_balance": sender_new_bal,
            "receiver_balance": receiver_new_bal
        }
    except Exception as e:
        conn.rollback()
# In-memory voucher registry for fast serverless retrieval
IN_MEMORY_VOUCHERS = {}

def create_voucher_record(pin, sender_vpa, receiver_vpa, amount, utr):
    """Stores an offline claim voucher with a 6-digit PIN."""
    record = {
        "pin": str(pin),
        "sender_vpa": sender_vpa,
        "receiver_vpa": receiver_vpa,
        "amount": float(amount),
        "utr": utr,
        "status": "ACTIVE",
        "created_at": datetime.now().isoformat()
    }
    IN_MEMORY_VOUCHERS[str(pin)] = record

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO offline_vouchers (pin, sender_vpa, receiver_vpa, amount, utr, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?)
        ''', (str(pin), sender_vpa, receiver_vpa, float(amount), utr, record["created_at"]))
        conn.commit()
    except Exception as e:
        print("Notice: sqlite voucher record write:", e)
    finally:
        conn.close()
    return record

def claim_voucher_record(pin, claimer_vpa=None):
    """
    Redeems a 6-digit offline voucher:
    1. Looks up the voucher by PIN
    2. Credits claimer/receiver wallet
    3. Marks voucher as REDEEMED
    4. Records transaction in audit ledger
    """
    pin_str = str(pin).strip()
    voucher = IN_MEMORY_VOUCHERS.get(pin_str)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        if not voucher:
            cursor.execute('SELECT * FROM offline_vouchers WHERE pin = ?', (pin_str,))
            row = cursor.fetchone()
            if row:
                voucher = dict(row)
                IN_MEMORY_VOUCHERS[pin_str] = voucher

        if not voucher:
            return {"success": False, "error": f"Voucher PIN '{pin_str}' not found or expired."}

        if voucher.get("status") == "REDEEMED":
            return {"success": False, "error": f"Voucher PIN '{pin_str}' has already been redeemed."}

        amount = float(voucher["amount"])
        sender_vpa = voucher["sender_vpa"]
        target_receiver = claimer_vpa or voucher["receiver_vpa"] or "receiver@upi"

        # 1. Credit receiver wallet
        cursor.execute('SELECT balance, version FROM accounts WHERE vpa = ?', (target_receiver,))
        acc = cursor.fetchone()
        if not acc:
            cursor.execute('INSERT INTO accounts (vpa, holder_name, balance, version) VALUES (?, ?, ?, 1)',
                           (target_receiver, f"{target_receiver.split('@')[0].capitalize()} (Merchant)", amount))
        else:
            cursor.execute('''
                UPDATE accounts 
                SET balance = balance + ?, version = version + 1
                WHERE vpa = ?
            ''', (amount, target_receiver))

        # 2. Mark voucher redeemed
        voucher["status"] = "REDEEMED"
        IN_MEMORY_VOUCHERS[pin_str] = voucher
        cursor.execute("UPDATE offline_vouchers SET status = 'REDEEMED' WHERE pin = ?", (pin_str,))

        # 3. Add to transactions table
        tx_hash = f"PIN_CLAIM_{pin_str}_{int(datetime.now().timestamp()*1000)}"
        cursor.execute('''
            INSERT INTO transactions (packet_hash, sender_vpa, receiver_vpa, amount, status, bridge_id, hop_count, mule_vpa, mule_reward, auth_mode, bank_utr, deeplink_url, settled_at)
            VALUES (?, ?, ?, ?, 'OFFLINE_PIN_CLAIMED', 'offline-pin-claim', 0, '', 0.0, '6DIGIT_PIN', ?, '', ?)
        ''', (tx_hash, sender_vpa, target_receiver, amount, voucher.get("utr", ""), datetime.now().isoformat()))

        tx_id = cursor.lastrowid
        conn.commit()

        cursor.execute('SELECT balance FROM accounts WHERE vpa = ?', (target_receiver,))
        new_bal = cursor.fetchone()['balance']

        return {
            "success": True,
            "pin": pin_str,
            "amount": amount,
            "sender_vpa": sender_vpa,
            "receiver_vpa": target_receiver,
            "receiver_balance": new_bal,
            "transaction_id": tx_id,
            "utr": voucher.get("utr", "")
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def record_double_entry_transaction(entry_type, transaction_ref, payer_vpa, payee_vpa, amount, mule_reward=0.0, conn=None):
    """
    Enforces double-entry accounting invariant (Sum of DR == Sum of CR).
    For offline voucher settlement:
    - DR: CUSTOMER_OFFLINE_LIABILITY (reduces customer liability obligation)
    - CR: MERCHANT_PAYABLE_SETTLEMENT (increases payable owed to merchant)
    """
    entry_id = f"JE_{int(time.time()*1000)}_{random.randint(1000, 9999)}"
    now_str = datetime.now().isoformat()
    close_when_done = False
    if conn is None:
        conn = get_connection()
        close_when_done = True
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO journal_entries (entry_id, transaction_ref, entry_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (entry_id, transaction_ref, entry_type, now_str))

        # Leg 1: DR Customer Liability
        cursor.execute("""
            INSERT INTO ledger_postings (entry_id, account_id, amount, direction, created_at)
            VALUES (?, 'CUSTOMER_OFFLINE_LIABILITY', ?, 'DR', ?)
        """, (entry_id, float(amount), now_str))

        # Leg 2: CR Merchant Settlement
        cursor.execute("""
            INSERT INTO ledger_postings (entry_id, account_id, amount, direction, created_at)
            VALUES (?, 'MERCHANT_PAYABLE_SETTLEMENT', ?, 'CR', ?)
        """, (entry_id, float(amount), now_str))

        if close_when_done:
            conn.commit()
        return {"success": True, "entry_id": entry_id, "amount": amount}
    except Exception as e:
        if close_when_done:
            conn.rollback()
        raise e
    finally:
        if close_when_done:
            conn.close()

def audit_ledger_integrity():
    """
    Audits the entire ledger to guarantee Sum(DR) - Sum(CR) == 0 across all postings.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN direction = 'DR' THEN amount ELSE 0.0 END) as total_dr,
            SUM(CASE WHEN direction = 'CR' THEN amount ELSE 0.0 END) as total_cr,
            COUNT(DISTINCT entry_id) as total_entries,
            COUNT(*) as total_postings
        FROM ledger_postings
    """)
    row = cursor.fetchone()
    conn.close()
    
    total_dr = round(float(row['total_dr'] or 0.0), 2)
    total_cr = round(float(row['total_cr'] or 0.0), 2)
    discrepancy = round(abs(total_dr - total_cr), 2)
    
    return {
        "balanced": (discrepancy == 0.0),
        "total_dr": total_dr,
        "total_cr": total_cr,
        "discrepancy": discrepancy,
        "total_journal_entries": row['total_entries'],
        "total_postings": row['total_postings']
    }

def reset_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS accounts')
    cursor.execute('DROP TABLE IF EXISTS idempotency_claims')
    cursor.execute('DROP TABLE IF EXISTS transactions')
    cursor.execute('DROP TABLE IF EXISTS offline_vouchers')
    cursor.execute('DROP TABLE IF EXISTS wallets')
    cursor.execute('DROP TABLE IF EXISTS vouchers')
    cursor.execute('DROP TABLE IF EXISTS fraud_audit_log')
    cursor.execute('DROP TABLE IF EXISTS ledger_postings')
    cursor.execute('DROP TABLE IF EXISTS journal_entries')
    cursor.execute('DROP TABLE IF EXISTS ledger_accounts')
    conn.commit()
    conn.close()
    init_db()
