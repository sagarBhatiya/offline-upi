import time
import json
import socket
import uuid
from flask import Blueprint, request, jsonify
from src.db.repository import (
    execute_offline_wallet_transfer,
    get_account_by_vpa,
    get_recent_transactions_for_vpa,
    upsert_user_account,
    record_offline_voucher,
    get_pending_sync_vouchers
)
from src.core.hotspot_socket import (
    HotspotVoucherEngine,
    OfflinePaymentService,
    MAX_OFFLINE_TRANSACTION_LIMIT
)

hotspot_bp = Blueprint('hotspot_bp', __name__)

recent_hotspot_events = []
# Registered peers on the Hotspot LAN: { device_id: { ... } }
connected_peers = {}

def cleanup_stale_peers():
    """Removes peers that have not checked in within the last 45 seconds."""
    now = time.time()
    stale_keys = [k for k, v in connected_peers.items() if now - v.get('lastSeen', 0) > 45]
    for k in stale_keys:
        connected_peers.pop(k, None)

@hotspot_bp.route('/api/hotspot/info', methods=['GET'])
def hotspot_info():
    """Returns local network info to help devices connect over Hotspot/Wi-Fi."""
    detected_ips = []
    hostname = "offline-host"
    try:
        hostname = socket.gethostname()
        detected_ips = socket.gethostbyname_ex(hostname)[2]
    except Exception:
        pass

    common_gateways = ["192.168.43.1", "172.20.10.1", "192.168.1.1"]

    return jsonify({
        "success": True,
        "hostname": hostname,
        "detectedIps": detected_ips,
        "commonGateways": common_gateways,
        "defaultPort": 5000,
        "status": "HOTSPOT_ACTIVE",
        "miniMilitiaMode": True,
        "mode": "OFFLINE_LAN"
    })

@hotspot_bp.route('/api/hotspot/qr', methods=['GET'])
def get_hotspot_qr():
    """
    Returns connection QR JSON for Device B (Sender) to connect to Device A (Receiver):
    Generates Dual-Compatible Wi-Fi format: WIFI:S:...;T:WPA;P:...;;URL:http://...
    """
    receiver_vpa = (request.args.get('vpa') or 'merchant@okhdfcbank').strip().lower()
    suffix = uuid.uuid4().hex[:6].upper()
    ssid = f"UPI_{suffix}"
    psk = uuid.uuid4().hex[:12]

    # Best detected host IP
    host_ip = "192.168.43.1"
    try:
        host_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        pass

    engine = HotspotVoucherEngine()
    wifi_string = f"WIFI:S:{ssid};T:WPA;P:{psk};;URL:http://{host_ip}:5000"
    qr_payload = {
        "ssid": ssid,
        "psk": psk,
        "host": host_ip,
        "port": 5000,
        "receiverVpa": receiver_vpa,
        "wifiString": wifi_string,
        "pubKey": engine.get_public_key_pem()
    }

    return jsonify({
        "success": True,
        "qr": qr_payload,
        "wifiString": wifi_string,
        "qrString": wifi_string
    })

@hotspot_bp.route('/api/hotspot/payment-qr', methods=['POST'])
def generate_payment_qr():
    """
    Generates Dynamic Payment QR (QR 2) for Receiver with locked amount and UPI URI.
    """
    data = request.json or {}
    receiver_vpa = (data.get('receiverVpa') or 'merchant@okhdfcbank').strip().lower()
    try:
        amount = float(data.get('amount', 0.0))
    except (ValueError, TypeError):
        amount = 0.0

    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than Rs. 0."}), 400
    if amount > MAX_OFFLINE_TRANSACTION_LIMIT:
        return jsonify({"success": False, "error": f"Amount exceeds maximum offline limit of Rs.{MAX_OFFLINE_TRANSACTION_LIMIT:.2f}."}), 400

    voucher_id = str(uuid.uuid4())
    nonce = int(time.time() * 1000)
    engine = HotspotVoucherEngine()
    
    # Dual-compatible UPI URL string for QR scanning
    upi_uri = f"upi://pay?pa={receiver_vpa}&pn=OfflineMerchant&am={amount:.2f}&cu=INR&mode=02&offline=true&vid={voucher_id}&nonce={nonce}"

    qr_payload = {
        "voucherId": voucher_id,
        "receiverVpa": receiver_vpa,
        "amount": amount,
        "nonce": nonce,
        "timestamp": int(time.time()),
        "upiUri": upi_uri,
        "pubKey": engine.get_public_key_pem()
    }

    return jsonify({
        "success": True,
        "voucherId": voucher_id,
        "receiverVpa": receiver_vpa,
        "amount": amount,
        "upiUri": upi_uri,
        "qrString": upi_uri,
        "qrPayload": qr_payload
    })

@hotspot_bp.route('/api/hotspot/sync', methods=['POST'])
def trigger_cloud_sync():
    """
    Simulates background WorkManager sync job:
    Pushes pending offline vouchers to the central ledger when connectivity resumes.
    """
    res = OfflinePaymentService.sync_pending_vouchers_to_cloud()
    return jsonify(res)

@hotspot_bp.route('/api/hotspot/ping', methods=['GET'])
def hotspot_ping():
    """Lightweight ping endpoint for connection latency & peer presence checks."""
    return jsonify({
        "success": True,
        "serverTime": int(time.time() * 1000),
        "status": "ONLINE_OFFLINE_LAN"
    })

@hotspot_bp.route('/api/hotspot/peers/register', methods=['POST'])
def register_peer():
    """Registers or updates a device peer presence on the Hotspot Wi-Fi subnet."""
    cleanup_stale_peers()
    data = request.json or {}
    device_id = (data.get('deviceId') or '').strip()
    device_name = (data.get('deviceName') or 'Offline Device').strip()
    vpa = (data.get('vpa') or '').strip().lower()
    holder_name = (data.get('holderName') or 'UPI Account Holder').strip()
    bank = (data.get('bank') or 'NPCI Bank').strip()
    role = (data.get('role') or 'peer').strip()

    if not device_id:
        return jsonify({"success": False, "error": "deviceId is required"}), 400

    if vpa:
        # Ensure account exists in local database
        upsert_user_account(new_vpa=vpa, holder_name=holder_name)

    caller_ip = request.remote_addr or '127.0.0.1'

    connected_peers[device_id] = {
        "deviceId": device_id,
        "deviceName": device_name,
        "vpa": vpa,
        "holderName": holder_name,
        "bank": bank,
        "role": role,
        "ip": caller_ip,
        "lastSeen": time.time()
    }

    peers_list = [p for p in connected_peers.values() if p["deviceId"] != device_id]
    return jsonify({
        "success": True,
        "registered": True,
        "peerCount": len(connected_peers),
        "peers": peers_list
    })

@hotspot_bp.route('/api/hotspot/peers', methods=['GET'])
def get_peers():
    """Returns active peers on the Hotspot LAN."""
    cleanup_stale_peers()
    current_device = (request.args.get('currentDeviceId') or '').strip()
    peers_list = [p for p in connected_peers.values() if p["deviceId"] != current_device]
    return jsonify({
        "success": True,
        "count": len(peers_list),
        "peers": peers_list
    })

@hotspot_bp.route('/api/hotspot/account', methods=['GET'])
def get_account_status():
    """Returns current balance and recent transactions for a UPI VPA."""
    vpa = (request.args.get('vpa') or '').strip().lower()
    if not vpa:
        return jsonify({"success": False, "error": "vpa parameter is required"}), 400

    acc = get_account_by_vpa(vpa)
    if not acc:
        # Default initialization for seamless offline experience
        holder_name = vpa.split('@')[0].capitalize()
        upsert_user_account(new_vpa=vpa, holder_name=holder_name, initial_balance=2000.0)
        acc = get_account_by_vpa(vpa) or {
            "vpa": vpa,
            "holder_name": holder_name,
            "balance": 2000.0,
            "version": 1
        }

    txns = get_recent_transactions_for_vpa(vpa, limit=10)
    return jsonify({
        "success": True,
        "account": acc,
        "transactions": txns
    })

@hotspot_bp.route('/api/hotspot/transfer', methods=['POST'])
def hotspot_transfer():
    """
    Direct Wi-Fi Hotspot LAN transfer endpoint.
    Transfers funds offline between two devices on the same Hotspot subnet.
    100% offline, zero internet needed.
    """
    data = request.json or {}
    sender = (data.get('senderVpa') or '').strip().lower()
    receiver = (data.get('receiverVpa') or '').strip().lower()
    client_balance = data.get('clientBalance')
    try:
        amount = float(data.get('amount', 0))
    except (ValueError, TypeError):
        amount = 0.0

    if not sender or not receiver:
        return jsonify({"success": False, "error": "Both sender and receiver UPI IDs required."}), 400
    if sender == receiver:
        return jsonify({"success": False, "error": "Sender and receiver cannot be the same UPI ID."}), 400
    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than 0."}), 400
    if amount > MAX_OFFLINE_TRANSACTION_LIMIT:
        return jsonify({
            "success": False,
            "error": f"Amount exceeds maximum offline limit of Rs.{MAX_OFFLINE_TRANSACTION_LIMIT:.2f} per transaction."
        }), 400

    transfer_res = execute_offline_wallet_transfer(
        sender_vpa=sender,
        receiver_vpa=receiver,
        amount=amount,
        auth_mode="WIFI_HOTSPOT_LAN",
        client_balance=client_balance
    )

    if not transfer_res.get('success'):
        return jsonify({"success": False, "error": transfer_res.get('error')}), 400

    # Record in Room/SQLite offline_vouchers state machine
    voucher_uuid = str(uuid.uuid4())
    record_offline_voucher(
        voucher_id=voucher_uuid,
        voucher_type="DEBIT",
        amount=amount,
        status="COMPLETED",
        raw_payload=json.dumps({"sender": sender, "receiver": receiver, "amount": amount}),
        sender_vpa=sender,
        receiver_vpa=receiver
    )

    tx_event = {
        "transactionId": transfer_res.get('transaction_id'),
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "senderBalance": transfer_res.get('sender_balance'),
        "receiverBalance": transfer_res.get('receiver_balance'),
        "timestamp": int(time.time() * 1000),
        "protocol": "WIFI_HOTSPOT_LAN_P2P"
    }

    global recent_hotspot_events
    recent_hotspot_events.append(tx_event)

    if len(recent_hotspot_events) > 50:
        recent_hotspot_events = recent_hotspot_events[-50:]

    return jsonify({
        "success": True,
        "amount": amount,
        "sender": sender,
        "receiver": receiver,
        "senderBalance": transfer_res.get('sender_balance'),
        "receiverBalance": transfer_res.get('receiver_balance'),
        "transactionId": transfer_res.get('transaction_id'),
        "mode": "WIFI_HOTSPOT_LAN",
        "message": f"Offline Wi-Fi Hotspot transfer of Rs.{amount:.2f} completed successfully!"
    })

@hotspot_bp.route('/api/hotspot/recent', methods=['GET'])
def hotspot_recent():
    """Returns recent payments received over Wi-Fi Hotspot."""
    target_vpa = (request.args.get('vpa') or '').strip().lower()
    since = int(request.args.get('since', 0))

    global recent_hotspot_events
    if not target_vpa or target_vpa == 'all':
        matched = [e for e in recent_hotspot_events if e["timestamp"] > since]
    else:
        matched = [
            e for e in recent_hotspot_events 
            if e["timestamp"] > since and (
                e["receiver"].strip().lower() == target_vpa or 
                e["sender"].strip().lower() == target_vpa or 
                target_vpa in e["receiver"].strip().lower()
            )
        ]
    return jsonify({"success": True, "events": matched, "count": len(matched)})
