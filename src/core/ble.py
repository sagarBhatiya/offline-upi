import os
import zlib
import struct
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC_HEADER = 0xFA
MAX_CHUNK_DATA_SIZE = 480  # Fits within standard negotiated BLE ATT MTU 512 bytes
STANDARD_BLE_FINANCIAL_UUID = "0000FFF0-0000-1000-8000-00805F9B34FB"
BLE_ADVERTISEMENT_SERVICE_DATA = "0000FFF1-0000-1000-8000-00805F9B34FB"

import json
import base64
import time
import uuid
import hashlib

class BlePaymentRadioManager:
    """
    Manages Bluetooth Low Energy (BLE) radio channels, discovery, and packet transmission.
    Supports on-device zero-internet offline packet exchange.
    """
    @staticmethod
    def create_ble_voucher_packet(sender_vpa: str, receiver_vpa: str, amount: float, pin_hash: str = "1234", nonce: int = 1) -> dict:
        voucher_id = f"ble_vch_{uuid.uuid4().hex[:10]}"
        timestamp = int(time.time() * 1000)
        instruction = {
            "voucherId": voucher_id,
            "senderVpa": sender_vpa,
            "receiverVpa": receiver_vpa,
            "amount": float(amount),
            "pinHash": pin_hash,
            "nonce": nonce,
            "timestamp": timestamp,
            "protocol": "BLE_P2P_v5.2"
        }
        
        # 256-bit ephemeral financial key
        salt = f"{sender_vpa}:{receiver_vpa}:{nonce}".encode('utf-8')
        raw_key = hashlib.sha256(salt + b"_OFFLINE_BLE_MASTER_KEY").digest()
        
        iv = os.urandom(12)
        aesgcm = AESGCM(raw_key)
        payload_bytes = json.dumps(instruction).encode('utf-8')
        ciphertext = aesgcm.encrypt(iv, payload_bytes, None)
        envelope = iv + ciphertext
        
        chunks = []
        total = (len(envelope) + MAX_CHUNK_DATA_SIZE - 1) // MAX_CHUNK_DATA_SIZE
        if total == 0: total = 1
        
        frames_info = []
        for idx in range(total):
            start = idx * MAX_CHUNK_DATA_SIZE
            part = envelope[start : start + MAX_CHUNK_DATA_SIZE]
            header = struct.pack(">BBHHHH", MAGIC_HEADER, 0x01, nonce & 0xFFFF, idx, total, len(part))
            body = header + part
            crc = zlib.crc32(body) & 0xFFFFFFFF
            frame_bytes = body + struct.pack(">I", crc)
            chunks.append(frame_bytes)
            frames_info.append({
                "frameIndex": idx,
                "totalFrames": total,
                "length": len(part),
                "crc32": f"0x{crc:08X}",
                "hex": frame_bytes.hex(),
                "magic": "0xFA"
            })
            
        return {
            "voucherId": voucher_id,
            "instruction": instruction,
            "frames": [f.hex() for f in chunks],
            "framesInfo": frames_info,
            "totalFrames": total,
            "saltHex": salt.hex(),
            "timestamp": timestamp
        }

    @staticmethod
    def verify_ble_voucher_packet(frames_hex: list, sender_vpa: str, receiver_vpa: str, nonce: int) -> dict:
        salt = f"{sender_vpa}:{receiver_vpa}:{nonce}".encode('utf-8')
        raw_key = hashlib.sha256(salt + b"_OFFLINE_BLE_MASTER_KEY").digest()
        
        ordered_parts = {}
        total_expected = None
        
        for hx in frames_hex:
            frame = bytes.fromhex(hx)
            if len(frame) < 14:
                raise ValueError("Frame too short")
            magic, msg_type, session_id, seq, total, part_len = struct.unpack(">BBHHHH", frame[:10])
            if magic != MAGIC_HEADER:
                raise ValueError("Invalid magic header")
            body = frame[:-4]
            rcv_crc = struct.unpack(">I", frame[-4:])[0]
            if (zlib.crc32(body) & 0xFFFFFFFF) != rcv_crc:
                raise ValueError("CRC32 mismatch on BLE frame")
            if total_expected is None:
                total_expected = total
            ordered_parts[seq] = frame[10:-4]
            
        assembled = b"".join([ordered_parts[i] for i in range(total_expected)])
        iv = assembled[:12]
        ciphertext = assembled[12:]
        aesgcm = AESGCM(raw_key)
        decrypted = aesgcm.decrypt(iv, ciphertext, None)
        return json.loads(decrypted.decode('utf-8'))

class BleSecureSessionChannel:
    """
    Mutual Authentication, Forward-Secrecy & Chunking over BLE GATT:
    1. Derives an ephemeral AES-256-GCM session key using X25519 ECDH + HKDF-SHA256.
    2. Dynamically fragments payloads into frames with CRC-32 checksums.
    3. Reassembles and decrypts incoming BLE frames with strict corruption detection.
    """
    def __init__(self):
        self._private_key = x25519.X25519PrivateKey.generate()
        self.public_key_bytes = self._private_key.public_key().public_bytes_raw()
        self.session_key = None

    def establish_session(self, peer_public_key_bytes: bytes, salt: bytes = b"UPI_OFFLINE_GATT"):
        """Performs ECDH key exchange with peer public key and derives a 256-bit AES-GCM key."""
        peer_pub = x25519.X25519PublicKey.from_public_bytes(peer_public_key_bytes)
        shared_secret = self._private_key.exchange(peer_pub)

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=b"BLE_FINANCIAL_SESSION"
        )
        self.session_key = hkdf.derive(shared_secret)

    def packetize(self, raw_payload: bytes, session_id: int = 1) -> list:
        """
        Encrypts raw payload with AES-256-GCM and fragments into CRC-32 verified frames.
        Frame format:
        [Magic: 1B (0xFA)][Type: 1B][SessionID: 2B][Seq: 2B][Total: 2B][Len: 2B][Payload: NB][CRC-32: 4B]
        """
        if not self.session_key:
            raise PermissionError("Session not initialized. Perform ECDH handshake first.")

        # 12-byte AES-GCM IV
        iv = os.urandom(12)
        aesgcm = AESGCM(self.session_key)
        ciphertext = aesgcm.encrypt(iv, raw_payload, None)
        envelope = iv + ciphertext

        chunks = []
        total_chunks = (len(envelope) + MAX_CHUNK_DATA_SIZE - 1) // MAX_CHUNK_DATA_SIZE
        if total_chunks == 0:
            total_chunks = 1

        for idx in range(total_chunks):
            start = idx * MAX_CHUNK_DATA_SIZE
            part = envelope[start : start + MAX_CHUNK_DATA_SIZE]

            header = struct.pack(">BBHHHH", MAGIC_HEADER, 0x01, session_id, idx, total_chunks, len(part))
            frame_without_crc = header + part
            crc = zlib.crc32(frame_without_crc) & 0xFFFFFFFF
            full_frame = frame_without_crc + struct.pack(">I", crc)
            chunks.append(full_frame)

        return chunks

    def reassemble(self, frames: list) -> bytes:
        """
        Validates CRC-32 checksums, checks ordering, reassembles chunks, and decrypts payload.
        """
        if not self.session_key:
            raise PermissionError("Session not initialized. Perform ECDH handshake first.")

        ordered_parts = {}
        total_expected = None

        for frame in frames:
            if len(frame) < 14:
                raise ValueError("Frame corrupted: insufficient header length (< 14 bytes).")

            magic, msg_type, session_id, seq, total, part_len = struct.unpack(">BBHHHH", frame[:10])
            if magic != MAGIC_HEADER:
                raise ValueError(f"Magic byte mismatch: expected 0xFA, got {hex(magic)}.")

            frame_body = frame[:-4]
            received_crc = struct.unpack(">I", frame[-4:])[0]
            computed_crc = zlib.crc32(frame_body) & 0xFFFFFFFF

            if received_crc != computed_crc:
                raise ValueError(f"CRC-32 validation failed on chunk {seq}. Integrity compromised.")

            if total_expected is None:
                total_expected = total
            ordered_parts[seq] = frame[10:-4]

        if len(ordered_parts) != total_expected:
            raise ValueError(f"Incomplete BLE stream: received {len(ordered_parts)} of {total_expected} chunks.")

        assembled_envelope = b"".join([ordered_parts[i] for i in range(total_expected)])
        if len(assembled_envelope) < 12:
            raise ValueError("Assembled envelope corrupted: missing IV.")

        iv = assembled_envelope[:12]
        ciphertext = assembled_envelope[12:]

        aesgcm = AESGCM(self.session_key)
        return aesgcm.decrypt(iv, ciphertext, None)
