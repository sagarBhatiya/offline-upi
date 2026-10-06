@echo off
title Offline UPI Server (Python + SQLite)
echo =========================================================
echo Starting Offline UPI Python Server...
echo =========================================================
echo.
python -m pip install -r requirements.txt
echo.
echo Opening Web Dashboard in browser...
start http://127.0.0.1:5000
echo.
python app.py
pause
