"""
Valida la geometría del parser contra pdfium, que es un motor independiente.

Por qué existe: el test de aceptación comparaba píxeles contra una región
PERMITIDA, construida con las cajas de nuestro propio parser. Si el parser se
equivoca, la región de permiso se equivoca con él y el error queda invisible.
Este fichero no comparte ni una línea con el parser: pregunta a pdfium dónde
está cada objeto en la página y lo compara con lo que dice el nuestro.

No busca coincidencias al decimal. pdfium da la caja del trazado sin el grosor
del trazo, y su caja de texto es la de los glifos, no una estimación con los
anchos de la fuente. Lo que busca es cazar errores gruesos: matrices mal
compuestas, coordenadas sin transformar, objetos desplazados por una escala de
emplazamiento. Un error de un par de puntos se tolera y se cuenta; un objeto
que aparece a 29.000 puntos de donde está, no.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import pikepdf                          # noqa: E402
import pypdfium2 as pdfium              # noqa: E402

from nucleo.objetos import extraer_objetos   # noqa: E402
from nucleo.alinear_texto import alinear, chars_de_pagina, filtrar_sinteticos  # noqa: E402
from nucleo.fuentes import resolver_fuentes     # noqa: E402

# Tolerancias por tipo. En textos y trazados hay diferencias legítimas.
#
# Para el texto la tolerancia es PROPORCIONAL, no absoluta: en un run rotado la
# caja se agrega a partir de las cajas de los glifos y los extremos bailan unos
# puntos. Medido en 07 (run rotado, caja de 73 pt): 3,5 pt de diferencia, un 5 %
# del tamaño de la caja. Lo que hay que cazar no es eso: es el error que metía
# la matriz sin conjugar, que colocaba una imagen a 29.000 pt de su sitio.
#
# El caso 01 no se compara objeto a objeto porque pdfium crea un objeto de texto
# POR CARÁCTER cuando el generador emite un `Tj` por carácter, y nosotros los
# agrupamos en runs (es la agrupación heurística de la decisión C3). Son 1746
# objetos contra 18 y los dos están bien. Cuando los recuentos no cuadran, se
# compara la caja de la UNIÓN por tipo, que es lo que no puede bailar.
TOL = {
    "texto": 3.0,       # pdfium mide glifos; nosotros estimamos con /Widths
    "vector": 4.0,      # el trazo: pdfium no lo expande, nosotros sí
    "imagen": 0.5,      # aquí no hay excusa: la caja es el CTM tal cual
    "sombreado": 6.0,
}
PROPORCIONAL_TEXTO = 0.06


def unir(cajas):
    """Caja que contiene a todas las demás."""
    cajas = [c for c in cajas if c]
    if not cajas:
        return None
    return (min(c[0] for c in cajas), min(c[1] for c in cajas),
            max(c[2] for c in cajas), max(c[3] for c in cajas))


def _tolerancia(tipo: str, caja) -> float:
    """Tolerancia del tipo; para texto, proporcional al tamaño de la caja."""
    base = TOL.get(tipo, 3.0)
    if tipo == "texto" and caja:
        lado = max(abs(caja[2] - caja[0]), abs(caja[3] - caja[1]))
        return max(base, PROPORCIONAL_TEXTO * lado)
    return base


def cajas_pdfium(ruta: Path, pagina: int = 0):
    """(tipo, caja) de cada objeto según pdfium, en coordenadas de página."""
    doc = pdfium.PdfDocument(str(ruta))
    try:
        pag = doc[pagina]
        salida = []
        for o in pag.get_objects():
            try:
                b = o.get_bounds()
            except Exception:
                continue
            nombre = {1: "texto", 2: "vector", 3: "imagen",
                      4: "sombreado", 5: "form"}.get(o.type, str(o.type))
            salida.append((nombre, tuple(float(v) for v in b)))
        return salida
    finally:
        doc.close()


def cajas_propias(ruta: Path, pagina: int = 0):
    """(tipo, caja) de cada objeto según nuestro parser."""
    with pikepdf.open(ruta) as pdf:
        pag = pdf.pages[pagina]
        try:
            fuentes = resolver_fuentes(pag)
        except Exception:
            fuentes = {}
        datos = pag.Contents.read_bytes()
        contenido = extraer_objetos(datos, fuentes)

    # El paso de alineación es obligatorio para que las cajas de texto sean
    # comparables: extraer_objetos da una caja aproximada a partir de /Widths,
    # y alinear() la sustituye por la de los glifos, que es la que ve pdfium.
    # Comparar sin alinear mide nuestra propia aproximación, no la geometría.
    doc = pdfium.PdfDocument(str(ruta))
    try:
        chars, _ = filtrar_sinteticos(
            chars_de_pagina(doc[pagina].get_textpage()))
        alinear(contenido, chars)
    finally:
        doc.close()

    return [(o.tipo, o.caja.como_tupla() if o.caja else None)
            for o in contenido.objetos]


def comparar(ruta: Path, pagina: int = 0):
    """Discrepancias entre las dos listas. Empareja por orden de pintado."""
    propias = cajas_propias(ruta, pagina)
    ajenas = cajas_pdfium(ruta, pagina)
    problemas = []
    nota = ""

    if len(propias) != len(ajenas):
        # Recuentos distintos: casi siempre por agrupación de texto. La
        # diferencia se explica sola cuando el generador emite un `Tj` por
        # carácter y pdfium hace un objeto por glifo (caso 01: 18 runs nuestros
        # frente a 1746 objetos suyos, y los dos están bien). Se compara
        # entonces la caja de la unión de cada tipo, que es lo que no puede
        # bailar.
        nota = (f"agrupación distinta (parser {len(propias)}, pdfium "
                f"{len(ajenas)}): se compara la unión por tipo")
        for tipo in ("texto", "vector", "imagen", "sombreado"):
            c1 = unir([c for t, c in propias if t == tipo])
            c2 = unir([c for t, c in ajenas if t == tipo])
            if c1 is None and c2 is None:
                continue
            if c1 is None or c2 is None:
                problemas.append(
                    f"{tipo}: solo está en un lado "
                    f"(parser={c1}, pdfium={c2})")
                continue
            d = max(abs(a - b) for a, b in zip(c1, c2))
            tol = _tolerancia(tipo, c1)
            if d > tol:
                problemas.append(
                    f"{tipo} (unión): desviación {d:.1f} pt (>{tol:.1f}) "
                    f"nuestra={tuple(round(v,1) for v in c1)} "
                    f"pdfium={tuple(round(v,1) for v in c2)}")
        return problemas, propias, ajenas, nota

    for i, ((t1, c1), (t2, c2)) in enumerate(zip(propias, ajenas)):
        if c1 is None:
            problemas.append(f"{i}: el parser no da caja para {t1}")
            continue
        if t1 != t2:
            problemas.append(f"{i}: tipo {t1} contra {t2} de pdfium")
        tol = _tolerancia(t1, c1)
        d = max(abs(a - b) for a, b in zip(c1, c2))
        if d > tol:
            problemas.append(
                f"{i} {t1}: desviación {d:.1f} pt "
                f"(>{tol}) nuestra={tuple(round(v,1) for v in c1)} "
                f"pdfium={tuple(round(v,1) for v in c2)}")
    return problemas, propias, ajenas, nota


def main() -> int:
    corpus = RAIZ / "corpus"
    ficheros = sorted(corpus.glob("*.pdf"))
    if not ficheros:
        print("no hay corpus")
        return 1

    total = fallos = 0
    print()
    print(f"  {'fichero':34} {'objetos':>8} {'pág.':>5}  resultado")
    print("  " + "─" * 78)
    for f in ficheros:
        paginas = 1
        if f.name.startswith("07"):
            paginas = 5
        for pag in range(paginas):
            total += 1
            try:
                problemas, propias, ajenas, nota = comparar(f, pag)
            except Exception as e:
                problemas = [f"excepción: {type(e).__name__}: {e}"]
                propias, nota = [], ""
            if problemas:
                fallos += 1
                print(f"  {f.name[:34]:34} {len(propias):>8} {pag:>5}  "
                      f"✖ {len(problemas)} discrepancia(s)")
                for x in problemas[:6]:
                    print(f"  {'':34} {'':8} {'':5}    {x}")
            elif nota:
                print(f"  {f.name[:34]:34} {len(propias):>8} {pag:>5}  "
                      f"✓ coincide, con matiz")
                print(f"  {'':34} {'':8} {'':5}    {nota}")
            else:
                print(f"  {f.name[:34]:34} {len(propias):>8} {pag:>5}  "
                      f"✓ coincide")
    print()
    print(f"  {total - fallos}/{total} páginas coinciden con pdfium "
          f"(tolerancia por tipo)")
    print()
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
