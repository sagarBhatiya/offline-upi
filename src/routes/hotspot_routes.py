import time
from flask import Blueprint, request, jsonify
from src.db.repository import execute_offline_wallet_transfer

hotspot_bp = Blueprint('hotspot_bp', __name__)

recent_hotspot_events = []

@hotspot_bp.route('/api/hotspot/info', methods=['GET'])
def hotspot_info():
    """Returns local network info to help Sender connect to Merchant Hotspot."""
    import socket
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
        "status": "HOTSPOT_LISTENER_ACTIVE",
        "miniMilitiaMode": True
    })

@hotspot_bp.route('/api/hotspot/transfer', methods=['POST'])
def hotspot_transfer():
    """
    Direct Wi-Fi Hotspot LAN transfer endpoint.
    Called by Payer connected to Merchant's mobile hotspot.
    Zero internet required — operates 100% over local Wi-Fi subnet!
    """
    data = request.json or {}
    sender = (data.get('senderVpa') or '').strip()
    receiver = (data.get('receiverVpa') or '').strip()
    client_balance = data.get('clientBalance')
    try:
        amount = float(data.get('amount', 0))
    except (ValueError, TypeError):
        amount = 0.0

    if not sender or not receiver:
        return jsonify({"success": False, "error": "Both sender and receiver UPI IDs required."}), 400
    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than ₹0."}), 400

    transfer_res = execute_offline_wallet_transfer(
        sender_vpa=sender,
        receiver_vpa=receiver,
        amount=amount,
        auth_mode="WIFI_HOTSPOT_LAN",
        client_balance=client_balance
    )

    if not transfer_res.get('success'):
        return jsonify({"success": False, "error": transfer_res.get('error')}), 400

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
        "message": f"Offline Wi-Fi Hotspot transfer of ₹{amount:.2f} completed!"
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
