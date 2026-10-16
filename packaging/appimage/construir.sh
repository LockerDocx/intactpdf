#!/usr/bin/env bash
#
# Construye un AppImage de IntactPDF.
#
# Un AppImage es un fichero ejecutable que lleva dentro el intérprete de Python,
# las bibliotecas y la aplicación. No necesita instalación, ni permisos de root,
# ni daemon. Ese es su encanto y también su límite.
#
# EL LÍMITE, Y HAY QUE DECIRLO CLARO: un AppImage NO evita el problema de glibc.
# El Python portátil que se usa aquí está compilado contra glibc 2.17, pero los
# wheels de pikepdf son manylinux_2_28, así que necesitan glibc 2.28 o superior.
# Medido: eso cubre RHEL/Rocky 8+, Debian 10+ y Ubuntu 20.04+, y deja fuera
# CentOS 7 y Debian 9. Es exactamente el motivo por el que la vía principal del
# proyecto es Flatpak (ver docs/distribucion.md): dentro del sandbox el anfitrión
# da igual, aquí no.
#
# Uso:
#     packaging/appimage/construir.sh
#
# Salida:
#     dist/IntactPDF-<version>-<arquitectura>.AppImage
#
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"

VERSION="$(python3 -c 'import re,sys; print(re.search(r"version = \"([^\"]+)\"", open("pyproject.toml").read()).group(1))')"

case "$(uname -m)" in
    x86_64)  ARQ="x86_64";  PY_SHA="d8faa1b588506b9e3e5a3f57807bb056d534a1641a6b10d15b6ea3f0b413b960" ;;
    aarch64) ARQ="aarch64"; PY_SHA="d8ae14f303d3971431184cf423ae5467202de2bc19bf6491a490250b87647d4b" ;;
    *) echo "arquitectura no soportada: $(uname -m)" >&2; exit 1 ;;
esac

PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.14.8%2B20261013-${ARQ}-unknown-linux-gnu-install_only_stripped.tar.gz"
APPIMAGETOOL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARQ}.AppImage"

# Versiones fijadas: las mismas que llevan los manifiestos de Flatpak. Un
# AppImage "reproducible" que instala lo que haya en PyPI ese día no es
# reproducible.
PIKEPDF="pikepdf==10.17.0"
PYPDFIUM2="pypdfium2==5.14.0"
FONTTOOLS="fonttools==4.67.0"

TD="$(mktemp -d)"
trap 'rm -rf "$TD"' EXIT

echo "== 1/6  Python portátil"
if [ ! -f "$TD/python.tar.gz" ]; then
    curl -fsSL -o "$TD/python.tar.gz" "$PY_URL"
fi
echo "$PY_SHA  $TD/python.tar.gz" | sha256sum -c - >/dev/null
echo "   sha256 correcto"

echo "== 2/6  AppDir"
APPDIR="$TD/IntactPDF.AppDir"
mkdir -p "$APPDIR/usr"
tar -xzf "$TD/python.tar.gz" -C "$TD"
mv "$TD/python" "$APPDIR/usr/python"
PY="$APPDIR/usr/python/bin/python3"

echo "== 3/6  dependencias y aplicación"
"$PY" -m pip install --no-cache-dir --no-warn-script-location \
    "$PIKEPDF" "$PYPDFIUM2" "$FONTTOOLS" >"$TD/pip.log" 2>&1
"$PY" -m pip install --no-cache-dir --no-warn-script-location --no-deps \
    "$RAIZ" >>"$TD/pip.log" 2>&1
"$PY" -c "import pikepdf, pypdfium2, fontTools; print('   pikepdf', pikepdf.__version__)"

# El script de consola que genera pip lleva un shebang con la ruta ABSOLUTA del
# intérprete que lo instaló. Durante la construcción eso es un directorio
# temporal (/tmp/tmp.XXXX) que dentro del AppImage ya no existe, así que el
# AppRun falla con un «not found» desconcertante: el fichero está ahí, lo que
# falta es el intérprete del shebang. Se reescribe a `env python3` y AppRun se
# encarga de que ese python3 sea el del AppImage.
sed -i '1s|^#!.*|#!/usr/bin/env python3|' "$APPDIR/usr/python/bin/intactpdf"
head -1 "$APPDIR/usr/python/bin/intactpdf"

echo "== 4/6  fuentes que viajan con la aplicación"
# Sin esto, escribir un carácter que no esté en el subconjunto falla en el
# AppImage: el directorio de fuentes del anfitrión puede no existir o no tener
# DejaVu. El núcleo las busca por XDG_DATA_DIRS, así que se instalan en el
# directorio estándar de dentro del AppImage.
install -d "$APPDIR/usr/share/fonts"
install -m644 fuentes/DejaVuSans.ttf fuentes/DejaVuSans-Bold.ttf "$APPDIR/usr/share/fonts/"

echo "== 5/6  AppRun, escritorio e icono"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
# AppRun: el punto de entrada. Coloca el Python y los datos del AppImage
# delante de los del sistema y ejecuta la aplicación.
AQUI="$(dirname "$(readlink -f "$0")")"
export PYTHONHOME="$AQUI/usr/python"
export PYTHONNOUSERSITE=1
export PATH="$AQUI/usr/python/bin:$PATH"
export XDG_DATA_DIRS="$AQUI/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

# Se invoca el módulo directamente en lugar del script de consola: así no
# depende de ningún shebang y funciona igual montado, extraído o movido de
# sitio. El script de consola sigue en bin/ por si alguien extrae el AppImage.
exec "$AQUI/usr/python/bin/python3" -m nucleo.cli "$@"
APPRUN
chmod +x "$APPDIR/AppRun"
install -m644 packaging/io.github.lockerdocx.IntactPDF.desktop "$APPDIR/io.github.lockerdocx.IntactPDF.desktop"
install -m644 packaging/icons/io.github.lockerdocx.IntactPDF.svg "$APPDIR/io.github.lockerdocx.IntactPDF.svg"
install -m644 packaging/icons/io.github.lockerdocx.IntactPDF.svg "$APPDIR/.DirIcon"

echo "== 6/6  empaquetado"
mkdir -p dist
if [ ! -x "$TD/appimagetool" ]; then
    curl -fsSL -o "$TD/appimagetool" "$APPIMAGETOOL"
    chmod +x "$TD/appimagetool"
fi
SALIDA="$RAIZ/dist/IntactPDF-${VERSION}-${ARQ}.AppImage"
# --appimage-extract-and-run evita depender de FUSE, que en un contenedor de
# construcción (y en muchos servidores) no está disponible. El AppImage que
# produce sí funciona sin FUSE en el equipo del usuario.
ARCH="$ARQ" "$TD/appimagetool" --appimage-extract-and-run \
    "$APPDIR" "$SALIDA" >"$TD/appimagetool.log" 2>&1 || {
        echo "appimagetool falló; últimas líneas:" >&2
        tail -20 "$TD/appimagetool.log" >&2
        exit 1
    }

echo
echo "  listo: $SALIDA"
echo "  tamaño: $(du -h "$SALIDA" | cut -f1)"
echo
echo "  pruébalo con:  $SALIDA info corpus/00_baseline.pdf"
