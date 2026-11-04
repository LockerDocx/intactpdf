"""Tests de las mejoras introducidas en esta versión (ver MEJORAS.md).

  1. El preludio de borrado se REEMITE: el estado gráfico que heredaba el
     objeto siguiente no cambia.
  2. `aplicar_ediciones` rechaza rangos solapados.
  3. `EditorPagina` encadena ediciones sobre un único snapshot.
  4. `verificar_fidelidad`: ni un píxel fuera de la zona editada.
  5. La CLI guarda en la página pedida por `--pagina` (antes siempre en la 0).
  6. El comando `diff` compara dos PDFs píxel a píxel.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nucleo.editar import (Edicion, EditorPagina, aplicar_ediciones,
                           edicion_borrar)
from nucleo.guardar import (escribir_incremental, guardar_pagina_editada,
                            rotar_pagina, verificar_fidelidad)
from nucleo.objetos import extraer_objetos
from nucleo.parser import parsear

CORPUS = ROOT / "corpus"


# ---------------------------------------------------------------------------
# 1. El preludio se reemite: el estado heredado no cambia
# ---------------------------------------------------------------------------

# Tres vectores: uno gris, uno rojo (que se borra) y un tercero que NO fija
# color: en el original se pinta rojo porque lo hereda del segundo. Si al
# borrar el segundo se elimina también su `1 0 0 rg`, el tercero saldría
# gris: un píxel cambiado fuera de la zona editada.
STREAM_HERENCIA = (
    b"0.5 0.5 0.5 rg\n"
    b"5 5 5 5 re f\n"
    b"1 0 0 rg\n"
    b"10 10 50 50 re f\n"
    b"20 20 40 40 re f\n"
)


def test_borrar_reemite_el_preludio_y_conserva_el_estado():
    contenido = extraer_objetos(STREAM_HERENCIA)
    vectores = contenido.por_tipo("vector")
    assert len(vectores) == 3

    ed = edicion_borrar(contenido, vectores[1], datos=STREAM_HERENCIA)
    resultado = aplicar_ediciones(STREAM_HERENCIA, [ed])

    # misma longitud (el diff queda mínimo) y la geometría del borrado fuera
    assert len(resultado) == len(STREAM_HERENCIA)
    assert b"10 10 50 50" not in resultado
    # el preludio sigue presente, reemitido tras la región
    assert b"1 0 0 rg" in resultado

    # y lo importante: el tercer vector sigue pintándose en ROJO
    reparse = extraer_objetos(resultado)
    restantes = reparse.por_tipo("vector")
    assert len(restantes) == 2
    colores = {v.color_relleno for v in restantes}
    assert (1.0, 0.0, 0.0) in colores, "el heredero del estado perdió el rojo"


def test_borrar_sin_datos_mantiene_comportamiento_historico():
    """Sin `datos` no se puede reemitir: el preludio se elimina (modo legado)."""
    contenido = extraer_objetos(STREAM_HERENCIA)
    vectores = contenido.por_tipo("vector")
    ed = edicion_borrar(contenido, vectores[1])     # sin datos=
    resultado = aplicar_ediciones(STREAM_HERENCIA, [ed])
    assert b"1 0 0 rg" not in resultado
    # y en este caso el tercero hereda el gris: es el riesgo documentado
    reparse = extraer_objetos(resultado)
    colores = {v.color_relleno for v in reparse.por_tipo("vector")}
    assert (1.0, 0.0, 0.0) not in colores


# ---------------------------------------------------------------------------
# 2. Validación de solapes
# ---------------------------------------------------------------------------

def test_ediciones_solapadas_se_rechazan():
    datos = b"0123456789ABCDEF"
    with pytest.raises(ValueError, match="solapadas"):
        aplicar_ediciones(datos, [Edicion(2, 6, b"xx"), Edicion(4, 8, b"yy")])


def test_ediciones_adyacentes_o_inserciones_no_solapan():
    datos = b"0123456789ABCDEF"
    out = aplicar_ediciones(datos, [Edicion(2, 2, b">>"), Edicion(4, 6, b"--")])
    assert out == b"01>>23--6789ABCDEF"


# ---------------------------------------------------------------------------
# 3. EditorPagina: encadenar sobre un único snapshot
# ---------------------------------------------------------------------------

def test_editor_pagina_encadena_mover_y_borrar(tmp_path):
    """El escenario exacto que rompe el encadenado ingenuo: mover inserta
    bytes al principio del stream y desplaza todos los offsets; calcular el
    borrado sobre el stream ya movido corrompe el documento."""
    import pikepdf
    from nucleo.fuentes import resolver_fuentes
    from nucleo.parser import contenido_pagina

    src = CORPUS / "05_cmyk_imprenta.pdf"
    with pikepdf.open(str(src)) as pdf:
        datos = contenido_pagina(pdf.pages[0])
        fuentes = resolver_fuentes(pdf.pages[0])
    contenido = extraer_objetos(datos, fuentes)

    img = contenido.por_tipo("imagen")[0]
    txt = contenido.por_tipo("texto")[0]

    ed = EditorPagina(datos, contenido)
    ed.mover(img, 50, 0).borrar(txt)
    editado = ed.aplicar()

    # la geometría del vector NO se ha tocado (síntoma del bug de offsets)
    assert b"72 540 320 26 re f*" in editado
    # el color negro del texto siguiente sigue donde estaba
    assert b"0 0 0 1 k" in editado
    # la imagen va envuelta en su matriz conjugada (50/320 = 0.15625)
    assert b"q 1 0 0 1 0.15625 0 cm" in editado
    # el primer texto ya no está
    assert b"Imagen JPEG" not in editado
    # y el stream re-parsea: mismos tipos de objeto esperados
    reparse = extraer_objetos(editado, fuentes)
    assert len(reparse.por_tipo("texto")) == 1
    assert len(reparse.por_tipo("vector")) == 1


def test_editor_pagina_rechaza_borrar_dos_veces_el_mismo_objeto():
    contenido = extraer_objetos(STREAM_HERENCIA)
    v = contenido.por_tipo("vector")[0]
    ed = EditorPagina(STREAM_HERENCIA, contenido)
    ed.borrar(v)
    with pytest.raises(ValueError, match="ya se ha borrado"):
        ed.borrar(v)


# ---------------------------------------------------------------------------
# 4. Verificación de fidelidad píxel a píxel en el guardado
# ---------------------------------------------------------------------------

def _editar_cmyk(tmp_path):
    """Mueve la imagen del corpus y devuelve (original, salida, zonas)."""
    import pikepdf
    from nucleo.fuentes import resolver_fuentes
    from nucleo.parser import contenido_pagina

    src = CORPUS / "05_cmyk_imprenta.pdf"
    with pikepdf.open(str(src)) as pdf:
        datos = contenido_pagina(pdf.pages[0])
        fuentes = resolver_fuentes(pdf.pages[0])
    contenido = extraer_objetos(datos, fuentes)
    img = contenido.por_tipo("imagen")[0]

    ed = EditorPagina(datos, contenido)
    ed.mover(img, 50, 0)
    editado = ed.aplicar()

    c = img.caja
    zonas = [(c.x0, c.y0, c.x1 + 50, c.y1)]
    salida = tmp_path / "editado.pdf"
    return src, salida, editado, zonas


def test_guardado_con_fidelidad_estricta_pasa(tmp_path):
    src, salida, editado, zonas = _editar_cmyk(tmp_path)
    info = guardar_pagina_editada(src, salida, 0, [editado],
                                  zonas_editadas=zonas)
    assert info.prefijo_intacto
    # y la comprobación directa también la pasa
    assert verificar_fidelidad(src, salida, 0, zonas) is None


def test_fidelidad_detecta_cambios_fuera_de_zona(tmp_path):
    """Si las zonas no cubren la edición real, la verificación PROTESTA:
    es la red de seguridad contra efectos colaterales."""
    src, salida, editado, _ = _editar_cmyk(tmp_path)
    guardar_pagina_editada(src, salida, 0, [editado], zonas_editadas=None)
    problema = verificar_fidelidad(src, salida, 0, zonas_pt=[])
    assert problema is not None
    assert "FUERA de la zona editada" in problema


def test_guardado_con_zonas_equivocadas_se_descarta(tmp_path):
    from nucleo.guardar import ErrorGuardado
    src, salida, editado, _ = _editar_cmyk(tmp_path)
    # una zona que no cubre la imagen movida: el guardado debe rechazarse
    # y NO debe quedar fichero escrito
    zona_mala = [(0, 0, 10, 10)]
    with pytest.raises(ErrorGuardado, match="FUERA de la zona editada"):
        guardar_pagina_editada(src, salida, 0, [editado],
                               zonas_editadas=zona_mala)
    assert not salida.exists()


# ---------------------------------------------------------------------------
# 5. La CLI guarda en la página pedida por --pagina
# ---------------------------------------------------------------------------

def test_cli_move_respeta_la_pagina(tmp_path):
    """Antes de la corrección, `--pagina 1` escribía el contenido editado en
    los streams de la página 0. Ahora la página 0 debe quedar INTACTA."""
    from nucleo.cli import main

    src = CORPUS / "07_paginas_rotadas_mixtas.pdf"
    trabajo = tmp_path / "doc.pdf"
    shutil.copy2(src, trabajo)
    salida = tmp_path / "salida.pdf"

    rc = main(["move", str(trabajo), "--object", "0", "--pagina", "1",
               "--dx", "25", "--dy", "0", "-o", str(salida)])
    assert rc == 0

    import pypdfium2 as pdfium
    da = pdfium.PdfDocument(str(src))
    db = pdfium.PdfDocument(str(salida))
    try:
        pa = bytes(da[0].render(scale=1.0).buffer)
        pb = bytes(db[0].render(scale=1.0).buffer)
        assert pa == pb, "la página 0 cambió al editar la página 1"
        qa = bytes(da[1].render(scale=1.0).buffer)
        qb = bytes(db[1].render(scale=1.0).buffer)
        assert qa != qb, "la página 1 no reflejó la edición"
    finally:
        da.close()
        db.close()


# ---------------------------------------------------------------------------
# 6. Comando diff
# ---------------------------------------------------------------------------

def test_cli_diff_identicos_y_distintos(tmp_path):
    from nucleo.cli import EXITO, ERROR, main

    src = CORPUS / "07_paginas_rotadas_mixtas.pdf"
    rotado = tmp_path / "rotado.pdf"
    rotar_pagina(src, rotado, 0, 90)

    assert main(["diff", str(src), str(src), "--paginas", "2",
                 "--escala", "1.0"]) == EXITO
    assert main(["diff", str(src), str(rotado), "--paginas", "2",
                 "--escala", "1.0"]) == ERROR
