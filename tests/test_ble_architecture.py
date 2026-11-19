import unittest
import json
import time
from src import create_app
from src.db.schema import reset_db
from src.db.repository import (
    get_account_by_vpa,
    upsert_user_account,
    get_transactions
)
from src.core.ble import (
    BleSecureSessionChannel,
    BlePaymentRadioManager,
    MAGIC_HEADER,
    MAX_CHUNK_DATA_SIZE,
    STANDARD_BLE_FINANCIAL_UUID
)

class BleArchitectureTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.app.app_context():
            reset_db()
            upsert_user_account("payer@okhdfcbank", holder_name="Payer User", initial_balance=2000.0)
            upsert_user_account("merchant@okhdfcbank", holder_name="Merchant Store", initial_balance=500.0)

    def tearDown(self):
        with self.app.app_context():
            reset_db()

    def test_1_ble_secure_session_ecdh_key_exchange(self):
        """Verifies X25519 ECDH key exchange and AES-256-GCM derivation between two BLE nodes."""
        node_payer = BleSecureSessionChannel()
        node_merchant = BleSecureSessionChannel()

        # Mutual Key Exchange
        node_payer.establish_session(node_merchant.public_key_bytes)
        node_merchant.establish_session(node_payer.public_key_bytes)

        self.assertIsNotNone(node_payer.session_key)
        self.assertIsNotNone(node_merchant.session_key)
        self.assertEqual(node_payer.session_key, node_merchant.session_key)

    def test_2_ble_chunk_fragmentation_crc32_and_reassembly(self):
        """Verifies frame fragmentation (480B chunks, 0xFA magic, CRC-32) and seamless decryption."""
        payer = BleSecureSessionChannel()
        merchant = BleSecureSessionChannel()
        payer.establish_session(merchant.public_key_bytes)
        merchant.establish_session(payer.public_key_bytes)

        # 1200 bytes test payload (requires 3 frames)
        large_instruction = json.dumps({
            "payer": "payer@okhdfcbank",
            "payee": "merchant@okhdfcbank",
            "amount": 250.0,
            "nonce": 42,
            "padding": "X" * 1000
        }).encode('utf-8')

        frames = payer.packetize(large_instruction, session_id=101)
        self.assertGreaterEqual(len(frames), 2)

        # Validate Magic Header & Length on all frames
        for frame in frames:
            self.assertEqual(frame[0], MAGIC_HEADER)
            self.assertGreaterEqual(len(frame), 14)

        # Reassemble on receiver
        recovered = merchant.reassemble(frames)
        self.assertEqual(recovered, large_instruction)
        recovered_obj = json.loads(recovered.decode('utf-8'))
        self.assertEqual(recovered_obj["amount"], 250.0)

    def test_3_ble_frame_tampering_rejection(self):
        """Verifies that tampering with even a single bit in a BLE frame causes immediate CRC-32 rejection."""
        payer = BleSecureSessionChannel()
        merchant = BleSecureSessionChannel()
        payer.establish_session(merchant.public_key_bytes)
        merchant.establish_session(payer.public_key_bytes)

        raw_payload = b"TRANSFER:payer@okhdfcbank:merchant@okhdfcbank:100.00"
        frames = payer.packetize(raw_payload, session_id=1)

        # Tamper byte in middle of first frame
        tampered_first = bytearray(frames[0])
        tampered_first[15] ^= 0xFF
        frames[0] = bytes(tampered_first)

        with self.assertRaises(ValueError) as ctx:
            merchant.reassemble(frames)
        self.assertIn("CRC-32 validation failed", str(ctx.exception))

    def test_4_ble_radio_manager_voucher_packet(self):
        """Verifies BlePaymentRadioManager packet generation and verification."""
        pkt = BlePaymentRadioManager.create_ble_voucher_packet(
            sender_vpa="payer@okhdfcbank",
            receiver_vpa="merchant@okhdfcbank",
            amount=175.50,
            pin_hash="test_pin",
            nonce=77
        )

        self.assertIn("voucherId", pkt)
        self.assertIn("frames", pkt)
        self.assertGreaterEqual(len(pkt["frames"]), 1)

        verified = BlePaymentRadioManager.verify_ble_voucher_packet(
            frames_hex=pkt["frames"],
            sender_vpa="payer@okhdfcbank",
            receiver_vpa="merchant@okhdfcbank",
            nonce=77
        )

        self.assertEqual(verified["amount"], 175.50)
        self.assertEqual(verified["senderVpa"], "payer@okhdfcbank")
        self.assertEqual(verified["receiverVpa"], "merchant@okhdfcbank")

    def test_5_ble_transfer_endpoint_and_balance_settlement(self):
        """Verifies POST /api/ble/transfer debits sender and credits receiver in double-entry database."""
        resp = self.client.post('/api/ble/transfer', json={
            "senderVpa": "payer@okhdfcbank",
            "receiverVpa": "merchant@okhdfcbank",
            "amount": 250.0,
            "clientBalance": 2000.0
        })

        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["amount"], 250.0)
        self.assertEqual(data["protocol"], "BLUETOOTH_BLE_P2P")
        self.assertTrue(len(data["bankUtr"]) >= 8)

        # Database Check: Payer Debited (2000 - 250 = 1750), Merchant Credited (500 + 250 = 750)
        payer_acc = get_account_by_vpa("payer@okhdfcbank")
        merch_acc = get_account_by_vpa("merchant@okhdfcbank")
        self.assertEqual(payer_acc["balance"], 1750.0)
        self.assertEqual(merch_acc["balance"], 750.0)

    def test_6_ble_offline_rbi_limit_500_enforcement(self):
        """Verifies that offline payments strictly enforce RBI ₹500 per transaction limit."""
        resp = self.client.post('/api/ble/transfer', json={
            "senderVpa": "payer@okhdfcbank",
            "receiverVpa": "merchant@okhdfcbank",
            "amount": 501.0,
            "clientBalance": 2000.0
        })

        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("exceeds RBI maximum offline limit", data["error"])

        # Balances untouched
        payer_acc = get_account_by_vpa("payer@okhdfcbank")
        self.assertEqual(payer_acc["balance"], 2000.0)

    def test_7_ble_nearby_devices_and_status(self):
        """Verifies status and nearby device discovery endpoints."""
        res_status = self.client.get('/api/ble/status')
        status_data = res_status.get_json()
        self.assertTrue(status_data["success"])
        self.assertEqual(status_data["serviceUuid"], STANDARD_BLE_FINANCIAL_UUID)
        self.assertEqual(status_data["mode"], "BLUETOOTH_BLE_P2P")

        res_devices = self.client.get('/api/ble/devices')
        dev_data = res_devices.get_json()
        self.assertTrue(dev_data["success"])
        self.assertGreaterEqual(len(dev_data["devices"]), 2)

    def test_8_ble_batch_sync(self):
        """Verifies syncing offline client vouchers."""
        resp = self.client.post('/api/ble/sync', json={
            "vouchers": [
                {
                    "voucherId": "vch_1",
                    "senderVpa": "payer@okhdfcbank",
                    "receiverVpa": "merchant@okhdfcbank",
                    "amount": 100.0
                }
            ]
        })
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["syncedCount"], 1)

if __name__ == '__main__':
    unittest.main()

