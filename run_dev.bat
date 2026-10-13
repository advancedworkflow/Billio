@echo off
REM Billio Development Server Launcher (Windows)
REM This script ensures HTTP-only mode and prevents SSL errors

echo 🚀 Starting Billio Development Server (HTTP-only)
echo 📍 URL: http://127.0.0.1:8000
echo ⚠️  IMPORTANT: Use HTTP (not HTTPS) in your browser
echo.

REM Set environment variables to force HTTP
set wsgi.url_scheme=http
set HTTPS=off
set DJANGO_SETTINGS_MODULE=config.settings.dev

REM Clear any SSL cache by making a dummy request
echo 🧹 Clearing SSL cache...
powershell -Command "& {try { Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -TimeoutSec 1 -ErrorAction Stop } catch {}}"

REM Start the Django development server
echo 🚀 Launching server...
python manage.py runserver --noreload --insecure 127.0.0.1:8000

echo.
echo 👋 Server stopped.
pause


