"""
Backward-compatibility shim for ble_protocol module.
Re-exports from src.core.ble.
"""
from src.core.ble import (
    BleSecureSessionChannel,
    MAGIC_HEADER,
    MAX_CHUNK_DATA_SIZE
)

__all__ = [
    "BleSecureSessionChannel",
    "MAGIC_HEADER",
    "MAX_CHUNK_DATA_SIZE"
]
