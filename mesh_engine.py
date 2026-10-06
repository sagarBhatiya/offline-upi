import time
import uuid
import hashlib
from crypto_helper import crypto_engine

class MeshSimulationEngine:
    def __init__(self):
        self.reset()

    def reset(self):
        self.devices = {
            "phone-sender": {
                "id": "phone-sender",
                "name": "Sender Phone (Payer)",
                "has_internet": False,
                "role": "Sender",
                "held_packets": []
            },
            "pos-merchant": {
                "id": "pos-merchant",
                "name": "Merchant PoS & Soundbox",
                "has_internet": False,
                "role": "Merchant",
                "held_packets": []
            },
            "phone-stranger-1": {
                "id": "phone-stranger-1",
                "name": "Stranger 1 (Commuter Mule)",
                "has_internet": False,
                "role": "Relay",
                "held_packets": []
            },
            "phone-stranger-2": {
                "id": "phone-stranger-2",
                "name": "Stranger 2 (Commuter Mule)",
                "has_internet": False,
                "role": "Relay",
                "held_packets": []
            },
            "phone-bridge": {
                "id": "phone-bridge",
                "name": "Bridge Mule (4G Uplink)",
                "has_internet": False,
                "role": "Bridge",
                "held_packets": []
            }
        }
        self.gossip_round = 0
        self.hop_log = []
        self.merchant_vault = 0.0
        self.scanned_vouchers = []

    def create_payment_packet(self, sender_vpa: str, receiver_vpa: str, amount: float, pin: str, bounty: float = 0.25, auth_mode: str = "BLE_MESH", ttl: int = 5):
        """Creates an offline encrypted MeshPacket on the sender phone."""
        pin_hash = hashlib.sha256(pin.encode('utf-8')).hexdigest()
        nonce = str(uuid.uuid4())
        instruction = {
            "senderVpa": sender_vpa,
            "receiverVpa": receiver_vpa,
            "amount": amount,
            "pinHash": pin_hash,
            "bounty": bounty,
            "authMode": auth_mode,
            "nonce": nonce,
            "signedAt": int(time.time() * 1000)
        }

        ciphertext = crypto_engine.encrypt_payment_instruction(instruction)
        packet = {
            "packetId": f"pkt_{uuid.uuid4().hex[:8]}",
            "senderVpa": sender_vpa,
            "receiverVpa": receiver_vpa,
            "amount": amount,
            "bounty": bounty,
            "authMode": auth_mode,
            "ttl": ttl,
            "createdAt": int(time.time() * 1000),
            "ciphertext": ciphertext,
            "hopCount": 0
        }

        self.devices["phone-sender"]["held_packets"].append(packet)
        self.hop_log.append(f"Offline payment packet of ₹{amount} created on Sender Phone (Bounty: ₹{bounty}).")
        return packet

    def enqueue_merchant_voucher_for_gossip(self, voucher_data: dict, ttl: int = 5):
        """
        Takes a scanned offline Dynamic QR voucher on the merchant terminal
        and packages it into an encrypted BLE gossip packet with a mule bounty.
        """
        payload = voucher_data.get('payload', {})
        sender_vpa = payload.get('payerVpa', 'sagar@upi')
        receiver_vpa = payload.get('payeeVpa', 'merchant@upi')
        amount = float(payload.get('amount', 120.0))
        bounty = float(payload.get('bounty', 0.25))

        instruction = {
            "senderVpa": sender_vpa,
            "receiverVpa": receiver_vpa,
            "amount": amount,
            "pinHash": "offline-qr-verified",
            "bounty": bounty,
            "authMode": "DYNAMIC_QR_MESH",
            "nonce": str(payload.get('nonce', uuid.uuid4().hex[:8])),
            "qrSignature": voucher_data.get('signatureHex', ''),
            "signedAt": payload.get('signedAt', int(time.time() * 1000))
        }

        ciphertext = crypto_engine.encrypt_payment_instruction(instruction)
        packet = {
            "packetId": f"qr_pkt_{uuid.uuid4().hex[:8]}",
            "senderVpa": sender_vpa,
            "receiverVpa": receiver_vpa,
            "amount": amount,
            "bounty": bounty,
            "authMode": "DYNAMIC_QR_MESH",
            "ttl": ttl,
            "createdAt": int(time.time() * 1000),
            "ciphertext": ciphertext,
            "hopCount": 0
        }

        # Merchant stores it and broadcasts over BLE
        self.devices["pos-merchant"]["held_packets"].append(packet)
        self.hop_log.append(f"Merchant queued QR voucher ₹{amount} for BLE Gossip Mule relay (Bounty: ₹{bounty})")
        return packet

    def record_offline_scan(self, voucher_data: dict):
        """Records scanned offline QR into local merchant vault."""
        payload = voucher_data.get('payload', {})
        amount = float(payload.get('amount', 0.0))
        self.merchant_vault += amount
        self.scanned_vouchers.append({
            "time": time.strftime("%H:%M:%S"),
            "payer": payload.get('payerVpa', 'sagar@upi'),
            "amount": amount,
            "nonce": payload.get('nonce', 0),
            "verified": True
        })
        self.hop_log.append(f"PoS verified Dynamic QR from {payload.get('payerVpa')}. ₹{amount} added to Offline Vault.")
        return self.enqueue_merchant_voucher_for_gossip(voucher_data)

    def run_gossip_step(self):
        """
        Simulates 1 round of Bluetooth Low Energy (BLE) store-and-forward gossip:
        (Sender Phone OR Merchant PoS) -> Stranger 1 -> Stranger 2 -> Bridge Mule.
        """
        self.gossip_round += 1
        transfers = 0

        # Sources: both Sender Phone and Merchant PoS can broadcast
        sources = [self.devices["phone-sender"], self.devices["pos-merchant"]]

        for src in sources:
            for pkt in list(src["held_packets"]):
                if pkt["ttl"] > 0:
                    pkt_copy = dict(pkt)
                    pkt_copy["ttl"] -= 1
                    pkt_copy["hopCount"] += 1
                    if not any(p["packetId"] == pkt["packetId"] for p in self.devices["phone-stranger-1"]["held_packets"]):
                        self.devices["phone-stranger-1"]["held_packets"].append(pkt_copy)
                        self.hop_log.append(f"[Hop 1] {pkt['packetId']} relayed from {src['name']} to Stranger 1 via BLE")
                        transfers += 1

        # Step 2: Stranger 1 broadcasts to Stranger 2
        for pkt in list(self.devices["phone-stranger-1"]["held_packets"]):
            if pkt["ttl"] > 0:
                pkt_copy = dict(pkt)
                pkt_copy["ttl"] -= 1
                pkt_copy["hopCount"] += 1
                if not any(p["packetId"] == pkt["packetId"] for p in self.devices["phone-stranger-2"]["held_packets"]):
                    self.devices["phone-stranger-2"]["held_packets"].append(pkt_copy)
                    self.hop_log.append(f"[Hop 2] {pkt['packetId']} relayed to Stranger 2")
                    transfers += 1

        # Step 3: Stranger 2 broadcasts to Bridge Mule
        for pkt in list(self.devices["phone-stranger-2"]["held_packets"]):
            if pkt["ttl"] > 0:
                pkt_copy = dict(pkt)
                pkt_copy["ttl"] -= 1
                pkt_copy["hopCount"] += 1
                if not any(p["packetId"] == pkt["packetId"] for p in self.devices["phone-bridge"]["held_packets"]):
                    self.devices["phone-bridge"]["held_packets"].append(pkt_copy)
                    self.hop_log.append(f"[Hop 3] {pkt['packetId']} reached Bridge Mule! Eligible for ₹{pkt.get('bounty', 0.25)} bounty.")
                    transfers += 1

        return {"transfers": transfers, "round": self.gossip_round}

    def set_bridge_internet(self, has_internet: bool):
        self.devices["phone-bridge"]["has_internet"] = has_internet
        status_text = "connected to 4G/Internet" if has_internet else "offline"
        self.hop_log.append(f"Bridge Mule moved into 4G range and is now {status_text}.")
        return has_internet

    def get_topology(self):
        return {
            "devices": self.devices,
            "gossip_round": self.gossip_round,
            "merchant_vault": self.merchant_vault,
            "scanned_vouchers": self.scanned_vouchers[-10:],
            "log": self.hop_log[-12:]
        }

mesh_simulator = MeshSimulationEngine()
