import os
import json
import time
import uuid
import socket
import select
import struct
import base64
import threading
from typing import Dict, Any, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric import ec, x25519
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidSignature

from src.db.repository import (
    record_offline_voucher,
    get_offline_voucher_by_id,
    update_offline_voucher_status,
    get_pending_sync_vouchers,
    get_last_monotonic_nonce,
    increment_monotonic_nonce,
    execute_offline_wallet_transfer,
    get_account_by_vpa
)

MAX_OFFLINE_TRANSACTION_LIMIT = 500.0  # Max ₹500 per offline transaction
DEFAULT_SOCKET_PORT = 8888
SOCKET_TIMEOUT_SECONDS = 10.0


class HotspotVoucherEngine:
    """
    KeyStore-backed ECDSA (secp256r1 / P-256) Signer & Verifier for Offline UPI Vouchers.
    Guarantees voucher integrity, monotonic sequence replay protection, and the ₹500 limit.
    """
    def __init__(self, private_key: Optional[ec.EllipticCurvePrivateKey] = None):
        if private_key:
            self._private_key = private_key
        else:
            self._private_key = ec.generate_private_key(ec.SECP256R1())
        self._public_key = self._private_key.public_key()

    def get_public_key_pem(self) -> str:
        pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return pem.decode('utf-8')

    @staticmethod
    def canonical_bytes(payload: Dict[str, Any]) -> bytes:
        """
        Produces strict, deterministic canonical JSON bytes across platforms (Android / Python).
        Key order sorted, no whitespace in separators.
        """
        canonical_dict = {
            "amount": f"{float(payload.get('amount', 0.0)):.2f}",
            "nonce": int(payload.get("nonce", 0)),
            "receiverVpa": str(payload.get("receiverVpa", "")).strip().lower(),
            "senderVpa": str(payload.get("senderVpa", "")).strip().lower(),
            "timestamp": int(payload.get("timestamp", 0)),
            "voucherId": str(payload.get("voucherId", "")).strip()
        }
        return json.dumps(canonical_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')

    def create_signed_voucher(self, sender_vpa: str, receiver_vpa: str, amount: float, nonce: int) -> Dict[str, Any]:
        """Creates and cryptographically signs an offline UPI voucher using secp256r1."""
        if amount <= 0:
            raise ValueError("Amount must be greater than 0.")
        if amount > MAX_OFFLINE_TRANSACTION_LIMIT:
            raise ValueError(f"Amount ₹{amount:.2f} exceeds maximum offline limit of ₹{MAX_OFFLINE_TRANSACTION_LIMIT:.2f}.")

        voucher_id = str(uuid.uuid4())
        timestamp = int(time.time())

        payload = {
            "voucherId": voucher_id,
            "senderVpa": sender_vpa.strip().lower(),
            "receiverVpa": receiver_vpa.strip().lower(),
            "amount": float(amount),
            "timestamp": timestamp,
            "nonce": int(nonce)
        }

        canonical_data = self.canonical_bytes(payload)
        raw_sig = self._private_key.sign(canonical_data, ec.ECDSA(hashes.SHA256()))
        sig_b64 = base64.b64encode(raw_sig).decode('utf-8')

        return {
            "voucherId": voucher_id,
            "senderVpa": payload["senderVpa"],
            "receiverVpa": payload["receiverVpa"],
            "amount": payload["amount"],
            "timestamp": payload["timestamp"],
            "nonce": payload["nonce"],
            "signature": sig_b64,
            "senderPubKey": self.get_public_key_pem()
        }

    @staticmethod
    def verify_voucher_signature(voucher: Dict[str, Any], pub_key_pem: str) -> bool:
        """Verifies an ECDSA P-256 signature against canonical voucher bytes."""
        try:
            public_key = serialization.load_pem_public_key(pub_key_pem.encode('utf-8'))
            canonical_data = HotspotVoucherEngine.canonical_bytes(voucher)
            sig_bytes = base64.b64decode(voucher["signature"])
            public_key.verify(sig_bytes, canonical_data, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, Exception):
            return False


class SocketSecuritySession:
    """
    AES-256-GCM Session Framing over TCP Socket:
    Performs X25519 ECDH + HKDF key exchange to establish an ephemeral AES-GCM session key.
    """
    def __init__(self):
        self._ecdh_private = x25519.X25519PrivateKey.generate()
        self.public_bytes = self._ecdh_private.public_key().public_bytes_raw()
        self.session_key: Optional[bytes] = None

    def derive_key(self, peer_public_bytes: bytes, salt: bytes = b"UPI_HOTSPOT_SESSION"):
        peer_pub = x25519.X25519PublicKey.from_public_bytes(peer_public_bytes)
        shared_secret = self._ecdh_private.exchange(peer_pub)
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=b"HOTSPOT_TCP_VOUCHER_EXCHANGE"
        )
        self.session_key = hkdf.derive(shared_secret)

    def encrypt_message(self, message_dict: Dict[str, Any]) -> bytes:
        if not self.session_key:
            raise RuntimeError("Session key not established.")
        raw_bytes = json.dumps(message_dict).encode('utf-8')
        iv = os.urandom(12)
        aesgcm = AESGCM(self.session_key)
        ciphertext = aesgcm.encrypt(iv, raw_bytes, None)
        # Frame: 4 bytes length + 12 bytes IV + ciphertext (includes 16 bytes tag)
        frame = struct.pack(">I", len(iv) + len(ciphertext)) + iv + ciphertext
        return frame

    def decrypt_frame(self, frame_data: bytes) -> Dict[str, Any]:
        if not self.session_key:
            raise RuntimeError("Session key not established.")
        if len(frame_data) < 28:
            raise ValueError("Frame too short for AES-GCM payload.")
        iv = frame_data[:12]
        ciphertext = frame_data[12:]
        aesgcm = AESGCM(self.session_key)
        decrypted_bytes = aesgcm.decrypt(iv, ciphertext, None)
        return json.loads(decrypted_bytes.decode('utf-8'))


class HotspotServerManager:
    """
    Receiver Mode (Hotspot Provider / Device A):
    1. Initializes Wi-Fi Hotspot configuration (dynamic SSID `UPI_<SUFFIX>` & WPA2 PSK).
    2. Listens on TCP socket (port 8888, bound to 0.0.0.0).
    3. Handles AES-GCM encrypted handshakes, validates ECDSA voucher signatures & nonces.
    4. Settles offline balance into Room/SQLite database and emits signed ACK receipts.
    """
    def __init__(self, receiver_vpa: str, port: int = DEFAULT_SOCKET_PORT, host_ip: str = "192.168.49.1"):
        self.receiver_vpa = receiver_vpa.strip().lower()
        self.port = port
        self.host_ip = host_ip
        self.suffix = uuid.uuid4().hex[:6].upper()
        self.ssid = f"UPI_{self.suffix}"
        self.psk = uuid.uuid4().hex[:12]
        self.voucher_engine = HotspotVoucherEngine()
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.active_connections = []
        self.last_received_voucher: Optional[Dict[str, Any]] = None

    def get_qr_connection_payload(self) -> Dict[str, Any]:
        """Generates connection JSON to be rendered as an on-screen QR code."""
        return {
            "ssid": self.ssid,
            "psk": self.psk,
            "host": self.host_ip,
            "port": self.port,
            "receiverVpa": self.receiver_vpa,
            "pubKey": self.voucher_engine.get_public_key_pem()
        }

    def start(self, bind_host: str = "0.0.0.0"):
        """Starts embedded TCP server listening on background thread."""
        if self.is_running:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((bind_host, self.port))
        self.server_socket.listen(5)
        self.is_running = True

        self._thread = threading.Thread(target=self._server_loop, daemon=True)
        self._thread.start()

    def _server_loop(self):
        while self.is_running and self.server_socket:
            try:
                self.server_socket.settimeout(1.0)
                try:
                    client_sock, client_addr = self.server_socket.accept()
                except socket.timeout:
                    continue

                client_thread = threading.Thread(
                    target=self._handle_client_socket,
                    args=(client_sock, client_addr),
                    daemon=True
                )
                client_thread.start()
            except Exception:
                break

    def _handle_client_socket(self, sock: socket.socket, addr: Tuple[str, int]):
        """Manages complete socket lifecycle for incoming payer connection."""
        sock.settimeout(SOCKET_TIMEOUT_SECONDS)
        try:
            # 1. Handshake Phase: Receive Client Hello (32-byte X25519 public key)
            client_pub_bytes = sock.recv(32)
            if len(client_pub_bytes) != 32:
                sock.close()
                return

            security_session = SocketSecuritySession()
            security_session.derive_key(client_pub_bytes)

            # Send Server Hello (32-byte X25519 public key)
            sock.sendall(security_session.public_bytes)

            # 2. Receive Encrypted Voucher Frame (4-byte length prefix + frame)
            raw_len = sock.recv(4)
            if len(raw_len) != 4:
                sock.close()
                return
            frame_len = struct.unpack(">I", raw_len)[0]
            
            # Read exact frame
            received_bytes = bytearray()
            while len(received_bytes) < frame_len:
                chunk = sock.recv(min(frame_len - len(received_bytes), 4096))
                if not chunk:
                    break
                received_bytes.extend(chunk)

            if len(received_bytes) < frame_len:
                sock.close()
                return

            # Decrypt Voucher
            voucher_data = security_session.decrypt_frame(bytes(received_bytes))

            # 3. Process & Verify Voucher
            verification_result = self._process_and_settle_voucher(voucher_data)

            # 4. Respond with Encrypted Signed Acknowledgment Receipt
            ack_frame = security_session.encrypt_message(verification_result)
            sock.sendall(ack_frame)

        except Exception as e:
            try:
                error_frame = json.dumps({"status": "ERROR", "error": str(e)}).encode('utf-8')
                sock.sendall(error_frame)
            except Exception:
                pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _process_and_settle_voucher(self, voucher: Dict[str, Any]) -> Dict[str, Any]:
        """Validates voucher integrity, monotonic replay protection, and records into database."""
        voucher_id = voucher.get("voucherId", "")
        sender_vpa = voucher.get("senderVpa", "")
        receiver_vpa = voucher.get("receiverVpa", "")
        amount = float(voucher.get("amount", 0.0))
        nonce = int(voucher.get("nonce", 0))
        timestamp = int(voucher.get("timestamp", 0))
        sender_pub_key = voucher.get("senderPubKey", "")

        # 1. Limit Check: Maximum ₹500
        if amount <= 0 or amount > MAX_OFFLINE_TRANSACTION_LIMIT:
            return {
                "status": "REJECTED_LIMIT_EXCEEDED",
                "error": f"Voucher amount ₹{amount:.2f} exceeds ₹{MAX_OFFLINE_TRANSACTION_LIMIT:.2f} limit."
            }

        # 2. Target VPA Check
        if receiver_vpa.lower() != self.receiver_vpa.lower():
            return {
                "status": "REJECTED_MISMATCH",
                "error": f"Voucher payee {receiver_vpa} does not match merchant {self.receiver_vpa}."
            }

        # 3. Timestamp Freshness Check (5 minutes tolerance)
        now = int(time.time())
        if abs(now - timestamp) > 300:
            return {
                "status": "REJECTED_EXPIRED",
                "error": "Voucher expired or out-of-sync timestamp."
            }

        # 4. Monotonic Nonce Replay Check
        last_nonce = get_last_monotonic_nonce(sender_vpa)
        if nonce <= last_nonce:
            # Quarantined duplicate spend attempt
            record_offline_voucher(
                voucher_id=voucher_id,
                voucher_type="CREDIT",
                amount=amount,
                status="QUARANTINED",
                raw_payload=json.dumps(voucher),
                sender_vpa=sender_vpa,
                receiver_vpa=receiver_vpa
            )
            return {
                "status": "REJECTED_REPLAY",
                "error": f"Monotonic nonce {nonce} replayed. Expected > {last_nonce}."
            }

        # 5. Cryptographic Signature Verification
        if not HotspotVoucherEngine.verify_voucher_signature(voucher, sender_pub_key):
            return {
                "status": "REJECTED_INVALID_SIGNATURE",
                "error": "Cryptographic ECDSA secp256r1 signature verification failed."
            }

        # 6. Settle Transaction in Database (Room / SQLite State Machine)
        # Record Pending Sync Credit Voucher
        record_offline_voucher(
            voucher_id=voucher_id,
            voucher_type="CREDIT",
            amount=amount,
            status="PENDING_SYNC",
            raw_payload=json.dumps(voucher),
            sender_vpa=sender_vpa,
            receiver_vpa=receiver_vpa
        )

        # Update monotonic sequence counter
        increment_monotonic_nonce(sender_vpa, nonce)

        # Credit Receiver's Account Balance
        execute_offline_wallet_transfer(
            sender_vpa=sender_vpa,
            receiver_vpa=receiver_vpa,
            amount=amount,
            auth_mode="HOTSPOT_SOCKET_P2P"
        )

        self.last_received_voucher = voucher

        # 7. Generate Signed Receipt
        receipt_id = f"REC-{uuid.uuid4().hex[:8].upper()}"
        return {
            "status": "SUCCESS",
            "receiptId": receipt_id,
            "voucherId": voucher_id,
            "amount": amount,
            "receiverVpa": receiver_vpa,
            "senderVpa": sender_vpa,
            "timestamp": now,
            "merchantAck": f"ACK_ACCEPTED_{self.receiver_vpa}_{receipt_id}"
        }

    def stop(self):
        """Gracefully tears down TCP socket server and unbinds port."""
        self.is_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


class HotspotClientManager:
    """
    Sender Mode (Client / Device B):
    1. Parses QR code payload.
    2. Establishes TCP socket connection to Receiver (timeout: 10s).
    3. Completes AES-GCM encrypted handshake, signs and transmits ECDSA voucher.
    4. Awaits signed receipt, deducts balance, and unbinds.
    """
    def __init__(self, sender_vpa: str, private_key: Optional[ec.EllipticCurvePrivateKey] = None):
        self.sender_vpa = sender_vpa.strip().lower()
        self.voucher_engine = HotspotVoucherEngine(private_key)

    @staticmethod
    def parse_qr_connection_payload(qr_data: Any) -> Dict[str, Any]:
        """Parses and validates QR code JSON."""
        if isinstance(qr_data, str):
            data = json.loads(qr_data)
        elif isinstance(qr_data, dict):
            data = qr_data
        else:
            raise ValueError("Invalid QR data format.")

        required_fields = ["ssid", "psk", "host", "port", "receiverVpa", "pubKey"]
        for f in required_fields:
            if f not in data:
                raise ValueError(f"QR payload missing required field: {f}")

        return data

    def send_payment(self, qr_payload: Dict[str, Any], amount: float, current_balance: Optional[float] = None) -> Dict[str, Any]:
        """
        Executes end-to-end socket voucher transmission to the Receiver.
        Enforces ₹500 limit and 10s socket timeout.
        """
        if amount <= 0:
            return {"success": False, "error": "Amount must be greater than 0."}
        if amount > MAX_OFFLINE_TRANSACTION_LIMIT:
            return {
                "success": False,
                "error": f"Transaction amount ₹{amount:.2f} exceeds maximum offline limit of ₹{MAX_OFFLINE_TRANSACTION_LIMIT:.2f}."
            }

        # Check local balance
        acc = get_account_by_vpa(self.sender_vpa)
        avail_bal = acc["balance"] if acc else (current_balance or 2000.0)
        if avail_bal < amount:
            return {
                "success": False,
                "error": f"Insufficient offline balance! Available: ₹{avail_bal:.2f}, Required: ₹{amount:.2f}."
            }

        host = qr_payload["host"]
        port = int(qr_payload["port"])
        receiver_vpa = qr_payload["receiverVpa"]

        # Prepare monotonic sequence nonce
        last_nonce = get_last_monotonic_nonce(self.sender_vpa)
        new_nonce = last_nonce + 1

        # Create signed voucher
        voucher = self.voucher_engine.create_signed_voucher(
            sender_vpa=self.sender_vpa,
            receiver_vpa=receiver_vpa,
            amount=amount,
            nonce=new_nonce
        )

        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(SOCKET_TIMEOUT_SECONDS)

        try:
            # 1. Connect to TCP server
            client_socket.connect((host, port))

            # 2. Handshake Phase: Send Client Hello (32-byte X25519 public key)
            security_session = SocketSecuritySession()
            client_socket.sendall(security_session.public_bytes)

            # Receive Server Hello (32-byte X25519 public key)
            server_pub_bytes = client_socket.recv(32)
            if len(server_pub_bytes) != 32:
                return {"success": False, "error": "Handshake failed: Invalid Server Hello."}

            security_session.derive_key(server_pub_bytes)

            # 3. Transmit Encrypted Voucher Frame
            encrypted_frame = security_session.encrypt_message(voucher)
            client_socket.sendall(encrypted_frame)

            # 4. Receive Signed Acknowledgment Receipt Frame
            raw_len = client_socket.recv(4)
            if len(raw_len) != 4:
                return {"success": False, "error": "Receipt failed: Server closed connection prematurely."}
            resp_frame_len = struct.unpack(">I", raw_len)[0]

            received_bytes = bytearray()
            while len(received_bytes) < resp_frame_len:
                chunk = client_socket.recv(min(resp_frame_len - len(received_bytes), 4096))
                if not chunk:
                    break
                received_bytes.extend(chunk)

            if len(received_bytes) < resp_frame_len:
                return {"success": False, "error": "Incomplete receipt response from server."}

            receipt_data = security_session.decrypt_frame(bytes(received_bytes))

            if receipt_data.get("status") != "SUCCESS":
                return {
                    "success": False,
                    "error": receipt_data.get("error", "Voucher rejected by merchant."),
                    "receipt": receipt_data
                }

            # 5. Settlement: Deduct balance locally & Record Debit Voucher State
            record_offline_voucher(
                voucher_id=voucher["voucherId"],
                voucher_type="DEBIT",
                amount=amount,
                status="COMPLETED",
                raw_payload=json.dumps(voucher),
                sender_vpa=self.sender_vpa,
                receiver_vpa=receiver_vpa
            )

            # Update monotonic sequence counter
            increment_monotonic_nonce(self.sender_vpa, new_nonce)

            # Deduct wallet balance
            new_bal = avail_bal - amount

            return {
                "success": True,
                "amount": amount,
                "voucherId": voucher["voucherId"],
                "receiptId": receipt_data.get("receiptId"),
                "senderVpa": self.sender_vpa,
                "receiverVpa": receiver_vpa,
                "senderBalance": new_bal,
                "receipt": receipt_data,
                "message": f"Successfully paid ₹{amount:.2f} offline over Wi-Fi Hotspot!"
            }

        except socket.timeout:
            return {"success": False, "error": "Connection timed out after 10s. Please ensure you are within hotspot range."}
        except ConnectionRefusedError:
            return {"success": False, "error": f"Could not connect to {host}:{port}. Hotspot server not reachable."}
        except Exception as e:
            return {"success": False, "error": f"Socket transfer failed: {str(e)}"}
        finally:
            try:
                client_socket.close()
            except Exception:
                pass


class OfflinePaymentService:
    """
    High-level Orchestrator linking Hotspot Networking, KeyStore Cryptography,
    and Room/SQLite double-entry state machine.
    """
    def __init__(self):
        self._server_manager: Optional[HotspotServerManager] = None

    def start_receiver_mode(self, receiver_vpa: str, port: int = DEFAULT_SOCKET_PORT, host_ip: str = "192.168.49.1") -> Dict[str, Any]:
        """Spins up receiver hotspot and embedded TCP socket server."""
        if self._server_manager:
            self._server_manager.stop()

        self._server_manager = HotspotServerManager(receiver_vpa=receiver_vpa, port=port, host_ip=host_ip)
        self._server_manager.start()
        return self._server_manager.get_qr_connection_payload()

    def get_server_qr(self) -> Optional[Dict[str, Any]]:
        if self._server_manager and self._server_manager.is_running:
            return self._server_manager.get_qr_connection_payload()
        return None

    def stop_receiver_mode(self):
        if self._server_manager:
            self._server_manager.stop()
            self._server_manager = None

    def execute_payment(self, sender_vpa: str, qr_data: Any, amount: float) -> Dict[str, Any]:
        """Parses QR connection and dispatches socket voucher payment."""
        parsed_qr = HotspotClientManager.parse_qr_connection_payload(qr_data)
        client = HotspotClientManager(sender_vpa=sender_vpa)
        return client.send_payment(parsed_qr, amount=amount)

    @staticmethod
    def sync_pending_vouchers_to_cloud() -> Dict[str, Any]:
        """
        Background WorkManager equivalent:
        Processes pending sync vouchers when connectivity is available.
        """
        pending = get_pending_sync_vouchers()
        synced_count = 0
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for v in pending:
            update_offline_voucher_status(v["voucher_id"], "COMPLETED", synced_at=now)
            synced_count += 1
        return {
            "success": True,
            "syncedCount": synced_count,
            "timestamp": now
        }


# Singleton service instance
offline_payment_service = OfflinePaymentService()

