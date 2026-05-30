@echo off
cd /d "%~dp0"
python -m pip install openpyxl requests beautifulsoup4 python-docx PyPDF2 --quiet 2>nul
python app.py
