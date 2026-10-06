import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'upi.db')

def get_connection():
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
    
    # Seed initial accounts if empty
    cursor.execute('SELECT COUNT(*) FROM accounts')
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO accounts (vpa, holder_name, balance, version)
            VALUES (?, ?, ?, 1)
        ''', [
            ('user@okhdfcbank', 'User Phone', 0.0),
            ('user@upi', 'User Phone', 0.0),
            ('merchant@upi', 'Sharma Kirana / Metro Cafe', 0.0),
            ('sharma_kirana@paytm', 'Sharma Kirana Store', 0.0),
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
            # Auto-provision user account with 0 balance if new
            holder = f"{sender_vpa.split('@')[0].capitalize()} (Customer)"
            cursor.execute('INSERT INTO accounts (vpa, holder_name, balance, version) VALUES (?, ?, 0.0, 1)', (sender_vpa, holder))
            conn.commit()
            return {
                "success": False,
                "error": f"Your wallet balance is ₹0.00! Please recharge your wallet with Real UPI before paying."
            }

        if sender['balance'] < amount:
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
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

def reset_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS accounts')
    cursor.execute('DROP TABLE IF EXISTS idempotency_claims')
    cursor.execute('DROP TABLE IF EXISTS transactions')
    conn.commit()
    conn.close()
    init_db()
