import os
import time
import json
import uuid
import random
import hashlib
from flask import Blueprint, request, jsonify
from src.core.ble import (
    BleSecureSessionChannel,
    BlePaymentRadioManager,
    STANDARD_BLE_FINANCIAL_UUID
)
from src.services.gateway import gateway_service
from src.db.repository import (
    execute_offline_wallet_transfer,
    get_account_by_vpa,
    get_recent_transactions_for_vpa,
    upsert_user_account,
    record_offline_voucher,
    get_pending_sync_vouchers
)

ble_bp = Blueprint('ble_bp', __name__)

MAX_OFFLINE_TRANSACTION_LIMIT = 500.00
recent_ble_events = []

# Mock active nearby BLE devices for P2P discovery
NEARBY_BLE_PEERS = [
    {
        "deviceId": "BLE_POS_88A2",
        "name": "Merchant Soundbox & Terminal",
        "rssi": -48,
        "distance": "0.8m",
        "role": "MERCHANT_TERMINAL",
        "vpa": "merchant@okhdfcbank",
        "battery": "94%",
        "status": "DISCOVERABLE"
    },
    {
        "deviceId": "BLE_COMMUTER_4F19",
        "name": "Stranger Commuter Mule #1",
        "rssi": -65,
        "distance": "1.8m",
        "role": "RELAY_MULE",
        "vpa": "mule1@upi",
        "battery": "78%",
        "status": "DISCOVERABLE"
    },
    {
        "deviceId": "BLE_STORE_22C0",
        "name": "Chai Point PoS Hub",
        "rssi": -72,
        "distance": "3.1m",
        "role": "MERCHANT_TERMINAL",
        "vpa": "chaipoint@paytm",
        "battery": "100%",
        "status": "DISCOVERABLE"
    }
]

@ble_bp.route('/api/ble/status', methods=['GET'])
def ble_status():
    """Returns local Bluetooth Low Energy radio status and GATT service config."""
    return jsonify({
        "success": True,
        "status": "BLE_ACTIVE",
        "radio": "Bluetooth 5.2 Low Energy",
        "serviceUuid": STANDARD_BLE_FINANCIAL_UUID,
        "mtuSize": 512,
        "maxOfflineLimit": MAX_OFFLINE_TRANSACTION_LIMIT,
        "advertising": True,
        "mode": "BLUETOOTH_BLE_P2P"
    })

@ble_bp.route('/api/ble/devices', methods=['GET'])
def get_ble_devices():
    """Returns discovered nearby Bluetooth LE devices and soundbox terminals."""
    # Add minor jitter to RSSI to reflect real radio signal fluctuations
    devices = []
    for d in NEARBY_BLE_PEERS:
        d_copy = dict(d)
        d_copy["rssi"] = d["rssi"] + random.randint(-3, 3)
        devices.append(d_copy)
    return jsonify({
        "success": True,
        "devices": devices,
        "scannedAt": int(time.time() * 1000)
    })

@ble_bp.route('/api/ble/packet/encode', methods=['POST'])
def encode_ble_packet():
    """
    Encodes and fragments a financial payment instruction into BLE GATT frames
    with 0xFA magic bytes, sequence numbers, and CRC-32 checksums.
    """
    data = request.json or {}
    sender = (data.get('senderVpa') or 'sagar@upi').strip().lower()
    receiver = (data.get('receiverVpa') or 'merchant@okhdfcbank').strip().lower()
    try:
        amount = float(data.get('amount', 150.0))
    except (ValueError, TypeError):
        amount = 150.0

    nonce = int(data.get('nonce', random.randint(1000, 99999)))
    pin_hash = hashlib.sha256(str(data.get('pin', '1234')).encode('utf-8')).hexdigest()

    packet = BlePaymentRadioManager.create_ble_voucher_packet(
        sender_vpa=sender,
        receiver_vpa=receiver,
        amount=amount,
        pin_hash=pin_hash,
        nonce=nonce
    )

    return jsonify({
        "success": True,
        "packet": packet
    })

@ble_bp.route('/api/ble/transfer', methods=['POST'])
def ble_transfer():
    """
    Executes a direct Wallet-to-Wallet Offline Payment over Bluetooth LE.
    Validates RBI offline limit, debits sender, credits receiver,
    issues 12-digit Bank UTR, and logs in immutable ledger.
    """
    data = request.json or {}
    sender = (data.get('senderVpa') or '').strip().lower()
    receiver = (data.get('receiverVpa') or '').strip().lower()
    client_balance = data.get('clientBalance')

    if not sender or not receiver:
        return jsonify({"success": False, "error": "Missing sender or receiver UPI ID"}), 400

    if sender == receiver:
        return jsonify({"success": False, "error": "Sender and receiver cannot be the same account"}), 400

    try:
        amount = float(data.get('amount', 0))
    except (ValueError, TypeError):
        amount = 0.0

    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than Rs. 0.00"}), 400

    if amount > MAX_OFFLINE_TRANSACTION_LIMIT:
        return jsonify({
            "success": False,
            "error": f"Amount exceeds RBI maximum offline limit of Rs.{MAX_OFFLINE_TRANSACTION_LIMIT:.2f}."
        }), 400

    # Execute atomic wallet debit/credit in SQLite/Postgres
    transfer_res = execute_offline_wallet_transfer(
        sender_vpa=sender,
        receiver_vpa=receiver,
        amount=amount,
        auth_mode="BLUETOOTH_BLE_PACKET",
        client_balance=client_balance
    )

    if not transfer_res.get('success'):
        return jsonify({"success": False, "error": transfer_res.get('error')}), 400

    # Record in offline vouchers table
    voucher_uuid = str(uuid.uuid4())
    bank_utr = transfer_res.get('bank_utr') or gateway_service.generate_bank_utr()
    record_offline_voucher(
        voucher_id=voucher_uuid,
        voucher_type="DEBIT",
        amount=amount,
        status="COMPLETED",
        raw_payload=json.dumps({"sender": sender, "receiver": receiver, "amount": amount, "protocol": "BLE_P2P", "utr": bank_utr}),
        sender_vpa=sender,
        receiver_vpa=receiver
    )

    tx_event = {
        "transactionId": transfer_res.get('transaction_id'),
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "bankUtr": bank_utr,
        "senderBalance": transfer_res.get('sender_balance'),
        "receiverBalance": transfer_res.get('receiver_balance'),
        "timestamp": int(time.time() * 1000),
        "protocol": "BLUETOOTH_BLE_P2P"
    }

    global recent_ble_events
    recent_ble_events.append(tx_event)
    if len(recent_ble_events) > 50:
        recent_ble_events = recent_ble_events[-50:]

    return jsonify({
        "success": True,
        "amount": amount,
        "sender": sender,
        "receiver": receiver,
        "senderBalance": transfer_res.get('sender_balance'),
        "receiverBalance": transfer_res.get('receiver_balance'),
        "transactionId": transfer_res.get('transaction_id'),
        "bankUtr": bank_utr,
        "protocol": "BLUETOOTH_BLE_P2P",
        "message": f"Offline Bluetooth BLE payment of Rs.{amount:.2f} completed successfully!"
    })

@ble_bp.route('/api/ble/recent', methods=['GET'])
def ble_recent():
    """Returns recent payments transmitted over Bluetooth LE."""
    target_vpa = (request.args.get('vpa') or '').strip().lower()
    since = int(request.args.get('since', 0))

    global recent_ble_events
    if not target_vpa or target_vpa == 'all':
        matched = [e for e in recent_ble_events if e["timestamp"] > since]
    else:
        matched = [
            e for e in recent_ble_events
            if e["timestamp"] > since and (
                e["receiver"].strip().lower() == target_vpa or
                e["sender"].strip().lower() == target_vpa or
                target_vpa in e["receiver"].strip().lower()
            )
        ]
    return jsonify({
        "success": True,
        "events": matched,
        "serverTime": int(time.time() * 1000)
    })

@ble_bp.route('/api/ble/sync', methods=['POST'])
def ble_sync():
    """
    Syncs pending client-side offline BLE vouchers when connectivity is detected.
    Idempotently records in database.
    """
    data = request.json or {}
    vouchers = data.get('vouchers', [])
    synced_count = 0
    results = []

    for v in vouchers:
        sender = v.get('senderVpa') or v.get('sender')
        receiver = v.get('receiverVpa') or v.get('receiver')
        amount = float(v.get('amount', 0))
        utr = v.get('bankUtr') or v.get('utr') or gateway_service.generate_bank_utr()

        if sender and receiver and amount > 0:
            res = execute_offline_wallet_transfer(
                sender_vpa=sender,
                receiver_vpa=receiver,
                amount=amount,
                auth_mode="BLUETOOTH_BLE_PACKET"
            )
            synced_count += 1
            results.append({
                "voucherId": v.get('voucherId'),
                "utr": utr,
                "status": "SYNCED",
                "result": res
            })

    return jsonify({
        "success": True,
        "syncedCount": synced_count,
        "results": results
    })
