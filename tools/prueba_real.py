#!/usr/bin/env python3
"""Prueba IntactPDF con PDFs reales de servidores públicos.

Qué comprueba, en este orden:

1. que el fichero se puede abrir y cuántas páginas, formularios y anotaciones
   tiene;
2. que una edición (escalar un objeto) se puede hacer;
3. que la salida **empieza por los bytes del original**, byte a byte: si eso es
   cierto, es imposible que haya cambiado cualquier otra cosa;
4. que la salida sigue siendo un PDF válido, con las mismas páginas, los mismos
   campos de formulario y las mismas anotaciones.

El punto 4 es el interesante con documentos reales: los formularios y las
anotaciones son justo lo que se pierde al reescribir un PDF con otras
herramientas, y la promesa de este programa es que eso no pasa.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pikepdf

RAIZ = Path("/home/user/linuxpdf")
CARPETA = Path("/home/user/PDFs-reales")
PY = sys.executable


def datos(ruta: Path) -> dict:
    """Lo que hay que no se puede perder: páginas, campos, anotaciones."""
    with pikepdf.open(ruta) as pdf:
        campos, anotaciones = 0, 0
        raiz = pdf.Root
        if "/AcroForm" in raiz and "/Fields" in raiz.AcroForm:
            pila = list(raiz.AcroForm.Fields)
            while pila:
                f = pila.pop()
                campos += 1
                if "/Kids" in f:
                    pila.extend(f.Kids)
        for pagina in pdf.pages:
            if "/Annots" in pagina:
                anotaciones += len(pagina.Annots)
        return {
            "paginas": len(pdf.pages),
            "campos": campos,
            "anotaciones": anotaciones,
            "bytes": ruta.stat().st_size,
        }


def editar(ruta: Path, salida: Path) -> tuple[bool, str]:
    """Escala un objeto. Devuelve si lo consiguió y qué dijo."""
    r = subprocess.run(
        [PY, "-m", "nucleo.cli", "scale", str(ruta), "--object", "0",
         "--factor", "0.9", "-o", str(salida)],
        capture_output=True, text=True, cwd=str(RAIZ), timeout=300)
    salida_texto = (r.stdout + r.stderr).strip()
    return r.returncode == 0 and salida.exists(), salida_texto


def prefijo_intacto(original: Path, editado: Path) -> bool:
    """¿Los primeros bytes de la salida son el original ENTERO?"""
    r = subprocess.run(
        ["sh", "-c",
         f'head -c "$(stat -c%s "{original}")" "{editado}" | cmp - "{original}"'],
        capture_output=True, text=True)
    return r.returncode == 0


def avisos(ruta: Path) -> set[str]:
    """Las advertencias de qpdf sobre un fichero, sin el nombre propio.

    No se pregunta «¿es perfecto?»: casi ningún PDF real lo es. Se pregunta «¿el
    nuestro es PEOR que el original?», que es lo único que depende de nosotros.
    Aquí, por ejemplo, el de govinfo ya viene con un stream sin /Length y el de
    orimi con una tabla de referencias híbrida: son suyos, no nuestros.
    """
    r = subprocess.run(["qpdf", "--check", str(ruta)], capture_output=True,
                       text=True, timeout=600)
    return {l.split("WARNING:", 1)[1].strip().replace(ruta.name, "FICHERO")
            for l in (r.stdout + r.stderr).splitlines() if "WARNING:" in l}


def tinta(ruta: Path) -> float:
    """Proporción de la página con algo dibujado, con pdfium (lo que ve la GUI)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(ruta))
    try:
        bmp = doc[0].render(scale=0.3)
        ancho, alto, canales, paso = bmp.width, bmp.height, bmp.n_channels, bmp.stride
        datos = bytes(bmp.buffer)
    finally:
        doc.close()
    con_algo = 0
    total = 0
    for y in range(0, alto, 3):
        base = y * paso
        for x in range(0, ancho, 3):
            i = base + x * canales
            if datos[i] < 250 or datos[i + 1] < 250 or datos[i + 2] < 250:
                con_algo += 1
            total += 1
    return con_algo / total if total else 0.0


def main() -> int:
    for original in sorted(CARPETA.glob("*.pdf")):
        print(f"\n  {'─' * 72}")
        print(f"  {original.name}  ({original.stat().st_size / 1e6:.2f} MB)")
        try:
            antes = datos(original)
        except Exception as e:
            print(f"    ✗ no se puede abrir: {type(e).__name__}: {e}")
            continue
        print(f"    páginas {antes['paginas']} · campos de formulario "
              f"{antes['campos']} · anotaciones {antes['anotaciones']}")

        salida = original.with_name(original.stem + "-editado.pdf")
        if salida.exists():
            salida.unlink()
        hecho, dicho = editar(original, salida)
        if not hecho:
            # Negarse a escribir puede ser la respuesta correcta: el guardado se
            # comprueba a sí mismo antes de dar el fichero por bueno.
            razon = [l for l in dicho.splitlines() if l.strip()][-1] if dicho else "?"
            aviso = "NO se ha guardado" in dicho or "en blanco" in dicho
            print(f"    {'·' if not aviso else '!'} sin edición: {razon[:150]}")
            continue

        despues = datos(salida)
        prefijo = prefijo_intacto(original, salida)
        t_antes, t_despues = tinta(original), tinta(salida)
        nuevos = avisos(salida) - avisos(original)
        iguales = (antes["paginas"] == despues["paginas"]
                   and antes["campos"] == despues["campos"]
                   and antes["anotaciones"] == despues["anotaciones"])
        print(f"    edición: {antes['bytes']:,} → {despues['bytes']:,} bytes "
              f"(+{despues['bytes'] - antes['bytes']:,})")
        print(f"    {'✓' if prefijo else '✗'} el original está al principio, byte a byte")
        print(f"    {'✓' if iguales else '✗'} páginas, campos y anotaciones iguales"
              f" ({despues['paginas']} · {despues['campos']} · {despues['anotaciones']})")
        print(f"    {'✓' if t_despues > t_antes * 0.5 else '✗'} la página se sigue viendo "
              f"({t_antes * 100:.1f} % → {t_despues * 100:.1f} % de superficie con algo)")
        print(f"    {'✓' if not nuevos else '·'} sin avisos nuevos de qpdf"
              + (f": {sorted(nuevos)[:2]}" if nuevos else ""))
    print(f"\n  {'─' * 72}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
