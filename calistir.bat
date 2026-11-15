@echo off
python factory.py
if errorlevel 1 goto end
python check.py
:end
pause
