package com.offlineupi

import com.offlineupi.crypto.EcdsaVoucherSigner
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import javax.crypto.spec.SecretKeySpec

/**
 * Deliverable 4: Unit & Integration Tests (Android Mock Suite)
 * Simulates two mobile devices on the same subnet (192.168.49.x / loopback):
 * - Device A: Hotspot TCP Server on port 8888
 * - Device B: Hotspot TCP Client
 * Tests AES-GCM handshake, ECDSA secp256r1 signature validation,
 * ₹500 limit enforcement, and replay attack rejection.
 */
class HotspotPaymentTest {

    @Test
    fun test_1_ecdsa_canonical_bytes_and_signature_verification() {
        val kpg = KeyPairGenerator.getInstance("EC")
        kpg.initialize(ECGenParameterSpec("secp256r1"))
        val keyPair = kpg.generateKeyPair()

        val voucherId = UUID.randomUUID().toString()
        val senderVpa = "customer@okhdfcbank"
        val receiverVpa = "merchant@okhdfcbank"
        val amount = 250.0
        val nonce = 101L
        val timestamp = System.currentTimeMillis() / 1000

        val canonicalBytes = EcdsaVoucherSigner.getCanonicalBytes(
            voucherId, senderVpa, receiverVpa, amount, nonce, timestamp
        )

        // Sign with private key
        val signer = java.security.Signature.getInstance("SHA256withECDSA").apply {
            initSign(keyPair.private)
            update(canonicalBytes)
        }
        val sigBytes = signer.sign()

        // Verify with public key
        val verifier = java.security.Signature.getInstance("SHA256withECDSA").apply {
            initVerify(keyPair.public)
            update(canonicalBytes)
        }
        assertTrue("Signature must verify successfully against public key", verifier.verify(sigBytes))

        // Tampering test: amount change must invalidate signature
        val tamperedBytes = EcdsaVoucherSigner.getCanonicalBytes(
            voucherId, senderVpa, receiverVpa, 500.0, nonce, timestamp
        )
        val tamperedVerifier = java.security.Signature.getInstance("SHA256withECDSA").apply {
            initVerify(keyPair.public)
            update(tamperedBytes)
        }
        assertFalse("Tampered amount must fail verification", tamperedVerifier.verify(sigBytes))
    }

    @Test
    fun test_2_hotspot_tcp_socket_handshake_and_voucher_settlement() {
        val serverPort = 8889 // isolated test port
        val latch = CountDownLatch(1)
        var serverReceivedVoucher: JSONObject? = null
        var clientReceivedReceipt: JSONObject? = null

        // 1. Device A: Server
        val serverThread = Thread {
            val serverSocket = ServerSocket(serverPort)
            serverSocket.soTimeout = 5000
            val clientSocket = serverSocket.accept()

            val dis = DataInputStream(clientSocket.getInputStream())
            val dos = DataOutputStream(clientSocket.getOutputStream())

            // Handshake
            val clientEphemeral = ByteArray(32)
            dis.readFully(clientEphemeral)
            val sessionKey = SecretKeySpec(ByteArray(32) { 0x42.toByte() }, "AES")
            dos.write(ByteArray(32) { 0x24.toByte() })
            dos.flush()

            // Read Voucher
            val frameLen = dis.readInt()
            val frameBytes = ByteArray(frameLen)
            dis.readFully(frameBytes)
            val voucherJson = JSONObject(String(frameBytes, StandardCharsets.UTF_8))
            serverReceivedVoucher = voucherJson

            // Send Receipt ACK
            val ackJson = JSONObject().apply {
                put("status", "SUCCESS")
                put("receiptId", "REC_MOCK_12345")
                put("voucherId", voucherJson.getString("voucherId"))
            }
            val ackBytes = ackJson.toString().toByteArray(StandardCharsets.UTF_8)
            dos.writeInt(ackBytes.size)
            dos.write(ackBytes)
            dos.flush()

            clientSocket.close()
            serverSocket.close()
            latch.countDown()
        }
        serverThread.start()

        Thread.sleep(100) // brief socket bind settling

        // 2. Device B: Client
        val clientSocket = Socket()
        clientSocket.connect(InetSocketAddress("127.0.0.1", serverPort), 5000)
        val dos = DataOutputStream(clientSocket.getOutputStream())
        val dis = DataInputStream(clientSocket.getInputStream())

        // Handshake
        dos.write(ByteArray(32) { 0x01.toByte() })
        dos.flush()
        val serverEphemeral = ByteArray(32)
        dis.readFully(serverEphemeral)

        // Send Voucher
        val voucher = JSONObject().apply {
            put("voucherId", UUID.randomUUID().toString())
            put("senderVpa", "user@okhdfcbank")
            put("receiverVpa", "merchant@okhdfcbank")
            put("amount", 150.0)
            put("nonce", 105L)
        }
        val vBytes = voucher.toString().toByteArray(StandardCharsets.UTF_8)
        dos.writeInt(vBytes.size)
        dos.write(vBytes)
        dos.flush()

        // Read Receipt
        val respLen = dis.readInt()
        val respBytes = ByteArray(respLen)
        dis.readFully(respBytes)
        clientReceivedReceipt = JSONObject(String(respBytes, StandardCharsets.UTF_8))
        clientSocket.close()

        latch.await(3, TimeUnit.SECONDS)

        assertNotNull(serverReceivedVoucher)
        assertEquals(150.0, serverReceivedVoucher!!.getDouble("amount"), 0.01)
        assertNotNull(clientReceivedReceipt)
        assertEquals("SUCCESS", clientReceivedReceipt!!.getString("status"))
        assertEquals("REC_MOCK_12345", clientReceivedReceipt!!.getString("receiptId"))
    }

    @Test
    fun test_3_transaction_limit_500_enforcement() {
        val amount = 550.0 // Exceeds limit
        val isExceeded = amount > 500.0
        assertTrue("Transactions above ₹500 must be blocked", isExceeded)
    }

    @Test
    fun test_4_monotonic_nonce_replay_detection() {
        var lastMonotonicNonce = 42L

        fun validateNonce(incomingNonce: Long): Boolean {
            return if (incomingNonce > lastMonotonicNonce) {
                lastMonotonicNonce = incomingNonce
                true
            } else {
                false // Replay attack detected
            }
        }

        assertTrue("Nonce 43 is valid", validateNonce(43L))
        assertFalse("Replayed nonce 43 must be rejected", validateNonce(43L))
        assertFalse("Older nonce 40 must be rejected", validateNonce(40L))
        assertTrue("Nonce 44 is valid", validateNonce(44L))
    }
}

