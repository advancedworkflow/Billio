@echo off
REM Lance les automatisations planifiées de Billio (relances, factures récurrentes,
REM dates du calendrier, attentes de workflows). À planifier toutes les 10 minutes :
REM   schtasks /Create /SC MINUTE /MO 10 /TN "Billio automatisations" /TR "\"%~f0\""
cd /d "%~dp0.."
".venv\Scripts\python.exe" manage.py run_automations >> "logs\run_automations.log" 2>&1
