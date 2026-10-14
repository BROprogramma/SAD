@echo off
rem Test alle versies (geleverde mappen naast SAD testsuite met een configuratie in versies\).
cd /d "%~dp0"

rem Python aanwezig?
where python >nul 2>nul
if errorlevel 1 goto :geenpython

rem Benodigde pakketten aanwezig? Anders eenmalig installeren.
python -c "import lxml, saxonche" >nul 2>nul
if errorlevel 1 goto :installeer

:start
python "%~dp0run_tests.py" %*
echo.
pause
exit /b

:installeer
echo De Python-pakketten saxonche en lxml ontbreken. Ze worden nu eenmalig geinstalleerd...
python -m pip install --user -r "%~dp0requirements.txt"
if errorlevel 1 goto :installatiefout
echo.
goto :start

:installatiefout
echo.
echo Installatie mislukt. Voer handmatig uit: python -m pip install --user saxonche lxml
pause
exit /b 1

:geenpython
echo Python is niet gevonden. Installeer Python 3 via python.org en vink 'Add python.exe to PATH' aan.
pause
exit /b 1
