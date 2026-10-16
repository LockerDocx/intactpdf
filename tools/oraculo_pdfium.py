"""Oráculo independiente: mide los objetos de una página con pdfium, no con
nuestro parser ni con nuestro escritor."""
import pypdfium2 as pdfium

TIPOS = {1: 'texto', 2: 'vector', 3: 'imagen', 4: 'sombreado', 5: 'form'}

def objetos(ruta, pagina=0):
    d = pdfium.PdfDocument(ruta)
    p = d[pagina]
    salida = []
    for o in p.get_objects():
        try:
            b = o.get_bounds()
        except Exception as e:
            salida.append((TIPOS.get(o.type, o.type), None, f'error: {e}'))
            continue
        m = None
        try:
            m = tuple(round(v, 3) for v in o.get_matrix())
        except Exception:
            pass
        salida.append((TIPOS.get(o.type, o.type),
                       tuple(round(v, 1) for v in b), m))
    d.close()
    return salida

if __name__ == '__main__':
    import sys
    for f in sys.argv[1:]:
        print(f'== {f}')
        for t, b, m in objetos(f):
            print(f'   {t:9} caja={b}  matriz={m}')
        print()
