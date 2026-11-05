package com.offlineupi.crypto

import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.charset.StandardCharsets
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.PublicKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class EcdsaVoucherSigner(private val alias: String = "OfflineUpiKey") {

    companion object {
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val ECDSA_ALGORITHM = "SHA256withECDSA"
        private const val EC_CURVE = "secp256r1"
        private const val GCM_IV_LENGTH = 12
        private const val GCM_TAG_LENGTH = 128 // bits

        /**
         * Produces strict, deterministic canonical JSON bytes sorted by key without whitespaces.
         */
        fun getCanonicalBytes(
            voucherId: String,
            senderVpa: String,
            receiverVpa: String,
            amount: Double,
            nonce: Long,
            timestamp: Long
        ): ByteArray {
            val amountFormatted = String.format(java.util.Locale.US, "%.2f", amount)
            val json = JSONObject().apply {
                put("amount", amountFormatted)
                put("nonce", nonce)
                put("receiverVpa", receiverVpa.trim().lowercase())
                put("senderVpa", senderVpa.trim().lowercase())
                put("timestamp", timestamp)
                put("voucherId", voucherId.trim())
            }
            // Sort keys deterministically
            val keys = json.keys().asSequence().toList().sorted()
            val sb = StringBuilder("{")
            for (i in keys.indices) {
                val k = keys[i]
                sb.append("\"").append(k).append("\":\"").append(json.get(k)).append("\"")
                if (i < keys.size - 1) sb.append(",")
            }
            sb.append("}")
            return sb.toString().toByteArray(StandardCharsets.UTF_8)
        }
    }

    private val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    init {
        ensureKeyPairGenerated()
    }

    private fun ensureKeyPairGenerated() {
        if (!keyStore.containsAlias(alias)) {
            val kpg = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, ANDROID_KEYSTORE)
            val spec = KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY
            )
            .setAlgorithmParameterSpec(ECGenParameterSpec(EC_CURVE))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .build()

            kpg.initialize(spec)
            kpg.generateKeyPair()
        }
    }

    fun getPublicKey(): PublicKey {
        return keyStore.getCertificate(alias).publicKey
    }

    fun getPublicKeyBase64(): String {
        return Base64.encodeToString(getPublicKey().encoded, Base64.NO_WRAP)
    }

    fun signVoucher(canonicalBytes: ByteArray): String {
        val privateKey = keyStore.getKey(alias, null) as PrivateKey
        val signatureInstance = Signature.getInstance(ECDSA_ALGORITHM).apply {
            initSign(privateKey)
            update(canonicalBytes)
        }
        val sigBytes = signatureInstance.sign()
        return Base64.encodeToString(sigBytes, Base64.NO_WRAP)
    }

    fun verifyVoucher(
        canonicalBytes: ByteArray,
        signatureBase64: String,
        publicKey: PublicKey
    ): Boolean {
        return try {
            val sigBytes = Base64.decode(signatureBase64, Base64.NO_WRAP)
            val signatureInstance = Signature.getInstance(ECDSA_ALGORITHM).apply {
                initVerify(publicKey)
                update(canonicalBytes)
            }
            signatureInstance.verify(sigBytes)
        } catch (e: Exception) {
            false
        }
    }

    fun parsePublicKeyFromBase64(base64Key: String): PublicKey {
        val decoded = Base64.decode(base64Key, Base64.NO_WRAP)
        val keySpec = X509EncodedKeySpec(decoded)
        val kf = KeyFactory.getInstance(KeyProperties.KEY_ALGORITHM_EC)
        return kf.generatePublic(keySpec)
    }

    // AES-GCM Framing Support for Socket Session Handshake
    fun encryptAesGcm(plainText: ByteArray, secretKey: SecretKey): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey)
        val iv = cipher.iv
        val cipherText = cipher.doFinal(plainText)

        // 4-byte total length + 12-byte IV + Ciphertext (with auth tag)
        val buffer = ByteBuffer.allocate(4 + iv.size + cipherText.size)
        buffer.putInt(iv.size + cipherText.size)
        buffer.put(iv)
        buffer.put(cipherText)
        return buffer.array()
    }

    fun decryptAesGcm(frameBytes: ByteArray, secretKey: SecretKey): ByteArray {
        val buffer = ByteBuffer.wrap(frameBytes)
        val iv = ByteArray(GCM_IV_LENGTH)
        buffer.get(iv)
        val cipherText = ByteArray(buffer.remaining())
        buffer.get(cipherText)

        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val spec = GCMParameterSpec(GCM_TAG_LENGTH, iv)
        cipher.init(Cipher.DECRYPT_MODE, secretKey, spec)
        return cipher.doFinal(cipherText)
    }
}

