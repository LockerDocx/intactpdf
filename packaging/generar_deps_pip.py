#!/usr/bin/env python3
"""
Genera packaging/python3-deps.json, el módulo de wheels del manifiesto Flatpak.

Por qué un generador y no un JSON escrito a mano: un manifiesto de Flatpak no
puede descargar nada durante la construcción, así que cada wheel tiene que
aparecer como source con su URL y su sha256. Escribir nueve líneas de hash a
mano y encima mantenerlas cuando suben de versión es la clase de tarea donde uno
se equivoca y no se entera hasta que el build falla en Flathub.

Por qué Python 3.14: el runtime `org.gnome.Platform//51` (Freedesktop SDK 26.08)
trae Python 3.14, no 3.13. Las wheels con etiqueta cp313 NO valen ahí.

Se incluyen las dos arquitecturas que compila Flathub (x86_64 y aarch64). pip
ignora las incompatibles, así que basta con tenerlas todas en el directorio y
dejar que `--find-links` elija.

Uso:
    python3 packaging/generar_deps_pip.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
WHEELS = RAIZ / ".tmp" / "wheels"
SALIDA = Path(__file__).resolve().parent / "python3-deps.json"

PYTHON = "314"
ARQUITECTURAS = {
    "x86_64": ["manylinux_2_28_x86_64", "manylinux2014_x86_64"],
    "aarch64": ["manylinux_2_28_aarch64", "manylinux2014_aarch64"],
}

# Lo que necesita la aplicación en tiempo de ejecución. NO van aquí las del
# arnés de tests (pypdf, numpy): el Flatpak distribuye el editor, no el banco de
# pruebas.
PAQUETES = ["pikepdf", "pypdfium2", "fonttools", "pillow", "packaging"]


def descargar_wheels() -> None:
    WHEELS.mkdir(parents=True, exist_ok=True)
    for arch, plataformas in ARQUITECTURAS.items():
        orden = [sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                 "--no-deps", "-d", str(WHEELS), "--python-version", PYTHON,
                 "--implementation", "cp", "--abi", f"cp{PYTHON}"]
        for p in plataformas:
            orden += ["--platform", p]
        orden += PAQUETES[:-1]                       # packaging es py3-none-any
        print(f"  descargando wheels de {arch}…")
        subprocess.run(orden, check=True, capture_output=True)
    subprocess.run([sys.executable, "-m", "pip", "download",
                    "--only-binary=:all:", "--no-deps", "-d", str(WHEELS),
                    PAQUETES[-1]], check=True, capture_output=True)


def url_en_pypi(nombre_fichero: str) -> str:
    """URL real de descarga, preguntando a la API de PyPI."""
    proyecto = nombre_fichero.split("-")[0]
    with urllib.request.urlopen(
            f"https://pypi.org/pypi/{proyecto}/json", timeout=30) as r:
        datos = json.load(r)
    for ficheros in datos["releases"].values():
        for f in ficheros:
            if f["filename"] == nombre_fichero:
                return f["url"]
    raise SystemExit(f"no encuentro {nombre_fichero} en PyPI")


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def main() -> int:
    if not list(WHEELS.glob("*.whl")):
        descargar_wheels()

    fuentes = []
    for whl in sorted(WHEELS.glob("*.whl")):
        entrada: dict = {
            "type": "file",
            "url": url_en_pypi(whl.name),
            "sha256": sha256(whl),
            "dest": "wheels",
            "dest-filename": whl.name,
        }
        # Solo las wheels atadas a una arquitectura necesitan `only-arches`;
        # las py3-none-any valen para todas.
        for arch, plataformas in ARQUITECTURAS.items():
            if any(p in whl.name for p in plataformas):
                entrada["only-arches"] = [arch]
                break
        fuentes.append(entrada)

    modulo = {
        "name": "python3-deps",
        "buildsystem": "simple",
        "build-commands": [
            # Sin red: todas las wheels están ya en el directorio de construcción.
            # pip elige la compatible con la arquitectura y el Python del runtime
            # e ignora el resto.
            "pip3 install --no-index --find-links=wheels --prefix=/app " + " ".join(PAQUETES),
        ],
        "sources": fuentes,
    }
    SALIDA.write_text(json.dumps(modulo, indent=4) + "\n")
    print(f"  {SALIDA.relative_to(RAIZ)}: {len(fuentes)} wheels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
