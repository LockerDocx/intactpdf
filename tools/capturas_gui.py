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


def main() -> int:
    print("  generando capturas")

    # 1. Un PDF de imprenta recién abierto: es el caso que más se rompe en otros
    #    editores (CMYK, imágenes con alfa, vectores rellenos).
    capturar("01-recien-abierto")

    # 2. Un objeto seleccionado, con sus asas y los contornos de los demás.
    def seleccionar_imagen(s: Sesion):
        s.seleccionar_en(232, 680)
    capturar("02-seleccion", seleccionar_imagen)

    # 3. Después de redimensionar al 60 %: la imagen encoge donde estaba y todo
    #    lo demás se queda clavado.
    def escalar(s: Sesion):
        s.seleccionar_en(232, 680)
        s.escalar(0.6)
    capturar("03-redimensionada", escalar)

    # 4. Texto: el caso de escribir un carácter que no estaba en el subconjunto,
    #    que es donde hace falta incrustar una fuente nueva.
    def editar_texto(s: Sesion):
        s.seleccionar_en(150, 500)
        s.editar_texto("Una frase distinta, con acentos: ñ, ó, €.")
    capturar("04-texto-cambiado", editar_texto)

    # 5. Documento con páginas giradas: la navegación y el /Rotate.
    capturar("05-paginas-giradas", pdf="07_paginas_rotadas_mixtas.pdf")

    # 6 a 9. Las pestañas de la cinta, que es donde están todas las opciones.
    #        Se enseña cada una con la selección que le corresponde, porque la
    #        gracia de la cinta es justo esa: lo que no aplica se ve apagado.
    def imagen_seleccionada(s: Sesion):
        s.seleccionar_en(232, 680)

    def texto_seleccionado(s: Sesion):
        s.seleccionar_en(150, 500)

    capturar("06-cinta-objeto", imagen_seleccionada,
             al_abrir=lambda v: v.cinta.activar("objeto"))
    capturar("07-cinta-texto", texto_seleccionado,
             al_abrir=lambda v: v.cinta.activar("texto"))
    capturar("08-cinta-pagina", None,
             pdf="07_paginas_rotadas_mixtas.pdf",
             al_abrir=lambda v: v.cinta.activar("pagina"))

    def pestana_ver(v):
        v.cinta.activar("ver")

    capturar("09-cinta-ver", imagen_seleccionada, al_abrir=pestana_ver)

    # 10. Sin documento: la cinta casi entera apagada, que es lo que enseña que
    #     el programa desactiva en vez de esconder.
    capturar("10-sin-documento", None, pdf=None)

    print("  listo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
