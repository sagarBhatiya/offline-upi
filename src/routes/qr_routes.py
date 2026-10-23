from flask import Blueprint, request, jsonify
from src.core.crypto import qr_voucher_engine
from src.core.mesh import mesh_simulator
from src.db.repository import execute_offline_wallet_transfer

qr_bp = Blueprint('qr_bp', __name__)

@qr_bp.route('/api/qr/generate', methods=['POST'])
def qr_generate():
    """Generates an ECDSA P-256 signed offline Dynamic QR Voucher."""
    data = request.json or {}
    payer_vpa = (data.get('payerVpa') or 'sagar@upi').strip()
    payee_vpa = (data.get('payeeVpa') or 'merchant@upi').strip()
    try:
        amount = float(data.get('amount', 120.0))
    except (ValueError, TypeError):
        amount = 120.0
    try:
        nonce = int(data.get('nonce', 1))
    except (ValueError, TypeError):
        nonce = 1
    try:
        bounty = float(data.get('bounty', 0.25))
    except (ValueError, TypeError):
        bounty = 0.25

    voucher = qr_voucher_engine.create_signed_qr_voucher(
        payer_vpa=payer_vpa,
        payee_vpa=payee_vpa,
        amount=amount,
        nonce=nonce,
        bounty=bounty
    )
    return jsonify({
        "success": True,
        "voucher": voucher,
        "message": "Offline Dynamic QR generated & signed with ECDSA (P-256)!"
    })

@qr_bp.route('/api/qr/verify-scan', methods=['POST'])
def qr_verify_scan():
    """Verifies a scanned Dynamic QR Voucher and settles offline balance."""
    data = request.json or {}
    voucher = data.get('voucher')

    if not voucher:
        return jsonify({"success": False, "error": "Missing voucher object."}), 400

    payload = voucher.get('payload', {})
    signature_hex = voucher.get('signatureHex', '')
    public_key_pem = voucher.get('publicKeyPem')

    # 1. Cryptographic Verification
    is_valid = qr_voucher_engine.verify_qr_voucher(
        payload=payload,
        signature_hex=signature_hex,
        public_key_pem=public_key_pem
    )

    if not is_valid:
        return jsonify({
            "success": False,
            "error": "INVALID_SIGNATURE",
            "message": "Cryptographic signature check failed! Voucher has been tampered with."
        }), 400

    # 2. Execute Offline Balance Transfer
    payer_vpa = payload.get('payerVpa')
    payee_vpa = payload.get('payeeVpa')
    amount = float(payload.get('amount', 0))
    client_balance = payload.get('clientBalance') or data.get('clientBalance')

    transfer_res = execute_offline_wallet_transfer(
        sender_vpa=payer_vpa,
        receiver_vpa=payee_vpa,
        amount=amount,
        auth_mode="OFFLINE_QR_VOUCHER",
        voucher_sig=signature_hex,
        client_balance=client_balance
    )

    if not transfer_res.get('success'):
        return jsonify({
            "success": False,
            "error": "INSUFFICIENT_BALANCE",
            "message": transfer_res.get('error')
        }), 400

    # 3. Queue in mesh simulator
    packet = mesh_simulator.record_offline_scan(voucher)

    return jsonify({
        "success": True,
        "verified": True,
        "amount": amount,
        "payer": payer_vpa,
        "payee": payee_vpa,
        "senderBalance": transfer_res.get('sender_balance'),
        "receiverBalance": transfer_res.get('receiver_balance'),
        "transactionId": transfer_res.get('transaction_id'),
        "bounty": payload.get('bounty', 0.25),
        "queuedPacketId": packet["packetId"],
        "merchantVault": mesh_simulator.merchant_vault,
        "state": mesh_simulator.get_topology(),
        "message": f"Transferred ₹{amount:.2f} offline from {payer_vpa} to {payee_vpa}!"
    })
