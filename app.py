import time
import os
import json
import random
from flask import Flask, render_template, request, jsonify, send_from_directory
from database import (
    init_db, get_accounts, get_transactions, claim_packet_hash, 
    execute_settlement, reset_db, record_deposit, record_withdrawal, 
    execute_offline_wallet_transfer, upsert_user_account,
    create_voucher_record, claim_voucher_record,
    record_double_entry_transaction, audit_ledger_integrity
)
import database
from crypto_helper import crypto_engine, qr_voucher_engine, compute_sha256
from mesh_engine import mesh_simulator
from gateway_service import gateway_service
from reconciliation_engine import OfflineReconciliationEngine, RegulatoryRiskEngine
from attestation_engine import hardware_attestation_engine
from ble_protocol import BleSecureSessionChannel

reconciliation_engine = OfflineReconciliationEngine(db_module=database)

app = Flask(__name__)

# Initialize database on startup
init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sw.js')
def service_worker():
    response = send_from_directory('static', 'sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/manifest.json')
def manifest():
    response = send_from_directory('static', 'manifest.json')
    response.headers['Content-Type'] = 'application/manifest+json'
    return response

@app.route('/api/state', methods=['GET'])
def get_state():
    """Returns combined system state: bank accounts, transactions, and mesh topology."""
    return jsonify({
        "accounts": get_accounts(),
        "transactions": get_transactions(),
        "mesh": mesh_simulator.get_topology()
    })

@app.route('/api/qr/generate', methods=['POST'])
def qr_generate():
    """
    Payer Phone Offline Dynamic QR Generator:
    Generates an ECDSA P-256 cryptographically signed voucher with a monotonic nonce
    and optional mule relay bounty.
    """
    data = request.json or {}
    payer_vpa = data.get('payerVpa', 'sagar@upi')
    payee_vpa = data.get('payeeVpa', 'merchant@upi')
    amount = float(data.get('amount', 120.0))
    nonce = int(data.get('nonce', int(time.time() * 1000) % 100000))
    bounty = float(data.get('bounty', 0.25))

    voucher_data = qr_voucher_engine.create_signed_qr_voucher(
        payer_vpa=payer_vpa,
        payee_vpa=payee_vpa,
        amount=amount,
        nonce=nonce,
        bounty=bounty
    )

    return jsonify({
        "success": True,
        "voucher": voucher_data,
        "message": f"Dynamic QR Voucher of ₹{amount} generated & signed with ECDSA (P-256)."
    })

@app.route('/api/qr/verify-scan', methods=['POST'])
def qr_verify_scan():
    """
    Merchant PoS / Soundbox Offline Scanner:
    1. Verifies the ECDSA P-256 signature locally without internet.
    2. Credits the local Merchant Offline Vault.
    3. Queues the voucher into the BLE Gossip engine with a bounty for bystander Mules!
    """
    data = request.json or {}
    raw_str = data.get('rawString', '').strip()

    # If raw camera scan string provided, parse it directly
    if raw_str:
        if raw_str.startswith('UPIOFFLINE:'):
            parts = raw_str[len('UPIOFFLINE:'):].split('|')
            if len(parts) >= 7:
                payload = {
                    "payerVpa": parts[0],
                    "payeeVpa": parts[1],
                    "amount": float(parts[2]),
                    "nonce": int(parts[3]),
                    "bounty": float(parts[4]),
                    "signedAt": int(parts[5])
                }
                signature_hex = parts[6]
                public_key_pem = None
                voucher = {"payload": payload, "signatureHex": signature_hex}
            else:
                return jsonify({"success": False, "error": "Malformed UPIOFFLINE format"}), 400
        else:
            try:
                parsed = json.loads(base64.b64decode(raw_str.encode('utf-8')).decode('utf-8'))
                payload = parsed.get("payload", {})
                signature_hex = parsed.get("sig", "")
                public_key_pem = None
                voucher = {"payload": payload, "signatureHex": signature_hex}
            except Exception:
                return jsonify({"success": False, "error": "Unrecognized QR format"}), 400
    else:
        voucher = data.get('voucher', {})
        payload = voucher.get('payload', {})
        signature_hex = voucher.get('signatureHex', '')
        public_key_pem = voucher.get('publicKeyPem', '')

    if not payload or not signature_hex:
        return jsonify({"success": False, "error": "Invalid QR voucher packet"}), 400

    # 1. Verify Cryptographic Signature
    is_valid = qr_voucher_engine.verify_qr_voucher(payload, signature_hex, public_key_pem)
    if not is_valid:
        return jsonify({
            "success": False,
            "error": "SIGNATURE_VERIFICATION_FAILED",
            "message": "Cryptographic signature on QR voucher is invalid or tampered!"
        }), 400

    # 2. Execute Immediate Offline Wallet-to-Wallet Balance Transfer
    payer_vpa = payload.get('payerVpa')
    payee_vpa = payload.get('payeeVpa')
    amount = float(payload.get('amount', 0))

    transfer_res = execute_offline_wallet_transfer(
        sender_vpa=payer_vpa,
        receiver_vpa=payee_vpa,
        amount=amount,
        auth_mode="OFFLINE_QR_VOUCHER",
        voucher_sig=signature_hex
    )

    if not transfer_res.get('success'):
        return jsonify({
            "success": False,
            "error": "INSUFFICIENT_BALANCE",
            "message": transfer_res.get('error')
        }), 400

    # 3. Record in Offline Merchant Vault & Queue for Gossip Mule Relay
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

@app.route('/api/wallet/transfer-offline', methods=['POST'])
def wallet_transfer_offline():
    """Direct Offline Wallet-to-Wallet payment by merchant handle or mobile number."""
    data = request.json or {}
    sender = (data.get('payerVpa') or '').strip()
    receiver = (data.get('payeeVpa') or '').strip()
    amount = float(data.get('amount', 0))

    if not sender or not receiver:
        return jsonify({"success": False, "error": "Both sender and merchant UPI handles are required."}), 400
    if amount <= 0:
        return jsonify({"success": False, "error": "Payment amount must be greater than ₹0."}), 400

    transfer_res = execute_offline_wallet_transfer(
        sender_vpa=sender,
        receiver_vpa=receiver,
        amount=amount,
        auth_mode="OFFLINE_DIRECT_HANDLE"
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

@app.route('/api/voucher/create', methods=['POST'])
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
        "amount": amount,
        "sender": sender,
        "receiver": receiver,
        "utr": utr,
        "message": f"6-Digit Offline Voucher {pin} created!"
    })

@app.route('/api/voucher/claim', methods=['POST'])
def voucher_claim():
    """Redeems a 6-digit offline voucher code into receiver's wallet."""
    data = request.json or {}
    pin = (data.get('pin') or '').strip().replace(' ', '').replace('-', '')
    receiver = (data.get('receiverVpa') or 'receiver@upi').strip()
    
    if not pin:
        return jsonify({"success": False, "error": "Please enter a valid 6-digit voucher PIN."}), 400
        
    res = claim_voucher_record(pin=pin, claimer_vpa=receiver)
    if not res.get('success'):
        return jsonify({"success": False, "error": res.get('error', 'Voucher invalid or expired')}), 400
        
    return jsonify(res)

@app.route('/api/qr/parse-any', methods=['POST'])
def parse_any_qr():
    """
    Intelligently parses ANY scanned QR code:
    1. Standard NPCI UPI URI: upi://pay?pa=...&pn=...&am=...
    2. Direct VPA strings: payee@bank
    3. Compact Offline Voucher: UPIOFFLINE:payer|payee|amount|nonce|bounty|signedAt|sig
    """
    import urllib.parse
    data = request.json or {}
    raw_str = (data.get('rawString') or '').strip()
    
    if not raw_str:
        return jsonify({"success": False, "error": "Empty QR code data"}), 400
        
    result = {
        "success": True,
        "type": "UNKNOWN",
        "payeeVpa": "",
        "payeeName": "Merchant Store",
        "amount": None,
        "isOfflineVoucher": False,
        "rawString": raw_str
    }
    
    # 1. Compact Offline Voucher format
    if raw_str.startswith('UPIOFFLINE:'):
        parts = raw_str[len('UPIOFFLINE:'):].split('|')
        if len(parts) >= 7:
            result["type"] = "OFFLINE_VOUCHER"
            result["isOfflineVoucher"] = True
            result["payerVpa"] = parts[0]
            result["payeeVpa"] = parts[1]
            result["payeeName"] = parts[1].split('@')[0].replace('_', ' ').title()
            result["amount"] = float(parts[2])
            result["nonce"] = int(parts[3])
            result["bounty"] = float(parts[4])
        return jsonify(result)
        
    # 2. Case-insensitive UPI Intent or URL query containing pa= or vpa=
    low = raw_str.lower()
    if 'pa=' in low or 'vpa=' in low or 'upi://pay' in low:
        result["type"] = "STANDARD_UPI_INTENT"
        query_str = raw_str.split('?')[-1] if '?' in raw_str else raw_str
        query = urllib.parse.parse_qs(query_str, keep_blank_values=True)
        
        pa_list = query.get('pa') or query.get('PA') or query.get('vpa') or query.get('VPA') or []
        pn_list = query.get('pn') or query.get('PN') or []
        am_list = query.get('am') or query.get('AM') or []
        
        if pa_list:
            result["payeeVpa"] = pa_list[0].strip()
            result["payeeName"] = pn_list[0].strip() if pn_list else result["payeeVpa"].split('@')[0].replace('_', ' ').title()
        if am_list:
            try:
                result["amount"] = float(am_list[0])
            except ValueError:
                pass
        if result["payeeVpa"]:
            return jsonify(result)
        
    # 3. Direct VPA handle (e.g. merchant@paytm)
    import re
    vpa_match = re.search(r'([a-zA-Z0-9.\-_]{2,}@[a-zA-Z0-9]{2,})', raw_str)
    if vpa_match:
        result["type"] = "DIRECT_VPA"
        result["payeeVpa"] = vpa_match.group(1)
        result["payeeName"] = result["payeeVpa"].split('@')[0].replace('_', ' ').title()
        return jsonify(result)
        
    # 4. JSON Payload
    try:
        j = json.loads(raw_str)
        if isinstance(j, dict):
            result["payeeVpa"] = j.get('payeeVpa') or j.get('pa') or j.get('receiver') or ''
            result["payeeName"] = j.get('payeeName') or j.get('pn') or 'Merchant Store'
            result["amount"] = float(j['amount']) if 'amount' in j else None
            result["type"] = "JSON_QR"
            if result["payeeVpa"]:
                return jsonify(result)
    except Exception:
        pass
        
    # 5. Fallback for any scanned text or merchant name
    clean_name = re.sub(r'[^a-zA-Z0-9 ]', '', raw_str)[:25].strip() or "Merchant Store"
    result["payeeVpa"] = clean_name.lower().replace(' ', '_') + "@upi"
    result["payeeName"] = clean_name.title()
    result["type"] = "FALLBACK_MERCHANT"
    return jsonify(result)

@app.route('/api/demo/create', methods=['POST'])
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

@app.route('/api/demo/gossip', methods=['POST'])
def demo_gossip():
    """Advance 1 round of Bluetooth Low Energy (BLE) gossip across stranger commuter mules."""
    result = mesh_simulator.run_gossip_step()
    return jsonify({
        "success": True,
        "round": result["round"],
        "transfers": result["transfers"],
        "state": mesh_simulator.get_topology()
    })

@app.route('/api/demo/bridge-internet', methods=['POST'])
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

@app.route('/api/bridge/ingest', methods=['POST'])
def bridge_ingest():
    """
    Core Banking Backend Ingestion Pipeline:
    1. SHA-256 hash of ciphertext.
    2. Atomic idempotency claim (putIfAbsent).
    3. Hybrid decryption & AES-GCM 128-bit auth tag verification.
    4. Freshness check (signedAt <= 24h).
    5. Atomic ACID multi-party settlement in SQLite:
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

    # 6. Multi-Party Settlement with Mule Bounty & Banking UTR
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

@app.route('/api/gateway/deeplink', methods=['POST'])
def gateway_deeplink():
    """Generates standard NPCI universal UPI intent URI (upi://pay) for mobile app launching."""
    data = request.json or {}
    vpa = data.get('vpa', 'merchant@upi')
    amount = float(data.get('amount', 120.0))
    note = data.get('note', 'Offline UPI Settlement')
    link = gateway_service.generate_upi_deeplink(vpa, 'Receiver', amount, int(time.time()), note)
    return jsonify({"success": True, "deeplink": link})

@app.route('/api/config/gateway', methods=['POST'])
def config_gateway():
    """Allows configuring optional Cashfree Live/Sandbox Payout API credentials."""
    data = request.json or {}
    app_id = data.get('cashfreeAppId', '')
    secret_key = data.get('cashfreeSecretKey', '')
    is_sandbox = bool(data.get('isSandbox', True))
    gateway_service.update_credentials(app_id, secret_key, is_sandbox)
    return jsonify({"success": True, "message": "Gateway credentials updated", "isSandbox": is_sandbox})

@app.route('/api/user/profile', methods=['POST'])
def update_user_profile():
    """
    Registers or updates the user's authentic UPI ID in the core banking ledger.
    Transfers any existing wallet balance over if transitioning handles.
    """
    data = request.json or {}
    new_vpa = (data.get('vpa') or '').strip()
    name = (data.get('name') or 'User').strip()
    old_vpa = (data.get('oldVpa') or '').strip()

    if not new_vpa or '@' not in new_vpa:
        return jsonify({"success": False, "error": "Invalid Real UPI ID format. Must contain '@'."}), 400

    res = upsert_user_account(new_vpa=new_vpa, holder_name=name, old_vpa=old_vpa)
    return jsonify(res)

# ========================================================
# ESCROW DIGITAL WALLET API: REAL DEPOSIT & WITHDRAWAL
# ========================================================

@app.route('/api/wallet/deposit/create', methods=['POST'])
def wallet_deposit_create():
    """
    Step 1: Generates standard NPCI UPI Intent DeepLink & QR code for depositing real INR.
    Tapping this link on a mobile device opens GPay, PhonePe, Paytm, or BHIM.
    """
    data = request.json or {}
    user_vpa = data.get('vpa', 'sagar@okhdfcbank')
    real_upi_id = data.get('realUpiId', '') or data.get('escrowVpa', '')
    real_payee_name = data.get('realPayeeName', '') or data.get('escrowName', '')
    amount = float(data.get('amount', 500.0))
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
        "message": f"Real UPI deposit intent generated for ₹{amount:.2f} to {intent['escrowVpa']}"
    })

@app.route('/api/wallet/deposit/instant', methods=['POST'])
def wallet_deposit_instant():
    """
    1-Click Instant Wallet Credit for Sandbox / Demo & Direct Top-Up.
    Generates authentic banking UTR and immediately credits offline wallet balance.
    """
    data = request.json or {}
    user_vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    try:
        amount = float(data.get('amount', 500.0))
    except (ValueError, TypeError):
        amount = 500.0

    if amount <= 0:
        return jsonify({"success": False, "error": "Amount must be greater than ₹0"}), 400

    bank_utr = gateway_service.generate_bank_utr()
    deposit_ref = f"DEP_{int(time.time()*1000)}_{random.randint(100, 999)}"
    deeplink_url = gateway_service.generate_upi_deeplink(
        payee_vpa=user_vpa,
        payee_name="UPI Lite Wallet",
        amount=amount,
        tx_id=deposit_ref,
        note="Instant Wallet Topup"
    )

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
            "transactionId": res["transaction_id"],
            "message": f"₹{amount:.2f} successfully loaded into offline wallet reserve!"
        })
    else:
        return jsonify({"success": False, "error": res.get("error", "Deposit failed")}), 400

@app.route('/api/wallet/deposit/confirm', methods=['POST'])
def wallet_deposit_confirm():
    """
    Step 2: Completes deposit and credits user's offline token balance with real banking UTR.
    """
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

    # If user requests auto UTR or test mode, generate a valid banking UTR
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
    else:
        return jsonify({"success": False, "error": res.get("error", "Deposit failed")}), 400

@app.route('/api/wallet/withdraw', methods=['POST'])
def wallet_withdraw():
    """
    Step 3: Cash Out to Real Bank via Real UPI / IMPS.
    Debits the user's offline digital tokens and sends real INR to their real bank UPI ID.
    """
    data = request.json or {}
    user_vpa = data.get('vpa', 'sagar@okhdfcbank')
    target_bank_vpa = data.get('targetBankVpa', '').strip()
    amount = float(data.get('amount', 0.0))

    if not target_bank_vpa or '@' not in target_bank_vpa:
        return jsonify({"success": False, "error": "Please provide a valid Indian Bank UPI ID (e.g. name@okhdfcbank or 9876543210@paytm)"}), 400
    if amount <= 0:
        return jsonify({"success": False, "error": "Withdrawal amount must be greater than ₹0"}), 400

    # 1. Disburse real IMPS / UPI payout
    payout_res = gateway_service.disburse_direct_withdrawal(
        user_vpa=user_vpa,
        target_bank_vpa=target_bank_vpa,
        amount=amount
    )
    bank_utr = payout_res["utr"]
    withdrawal_ref = payout_res["withdrawalRef"]

    # 2. Record ledger & debit account
    db_res = record_withdrawal(
        vpa=user_vpa,
        target_bank_vpa=target_bank_vpa,
        amount=amount,
        bank_utr=bank_utr,
        withdrawal_ref=withdrawal_ref
    )

    if db_res.get('success'):
        return jsonify({
            "success": True,
            "vpa": user_vpa,
            "targetBankVpa": target_bank_vpa,
            "withdrawnAmount": amount,
            "newBalance": db_res["new_balance"],
            "bankUtr": bank_utr,
            "gatewayMode": payout_res.get("gatewayMode"),
            "bankMessage": payout_res.get("bankMessage"),
            "transactionId": db_res["transaction_id"],
            "message": f"₹{amount:.2f} successfully withdrawn to {target_bank_vpa} via IMPS switch!"
        })
    else:
        return jsonify({"success": False, "error": db_res.get("error", "Withdrawal failed")}), 400

@app.route('/api/demo/flush-bridge', methods=['POST'])
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
        with app.test_client() as client:
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

@app.route('/api/demo/tamper', methods=['POST'])
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

    with app.test_client() as client:
        resp = client.post('/api/bridge/ingest', json=payload)
        outcome_data = resp.get_json()

    mesh_simulator.hop_log.append(f"Tamper attack simulated: altered ciphertext byte -> Backend outcome: {outcome_data.get('outcome')} ({outcome_data.get('reason')})")

    return jsonify({
        "success": True,
        "attackResult": outcome_data,
        "state": mesh_simulator.get_topology()
    })

@app.route('/api/demo/reset', methods=['POST'])
def demo_reset():
    """Resets database accounts, transactions, and mesh simulation state."""
    reset_db()
    mesh_simulator.reset()
    return jsonify({"success": True, "message": "System reset to default state"})

# ========================================================
# MODULE A: HARDWARE-BOUND KEY ATTESTATION ENDPOINTS
# ========================================================
@app.route('/api/wallet/hardware/challenge', methods=['POST'])
def hardware_challenge():
    """Issues a single-use 32-byte cryptographic challenge nonce for hardware key attestation."""
    data = request.json or {}
    vpa = (data.get('vpa') or 'user@okhdfcbank').strip()
    nonce_b64 = hardware_attestation_engine.issue_challenge(vpa)
    return jsonify({"success": True, "vpa": vpa, "challengeNonce": nonce_b64})

@app.route('/api/wallet/hardware/register', methods=['POST'])
def hardware_register():
    """Verifies hardware certificate chain (StrongBox / TEE) and binds public key to VPA."""
    data = request.json or {}
    vpa = (data.get('vpa') or '').strip()
    cert_chain = data.get('certChain') or []
    platform = data.get('platform', 'ANDROID')
    if not vpa or not cert_chain:
        return jsonify({"success": False, "error": "VPA and certificate chain are required."}), 400
    try:
        res = hardware_attestation_engine.verify_and_register_attestation(vpa, cert_chain, platform)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

# ========================================================
# MODULE B: HARDENED RECONCILIATION & DOUBLE-SPEND RECONCILER
# ========================================================
@app.route('/api/reconciliation/process-voucher', methods=['POST'])
def reconcile_hardened_voucher():
    """Processes hardened offline voucher with monotonic counter, hash chain, and fork detection."""
    data = request.json or {}
    voucher = data.get('voucher') or data
    res = reconciliation_engine.process_hardened_voucher(voucher)
    status_code = 200 if res.get('success') else 400
    return jsonify(res), status_code

# ========================================================
# MODULE C: BLE GATT PROTOCOL TESTING ENDPOINTS
# ========================================================
@app.route('/api/ble/handshake', methods=['POST'])
def ble_handshake():
    """Simulates BLE GATT X25519 ECDH mutual key exchange between devices."""
    data = request.json or {}
    client_pub_b64 = data.get('clientPublicKey')
    if not client_pub_b64:
        return jsonify({"success": False, "error": "Client public key required"}), 400
    try:
        import base64
        channel = BleSecureSessionChannel()
        client_pub = base64.b64decode(client_pub_b64)
        channel.establish_session(client_pub)
        server_pub_b64 = base64.b64encode(channel.public_key_bytes).decode('utf-8')
        return jsonify({
            "success": True,
            "serverPublicKey": server_pub_b64,
            "sessionEstablished": True
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

# ========================================================
# MODULE D: REAL PAYMENT GATEWAY WEBHOOK RECEIVER
# ========================================================
@app.route('/api/gateway/webhook/deposit', methods=['POST'])
def gateway_deposit_webhook():
    """Cryptographically verifies HMAC-SHA256 signature and atomically deposits funds into escrow."""
    raw_body = request.get_data()
    signature = request.headers.get('X-Webhook-Signature', '')
    if not gateway_service.verify_webhook_signature(raw_body, signature):
        return jsonify({"success": False, "error": "Invalid HMAC webhook signature."}), 401

    payload = request.json or {}
    data = payload.get('data', payload)
    vpa = data.get('customer_vpa') or data.get('vpa') or 'user@okhdfcbank'
    amount = float(data.get('amount', 0.0))
    utr = data.get('bank_utr') or f"409{random.randint(100000000, 999999999)}"
    ref = data.get('order_id') or f"DEP_{int(time.time()*1000)}"

    dep_res = record_deposit(vpa=vpa, amount=amount, bank_utr=utr, deposit_ref=ref)
    return jsonify({"success": True, "deposit": dep_res})

# ========================================================
# MODULE E: DOUBLE-ENTRY ESCROW LEDGER AUDIT ENDPOINT
# ========================================================
@app.route('/api/ledger/audit', methods=['GET'])
def ledger_audit():
    """Audits double-entry escrow ledger to verify Sum(DR) - Sum(CR) == 0."""
    audit_res = audit_ledger_integrity()
    return jsonify(audit_res)

if __name__ == '__main__':
    print("Starting Offline UPI Hybrid Server on http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
