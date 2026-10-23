from src.db.connection import get_connection, get_db_type

def init_db():
    """
    Initializes database tables and default seed records.
    Adapts DDL syntax automatically for PostgreSQL or SQLite.
    """
    conn = get_connection()
    cursor = conn.cursor()
    db_type = get_db_type()
    
    # Primary Key Auto-Increment syntax
    pk_auto = "SERIAL PRIMARY KEY" if db_type == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real_type = "DOUBLE PRECISION" if db_type == "postgres" else "REAL"

    # 1. Accounts Table
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS accounts (
            vpa VARCHAR(255) PRIMARY KEY,
            holder_name VARCHAR(255) NOT NULL,
            balance {real_type} NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        )
    ''')

    # 2. Idempotency Claims Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS idempotency_claims (
            packet_hash VARCHAR(255) PRIMARY KEY,
            claimed_at VARCHAR(100) NOT NULL,
            status VARCHAR(50) NOT NULL
        )
    ''')

    # 3. Transaction Audit Ledger Table
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS transactions (
            id {pk_auto},
            packet_hash VARCHAR(255) NOT NULL,
            sender_vpa VARCHAR(255) NOT NULL,
            receiver_vpa VARCHAR(255) NOT NULL,
            amount {real_type} NOT NULL,
            status VARCHAR(50) NOT NULL,
            bridge_id VARCHAR(100) NOT NULL,
            hop_count INTEGER NOT NULL,
            mule_vpa VARCHAR(255) DEFAULT 'mule@upi',
            mule_reward {real_type} DEFAULT 0.0,
            auth_mode VARCHAR(50) DEFAULT 'BLE_MESH',
            bank_utr VARCHAR(100) DEFAULT '',
            deeplink_url TEXT DEFAULT '',
            settled_at VARCHAR(100) NOT NULL
        )
    ''')

    # 4. Offline Vouchers Table
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS offline_vouchers (
            pin VARCHAR(20) PRIMARY KEY,
            sender_vpa VARCHAR(255) NOT NULL,
            receiver_vpa VARCHAR(255) NOT NULL,
            amount {real_type} NOT NULL,
            utr VARCHAR(100) NOT NULL,
            status VARCHAR(50) NOT NULL,
            created_at VARCHAR(100) NOT NULL
        )
    ''')

    # 5. Production Wallets State Table
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS wallets (
            vpa VARCHAR(255) PRIMARY KEY,
            state VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
            current_seq INTEGER NOT NULL DEFAULT 0,
            last_hash VARCHAR(255) NOT NULL,
            escrow_balance {real_type} NOT NULL DEFAULT 2000.0,
            updated_at VARCHAR(100) NOT NULL
        )
    ''')

    # 6. Cryptographically Reconciled Vouchers Table
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS vouchers (
            id {pk_auto},
            payer_vpa VARCHAR(255) NOT NULL,
            payee_vpa VARCHAR(255) NOT NULL,
            seq_counter INTEGER NOT NULL,
            prev_hash VARCHAR(255) NOT NULL,
            current_hash VARCHAR(255) NOT NULL,
            amount {real_type} NOT NULL,
            status VARCHAR(50) NOT NULL,
            raw_sig TEXT NOT NULL,
            submitted_at VARCHAR(100) NOT NULL,
            bank_utr VARCHAR(100) NOT NULL
        )
    ''')

    # 7. Fraud Audit Trail Table
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS fraud_audit_log (
            id {pk_auto},
            vpa VARCHAR(255) NOT NULL,
            sequence_counter INTEGER NOT NULL,
            evidence_payload TEXT NOT NULL,
            quarantined_at VARCHAR(100) NOT NULL
        )
    ''')

    # 8. Immutable Double-Entry Escrow Ledger Tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ledger_accounts (
            account_id VARCHAR(100) PRIMARY KEY,
            account_type VARCHAR(50) NOT NULL,
            currency VARCHAR(10) NOT NULL DEFAULT 'INR',
            description TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS journal_entries (
            entry_id VARCHAR(100) PRIMARY KEY,
            transaction_ref VARCHAR(100) NOT NULL UNIQUE,
            entry_type VARCHAR(50) NOT NULL,
            created_at VARCHAR(100) NOT NULL
        )
    ''')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS ledger_postings (
            posting_id {pk_auto},
            entry_id VARCHAR(100) NOT NULL,
            account_id VARCHAR(100) NOT NULL,
            amount {real_type} NOT NULL,
            direction VARCHAR(10) NOT NULL CHECK (direction IN ('DR', 'CR')),
            created_at VARCHAR(100) NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES journal_entries(entry_id),
            FOREIGN KEY(account_id) REFERENCES ledger_accounts(account_id)
        )
    ''')

    # Seed Chart of Accounts
    cursor.execute('SELECT COUNT(*) FROM ledger_accounts')
    row = cursor.fetchone()
    count = row['count'] if isinstance(row, dict) and 'count' in row else (row[0] if row else 0)
    if count == 0:
        cursor.executemany('''
            INSERT INTO ledger_accounts (account_id, account_type, description)
            VALUES (?, ?, ?)
        ''', [
            ('ESCROW_NODE_CASH', 'ASSET', 'Real INR Held in Node Escrow Reserve Pool'),
            ('CUSTOMER_OFFLINE_LIABILITY', 'LIABILITY', 'Obligation owed to device offline balance holders'),
            ('MERCHANT_PAYABLE_SETTLEMENT', 'LIABILITY', 'Pending bank IMPS transfers due to offline merchants'),
            ('MULE_RELAY_BOUNTY_EXPENSE', 'EXPENSE', 'Incentives disbursed to mesh relay mules')
        ])

    # Seed Default Accounts
    cursor.execute('SELECT COUNT(*) FROM accounts')
    row = cursor.fetchone()
    count = row['count'] if isinstance(row, dict) and 'count' in row else (row[0] if row else 0)
    if count == 0:
        cursor.executemany('''
            INSERT INTO accounts (vpa, holder_name, balance, version)
            VALUES (?, ?, ?, 1)
        ''', [
            ('user@okhdfcbank', 'User Phone', 0.0),
            ('user@upi', 'User Phone', 2000.0),
            ('merchant@upi', 'Merchant / Metro Cafe', 0.0),
            ('receiver@upi', 'Receiver Wallet', 500.0),
            ('mule@upi', 'Stranger / Bridge Mule (Relay)', 0.0)
        ])

    conn.commit()
    conn.close()


def reset_db():
    """Drops and re-creates all tables (useful for test isolation)."""
    conn = get_connection()
    cursor = conn.cursor()
    tables = [
        'ledger_postings', 'journal_entries', 'ledger_accounts',
        'fraud_audit_log', 'vouchers', 'wallets', 'offline_vouchers',
        'transactions', 'idempotency_claims', 'accounts'
    ]
    for tbl in tables:
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE" if get_db_type() == 'postgres' else f"DROP TABLE IF EXISTS {tbl}")
        except Exception:
            pass
    conn.commit()
    conn.close()
    init_db()
