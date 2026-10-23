import time
import random
from flask import Blueprint, request, jsonify, current_app
from src.core.mesh import mesh_simulator
from src.core.crypto import crypto_engine, compute_sha256
from src.core.attestation import hardware_attestation_engine
from src.services.gateway import gateway_service
from src.db.schema import reset_db
from src.db.repository import (
    get_accounts,
    get_transactions,
    claim_packet_hash,
    execute_settlement
)

mesh_bp = Blueprint('mesh_bp', __name__)

@mesh_bp.route('/api/state', methods=['GET'])
def get_state():
    accounts = get_accounts()
    transactions = get_transactions()
    topology = mesh_simulator.get_topology()
    return jsonify({
        "mesh": topology,
        "accounts": accounts,
        "transactions": transactions,
        "serverPublicKey": crypto_engine.get_public_key_pem()
    })

@mesh_bp.route('/api/topology', methods=['GET'])
def get_topology():
    return jsonify(mesh_simulator.get_topology())

@mesh_bp.route('/api/mesh/send', methods=['POST'])
def mesh_send():
    data = request.json or {}
    sender = data.get('sender', 'sagar@upi')
    receiver = data.get('receiver', 'merchant@upi')
    amount = float(data.get('amount', 350.0))
    pin = data.get('pin', '1234')
    bounty = float(data.get('bounty', 0.25))

    pkt = mesh_simulator.create_payment_packet(
        sender_vpa=sender,
        receiver_vpa=receiver,
        amount=amount,
        pin=pin,
        bounty=bounty,
        auth_mode="BLE_MESH"
    )

    return jsonify({
        "success": True,
        "packet": pkt,
        "state": mesh_simulator.get_topology()
    })

@mesh_bp.route('/api/mesh/step', methods=['POST'])
def mesh_step():
    res = mesh_simulator.run_gossip_step()
    return jsonify({
        "result": res,
        "state": mesh_simulator.get_topology()
    })

@mesh_bp.route('/api/mesh/toggle-internet', methods=['POST'])
def mesh_toggle_internet():
    data = request.json or {}
    has_internet = data.get('has_internet', True)
    mesh_simulator.set_bridge_internet(has_internet)
    return jsonify({
        "has_internet": has_internet,
        "state": mesh_simulator.get_topology()
    })

@mesh_bp.route('/api/demo/create', methods=['POST'])
def demo_create():
    """Sender phone creates offline encrypted payment instruction directly."""
    data = request.json or {}
    sender = data.get('sender', 'sagar@upi')
    receiver = data.get('receiver', 'merchant@upi')
    amount = float(data.get('amount', 120.0))
    pin = str(data.get('pin', '1234'))
    bounty = float(data.get('bounty', 0.25))

    packet = mesh_simulator.create_payment_packet(sender, receiver, amount, pin, bounty=bounty)
    return jsonify({
        "success": True,
        "packetId": packet["packetId"],
        "message": f"Payment of ₹{amount} encrypted on offline phone (Bounty: ₹{bounty})",
        "state": mesh_simulator.get_topology()
    })

@mesh_bp.route('/api/demo/gossip', methods=['POST'])
def demo_gossip():
    """Advance 1 round of Bluetooth Low Energy (BLE) gossip across stranger commuter mules."""
    result = mesh_simulator.run_gossip_step()
    return jsonify({
        "success": True,
        "round": result["round"],
        "transfers": result["transfers"],
        "state": mesh_simulator.get_topology()
    })

@mesh_bp.route('/api/demo/bridge-internet', methods=['POST'])
def demo_bridge_internet():
    """Toggle Bridge Mule internet connectivity (walks outside into 4G range)."""
    data = request.json or {}
    has_internet = bool(data.get('hasInternet', True))
    mesh_simulator.set_bridge_internet(has_internet)
    return jsonify({
        "success": True,
        "hasInternet": has_internet,
        "state": mesh_simulator.get_topology()
    })

@mesh_bp.route('/api/bridge/ingest', methods=['POST'])
def bridge_ingest():
    """
    Core Banking Backend Ingestion Pipeline:
    1. SHA-256 hash of ciphertext.
    2. Atomic idempotency claim (putIfAbsent).
    3. Hybrid decryption & AES-GCM 128-bit auth tag verification.
    4. Freshness check (signedAt <= 24h).
    5. Atomic ACID multi-party settlement in SQLite / PostgreSQL:
       - Debits Payer
       - Credits Merchant (minus bounty)
       - Credits Mule (bounty reward)
    """
    packet = request.json or {}
    ciphertext = packet.get('ciphertext')
    bridge_id = packet.get('bridgeId', 'phone-bridge')
    mule_vpa = packet.get('muleVpa', 'mule@upi')
    hop_count = int(packet.get('hopCount', 1))

    if not ciphertext:
        return jsonify({"outcome": "INVALID", "reason": "missing_ciphertext"}), 400

    # 1. Compute SHA-256 Hash
    packet_hash = compute_sha256(ciphertext)

    # 2. Atomic Idempotency Claim (Deduplication)
    claimed = claim_packet_hash(packet_hash)
    if not claimed:
        return jsonify({
            "outcome": "DUPLICATE_DROPPED",
            "packetHash": packet_hash,
            "reason": "Duplicate ciphertext hash already claimed and processed"
        }), 200

    # 3. Hybrid Decryption & Tag Verification
    try:
        instruction = crypto_engine.decrypt_payment_instruction(ciphertext)
    except Exception as e:
        return jsonify({
            "outcome": "INVALID",
            "packetHash": packet_hash,
            "reason": "decryption_failed_or_tampered"
        }), 400

    # 4. Freshness Check (24-hour sliding window)
    signed_at = instruction.get('signedAt', 0)
    current_time_ms = int(time.time() * 1000)
    if (current_time_ms - signed_at) > (24 * 60 * 60 * 1000):
        return jsonify({
            "outcome": "INVALID",
            "packetHash": packet_hash,
            "reason": "packet_expired_over_24h"
        }), 400

    # 5. Extract Verified Transaction Attributes
    sender_vpa = instruction.get('senderVpa')
    receiver_vpa = instruction.get('receiverVpa')
    amount = float(instruction.get('amount', 0))
    bounty = float(instruction.get('bounty', 0.25))
    auth_mode = instruction.get('authMode', 'BLE_MESH')

    # 6. Invoke Real UPI / Cashfree / Razorpay Gateway Disbursal Pipeline
    tx_timestamp_id = int(time.time() * 1000) % 100000
    merchant_amt = amount - bounty if bounty > 0 else amount
    payout_data = gateway_service.disburse_payout(
        merchant_vpa=receiver_vpa,
        merchant_amount=merchant_amt,
        mule_vpa=mule_vpa,
        mule_amount=bounty,
        tx_id=tx_timestamp_id
    )

    bank_utr = payout_data["merchantPayout"]["utr"]
    deeplink_url = payout_data["deeplink"]

    # 7. Multi-Party Settlement with Mule Bounty & Banking UTR
    settle_res = execute_settlement(
        packet_hash=packet_hash,
        sender_vpa=sender_vpa,
        receiver_vpa=receiver_vpa,
        amount=amount,
        bridge_id=bridge_id,
        hop_count=hop_count,
        mule_vpa=mule_vpa,
        mule_reward=bounty,
        auth_mode=auth_mode,
        bank_utr=bank_utr,
        deeplink_url=deeplink_url
    )

    if settle_res.get('success'):
        return jsonify({
            "outcome": "SETTLED",
            "packetHash": packet_hash,
            "transactionId": settle_res["transaction_id"],
            "amount": amount,
            "sender": sender_vpa,
            "receiver": receiver_vpa,
            "merchantCredit": settle_res["merchant_credit"],
            "muleReward": settle_res["mule_reward"],
            "muleVpa": settle_res["mule_vpa"],
            "bankUtr": bank_utr,
            "deeplinkUrl": deeplink_url,
            "payout": payout_data
        }), 200
    else:
        return jsonify({
            "outcome": "INVALID",
            "packetHash": packet_hash,
            "reason": settle_res.get("error")
        }), 400

@mesh_bp.route('/api/demo/flush-bridge', methods=['POST'])
def demo_flush_bridge():
    """Uploads all packets held on the bridge node to /api/bridge/ingest."""
    bridge_node = mesh_simulator.devices["phone-bridge"]
    if not bridge_node["has_internet"]:
        return jsonify({"success": False, "error": "Bridge Node is still offline! Turn on 4G first."}), 400

    held_packets = list(bridge_node["held_packets"])
    if not held_packets:
        return jsonify({"success": False, "error": "No packets currently on the Bridge Node."}), 400

    data = request.json or {}
    custom_mule_vpa = data.get('muleVpa', 'mule@upi')

    results = []
    for pkt in held_packets:
        payload = {
            "ciphertext": pkt["ciphertext"],
            "bridgeId": "phone-bridge",
            "muleVpa": custom_mule_vpa,
            "hopCount": pkt.get("hopCount", 3)
        }
        with current_app.test_client() as client:
            resp = client.post('/api/bridge/ingest', json=payload)
            results.append(resp.get_json())

    # Clear uploaded packets from bridge
    bridge_node["held_packets"] = []
    mesh_simulator.hop_log.append(f"Bridge Mule uploaded {len(held_packets)} packet(s) to banking cloud. Payouts disbursed!")

    return jsonify({
        "success": True,
        "results": results,
        "state": mesh_simulator.get_topology()
    })

@mesh_bp.route('/api/demo/tamper', methods=['POST'])
def demo_tamper():
    """Demonstrates tampering attack: flips a byte in the packet to prove rejection."""
    bridge_node = mesh_simulator.devices["phone-bridge"]
    if not bridge_node["held_packets"]:
        sample = mesh_simulator.create_payment_packet('sagar@upi', 'merchant@upi', 500.0, '1234')
        ciphertext = sample["ciphertext"]
    else:
        ciphertext = bridge_node["held_packets"][0]["ciphertext"]

    mid = len(ciphertext) // 2
    flipped_char = 'B' if ciphertext[mid] == 'A' else 'A'
    tampered_ciphertext = ciphertext[:mid] + flipped_char + ciphertext[mid+1:]

    payload = {
        "ciphertext": tampered_ciphertext,
        "bridgeId": "phone-bridge-attacker",
        "hopCount": 4
    }

    with current_app.test_client() as client:
        resp = client.post('/api/bridge/ingest', json=payload)
        outcome_data = resp.get_json()

    mesh_simulator.hop_log.append(f"Tamper attack simulated: altered ciphertext byte -> Backend outcome: {outcome_data.get('outcome')} ({outcome_data.get('reason')})")

    return jsonify({
        "success": True,
        "attackResult": outcome_data,
        "state": mesh_simulator.get_topology()
    })

@mesh_bp.route('/api/demo/reset', methods=['POST'])
def demo_reset():
    """Resets database accounts, transactions, and mesh simulation state."""
    reset_db()
    mesh_simulator.reset()
    return jsonify({"success": True, "message": "System reset to default state"})

@mesh_bp.route('/api/mesh/settle-cloud', methods=['POST'])
def mesh_settle_cloud():
    """
    Bridge Mule Uplink Settlement:
    1. Uploads accumulated BLE mesh packets to cloud bank.
    2. Atomic Idempotency check with SHA-256 deduplication.
    3. Decrypts AES-GCM + RSA-OAEP payload and updates double-entry balance.
    4. Disburses IMPS payout and mule bounties.
    """
    bridge = mesh_simulator.devices["phone-bridge"]
    if not bridge["has_internet"]:
        return jsonify({
            "success": False,
            "error": "BRIDGE_OFFLINE",
            "message": "Bridge mule has no 4G/Internet connection! Move bridge into cellular range."
        }), 400

    packets_to_settle = list(bridge["held_packets"])
    if not packets_to_settle:
        return jsonify({
            "success": False,
            "message": "No held packets on Bridge Mule to settle."
        })

    settled_results = []
    for pkt in packets_to_settle:
        ciphertext = pkt["ciphertext"]
        pkt_hash = compute_sha256(ciphertext)

        # 1. Atomic Idempotency Check
        is_unique = claim_packet_hash(pkt_hash)
        if not is_unique:
            bridge["held_packets"].remove(pkt)
            settled_results.append({
                "packetId": pkt["packetId"],
                "status": "DUPLICATE_REJECTED",
                "message": "Packet already claimed and settled earlier."
            })
            continue

        # 2. Cryptographic Hybrid Decryption
        try:
            instruction = crypto_engine.decrypt_payment_instruction(ciphertext)
        except ValueError as err:
            settled_results.append({
                "packetId": pkt["packetId"],
                "status": "TAMPERED_REJECTED",
                "error": str(err)
            })
            continue

        sender_vpa = instruction["senderVpa"]
        receiver_vpa = instruction["receiverVpa"]
        amount = float(instruction["amount"])
        bounty = float(instruction.get("bounty", 0.25))
        mule_vpa = pkt.get("muleVpa", "mule@upi")

        # 3. Settle Ledger
        settle_res = execute_settlement(
            packet_hash=pkt_hash,
            sender_vpa=sender_vpa,
            receiver_vpa=receiver_vpa,
            amount=amount,
            bridge_id="bridge-mule-4g",
            hop_count=pkt.get("hopCount", 3),
            mule_vpa=mule_vpa,
            mule_reward=bounty
        )

        # 4. Bank Payout
        payout = gateway_service.disburse_payout(
            merchant_vpa=receiver_vpa,
            merchant_amount=amount,
            mule_vpa=mule_vpa,
            mule_amount=bounty,
            tx_id=settle_res["transaction_id"]
        )

        bridge["held_packets"].remove(pkt)
        settled_results.append({
            "packetId": pkt["packetId"],
            "status": "SETTLED",
            "amount": amount,
            "sender": sender_vpa,
            "receiver": receiver_vpa,
            "payout": payout
        })

    return jsonify({
        "success": True,
        "settled": settled_results,
        "state": mesh_simulator.get_topology(),
        "accounts": get_accounts(),
        "transactions": get_transactions()
    })

@mesh_bp.route('/api/attestation/challenge', methods=['POST'])
def attestation_challenge():
    data = request.json or {}
    vpa = (data.get('vpa') or 'sagar@upi').strip()
    nonce_b64 = hardware_attestation_engine.issue_challenge(vpa)
    return jsonify({
        "success": True,
        "vpa": vpa,
        "challenge": nonce_b64,
        "expiresInSeconds": 300
    })

@mesh_bp.route('/api/attestation/verify', methods=['POST'])
def attestation_verify():
    data = request.json or {}
    vpa = (data.get('vpa') or '').strip()
    cert_chain = data.get('certificateChain', [])
    platform = data.get('platform', 'ANDROID')
    try:
        res = hardware_attestation_engine.verify_and_register_attestation(
            vpa=vpa,
            cert_chain_b64=cert_chain,
            platform=platform
        )
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
