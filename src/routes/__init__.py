from src.routes.main_routes import main_bp
from src.routes.hotspot_routes import hotspot_bp
from src.routes.qr_routes import qr_bp
from src.routes.wallet_routes import wallet_bp
from src.routes.upi_routes import upi_bp
from src.routes.mesh_routes import mesh_bp

def register_blueprints(app):
    """Registers all modular route blueprints with the Flask application."""
    app.register_blueprint(main_bp)
    app.register_blueprint(hotspot_bp)
    app.register_blueprint(qr_bp)
    app.register_blueprint(wallet_bp)
    app.register_blueprint(upi_bp)
    app.register_blueprint(mesh_bp)

__all__ = [
    "main_bp",
    "hotspot_bp",
    "qr_bp",
    "wallet_bp",
    "upi_bp",
    "mesh_bp",
    "register_blueprints"
]
