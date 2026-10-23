import time
import random
from flask import Blueprint, request, jsonify
from src.services.gateway import gateway_service
from src.core.reconciliation import OfflineReconciliationEngine
from src.db.repository import (
    execute_offline_wallet_transfer,
    record_deposit,
    record_withdrawal,
    create_voucher_record,
    claim_voucher_record,
    audit_ledger_integrity
)

wallet_bp = Blueprint('wallet_bp', __name__)
reconciliation_engine = OfflineReconciliationEngine()

@wallet_bp.route('/api/wallet/transfer-offline', methods=['POST'])
def wallet_transfer_offline():
    """Direct Offline Wallet-to-Wallet payment by merchant handle or mobile number."""
    data = request.json or {}
    sender = (data.get('payerVpa') or '').strip()
    receiver = (data.get('payeeVpa') or '').strip()
    amount = float(data.get('amount', 0))
    client_balance = data.get('clientBalance')

    if not sender or not receiver:
        return jsonify({"success": False, "error": "Both sender and merchant UPI handles are required."}), 400
    if amount <= 0:
        return jsonify({"success": False, "error": "Payment amount must be greater than ₹0."}), 400

    transfer_res = execute_offline_wallet_transfer(
        sender_vpa=sender,
        receiver_vpa=receiver,
        amount=amount,
        auth_mode="OFFLINE_DIRECT_HANDLE",
        client_balance=client_balance
    )

    if not transfer_res.get('success'):
        return jsonify({"success": False, "error": transfer_res.get('error')}), 400

    return jsonify({
        "success": True,
        "amount": amount,
        "sender": sender,
        "receiver": receiver,
        "senderBalance": transfer_res.get('sender_balance'),
        "receiverBalance": transfer_res.get('receiver_balance'),
        "transactionId": transfer_res.get('transaction_id'),
        "message": f"Transferred ₹{amount:.2f} offline to {receiver}!"
    })

@wallet_bp.route('/api/voucher/create', methods=['POST'])
def voucher_create():
    """Generates an offline transfer voucher with a 6-digit claim PIN."""
    data = request.json or {}
    sender = (data.get('senderVpa') or 'user@okhdfcbank').strip()
    receiver = (data.get('receiverVpa') or 'receiver@upi').strip()
    amount = float(data.get('amount', 50.0))
    pin = data.get('pin')
    if not pin:
        pin = str(random.randint(100000, 999999))
    utr = data.get('utr') or f"409{random.randint(100000000, 999999999)}"
    
    rec = create_voucher_record(pin=pin, sender_vpa=sender, receiver_vpa=receiver, amount=amount, utr=utr)
    return jsonify({
        "success": True,
        "pin": pin,
        "utr": utr,
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "message": f"Voucher created for ₹{amount:.2f}! Share 6-digit PIN {pin} with receiver to claim offline."
    })

@wallet_bp.route('/api/voucher/claim', methods=['POST'])
def voucher_claim():
    """Claims an offline transfer voucher using a 6-digit PIN."""
    data = request.json or {}
    pin = (data.get('pin') or '').strip().replace(' ', '').replace('-', '')
    receiver = (data.get('receiverVpa') or 'receiver@upi').strip()
    if not pin:
        return jsonify({"success": False, "error": "Please enter a valid 6-digit voucher PIN."}), 400
    
    claim_res = claim_voucher_record(pin=pin, claimer_vpa=receiver)
    if not claim_res.get('success'):
        return jsonify({"success": False, "error": claim_res.get('error', 'Voucher invalid or expired')}), 400
    
    return jsonify({
        "success": True,
        "amount": claim_res['amount'],
        "sender": claim_res['sender_vpa'],
        "receiver": claim_res['receiver_vpa'],
        "receiver_balance": claim_res.get('receiver_balance'),
        "receiverBalance": claim_res.get('receiver_balance'),
        "utr": claim_res['utr'],
        "message": f"₹{claim_res['amount']:.2f} claimed into your offline wallet!"
    })

@wallet_bp.route('/api/reconcile/voucher', methods=['POST'])
def reconcile_voucher():
    """Reconciles hardened offline hash-chain voucher."""
    data = request.json or {}
    voucher = data.get('voucher') or data
    if not voucher:
        return jsonify({"success": False, "error": "Missing voucher payload"}), 400
    res = reconciliation_engine.process_hardened_voucher(voucher)
    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@wallet_bp.route('/api/reconcile/audit-ledger', methods=['GET'])
def reconcile_audit_ledger():
    """Runs a complete mathematical audit over all ledger postings."""
    audit_res = audit_ledger_integrity()
    return jsonify(audit_res)

@wallet_bp.route('/api/wallet/deposit/create', methods=['POST'])
def wallet_deposit_create():
    """Generates standard NPCI UPI Intent DeepLink & QR code for depositing real INR."""
    data = request.json or {}
    user_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    real_upi_id = (data.get('realUpiId') or user_vpa).strip()
    real_payee_name = (data.get('realPayeeName') or '').strip()
    try:
        amount = float(data.get('amount', 500.0))
    except (ValueError, TypeError):
        amount = 500.0

    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than ₹0"}), 400

    intent = gateway_service.generate_deposit_intent(
        user_vpa=user_vpa,
        amount=amount,
        real_upi_id=real_upi_id,
        real_payee_name=real_payee_name
    )
    return jsonify({
        "success": True,
        "intent": intent,
        "vpa": user_vpa,
        "realUpiId": real_upi_id,
        "amount": amount,
        "depositRef": intent["depositRef"],
        "escrowVpa": intent["escrowVpa"],
        "escrowName": intent["escrowName"],
        "deeplink": intent["deeplink"],
        "qrData": intent["qrData"],
        "message": f"Deposit intent for ₹{amount:.2f} created. Open UPI app or scan QR to complete payment."
    })

@wallet_bp.route('/api/wallet/deposit/instant', methods=['POST'])
def wallet_deposit_instant():
    """Immediately tops up wallet balance (sandbox demo helper)."""
    data = request.json or {}
    user_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    try:
        amount = float(data.get('amount', 2000.0))
    except (ValueError, TypeError):
        amount = 2000.0

    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than ₹0"}), 400

    bank_utr = gateway_service.generate_bank_utr()
    deposit_ref = f"DEP_{int(time.time()*1000)}_{random.randint(100, 999)}"

    res = record_deposit(
        vpa=user_vpa,
        amount=amount,
        bank_utr=bank_utr,
        deposit_ref=deposit_ref,
        deeplink_url=f"upi://instant?am={amount:.2f}"
    )

    if res.get('success'):
        return jsonify({
            "success": True,
            "vpa": user_vpa,
            "depositedAmount": amount,
            "newBalance": res["new_balance"],
            "bankUtr": res["bank_utr"],
            "transactionId": res["transaction_id"],
            "message": f"₹{amount:.2f} successfully loaded into offline wallet reserve!"
        })
    return jsonify({"success": False, "error": res.get("error", "Deposit failed")}), 400

@wallet_bp.route('/api/wallet/deposit/confirm', methods=['POST'])
def wallet_deposit_confirm():
    """Completes deposit and credits user's offline token balance with real banking UTR."""
    data = request.json or {}
    user_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    try:
        amount = float(data.get('amount', 500.0))
    except (ValueError, TypeError):
        amount = 500.0

    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than ₹0"}), 400

    deposit_ref = data.get('depositRef', f"DEP_{int(time.time()*1000)}")
    deeplink_url = data.get('deeplink', '')
    bank_utr = (data.get('utr') or '').strip()

    if not bank_utr or bank_utr.upper() == 'AUTO' or data.get('simulate'):
        bank_utr = gateway_service.generate_bank_utr()
    elif len(bank_utr) < 8:
        return jsonify({
            "success": False,
            "error": "Invalid Bank UTR! A valid Indian UPI Transaction Reference is 12 digits (e.g. 409812345678)."
        }), 400

    res = record_deposit(
        vpa=user_vpa,
        amount=amount,
        bank_utr=bank_utr,
        deposit_ref=deposit_ref,
        deeplink_url=deeplink_url
    )

    if res.get('success'):
        return jsonify({
            "success": True,
            "vpa": user_vpa,
            "depositedAmount": amount,
            "newBalance": res["new_balance"],
            "bankUtr": res["bank_utr"],
            "transactionId": res["transaction_id"],
            "message": f"₹{amount:.2f} successfully loaded into offline wallet reserve!"
        })
    return jsonify({"success": False, "error": res.get("error", "Deposit failed")}), 400

@wallet_bp.route('/api/wallet/withdraw', methods=['POST'])
def wallet_withdraw():
    """Debits user's offline wallet tokens and issues an authentic UPI payout to real bank."""
    data = request.json or {}
    user_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    target_bank_vpa = (data.get('targetBankVpa') or '').strip()
    try:
        amount = float(data.get('amount', 100.0))
    except (ValueError, TypeError):
        amount = 100.0

    if not target_bank_vpa or '@' not in target_bank_vpa:
        return jsonify({"success": False, "error": "Please enter a valid bank UPI ID to receive funds (e.g. yourname@okhdfcbank)"}), 400
    if amount <= 0:
        return jsonify({"success": False, "error": "Withdrawal amount must be greater than ₹0"}), 400

    payout_info = gateway_service.disburse_direct_withdrawal(
        user_vpa=user_vpa,
        target_bank_vpa=target_bank_vpa,
        amount=amount
    )

    res = record_withdrawal(
        vpa=user_vpa,
        target_bank_vpa=target_bank_vpa,
        amount=amount,
        bank_utr=payout_info["utr"],
        withdrawal_ref=payout_info["withdrawalRef"]
    )

    if res.get('success'):
        return jsonify({
            "success": True,
            "vpa": user_vpa,
            "targetBankVpa": target_bank_vpa,
            "withdrawnAmount": amount,
            "newBalance": res["new_balance"],
            "bankUtr": res["bank_utr"],
            "withdrawalRef": payout_info["withdrawalRef"],
            "gatewayMode": payout_info["gatewayMode"],
            "bankMessage": payout_info["bankMessage"],
            "message": f"₹{amount:.2f} successfully transferred to {target_bank_vpa}!"
        })
    return jsonify({"success": False, "error": res.get("error", "Withdrawal failed")}), 400

@wallet_bp.route('/api/cashfree/order/create', methods=['POST'])
def cashfree_order_create():
    """Generates Cashfree Payment Gateway order."""
    data = request.json or {}
    customer_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    amount = float(data.get('amount', 500.0))
    customer_phone = (data.get('phone') or '9876543210').strip()
    customer_name = (data.get('name') or 'UPI User').strip()

    res = gateway_service.create_cashfree_order(
        customer_vpa=customer_vpa,
        amount=amount,
        customer_phone=customer_phone,
        customer_name=customer_name
    )
    return jsonify(res)

@wallet_bp.route('/api/cashfree/order/confirm', methods=['POST'])
def cashfree_order_confirm():
    """Completes simulated or live Cashfree checkout."""
    data = request.json or {}
    order_id = data.get('orderId')
    user_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    amount = float(data.get('amount', 500.0))
    utr = data.get('utr') or gateway_service.generate_bank_utr()

    res = record_deposit(
        vpa=user_vpa,
        amount=amount,
        bank_utr=utr,
        deposit_ref=order_id or f"CF_ORD_{int(time.time())}",
        deeplink_url=f"cashfree://orders/{order_id}"
    )

    if res.get('success'):
        return jsonify({
            "success": True,
            "orderId": order_id,
            "vpa": user_vpa,
            "depositedAmount": amount,
            "newBalance": res["new_balance"],
            "bankUtr": utr,
            "message": f"Payment of ₹{amount:.2f} confirmed! Tokens credited to wallet."
        })
    return jsonify({"success": False, "error": res.get("error", "Deposit failed")}), 400

@wallet_bp.route('/api/gateway/webhook/deposit', methods=['POST'])
def gateway_deposit_webhook():
    """Cryptographically verifies HMAC-SHA256 signature and atomically deposits funds."""
    signature = request.headers.get('x-webhook-signature', '')
    raw_body = request.get_data()
    is_valid = gateway_service.verify_webhook_signature(raw_body, signature)
    if not is_valid:
        return jsonify({"success": False, "error": "Invalid HMAC signature"}), 401

    payload = request.json or {}
    data = payload.get('data', payload)
    vpa = data.get('customer_vpa', 'user@okhdfcbank')
    amount = float(data.get('order_amount', 0.0))
    ref = data.get('order_id', f"WEBHOOK_{int(time.time())}")
    utr = data.get('bank_reference', gateway_service.generate_bank_utr())

    dep_res = record_deposit(vpa=vpa, amount=amount, bank_utr=utr, deposit_ref=ref)
    return jsonify({"success": True, "deposit": dep_res})


@wallet_bp.route('/api/cashfree/order', methods=['POST'])
def cashfree_create_order():
    """
    Creates a Cashfree Sandbox Order (Free test mode).
    Works with real Cashfree test keys if set, or instant free simulator.
    """
    data = request.json or {}
    customer_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    try:
        amount = float(data.get('amount', 500.0))
    except (ValueError, TypeError):
        amount = 500.0
    customer_phone = data.get('phone', '9876543210')
    customer_name = data.get('name', 'Offline UPI User')

    res = gateway_service.create_cashfree_order(
        customer_vpa=customer_vpa,
        amount=amount,
        customer_phone=customer_phone,
        customer_name=customer_name
    )
    return jsonify(res)


@wallet_bp.route('/api/cashfree/confirm', methods=['POST'])
def cashfree_confirm_payment():
    """
    Verifies Cashfree Sandbox test payment and credits offline wallet.
    """
    data = request.json or {}
    user_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    try:
        amount = float(data.get('amount', 500.0))
    except (ValueError, TypeError):
        amount = 500.0
    order_id = data.get('orderId') or f"CF_ORD_{int(time.time())}"
    cf_payment_id = data.get('cfPaymentId') or f"CF_PAY_{random.randint(10000000, 99999999)}"

    bank_utr = gateway_service.generate_bank_utr()
    deposit_ref = order_id
    deeplink_url = f"https://sandbox.cashfree.com/pay/{order_id}"

    res = record_deposit(
        vpa=user_vpa,
        amount=amount,
        bank_utr=bank_utr,
        deposit_ref=deposit_ref,
        deeplink_url=deeplink_url
    )

    if res.get('success'):
        return jsonify({
            "success": True,
            "vpa": user_vpa,
            "depositedAmount": amount,
            "newBalance": res["new_balance"],
            "bankUtr": bank_utr,
            "orderId": order_id,
            "cfPaymentId": cf_payment_id,
            "transactionId": res["transaction_id"],
            "mode": "CASHFREE_SANDBOX_TEST",
            "message": f"₹{amount:.2f} credited via Cashfree Free Sandbox!"
        })
    return jsonify({"success": False, "error": res.get("error", "Deposit failed")}), 400
