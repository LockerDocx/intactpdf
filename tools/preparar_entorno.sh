#!/usr/bin/env bash
# Prepara el entorno para IntactPDF.
#
# Por qué existe este script: en el entorno de desarrollo de este proyecto, los
# paquetes instalados con `pip --user` viven en ~/.local, que NO se conserva
# entre sesiones. El workspace (código, corpus, resultados) sí. Así que cada
# sesión nueva hay que reinstalar las dependencias, y esto lo hace en un paso.
#
#   bash tools/preparar_entorno.sh
#
# Licencias: todas permisivas (BSD, Apache-2.0, MIT, MPL-2.0). Nada de AGPL.
#   pikepdf / qpdf    MPL-2.0
#   pypdfium2         Apache-2.0 / BSD-3
#   fontTools         MIT
#   reportlab         BSD-3
#   numpy / pillow    BSD-3
set -euo pipefail

# Opcional, solo para empaquetar (no hace falta para desarrollar ni para los
# tests). Descomenta si vas a construir el Flatpak:
#   sudo apt-get install -y flatpak flatpak-builder

echo "== Python =="
python3 -m pip install --user --quiet --upgrade \
    pikepdf pypdfium2 pypdf reportlab fontTools numpy pillow
echo "   instalados: pikepdf, pypdfium2, pypdf, reportlab, fontTools, numpy, pillow"

echo "== Sistema (necesita sudo) =="
if sudo -n true 2>/dev/null; then
    sudo -n apt-get install -y -qq qpdf poppler-utils >/dev/null
    echo "   instalados: qpdf, poppler-utils"

    # LibreOffice Draw solo hace falta para el arnés de fidelidad comparativa
    # (03-validacion-empirica.md). Es opcional para el editor.
    if [ "${CON_LIBREOFFICE:-0}" = "1" ]; then
        sudo -n apt-get install -y -qq libreoffice-draw >/dev/null
        echo "   instalado: libreoffice-draw"
    fi
else
    echo "   AVISO: sin sudo. qpdf y poppler-utils no se instalan;"
    echo "          el test de aceptación necesita 'qpdf --check'."
fi

echo "== Comprobación =="
python3 - <<'PY'
import importlib, shutil, sys
mods = ["pikepdf", "pypdfium2", "pypdf", "reportlab", "fontTools", "numpy", "PIL"]
falta = []
for m in mods:
    try:
        importlib.import_module(m)
        print(f"   ok    {m}")
    except Exception:
        falta.append(m)
binarios = ["qpdf", "pdftoppm"]
for b in binarios:
    ruta = shutil.which(b)
    print(f"   {'ok   ' if ruta else 'FALTA'} {b}")
    if not ruta:
        falta.append(b)
if falta:
    print(f"\n   FALTAN: {', '.join(falta)}", file=sys.stderr)
    sys.exit(1)
print("\n   entorno listo")
PY
