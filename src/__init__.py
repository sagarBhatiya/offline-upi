import os
from flask import Flask
from src.config import Config
from src.db.schema import init_db
from src.routes import register_blueprints

def create_app(config_class=Config):
    """
    Application Factory:
    Initializes Flask with modular blueprints, database tables, and configuration.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    template_dir = os.path.join(root_dir, 'templates')
    static_dir = os.path.join(root_dir, 'static')

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir
    )
    app.config.from_object(config_class)

    # Initialize Database Tables (PostgreSQL or SQLite fallback)
    try:
        init_db()
    except Exception as e:
        print(f"[App Init] Database table initialization warning: {e}")

    # Register all modular Blueprints
    register_blueprints(app)

    return app
