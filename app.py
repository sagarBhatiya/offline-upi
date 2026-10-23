import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import create_app
from src.config import Config

# Initialize application using factory
app = create_app()

if __name__ == '__main__':
    print(f"=========================================================")
    print(f" Offline UPI PWA Server (Architecture: Modular Layered)")
    print(f" Database: {app.config.get('DATABASE_URL') and 'PostgreSQL' or 'SQLite Fallback'}")
    print(f" Listening on http://127.0.0.1:{Config.PORT}")
    print(f"=========================================================")
    app.run(host='0.0.0.0', port=Config.PORT, debug=Config.DEBUG)
