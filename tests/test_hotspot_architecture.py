import unittest
import time
import json
import uuid
import socket
from src.core.hotspot_socket import (
    HotspotVoucherEngine,
    SocketSecuritySession,
    HotspotServerManager,
    HotspotClientManager,
    OfflinePaymentService,
    MAX_OFFLINE_TRANSACTION_LIMIT
)
from src.db.schema import reset_db
from src.db.repository import (
    get_account_by_vpa,
    record_offline_voucher,
    get_offline_voucher_by_id,
    get_pending_sync_vouchers,
    upsert_user_account,
    get_last_monotonic_nonce
)

class HotspotArchitectureTestCase(unittest.TestCase):
    """
    Automated Test Suite for Refactored Wi-Fi Hotspot Architecture:
    - Verifies TCP Socket Server (Receiver) & Client (Payer) communication
    - Validates KeyStore-backed ECDSA secp256r1 voucher integrity
    - Tests AES-GCM encrypted session framing
    - Enforces maximum ₹500 transaction limits
    - Proves monotonic sequence nonce replay protection
    - Validates Room/SQLite offline_vouchers state machine and cloud sync
    """
    def setUp(self):
        reset_db()
        upsert_user_account("customer@okhdfcbank", "Customer A", initial_balance=2000.0)
        upsert_user_account("merchant@okhdfcbank", "Merchant Cafe", initial_balance=500.0)

    def test_1_ecdsa_secp256r1_signature_and_canonical_integrity(self):
        """Verifies deterministic canonical JSON hashing & ECDSA secp256r1 signing/verification."""
        engine = HotspotVoucherEngine()
        voucher = engine.create_signed_voucher(
            sender_vpa="customer@okhdfcbank",
            receiver_vpa="merchant@okhdfcbank",
            amount=250.0,
            nonce=1
        )

        self.assertIn("voucherId", voucher)
        self.assertIn("signature", voucher)
        self.assertIn("senderPubKey", voucher)

        # 1. Valid Signature Check
        is_valid = HotspotVoucherEngine.verify_voucher_signature(voucher, voucher["senderPubKey"])
        self.assertTrue(is_valid, "Valid voucher signature must pass ECDSA verification.")

        # 2. Tampered Amount Check
        tampered_voucher = dict(voucher)
        tampered_voucher["amount"] = 350.0
        is_tampered_valid = HotspotVoucherEngine.verify_voucher_signature(tampered_voucher, voucher["senderPubKey"])
        self.assertFalse(is_tampered_valid, "Tampered voucher amount must fail signature verification.")

        # 3. Tampered Payee Check
        tampered_payee = dict(voucher)
        tampered_payee["receiverVpa"] = "hacker@upi"
        self.assertFalse(HotspotVoucherEngine.verify_voucher_signature(tampered_payee, voucher["senderPubKey"]))

    def test_2_aes_gcm_socket_session_framing(self):
        """Verifies ephemeral X25519 ECDH key exchange and AES-256-GCM authenticated encryption."""
        client_session = SocketSecuritySession()
        server_session = SocketSecuritySession()

        # Mutual key derivation
        client_session.derive_key(server_session.public_bytes)
        server_session.derive_key(client_session.public_bytes)

        self.assertIsNotNone(client_session.session_key)
        self.assertEqual(client_session.session_key, server_session.session_key)

        # Encrypt from Client
        test_payload = {"test": "OFFLINE_UPI_PAYMENT", "amount": 100.0}
        frame = client_session.encrypt_message(test_payload)
        self.assertGreater(len(frame), 32)

        # Decrypt on Server (stripping 4-byte length prefix)
        decrypted = server_session.decrypt_frame(frame[4:])
        self.assertEqual(decrypted["test"], "OFFLINE_UPI_PAYMENT")
        self.assertEqual(decrypted["amount"], 100.0)

    def test_3_hotspot_tcp_server_client_transfer_settlement(self):
        """
        Simulates end-to-end Wi-Fi Hotspot socket transfer:
        Device A (Receiver / 192.168.49.1:8899) spins up TCP socket server.
        Device B (Sender) connects, handshakes, transmits voucher, and settles offline.
        """
        test_port = 8899
        server = HotspotServerManager(
            receiver_vpa="merchant@okhdfcbank",
            port=test_port,
            host_ip="127.0.0.1"
        )
        server.start(bind_host="127.0.0.1")
        time.sleep(0.2)  # Allow socket bind

        try:
            # 1. Receiver generates on-screen QR JSON
            qr_payload = server.get_qr_connection_payload()
            self.assertEqual(qr_payload["port"], test_port)
            self.assertEqual(qr_payload["receiverVpa"], "merchant@okhdfcbank")
            self.assertTrue(qr_payload["ssid"].startswith("UPI_"))

            # 2. Sender connects via HotspotClientManager
            client = HotspotClientManager(sender_vpa="customer@okhdfcbank")
            transfer_res = client.send_payment(qr_payload, amount=200.0)

            self.assertTrue(transfer_res.get("success"), f"Transfer failed: {transfer_res.get('error')}")
            self.assertEqual(transfer_res.get("amount"), 200.0)
            self.assertIn("receiptId", transfer_res)

            # 3. Verify Database Balances: Customer Debited (2000 - 200 = 1800), Merchant Credited (500 + 200 = 700)
            cust_acc = get_account_by_vpa("customer@okhdfcbank")
            merch_acc = get_account_by_vpa("merchant@okhdfcbank")
            self.assertEqual(cust_acc["balance"], 1800.0)
            self.assertEqual(merch_acc["balance"], 700.0)

            # 4. Verify Room/SQLite offline_vouchers Table Record
            voucher_id = transfer_res["voucherId"]
            stored_voucher = get_offline_voucher_by_id(voucher_id)
            self.assertIsNotNone(stored_voucher)
            self.assertEqual(stored_voucher["amount"], 200.0)

        finally:
            server.stop()

    def test_4_maximum_offline_limit_500_enforcement(self):
        """Verifies that offline payments strictly enforce the ₹500 transaction cap."""
        test_port = 8898
        server = HotspotServerManager(
            receiver_vpa="merchant@okhdfcbank",
            port=test_port,
            host_ip="127.0.0.1"
        )
        server.start(bind_host="127.0.0.1")
        time.sleep(0.2)

        try:
            qr_payload = server.get_qr_connection_payload()
            client = HotspotClientManager(sender_vpa="customer@okhdfcbank")

            # Attempt to pay ₹501 (exceeds ₹500 limit)
            res = client.send_payment(qr_payload, amount=501.0)
            self.assertFalse(res["success"])
            self.assertIn("exceeds maximum offline limit", res["error"])

            # Verify balance untouched
            cust_acc = get_account_by_vpa("customer@okhdfcbank")
            self.assertEqual(cust_acc["balance"], 2000.0)

        finally:
            server.stop()

    def test_5_monotonic_sequence_nonce_replay_attack_prevention(self):
        """Verifies that replaying a previously submitted nonce is detected and quarantined."""
        test_port = 8897
        server = HotspotServerManager(
            receiver_vpa="merchant@okhdfcbank",
            port=test_port,
            host_ip="127.0.0.1"
        )
        server.start(bind_host="127.0.0.1")
        time.sleep(0.2)

        try:
            qr_payload = server.get_qr_connection_payload()
            client = HotspotClientManager(sender_vpa="customer@okhdfcbank")

            # 1. First spend (Nonce = 1) -> Success
            res1 = client.send_payment(qr_payload, amount=100.0)
            self.assertTrue(res1["success"])

            # 2. Construct duplicate spend reusing the same or lower nonce
            replayed_voucher = client.voucher_engine.create_signed_voucher(
                sender_vpa="customer@okhdfcbank",
                receiver_vpa="merchant@okhdfcbank",
                amount=50.0,
                nonce=1 # REPLAY ATTACK! Nonce <= last_nonce
            )

            # Process directly against server verification
            res_replay = server._process_and_settle_voucher(replayed_voucher)
            self.assertEqual(res_replay["status"], "REJECTED_REPLAY")
            self.assertIn("replayed", res_replay["error"])

            # Verify quarantined in database
            quarantined = get_offline_voucher_by_id(replayed_voucher["voucherId"])
            self.assertIsNotNone(quarantined)
            self.assertEqual(quarantined["status"], "QUARANTINED")

        finally:
            server.stop()

    def test_6_background_workmanager_cloud_sync_simulation(self):
        """Verifies offline voucher state machine and background cloud reconciliation."""
        voucher_id = str(uuid.uuid4())
        record_offline_voucher(
            voucher_id=voucher_id,
            voucher_type="CREDIT",
            amount=150.0,
            status="PENDING_SYNC",
            raw_payload="{}",
            sender_vpa="customer@okhdfcbank",
            receiver_vpa="merchant@okhdfcbank"
        )

        pending = get_pending_sync_vouchers()
        self.assertTrue(any(v["voucher_id"] == voucher_id for v in pending))

        # Trigger WorkManager sync
        sync_res = OfflinePaymentService.sync_pending_vouchers_to_cloud()
        self.assertTrue(sync_res["success"])
        self.assertGreaterEqual(sync_res["syncedCount"], 1)

        # Voucher must now be COMPLETED with synced_at timestamp
        synced = get_offline_voucher_by_id(voucher_id)
        self.assertEqual(synced["status"], "COMPLETED")
        self.assertTrue(len(synced["synced_at"]) > 0)


if __name__ == '__main__':
    unittest.main()

