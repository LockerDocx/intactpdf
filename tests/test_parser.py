"""Tests del lexer y parser del content stream."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nucleo.parser import agrupar, parsear, tokenizar  # noqa: E402

CORPUS = Path(__file__).resolve().parent.parent / "corpus"


def test_lexer_tipos_basicos():
    src = b"q 1 0 0 1 72.5 -8 cm /F1 12 Tf (Hola) Tj <4865> Tj [1 -2 (a)] TJ Q"
    toks = tokenizar(src)
    tipos = [t.tipo for t in toks]
    # ojo: en PDF los operandos van ANTES del operador, así que `/F1 12 Tf`
    # es name, num, op (no op, num, num)
    assert tipos == ["op", "num", "num", "num", "num", "num", "num", "op",
                     "name", "num", "op", "string", "op", "hexstring", "op",
                     "array", "op", "op"], tipos
    assert toks[2].valor == 0
    assert toks[5].valor == 72.5, toks[5].valor
    assert toks[6].valor == -8, toks[6].valor
    assert toks[11].valor == b"Hola"
    assert toks[13].valor == b"He"
    assert toks[15].tipo == "array"
    assert toks[15].valor == [1, -2, b"a"], toks[15].valor


def test_lexer_escape_hex_en_nombre():
    toks = tokenizar(b"/A#42#43")
    assert len(toks) == 1
    assert toks[0].tipo == "name"
    assert toks[0].valor == "ABC", toks[0].valor


def test_lexer_string_con_parentesis_anidados_y_escapes():
    toks = tokenizar(rb"(hola \(mundo\) (anidado) fin\\) Tj")
    assert toks[0].tipo == "string"
    # el lexer deshace los escapes: \( -> (  y  \\ -> \
    assert toks[0].valor == b"hola (mundo) (anidado) fin\\", toks[0].valor
    assert toks[1].tipo == "op" and toks[1].valor == "Tj"


def test_lexer_string_octal():
    toks = tokenizar(rb"(\101\102\103) Tj")
    assert toks[0].valor == b"ABC", toks[0].valor


def test_lexer_hexstring_impar():
    toks = tokenizar(b"<ABC>")
    assert toks[0].valor == b"\xab\xc0", toks[0].valor


def test_lexer_posiciones_permiten_reescribir():
    src = b"1 0 0 1 0 0 cm"
    toks = tokenizar(src)
    # el último token debe terminar exactamente al final del stream
    assert toks[-1].fin == len(src)
    # cada token debe recuperar su texto exacto del stream original
    for t in toks:
        assert src[t.inicio:t.fin].strip() != b"", t
    assert src[toks[0].inicio:toks[0].fin] == b"1"
    assert src[toks[6].inicio:toks[6].fin] == b"cm"
    assert src[toks[-1].inicio:toks[-1].fin] == b"cm"
    # los spans no se solapan y están ordenados
    for a, b in zip(toks, toks[1:]):
        assert a.fin <= b.inicio, (a, b)


def test_operadores_especiales():
    for op in [b"f*", b"B*", b"b*", b"W*", b"T*", b"'", b'"', b"d0", b"d1"]:
        toks = tokenizar(op)
        assert len(toks) == 1, (op, toks)
        assert toks[0].tipo == "op", (op, toks)
        assert toks[0].valor == op.decode(), (op, toks[0].valor)


def test_agrupar_operandos():
    ins = parsear(b"q 1 0 0 1 5 6 cm BT /F1 12 Tf ET Q")
    assert [i.op for i in ins] == ["q", "cm", "BT", "Tf", "ET", "Q"]
    cm = ins[1]
    assert cm.operandos_num() == [1, 0, 0, 1, 5, 6]
    assert ins[3].operandos == ["F1", 12], ins[3].operandos


def test_array_tj_se_preserva():
    ins = parsear(b"[(A) -250 (B)] TJ")
    assert ins[0].op == "TJ"
    arr = ins[0].operandos[0]
    assert isinstance(arr, list)
    assert len(arr) == 3, arr


def test_basura_no_tumba_el_parser():
    # bytes aleatorios + un operador válido: no debe lanzar
    ins = parsear(bytes(range(256)) + b" Q")
    assert any(i.op == "Q" for i in ins)


def test_corpus_se_parsea_sin_excepciones():
    """Todos los PDFs del corpus deben parsearse sin lanzar.

    El recuento se lee del manifiesto, no se escribe a mano: el corpus crece
    (el 11 se añadió al descubrir que ningún PDF probaba el texto escalado) y un
    número fijo en el test sólo sirve para fallar cada vez que se añade un caso.
    """
    import json
    import pikepdf
    pdfs = sorted(CORPUS.glob("*.pdf"))
    manifiesto = CORPUS / "manifest.json"
    esperados = len(json.loads(manifiesto.read_text()))
    assert len(pdfs) == esperados, (
        f"el manifiesto dice {esperados} PDFs y hay {len(pdfs)}")
    total = 0
    for ruta in pdfs:
        pdf = pikepdf.open(str(ruta))
        for pagina in pdf.pages:
            c = pagina.get("/Contents")
            if c is None:
                continue
            if isinstance(c, pikepdf.Array):
                datos = b"\n".join(s.read_bytes() for s in c)
            else:
                datos = c.read_bytes()
            ins = parsear(datos)
            total += len(ins)
            # toda instrucción debe tener un operador no vacío
            assert all(i.op for i in ins), ruta.name
        pdf.close()
    assert total > 1000, f"solo {total} instrucciones en todo el corpus"
    print(f"  corpus parseado: {total} instrucciones en {len(pdfs)} PDFs")


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"  FALLA {nombre}: {e}")
            except Exception as e:
                fallos += 1
                print(f"  ERROR {nombre}: {type(e).__name__}: {e}")
    print(f"\n{fallos} fallos")
    sys.exit(1 if fallos else 0)
