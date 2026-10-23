import os
from flask import Blueprint, render_template, send_from_directory, jsonify
from src.db.connection import get_db_type, is_postgres_configured

main_bp = Blueprint('main_bp', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/manifest.json')
def manifest():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    static_dir = os.path.join(root_dir, 'static')
    return send_from_directory(static_dir, 'manifest.json', mimetype='application/manifest+json')

@main_bp.route('/sw.js')
def service_worker():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    static_dir = os.path.join(root_dir, 'static')
    resp = send_from_directory(static_dir, 'sw.js', mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@main_bp.route('/health')
def health():
    return jsonify({
        "status": "HEALTHY",
        "database": get_db_type(),
        "is_postgres": is_postgres_configured(),
        "architecture": "MODULAR_BLUEPRINT_SERVICE_LAYER"
    })
