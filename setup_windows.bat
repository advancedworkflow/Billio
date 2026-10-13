@echo off
REM Billio Windows Setup Script
REM This script sets up everything for Billio on Windows

echo [START] Billio Windows Setup
echo ===============================

REM Check if we're in the right directory
if not exist "manage.py" (
    echo [ERROR] Please run this script from the billio directory
    echo cd billio && setup_windows.bat
    pause
    exit /b 1
)

REM Check for virtual environment
if exist "venv\Scripts\activate.bat" (
    echo [VENV] Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [VENV] Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
)

REM Install dependencies
echo [INSTALL] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

REM Setup database
echo [DB] Setting up database...
python manage.py migrate
if errorlevel 1 (
    echo [ERROR] Database migration failed
    pause
    exit /b 1
)

REM Create superuser
echo [USER] Creating admin user...
python manage.py shell -c "
from django.contrib.auth.models import User
from apps.accounts.models import UserProfile
from apps.organizations.models import Organization

if not User.objects.filter(username='admin').exists():
    admin = User.objects.create_superuser('admin', 'admin@billio.local', 'admin123', first_name='Admin', last_name='Billio')
    UserProfile.objects.create(user=admin, company_name='Billio Company', address='123 Business St', city='Business City', country='France')
    org = Organization.objects.create(name='Test Company', type='small_business', owner=admin, email='test@company.com', address='123 Test Street', city='Test City', country='France')
    print('[OK] Admin user created')
else:
    print('[OK] Admin user already exists')
"

REM Start server
echo.
echo [SUCCESS] Setup complete!
echo [SERVER] Starting Billio server...
echo [URL] http://127.0.0.1:8000
echo [LOGIN] admin@billio.local / admin123
echo Press Ctrl+C to stop the server
echo.

python manage.py runserver 127.0.0.1:8000

pause


