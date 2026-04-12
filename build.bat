@echo off
echo.
echo  =========================================
echo   Contexta - Build Executable
echo  =========================================
echo.

py --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)

echo  Installing PyInstaller...
py -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo  [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

echo.
echo  Building executable...
echo.

if exist "dist\contexta.exe" del /f /q "dist\contexta.exe"
if exist "dist\contexta" rd /s /q "dist\contexta"
if exist "build" rd /s /q "build"
set VERSION_ARGS=
if exist "version_info.txt" set VERSION_ARGS=--version-file=version_info.txt
if exist "icon.ico" (
    py -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --exclude-module brand_assets --icon=icon.ico --add-data "icon.ico;." %VERSION_ARGS% --name=contexta contexta.py
) else (
    py -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --exclude-module brand_assets %VERSION_ARGS% --name=contexta contexta.py
)

if errorlevel 1 goto :build_error

where signtool >nul 2>&1
if errorlevel 1 goto :signing_skipped

if "%CONTEXTA_SIGN_PFX%"=="" goto :signing_skipped
if not exist "%CONTEXTA_SIGN_PFX%" goto :signing_skipped

echo.
echo  Signing executable...
if "%CONTEXTA_SIGN_PASSWORD%"=="" (
    signtool sign /fd SHA256 /f "%CONTEXTA_SIGN_PFX%" /tr http://timestamp.digicert.com /td SHA256 "dist\contexta.exe"
) else (
    signtool sign /fd SHA256 /f "%CONTEXTA_SIGN_PFX%" /p "%CONTEXTA_SIGN_PASSWORD%" /tr http://timestamp.digicert.com /td SHA256 "dist\contexta.exe"
)
if errorlevel 1 goto :build_error

:signing_skipped

echo.
echo  =========================================
echo   Done! Outputs:
echo     - dist\contexta.exe
echo  =========================================
echo.

explorer dist
pause
exit /b 0

:build_error
echo.
echo  [ERROR] Build failed. Check the output above.
pause
exit /b 1
