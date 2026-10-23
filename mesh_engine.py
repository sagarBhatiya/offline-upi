"""
Backward-compatibility shim for mesh_engine module.
Re-exports from src.core.mesh.
"""
from src.core.mesh import (
    MeshSimulationEngine,
    mesh_simulator
)

__all__ = [
    "MeshSimulationEngine",
    "mesh_simulator"
]
