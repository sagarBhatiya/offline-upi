import json
import base64
import hashlib
import os
import time
from cryptography.hazmat.primitives.asymmetric import rsa, ec, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidSignature

class ServerCryptoEngine:
    """
    Central Banking Server Crypto Engine:
    - Generates & holds Server RSA-2048 keypair.
    - Exports Public Key for mobile devices to encrypt payments offline.
    - Decrypts hybrid packets (RSA-OAEP unwraps AES key, AES-GCM verifies 128-bit auth tag).
    """
    def __init__(self):
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        self._public_key = self._private_key.public_key()

    def get_public_key_pem(self) -> str:
        pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return pem.decode('utf-8')

    def encrypt_payment_instruction(self, instruction: dict) -> str:
        payload_bytes = json.dumps(instruction).encode('utf-8')

        # 1. Generate random 256-bit AES key and 96-bit nonce/IV
        aes_key = AESGCM.generate_key(bit_length=256)
        iv = os.urandom(12)

        # 2. Encrypt payload with AES-GCM (returns ciphertext + 16-byte auth tag)
        aesgcm = AESGCM(aes_key)
        encrypted_payload = aesgcm.encrypt(iv, payload_bytes, None)

        # 3. Encrypt AES key with Server's RSA Public Key (RSA-OAEP with SHA-256)
        wrapped_key = self._public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        packet_envelope = {
            "wrapped_key": base64.b64encode(wrapped_key).decode('utf-8'),
            "iv": base64.b64encode(iv).decode('utf-8'),
            "payload": base64.b64encode(encrypted_payload).decode('utf-8')
        }

        full_json = json.dumps(packet_envelope)
        return base64.b64encode(full_json.encode('utf-8')).decode('utf-8')

    def decrypt_payment_instruction(self, ciphertext_b64: str) -> dict:
        try:
            raw_json = base64.b64decode(ciphertext_b64.encode('utf-8')).decode('utf-8')
            envelope = json.loads(raw_json)

            wrapped_key = base64.b64decode(envelope["wrapped_key"])
            iv = base64.b64decode(envelope["iv"])
            encrypted_payload = base64.b64decode(envelope["payload"])

            aes_key = self._private_key.decrypt(
                wrapped_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )

            aesgcm = AESGCM(aes_key)
            decrypted_bytes = aesgcm.decrypt(iv, encrypted_payload, None)
            
            return json.loads(decrypted_bytes.decode('utf-8'))
        except Exception as e:
            raise ValueError(f"Decryption failed or packet tampered: {str(e)}")

class QrVoucherEngine:
    """
    Offline Dynamic QR Voucher Engine:
    - Generates ECDSA (P-256) signed vouchers for zero-friction camera scanning.
    - Provides instant offline verification on Merchant PoS devices without internet.
    - Uses deterministic canonical bytes to prevent float/int JSON serialization mismatches.
    """
    def __init__(self):
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self._public_key = self._private_key.public_key()

    def get_public_key_pem(self) -> str:
        pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return pem.decode('utf-8')

    @staticmethod
    def canonical_bytes(payload: dict) -> bytes:
        norm = {
            "payerVpa": str(payload.get("payerVpa", "")),
            "payeeVpa": str(payload.get("payeeVpa", "")),
            "amount": f"{float(payload.get('amount', 0.0)):.2f}",
            "nonce": int(payload.get("nonce", 0)),
            "bounty": f"{float(payload.get('bounty', 0.25)):.2f}",
            "signedAt": int(payload.get("signedAt", 0))
        }
        return json.dumps(norm, sort_keys=True).encode('utf-8')

    def create_signed_qr_voucher(self, payer_vpa: str, payee_vpa: str, amount: float, nonce: int, bounty: float = 0.25) -> dict:
        payload = {
            "payerVpa": str(payer_vpa),
            "payeeVpa": str(payee_vpa),
            "amount": float(amount),
            "nonce": int(nonce),
            "bounty": float(bounty),
            "signedAt": int(time.time() * 1000)
        }
        signature = self._private_key.sign(
            self.canonical_bytes(payload),
            ec.ECDSA(hashes.SHA256())
        )
        signature_hex = signature.hex()
        
        # Compact delimiter-separated format for ultra-fast, high-contrast camera recognition
        compact_qr = f"UPIOFFLINE:{payload['payerVpa']}|{payload['payeeVpa']}|{float(payload['amount']):.2f}|{payload['nonce']}|{float(payload['bounty']):.2f}|{payload['signedAt']}|{signature_hex}"

        return {
            "payload": payload,
            "signatureHex": signature_hex,
            "publicKeyPem": self.get_public_key_pem(),
            "rawQrPayload": compact_qr
        }

    def verify_qr_voucher(self, payload: dict, signature_hex: str, public_key_pem: str = None) -> bool:
        try:
            pub_key = self._public_key
            if public_key_pem:
                pub_key = serialization.load_pem_public_key(public_key_pem.encode('utf-8'))
            
            sig_bytes = bytes.fromhex(signature_hex)
            pub_key.verify(sig_bytes, self.canonical_bytes(payload), ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, Exception):
            return False

def compute_sha256(data_str: str) -> str:
    """Computes hexadecimal SHA-256 digest of ciphertext string."""
    return hashlib.sha256(data_str.encode('utf-8')).hexdigest()

# Singleton instances
crypto_engine = ServerCryptoEngine()
qr_voucher_engine = QrVoucherEngine()
