"""
Backward-compatibility shim for attestation_engine module.
Re-exports from src.core.attestation.
"""
from src.core.attestation import (
    HardwareAttestationEngine,
    hardware_attestation_engine,
    KEY_ATTESTATION_OID
)

__all__ = [
    "HardwareAttestationEngine",
    "hardware_attestation_engine",
    "KEY_ATTESTATION_OID"
]
