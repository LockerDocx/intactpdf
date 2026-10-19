"""
El test de aceptación como test, no solo como herramienta.

Ejecuta todos los casos, exige que ninguno se salga de su región y escribe
`resultados/f2/aceptacion.json` para que quede constancia de las cifras.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# El arnés se carga por RUTA y no con `import test_aceptacion`. Con el import a
# secas, lanzar `pytest tests/` desde la raíz del repositorio hacía que este
# fichero se importara a sí mismo (los dos se llaman test_aceptacion y pytest no
# usa paquetes), y el resultado era un error de importación circular que no
# tenía nada que ver con el código. Cargándolo por ruta no hay colisión posible.
_spec = importlib.util.spec_from_file_location("arnes_aceptacion",
                                               RAIZ / "tools" / "test_aceptacion.py")
assert _spec and _spec.loader
_arnes = importlib.util.module_from_spec(_spec)
# Hay que dejarlo en sys.modules ANTES de ejecutarlo: `@dataclass` busca el
# módulo por su nombre en sys.modules para resolver los tipos, y si no está
# revienta con un AttributeError de lo más desconcertante.
sys.modules[_spec.name] = _arnes
_spec.loader.exec_module(_arnes)
CASOS, ejecutar = _arnes.CASOS, _arnes.ejecutar


def _correr_todos():
    resultados = []
    for caso in CASOS:
        resultados.append((caso, ejecutar(caso)))
    return resultados


def test_todos_los_casos_pasan():
    """Criterio: el cambio está Y nada más ha cambiado."""
    resultados = _correr_todos()
    fallos = [r for _, r in resultados if not r.ok]
    assert not fallos, [
        (r.caso, r.px_fuera, [d for d in r.detalle if "FUERA" in d])
        for r in fallos
    ]


def test_la_salida_empieza_por_el_original():
    """La propiedad que distingue a este editor: el fichero guardado es el
    original íntegro más un apéndice. Si se cumple, es imposible que se haya
    modificado cualquier otra cosa."""
    resultados = _correr_todos()
    malos = [r.caso for _, r in resultados if not r.prefijo_intacto]
    assert not malos, malos


def test_la_estructura_no_se_toca():
    """Lo que LibreOffice destruye y aquí debe sobrevivir: espacio de color
    CMYK, canal alfa (SMask), formularios, dimensiones y anotaciones."""
    import pikepdf

    def perfil(ruta):
        p = pikepdf.open(str(ruta))
        r = {
            "paginas": len(p.pages),
            "tamanos": [[round(float(pg.MediaBox[2]), 2),
                         round(float(pg.MediaBox[3]), 2)] for pg in p.pages],
            "acroform": p.Root.get("/AcroForm") is not None,
            "anotaciones": sum(len(pg.get("/Annots", []) or []) for pg in p.pages),
        }
        cmyk = smask = 0
        for pg in p.pages:
            res = pg.get("/Resources")
            xo = res.get("/XObject") if res is not None else None
            if xo is None:
                continue
            for k in xo.keys():
                o = xo[k]
                if "CMYK" in str(o.get("/ColorSpace", "")):
                    cmyk += 1
                if o.get("/SMask") is not None:
                    smask += 1
        r["imagenes_cmyk"] = cmyk
        r["imagenes_con_smask"] = smask
        p.close()
        return r

    comprobados = 0
    for caso, r in _correr_todos():
        editado = RAIZ / ".tmp" / f"acept_{r.caso}.pdf"
        if not editado.exists():
            continue
        a = perfil(RAIZ / "corpus" / caso.pdf)
        b = perfil(editado)
        assert a == b, (caso.nombre, {k: (a[k], b[k]) for k in a if a[k] != b[k]})
        comprobados += 1
    assert comprobados >= len(CASOS), comprobados
    print(f"\n  estructura idéntica en {comprobados} salidas")


def test_qpdf_valida_las_salidas():
    """Un fichero que el proyecto genere debe pasar un validador externo."""
    import shutil
    import subprocess
    import pytest
    if not shutil.which("qpdf"):
        pytest.skip("qpdf no está instalado en el sistema")
    for _, r in _correr_todos():
        editado = RAIZ / ".tmp" / f"acept_{r.caso}.pdf"
        if not editado.exists():
            continue
        res = subprocess.run(["qpdf", "--check", str(editado)],
                             capture_output=True, text=True)
        assert res.returncode == 0, (r.caso, res.stdout, res.stderr)
    print("\n  qpdf --check sin errores en todas las salidas")


def test_escribir_informe_json():
    resultados = _correr_todos()
    destino = RAIZ / "resultados" / "f2"
    destino.mkdir(parents=True, exist_ok=True)
    datos = {
        "criterio": "el cambio está y nada más ha cambiado",
        "casos": [
            {
                "caso": r.caso,
                "pdf": caso.pdf,
                "descripcion": caso.descripcion,
                "pasa": r.ok,
                "px_cambiados": r.px_cambiados,
                "px_fuera_de_la_region": r.px_fuera,
                "px_totales": r.px_totales,
                "empieza_por_el_original": r.prefijo_intacto,
                "bytes_original": r.bytes_original,
                "bytes_anadidos": r.bytes_anadidos,
                "detalle": r.detalle,
            }
            for caso, r in resultados
        ],
    }
    (destino / "aceptacion.json").write_text(
        json.dumps(datos, indent=2, ensure_ascii=False))
    print(f"\n  resultados escritos en {destino / 'aceptacion.json'}")
    assert all(c["pasa"] for c in datos["casos"])


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
