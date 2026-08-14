BIN_NAME=123pan
BIN_FILE="target/release/${BIN_NAME}.exe"

python_ver=3.14
python_full_ver=${python_ver}.7
python_num_ver=$(echo -n $python_ver | tr -cd '0-9')

(
    if ! [ -d "launcher" ]; then
        git clone --depth 1 \
            https://github.com/mokurin000/pyo3-simple-launcher \
            launcher
    fi

    cd launcher
    [ -d ".git" ] && git pull

    export CARGO_TARGET_DIR=target

    uv run generate.py "${BIN_NAME}" app.__main__:main || exit 1
    cargo +nightly build --release
)

[ $? != 0 ] && exit 1

mkdir -p deploy-gui && cd deploy-gui || exit 1


# Download the latest python embed 3.14 build here

python_zip="python-${python_full_ver}-embed-amd64"
if ! [ -f "${python_zip}.zip" ]; then
    curl -LO "https://www.python.org/ftp/python/${python_full_ver}/${python_zip}.zip"
fi

output_dir="Lib"
rm -rf "${output_dir}" || exit 1

(
    mkdir -p "${output_dir}" && cd "${output_dir}" || exit 1
    unzip "../${python_zip}.zip"
)

# Install dependencies
pip3.14 install ".." -t Lib/site-packages

# Clean-up unused files
for dir in "__pycache__" "tests"; do
    find "Lib/site-packages" -name "$dir" -type d | xargs rm -rf
done
# 3MiB
rm -rf Lib/site-packages/bin
# 5MB
find Lib/site-packages -name "*.pyi" -type f -delete
# 14MiB
rm -rf Lib/site-packages/PySide6/*.exe
# PySide6
for entry in \
    "Qt6Graphs.dll" "QtGraphs.pyd" \
    "Qt6OpenGLWidgets.dll" "QtOpenGLWidgets.pyd" "QtOpenGL.pyd" \
    "opengl32sw.dll" "Qt6OpenGL.dll"; do
    rm -rf "Lib/site-packages/PySide6/${entry}"
done
# WebEngine resources
rm -rf Lib/site-packages/PySide6/resources \
    "Lib/site-packages/PySide6/translations/qtwebengine_locales"
rm -rf Lib/site-packages/PySide6/Qt6WebEngine*.dll
rm -rf Lib/site-packages/PySide6/QtWebEngine*.pyd
# Qt63D
rm -rf Lib/site-packages/PySide6/Qt63D*.dll
rm -rf Lib/site-packages/PySide6/Qt3D*.pyd
# Qt6Quick
rm -rf Lib/site-packages/PySide6/qml
rm -rf Lib/site-packages/PySide6/Qt*Qml*
rm -rf Lib/site-packages/PySide6/Qt6Quick*.dll
rm -rf Lib/site-packages/PySide6/QtQuick*.pyd
# QDesigner
rm -rf Lib/site-packages/PySide6/Qt6Designer*.dll

# C++ headers, 1MiB
rm -rf Lib/site-packages/PySide6/include

# Translations
rm -rf Lib/site-packages/PySide6/translations/{assistant,designer,linguist,qtwebengine,qtlocation}_*.qm

# Other things
rm -rf Lib/site-packages/PySide6/Qt*Bluetooth*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*CanvasPainter*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Charts*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*DataVisualization*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Graphs*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Help*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*HttpServer*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Location*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Lottie*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Nfc*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Positioning*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*RemoteObjects*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Sensors*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*SerialBus*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*SerialPort*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*SpatialAudio*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*StateMachine*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Test*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*UiTools*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*VirtualKeyboard*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*WebChannel*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*WebSockets*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*ShaderTools*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*DBus*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Lab*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*Concurrent*.{dll,pyd}
rm -rf Lib/site-packages/PySide6/Qt*WebView*.{dll,pyd}

# python win, pywin32 docs: 6 MiB
rm -rf Lib/site-packages/pythonwin
rm -rf Lib/site-packages/PyWin32.chm

# Unused json files
rm -rf Lib/site-packages/PySide6/metatypes/
# 12.8 MiB
for entry in assetimporters canbus designer generic vectorimageformats webview \
    geometryloaders geoservices networkinformation platforminputcontexts \
    position qmllint qmltooling renderers renderplugins sceneparsers \
    scxmldatamodel sensors sqldrivers texttospeech; do
    rm -rf Lib/site-packages/PySide6/plugins/"${entry}"
done

# Remove python interceptors
rm Lib/python{,w}.exe Lib/python${python_num_ver}._pth
mv Lib/python${python_num_ver}.dll Lib/python3.dll .

cat > "python${python_num_ver}._pth" <<EOF
Lib/
Lib/python${python_num_ver}.zip
import site
EOF

cp "../launcher/${BIN_FILE}" .
