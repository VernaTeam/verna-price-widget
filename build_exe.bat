@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3.14 -m pip install --quiet --upgrade pyinstaller pywebview || goto :fail
py -3.14 -m PyInstaller --noconfirm --clean VernaPriceWidget.spec || goto :fail
echo Done: "%CD%\dist\VernaPriceWidget.exe"
pause
exit /b 0
:fail
echo BUILD FAILED. Close VernaPriceWidget.exe if it is running and try again.
pause
exit /b 1
