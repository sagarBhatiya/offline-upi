"""
Backward-compatibility shim for gateway_service module.
Re-exports from src.services.gateway.
"""
from src.services.gateway import (
    RealUpiGatewayService,
    gateway_service
)

__all__ = [
    "RealUpiGatewayService",
    "gateway_service"
]
