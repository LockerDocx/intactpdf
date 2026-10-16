#!/usr/bin/env python3
"""
Genera las capturas de pantalla de la interfaz.

Para qué: Flathub exige capturas para publicar una aplicación, y además es la
forma de comprobar que la ventana se dibuja de verdad sin tener un escritorio
delante. Se ejecuta con un servidor X virtual:

    Xvfb :99 -screen 0 1400x950x24 &
    DISPLAY=:99 /usr/bin/python3 tools/capturas_gui.py

Por qué hay que usar el python del sistema (o el del runtime) y no uno de pip:
PyGObject se instala con el gestor de paquetes de la distribución, porque va
atado a las bibliotecas de GTK que están instaladas. `pip install pygobject`
obliga a compilar y a tener los encabezados de GTK, y es la causa número uno de
gente que no consigue arrancar una aplicación GTK en Python.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from gui.modelo import Sesion          # noqa: E402
from gui.ventana import Aplicacion     # noqa: E402

SALIDA = RAIZ / "docs" / "capturas"
CORPUS = RAIZ / "corpus"


def capturar(nombre: str, preparar=None, pdf: str = "05_cmyk_imprenta.pdf",
             al_abrir=None) -> None:
    """Abre un PDF, opcionalmente lo manipula, y guarda una captura.

    `al_abrir` recibe la ventana ya construida: sirve para dejar la cinta en la
    pestaña que se quiere enseñar.

    Lo que NO conviene fotografiar por esta vía: un panel oculto. La instantánea
    dibuja el árbol de widgets entero, y un widget que está en el árbol pero sin
    mapear —el panel lateral cuando se oculta— sale pintado igual, en una banda
    oscura que en la ventana real no está. Es una limitación de «dibujar el
    árbol» frente a «hacer una foto de la pantalla», y se sabe porque se midió
    el píxel. Que el panel se oculta de verdad se comprueba en
    `tests/test_gui.py`, con el estado del widget y no con píxeles.
    """
    sesion = Sesion()
    if pdf:
        sesion.abrir(CORPUS / pdf)
    if preparar:
        preparar(sesion)
    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = SALIDA / f"{nombre}.png"
    app = Aplicacion(sesion, captura=str(destino), al_abrir=al_abrir)
    app.run(["intactpdf-gui"])
    print(f"  {destino.relative_to(RAIZ)}")


def _todas() -> int:
    """Genera todas: una captura por proceso.

    En su propio proceso y no en el mismo, porque **`Gio.Application.run()` sólo
    se puede llamar una vez por proceso**: la segunda vez no devuelve, imprime
    «Failed to register: An object is already exported for the interface
    org.gtk.Application» y sale sin dibujar nada. Reutilizar el mismo objeto de
    aplicación tampoco vale (probado: el segundo `run()` devuelve 1 sin captura).
    Se veía sólo a partir de la segunda captura, y por eso el CI, que ejecuta las
    pruebas en un proceso, destapó el problema: allí la captura de la prueba se
    quedaba sin fichero.
    """
    import subprocess
    this = Path(__file__).resolve()
    for nombre in _NOMBRES:
        r = subprocess.run([sys.executable, str(this), f"--solo={nombre}"],
                           text=True)
        if r.returncode != 0:
            print(f"  falló la captura {nombre}", file=sys.stderr)
            return r.returncode
    return 0


def main() -> int:
    solo = None
    for a in sys.argv[1:]:
        if a.startswith("--solo="):
            solo = a.split("=", 1)[1]
        elif a in ("-h", "--help"):
            print("genera las capturas de docs/capturas/\n"
                  "  --solo=NOMBRE   sólo una (se ejecuta en su propio proceso)")
            return 0
    if solo is None:
        print("  generando capturas")
        return _todas()
    _una(solo)
    return 0


def _una(nombre: str) -> None:
    """Genera UNA captura, en este proceso. La llama `_todas`, o tú a mano."""
    if nombre not in PLAN:
        print(f"no existe la captura {nombre}; las que hay:\n  "
              + "\n  ".join(_NOMBRES), file=sys.stderr)
        raise SystemExit(2)
    preparar, pdf, al_abrir = PLAN[nombre]
    capturar(nombre, preparar, pdf=pdf, al_abrir=al_abrir)


# 1. Un PDF de imprenta recién abierto: es el caso que más se rompe en otros
#    editores (CMYK, imágenes con alfa, vectores rellenos).
# 2. Un objeto seleccionado, con sus asas y los contornos de los demás.
# 3. Después de redimensionar al 60 %: la imagen encoge donde estaba y todo lo
#    demás se queda clavado.
# 4. Texto: el caso de escribir un carácter que no estaba en el subconjunto, que
#    es donde hace falta incrustar una fuente nueva.
# 5. Documento con páginas giradas: la navegación y el /Rotate.
# 6 a 9. Las pestañas de la cinta, que es donde están todas las opciones. Cada
#    una con la selección que le corresponde, porque la gracia de la cinta es
#    justo esa: lo que no aplica se ve apagado.
# 10. Sin documento: la cinta casi entera apagada, que es lo que enseña que el
#     programa desactiva en vez de esconder.

IMPRENTA = "05_cmyk_imprenta.pdf"
ROTADAS = "07_paginas_rotadas_mixtas.pdf"


def _seleccionar_imagen(s: Sesion):
    s.seleccionar_en(232, 680)


def _escalar(s: Sesion):
    s.seleccionar_en(232, 680)
    s.escalar(0.6)


def _editar_texto(s: Sesion):
    s.seleccionar_en(150, 500)
    s.editar_texto("Una frase distinta, con acentos: ñ, ó, €.")


def _texto_seleccionado(s: Sesion):
    s.seleccionar_en(150, 500)


def _pestana(nombre):
    return lambda v: v.cinta.activar(nombre)


PLAN = {
    "01-recien-abierto":  (None, IMPRENTA, None),
    "02-seleccion":       (_seleccionar_imagen, IMPRENTA, None),
    "03-redimensionada":  (_escalar, IMPRENTA, None),
    "04-texto-cambiado":  (_editar_texto, IMPRENTA, None),
    "05-paginas-giradas": (None, ROTADAS, None),
    "06-cinta-objeto":    (_seleccionar_imagen, IMPRENTA, _pestana("objeto")),
    "07-cinta-texto":     (_texto_seleccionado, IMPRENTA, _pestana("texto")),
    "08-cinta-pagina":    (None, ROTADAS, _pestana("pagina")),
    "09-cinta-ver":       (_seleccionar_imagen, IMPRENTA, _pestana("ver")),
    "10-sin-documento":   (None, None, None),
}
_NOMBRES = list(PLAN)


if __name__ == "__main__":
    raise SystemExit(main())
