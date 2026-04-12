#!/usr/bin/env bash
set -e
echo ""
echo " ========================================="
echo "  Contexta - Build Executable"
echo " ========================================="
echo ""

if ! pip show pyinstaller &>/dev/null; then
    echo " Installing PyInstaller..."
    pip install pyinstaller
fi

echo " Building..."
echo ""

rm -rf build
rm -rf dist/contexta
rm -f dist/contexta.exe dist/contexta-onefile.exe dist/contexta.zip

VERSION_ARGS=()
if [ -f "version_info.txt" ]; then
    VERSION_ARGS+=(--version-file=version_info.txt)
fi

if [ -f "icon.ico" ]; then
    pyinstaller --noconfirm --clean --onefile --windowed --exclude-module brand_assets --icon=icon.ico --add-data "icon.ico:." "${VERSION_ARGS[@]}" --name=contexta contexta.py
else
    pyinstaller --noconfirm --clean --onefile --windowed --exclude-module brand_assets "${VERSION_ARGS[@]}" --name=contexta contexta.py
fi

echo ""
echo " Done!"
echo "  - dist/contexta.exe"
echo ""
