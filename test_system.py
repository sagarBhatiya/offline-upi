import unittest
import time
from app import app
from database import reset_db, get_accounts
from crypto_helper import crypto_engine, qr_voucher_engine

class OfflineUPITestCase(unittest.TestCase):
    def setUp(self):
        reset_db()
        self.client = app.test_client()

    def test_1_crypto_encryption_roundtrip(self):
        """Verifies that Hybrid RSA-OAEP + AES-GCM encryption & decryption works accurately."""
        instruction = {
            "senderVpa": "sagar@upi",
            "receiverVpa": "sunny@upi",
            "amount": 350.0,
            "pinHash": "testpin123",
            "nonce": "test-uuid-999",
            "bounty": 0.25,
            "authMode": "BLE_MESH",
            "signedAt": int(time.time() * 1000)
        }
        ciphertext = crypto_engine.encrypt_payment_instruction(instruction)
        self.assertIsNotNone(ciphertext)
        self.assertGreater(len(ciphertext), 200)

        decrypted = crypto_engine.decrypt_payment_instruction(ciphertext)
        self.assertEqual(decrypted["senderVpa"], "sagar@upi")
        self.assertEqual(decrypted["receiverVpa"], "sunny@upi")
        self.assertEqual(decrypted["amount"], 350.0)

    def test_2_tampered_ciphertext_is_rejected(self):
        """Verifies that tampering a single byte in the ciphertext causes immediate rejection."""
        instruction = {
            "senderVpa": "sagar@upi",
            "receiverVpa": "sunny@upi",
            "amount": 500.0,
            "pinHash": "testpin123",
            "nonce": "test-uuid-tamper",
            "bounty": 0.25,
            "authMode": "BLE_MESH",
            "signedAt": int(time.time() * 1000)
        }
        ciphertext = crypto_engine.encrypt_payment_instruction(instruction)
        
        # Tamper with byte
        mid = len(ciphertext) // 2
        char_flip = 'B' if ciphertext[mid] == 'A' else 'A'
        tampered_ciphertext = ciphertext[:mid] + char_flip + ciphertext[mid+1:]

        response = self.client.post('/api/bridge/ingest', json={
            "ciphertext": tampered_ciphertext,
            "bridgeId": "attacker-bridge",
            "hopCount": 2
        })
        data = response.get_json()
        self.assertEqual(data["outcome"], "INVALID")
        self.assertEqual(data["reason"], "decryption_failed_or_tampered")

    def test_3_idempotent_deduplication_exact_once_with_bounty(self):
        """Verifies multi-party settlement: Payer debited, Merchant credited, Mule paid bounty."""
        # Pre-load wallet via Real UPI Deposit
        self.client.post('/api/wallet/deposit/confirm', json={
            "vpa": "sagar@upi",
            "amount": 5000.0,
            "utr": "409812345678"
        })

        instruction = {
            "senderVpa": "sagar@upi",
            "receiverVpa": "merchant@upi",
            "amount": 400.0,
            "pinHash": "testpin123",
            "nonce": "test-uuid-duplicate",
            "bounty": 0.50,
            "authMode": "BLE_MESH",
            "signedAt": int(time.time() * 1000)
        }
        ciphertext = crypto_engine.encrypt_payment_instruction(instruction)

        # First Bridge Upload
        resp1 = self.client.post('/api/bridge/ingest', json={
            "ciphertext": ciphertext,
            "bridgeId": "bridge-alpha",
            "muleVpa": "mule@upi",
            "hopCount": 2
        })
        data1 = resp1.get_json()
        self.assertEqual(data1["outcome"], "SETTLED")
        self.assertEqual(data1["muleReward"], 0.50)

        # Second Bridge Upload (Duplicate packet)
        resp2 = self.client.post('/api/bridge/ingest', json={
            "ciphertext": ciphertext,
            "bridgeId": "bridge-beta",
            "muleVpa": "mule@upi",
            "hopCount": 3
        })
        data2 = resp2.get_json()
        self.assertEqual(data2["outcome"], "DUPLICATE_DROPPED")

        # Check balances:
        # sagar@upi initial 5000 deposited - 400 = 4600
        # merchant@upi initial 0 + (400 - 0.50) = 399.50
        # mule@upi initial 0 + 0.50 = 0.50
        accounts = {a["vpa"]: a["balance"] for a in get_accounts()}
        self.assertEqual(accounts["sagar@upi"], 4600.0)
        self.assertEqual(accounts["merchant@upi"], 399.50)
        self.assertEqual(accounts["mule@upi"], 0.50)

    def test_4_dynamic_qr_signing_and_offline_verification(self):
        """Tests that dynamic ECDSA P-256 QR vouchers are generated and verified offline."""
        voucher = qr_voucher_engine.create_signed_qr_voucher(
            payer_vpa="sagar@upi",
            payee_vpa="merchant@upi",
            amount=150.0,
            nonce=1055,
            bounty=0.25
        )
        self.assertIn("signatureHex", voucher)
        self.assertIn("payload", voucher)

        # Verify offline
        valid = qr_voucher_engine.verify_qr_voucher(
            voucher["payload"],
            voucher["signatureHex"],
            voucher["publicKeyPem"]
        )
        self.assertTrue(valid)

        # Tampered amount check
        tampered_payload = dict(voucher["payload"])
        tampered_payload["amount"] = 999.0
        invalid = qr_voucher_engine.verify_qr_voucher(
            tampered_payload,
            voucher["signatureHex"],
            voucher["publicKeyPem"]
        )
        self.assertFalse(invalid)

    def test_5_escrow_deposit_flow(self):
        """Verifies loading real money via UPI intent into the offline wallet pool."""
        # 1. Create deposit intent
        create_resp = self.client.post('/api/wallet/deposit/create', json={
            "vpa": "sagar@upi",
            "amount": 1000.0
        })
        cdata = create_resp.get_json()
        self.assertTrue(cdata["success"])
        self.assertIn("upi://pay", cdata["intent"]["deeplink"])

        # 2. Confirm deposit with 12-digit UTR
        conf_resp = self.client.post('/api/wallet/deposit/confirm', json={
            "vpa": "sagar@upi",
            "amount": 1000.0,
            "depositRef": cdata["intent"]["depositRef"],
            "deeplink": cdata["intent"]["deeplink"],
            "utr": "409812345678"
        })
        conf_data = conf_resp.get_json()
        self.assertTrue(conf_data["success"])
        self.assertEqual(conf_data["newBalance"], 1000.0) # 0.0 initial + 1000.0

        # Verify ledger
        accounts = {a["vpa"]: a["balance"] for a in get_accounts()}
        self.assertEqual(accounts["sagar@upi"], 1000.0)

    def test_6_escrow_withdrawal_flow(self):
        """Verifies withdrawing money from the offline wallet to a real bank UPI ID."""
        # Pre-deposit funds
        self.client.post('/api/wallet/deposit/confirm', json={
            "vpa": "sagar@upi",
            "amount": 5000.0,
            "utr": "409876543210"
        })

        # Withdraw 1500 to sagar@okhdfcbank
        wdr_resp = self.client.post('/api/wallet/withdraw', json={
            "vpa": "sagar@upi",
            "targetBankVpa": "sagar@okhdfcbank",
            "amount": 1500.0
        })
        wdata = wdr_resp.get_json()
        self.assertTrue(wdata["success"])
        self.assertEqual(wdata["newBalance"], 3500.0) # 5000 initial - 1500
        self.assertTrue(len(wdata["bankUtr"]) >= 12)

        # Verify insufficient balance error
        wdr_fail = self.client.post('/api/wallet/withdraw', json={
            "vpa": "sagar@upi",
            "targetBankVpa": "sagar@okhdfcbank",
            "amount": 99999.0
        })
        self.assertEqual(wdr_fail.status_code, 400)
        self.assertIn("Insufficient", wdr_fail.get_json()["error"])

    def test_7_offline_wallet_to_merchant_and_merchant_withdrawal(self):
        """Tests customer loads money, pays offline to merchant wallet, and merchant withdraws to bank."""
        # 1. Customer recharges wallet with 2000
        self.client.post('/api/wallet/deposit/confirm', json={
            "vpa": "customer@upi",
            "amount": 2000.0,
            "utr": "409899112233"
        })

        # 2. Customer generates offline QR voucher to pay merchant 500
        voucher = qr_voucher_engine.create_signed_qr_voucher(
            payer_vpa="customer@upi",
            payee_vpa="merchant@upi",
            amount=500.0,
            nonce=1099,
            bounty=0.25
        )

        # 3. Merchant verifies scan offline -> balance moves immediately from customer to merchant
        v_resp = self.client.post('/api/qr/verify-scan', json={"voucher": voucher})
        v_data = v_resp.get_json()
        self.assertTrue(v_data["success"])
        self.assertEqual(v_data["senderBalance"], 1500.0) # 2000 - 500
        self.assertEqual(v_data["receiverBalance"], 500.0)  # 0 + 500

        # 4. Merchant withdraws ₹500 to real bank UPI ID
        w_resp = self.client.post('/api/wallet/withdraw', json={
            "vpa": "merchant@upi",
            "targetBankVpa": "merchant_bank@icici",
            "amount": 500.0
        })
        w_data = w_resp.get_json()
        self.assertTrue(w_data["success"])
        self.assertEqual(w_data["newBalance"], 0.0)
        self.assertTrue(len(w_data["bankUtr"]) >= 12)

    def test_8_instant_wallet_deposit_and_auto_utr(self):
        """Tests instant 1-tap wallet deposit and auto-UTR generation without external bank failure."""
        # 1. Test 1-click instant deposit
        resp1 = self.client.post('/api/wallet/deposit/instant', json={
            "vpa": "instant_user@upi",
            "amount": 750.0
        })
        data1 = resp1.get_json()
        self.assertTrue(data1["success"])
        self.assertEqual(data1["newBalance"], 750.0)
        self.assertTrue(data1["bankUtr"].startswith("409"))
        self.assertEqual(len(data1["bankUtr"]), 12)

        # 2. Test auto-UTR deposit confirmation
        resp2 = self.client.post('/api/wallet/deposit/confirm', json={
            "vpa": "instant_user@upi",
            "amount": 250.0,
            "utr": "AUTO"
        })
        data2 = resp2.get_json()
        self.assertTrue(data2["success"])
        self.assertEqual(data2["newBalance"], 1000.0)
        self.assertEqual(len(data2["bankUtr"]), 12)

    def test_9_real_upi_id_profile_and_deposit(self):
        """Tests that entering a real UPI ID registers in SQLite and correctly receives deposit."""
        # Deposit to user@okhdfcbank
        self.client.post('/api/wallet/deposit/instant', json={
            "vpa": "user@okhdfcbank",
            "amount": 500.0
        })

        # User changes their handle to a real UPI ID (e.g. sagar@okhdfcbank)
        p_resp = self.client.post('/api/user/profile', json={
            "vpa": "sagar@okhdfcbank",
            "name": "Sagar Bhatiya",
            "oldVpa": "user@okhdfcbank"
        })
        p_data = p_resp.get_json()
        self.assertTrue(p_data["success"])
        # Balance migrated from old to new
        self.assertEqual(p_data["balance"], 500.0)

        # Deposit additional money directly into sagar@okhdfcbank
        d_resp = self.client.post('/api/wallet/deposit/instant', json={
            "vpa": "sagar@okhdfcbank",
            "amount": 300.0
        })
        d_data = d_resp.get_json()
        self.assertTrue(d_data["success"])
        self.assertEqual(d_data["newBalance"], 800.0)

    def test_10_voucher_pin_create_and_claim(self):
        """Verifies 6-digit offline voucher creation and receiver redemption."""
        # Create voucher
        create_resp = self.client.post('/api/voucher/create', json={
            "senderVpa": "user@okhdfcbank",
            "receiverVpa": "sharma_kirana@paytm",
            "amount": 150.0,
            "pin": "784219"
        })
        c_data = create_resp.get_json()
        self.assertTrue(c_data["success"])
        self.assertEqual(c_data["pin"], "784219")
        self.assertEqual(c_data["amount"], 150.0)

        # Claim voucher as merchant
        claim_resp = self.client.post('/api/voucher/claim', json={
            "pin": "784219",
            "receiverVpa": "sharma_kirana@paytm"
        })
        claim_data = claim_resp.get_json()
        self.assertTrue(claim_data["success"])
        self.assertEqual(claim_data["amount"], 150.0)
        self.assertGreaterEqual(claim_data["receiver_balance"], 150.0)

        # Attempt duplicate claim - must be rejected
        dup_resp = self.client.post('/api/voucher/claim', json={
            "pin": "784219",
            "receiverVpa": "sharma_kirana@paytm"
        })
        dup_data = dup_resp.get_json()
        self.assertFalse(dup_data["success"])
        self.assertIn("already been redeemed", dup_data["error"])

if __name__ == '__main__':
    unittest.main()
