"""
Escritura incremental de PDF.

Por qué está escrito a mano: ni qpdf ni pikepdf saben escribir incrementalmente
(qpdf 12.2.0 no tiene la opción, y `Pdf.save()` de pikepdf no la expone). Ambos
reescriben el fichero entero. Para un proyecto que se define por NO reconstruir
el documento, eso es inaceptable: reescribir es exactamente lo que hace
LibreOffice Draw y lo que la validación empírica demostró que rompe CMYK,
formularios, dimensiones de página y fuentes.

Qué es una actualización incremental (especificación PDF, 7.5.6): en vez de
reescribir, se AÑADE al final del fichero la nueva versión de los objetos que
cambian, más una sección de referencias cruzadas nueva que apunta a la anterior
con /Prev. El fichero original queda intacto byte a byte.

Consecuencia verificable, y es la base del test de aceptación: el fichero de
salida EMPIEZA POR los bytes del original. Si eso se cumple, es imposible que se
haya modificado cualquier otra cosa.
"""
from __future__ import annotations

import re
import shutil
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf


class ErrorGuardado(Exception):
    pass


@dataclass
class Cambio:
    """Nueva definición completa de un objeto existente."""
    num: int
    gen: int
    cuerpo: bytes              # "N G obj ... endobj" ya montado
    offset: int = 0


@dataclass
class InformeGuardado:
    incremental: bool
    bytes_original: int
    bytes_salida: int
    bytes_anadidos: int
    objetos_redefinidos: list[tuple[int, int]] = field(default_factory=list)
    prefijo_intacto: bool = False

    @property
    def empieza_por_el_original(self) -> bool:
        return self.prefijo_intacto


@dataclass
class InformeCompactado:
    bytes_original: int
    bytes_salida: int
    bytes_ahorrados: int
    paginas: int


def offset_ultimo_xref(datos: bytes) -> int:
    """Offset de la sección de referencias cruzadas más reciente.

    Es lo que apunta `startxref` al final del fichero, y es por tanto el /Prev
    de la actualización incremental.
    """
    pos = datos.rfind(b"startxref")
    if pos < 0:
        raise ErrorGuardado("el PDF no tiene startxref")
    m = re.search(rb"startxref\s+(\d+)", datos[pos:])
    if not m:
        raise ErrorGuardado("no se pudo leer el offset de startxref")
    return int(m.group(1))


def cuerpo_stream(datos: bytes, comprimir: bool = True) -> bytes:
    """Cuerpo completo de un objeto stream: el diccionario, `stream` y los
    datos. Es lo que se le pasa a `escribir_incremental` como valor."""
    return _montar_stream(datos, comprimir)


def cuerpo_dict(texto: bytes) -> bytes:
    """Cuerpo de un objeto que es un diccionario normal."""
    return texto


def _montar_stream(datos: bytes, comprimir: bool) -> bytes:
    """Cuerpo de un objeto stream, sin el envoltorio obj/endobj."""
    if comprimir:
        payload = zlib.compress(datos, 9)
        extra = b" /Filter /FlateDecode"
    else:
        payload = datos
        extra = b""
    cab = (b"<< /Length " + str(len(payload)).encode()
           + extra + b" >>\nstream\n")
    return cab + payload + b"\nendstream"


def _formatear_xref(entradas: list[tuple[int, int, int]]) -> bytes:
    """Sección xref clásica.

    Cada entrada ocupa exactamente 20 bytes: 10 dígitos de offset, espacio,
    5 de generación, espacio, tipo, espacio, salto de línea.
    """
    if not entradas:
        return b"xref\n0 0\n"
    entradas = sorted(entradas, key=lambda e: e[0])

    # agrupar en subsecciones contiguas
    partes: list[bytes] = [b"xref\n"]
    grupos: list[list[tuple[int, int, int]]] = []
    actual = [entradas[0]]
    for e in entradas[1:]:
        if e[0] == actual[-1][0] + 1:
            actual.append(e)
        else:
            grupos.append(actual)
            actual = [e]
    grupos.append(actual)

    for g in grupos:
        partes.append(f"{g[0][0]} {len(g)}\n".encode("ascii"))
        for num, gen, off in g:
            if off < 0:
                partes.append(f"{num:010d} {gen:05d} f \n".encode("ascii"))
            else:
                partes.append(f"{off:010d} {gen:05d} n \n".encode("ascii"))
    return b"".join(partes)


def _formatear_id(valor) -> bytes:
    if valor is None:
        return b"[]"
    try:
        partes = []
        for x in valor:
            b = bytes(x)
            partes.append(b"<" + b.hex().encode("ascii") + b">")
        return b"[ " + b" ".join(partes) + b" ]"
    except Exception:
        return b"[]"


def escribir_incremental(
    ruta_original: str | Path,
    ruta_salida: str | Path,
    objetos: dict[tuple[int, int], bytes],
) -> InformeGuardado:
    """Añade objetos al final del PDF como actualización incremental.

    `objetos` mapea (num, gen) -> CUERPO COMPLETO del objeto, es decir lo que va
    entre «N G obj» y «endobj». Para un stream se construye con
    `cuerpo_stream(datos)`; para un diccionario, con `cuerpo_dict(texto)`.

    Un número que ya existía es una redefinición; uno mayor o igual que /Size es
    un objeto nuevo. Mecánicamente es lo mismo: se escribe al final y la xref
    nueva apunta ahí.

    El fichero original NO se modifica; se escribe uno nuevo compuesto por el
    original íntegro más el apéndice.
    """
    ruta_original = Path(ruta_original)
    original = ruta_original.read_bytes()

    with pikepdf.open(str(ruta_original)) as pdf:
        num_prev = offset_ultimo_xref(original)
        raiz = pdf.trailer.get("/Root")
        if raiz is None:
            raise ErrorGuardado("el PDF no tiene /Root")
        num_raiz, gen_raiz = raiz.objgen
        size_original = int(pdf.trailer.get("/Size", 0))
        id_original = pdf.trailer.get("/ID")

        salida = bytearray(original)
        lista = list(objetos.items())
        if not lista:
            Path(ruta_salida).write_bytes(original)
            return InformeGuardado(
                incremental=True, bytes_original=len(original),
                bytes_salida=len(original), bytes_anadidos=0,
                objetos_redefinidos=[], prefijo_intacto=True)

        entradas: list[tuple[int, int, int]] = []
        redefinidos: list[tuple[int, int]] = []
        for (num, gen), cuerpo_objeto in lista:
            offset = len(salida)
            cuerpo = (f"{num} {gen} obj\n".encode("ascii")
                      + cuerpo_objeto + b"\nendobj\n")
            salida += cuerpo
            entradas.append((num, gen, offset))
            redefinidos.append((num, gen))

        offset_xref = len(salida)
        salida += _formatear_xref(entradas)

        num_max = max([n for n, _ in redefinidos] + [size_original - 1])
        trailer = (
            b"trailer\n<< /Size " + str(num_max + 1).encode()
            + b" /Root " + f"{num_raiz} {gen_raiz} R".encode()
            + b" /Prev " + str(num_prev).encode()
            + b" /ID " + _formatear_id(id_original)
            + b" >>\nstartxref\n" + str(offset_xref).encode()
            + b"\n%%EOF\n")
        salida += trailer

    Path(ruta_salida).write_bytes(bytes(salida))
    prefijo = bytes(salida[:len(original)]) == original
    return InformeGuardado(
        incremental=True,
        bytes_original=len(original),
        bytes_salida=len(salida),
        bytes_anadidos=len(salida) - len(original),
        objetos_redefinidos=redefinidos,
        prefijo_intacto=prefijo,
    )


# ---------------------------------------------------------------------------
# La comprobación que de verdad importa: ¿se ve lo que se ha guardado?
# ---------------------------------------------------------------------------

def esta_cifrado(ruta: str | Path) -> bool:
    """¿El documento va cifrado?

    Importa mucho más de lo que parece: un documento cifrado se lee sin
    problema si la contraseña está vacía (pikepdf lo abre igual), pero el
    guardado incremental escribe el stream nuevo EN CLARO dentro de un fichero
    que dice estar cifrado. Un lector que respete el cifrado descifra esos bytes
    y obtiene basura: la página se ve en blanco. Se descubrió con un PDF de
    prueba que se distribuye cifrado con contraseña vacía, y el resultado era un
    fichero que abría... sin nada dentro.

    Conservar el cifrado al escribir es un pendiente (hay que cifrar el stream
    nuevo con la misma clave). Hasta entonces, mejor decirlo que escribir un
    fichero roto.
    """
    with pikepdf.open(str(ruta)) as pdf:
        return bool(pdf.is_encrypted)


def _tinta(ruta: str | Path, num_pagina: int, escala: float = 0.3) -> float:
    """Qué proporción de la página tiene algo dibujado (0.0 a 1.0).

    Se muestrean los píxeles del búfer de pdfium, sin numpy ni Pillow: los dos
    son dependencias del arnés de pruebas, no del programa, y el programa tiene
    que funcionar con lo mínimo (pikepdf, pypdfium2 y fontTools).

    A 0.3 de escala una página A4 son unos 44.000 píxeles, y el muestreo lee
    uno de cada diez: 4.400 lecturas por página. Suficiente para distinguir «hay
    página» de «no hay nada», que es lo único que se pregunta aquí.
    """
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(ruta))
    try:
        if num_pagina >= len(doc):
            return 0.0
        bmp = doc[num_pagina].render(scale=escala)
        ancho, alto, canales, paso = bmp.width, bmp.height, bmp.n_channels, bmp.stride
        datos = bytes(bmp.buffer)
    finally:
        doc.close()
    if not ancho or not alto:
        return 0.0
    con_algo, total = 0, 0
    for y in range(0, alto, 3):
        base = y * paso
        for x in range(0, ancho, 3):
            i = base + x * canales
            # Blanco = 255 en los tres canales. Todo lo demás es tinta.
            if datos[i] < 250 or datos[i + 1] < 250 or datos[i + 2] < 250:
                con_algo += 1
            total += 1
    return con_algo / total if total else 0.0


def verificar_que_se_ve(ruta_original: str | Path, ruta_salida: str | Path,
                        num_pagina: int) -> str | None:
    """Comprueba que la página editada sigue teniendo algo dibujado.

    Devuelve el motivo si el guardado no se puede dar por bueno, o None si está
    bien. Es una comprobación de humo, no de fidelidad: no mira si el resto de
    la página sigue igual (eso lo garantiza el prefijo intacto), mira lo único
    que el prefijo no puede garantizar: que un lector REAL siga viendo la
    página. Son dos cosas distintas, y la diferencia se descubrió así:

    Probando con PDFs reales de servidores públicos (ver tools/prueba_real.py),
    un fichero linearizado con tabla de referencias híbrida —de los que
    producen algunos programas con «vista web rápida»— se guardaba con el
    prefijo intacto, el objeto de contenido correcto y el fichero válido para
    poppler... y pdfium, que es el motor que usa nuestra propia vista previa,
    lo pintaba EN BLANCO. El fichero era correcto y no se veía, que para un
    editor es lo mismo que estar roto: quien lo abriera vería una página vacía
    y guardaría encima creyendo que estaba bien.

    La comprobación es tan poco estricta a propósito: sólo se niega cuando la
    página original tenÍa contenido y la guardada no tiene casi nada. Un cambio
    legítimo (borrar el último objeto de una página, por ejemplo) cabe dentro de
    ese margen la mayor parte de las veces; mentir sobre lo guardado, no.
    """
    try:
        antes = _tinta(ruta_original, num_pagina)
        despues = _tinta(ruta_salida, num_pagina)
    except Exception as e:      # sin pdfium no se puede comprobar: se dice y se sigue
        return f"no se pudo comprobar si la página se ve ({type(e).__name__}: {e})"
    if antes >= 0.01 and despues < antes * 0.1:
        return (f"la página {num_pagina + 1} tenía contenido "
                f"({antes * 100:.1f} % de la superficie) y en el fichero guardado "
                f"casi no queda ninguno ({despues * 100:.1f} %): un lector la ve "
                f"en blanco")
    return None


# ---------------------------------------------------------------------------
# Puente desde el editor
# ---------------------------------------------------------------------------

def num_objeto_stream_de_pagina(pagina) -> list[tuple[int, int]]:
    """(num, gen) de cada stream de contenido de la página, en orden."""
    c = pagina.get("/Contents")
    if c is None:
        return []
    if isinstance(c, pikepdf.Array):
        return [s.objgen for s in c]
    return [c.objgen]


def guardar_pagina_editada(
    ruta_original: str | Path,
    ruta_salida: str | Path,
    num_pagina: int,
    contenidos: list[bytes],
    objetos_extra: dict[tuple[int, int], bytes] | None = None,
    verificar: bool = True,
    crear_backup: bool = True,
) -> InformeGuardado:
    """Guarda una página con sus streams de contenido reemplazados.

    Se redefinen los MISMOS objetos que ya existían, así que el objeto de página,
    los recursos, las fuentes y todo lo demás no se tocan en absoluto.

    Cuando se pasa **un** contenido y la página tiene varios streams (lo normal
    en un PDF de verdad), el contenido entero va al primero y los demás se
    vacían. Es correcto porque el contenido de una página es la CONCATENACIÓN de
    sus streams (especificación PDF, §7.8.2) y el editor trabaja justamente sobre
    esa concatenación: al vaciar los demás, la concatenación vuelve a ser
    exactamente lo editado, y el array `/Contents` del objeto de página —y el
    objeto de página entero— siguen sin tocarse.

    Soporta guardar sobre el archivo original de forma completamente segura:
    escribe primero en un archivo temporal en la misma carpeta, verifica que
    un visor real dibuja la página con contenido y, solo si la verificación
    pasa, crea una copia de seguridad `archivo.pdf~` y reemplaza el original
    de forma atómica. Si la verificación falla, el archivo temporal se borra
    y el original permanece intacto.
    """
    ruta_original = Path(ruta_original)
    ruta_salida = Path(ruta_salida)
    es_mismo_archivo = False
    try:
        if ruta_salida.exists() and ruta_original.resolve() == ruta_salida.resolve():
            es_mismo_archivo = True
    except Exception:
        pass

    with pikepdf.open(str(ruta_original)) as pdf:
        refs = num_objeto_stream_de_pagina(pdf.pages[num_pagina])
    if len(contenidos) == 1 and len(refs) > 1:
        contenidos = [contenidos[0]] + [b""] * (len(refs) - 1)
    if len(refs) != len(contenidos):
        raise ErrorGuardado(
            f"la página tiene {len(refs)} streams de contenido y se han pasado "
            f"{len(contenidos)} contenidos")
    if esta_cifrado(ruta_original):
        raise ErrorGuardado(
            "el documento está cifrado y todavía no se sabe conservar el cifrado "
            "al editar. Escribir el contenido sin cifrar dentro de un fichero que "
            "dice estar cifrado deja un documento que abre en blanco, así que no "
            "se escribe nada. Trabaja sobre una copia sin cifrado (por ejemplo, "
            "usando 'intactpdf decrypt' o abriéndolo e imprimiéndolo a PDF) o espera "
            "a que el cifrado en guardado incremental sea un pendiente resuelto.")

    objetos = {ref: cuerpo_stream(datos) for ref, datos in zip(refs, contenidos)}
    if objetos_extra:
        objetos.update(objetos_extra)

    # Escritura segura mediante archivo temporal de fase (staging)
    tmp_salida = ruta_salida.with_name(f".{ruta_salida.name}.{uuid.uuid4().hex[:8]}.tmp")

    try:
        informe = escribir_incremental(ruta_original, tmp_salida, objetos)
        if verificar:
            problema = verificar_que_se_ve(ruta_original, tmp_salida, num_pagina)
            if problema:
                tmp_salida.unlink(missing_ok=True)
                raise ErrorGuardado(
                    f"{problema}. El fichero guardado se ha descartado: es preferible "
                    f"no escribir nada a escribir algo que no se ve. Pasa con "
                    f"documentos con estructuras complejas o linearizados. "
                    f"El original no se ha tocado.")

        if es_mismo_archivo and crear_backup:
            backup = ruta_salida.with_name(f"{ruta_salida.name}~")
            try:
                shutil.copy2(ruta_salida, backup)
            except Exception:
                pass

        tmp_salida.replace(ruta_salida)
        return informe
    except Exception:
        tmp_salida.unlink(missing_ok=True)
        raise


def compactar_pdf(
    ruta_entrada: str | Path,
    ruta_salida: str | Path,
    comprimir_streams: bool = True,
) -> InformeCompactado:
    """Eliminación segura y purga de historial (compactación / redacción).

    A diferencia del guardado incremental (que conserva los bytes de versiones
    anteriores y objetos eliminados en el historial del fichero), la compactación
    reescribe el documento eliminando revisiones anteriores, objetos huérfanos y
    datos descartados, logrando una purga irreversible del contenido eliminado
    y reduciendo el tamaño del archivo al mínimo.
    """
    ruta_entrada = Path(ruta_entrada)
    ruta_salida = Path(ruta_salida)
    bytes_orig = ruta_entrada.stat().st_size
    with pikepdf.open(str(ruta_entrada)) as pdf:
        n_paginas = len(pdf.pages)
        pdf.save(str(ruta_salida), compress_streams=comprimir_streams, linearize=False)
    bytes_out = ruta_salida.stat().st_size
    return InformeCompactado(
        bytes_original=bytes_orig,
        bytes_salida=bytes_out,
        bytes_ahorrados=max(0, bytes_orig - bytes_out),
        paginas=n_paginas,
    )


def descifrar_pdf(
    ruta_entrada: str | Path,
    ruta_salida: str | Path,
    password: str = "",
) -> bool:
    """Abre un PDF cifrado (con contraseña o contraseña vacía) y lo guarda
    sin cifrado, permitiendo su edición segura con el motor incremental."""
    ruta_entrada = Path(ruta_entrada)
    ruta_salida = Path(ruta_salida)
    with pikepdf.open(str(ruta_entrada), password=password) as pdf:
        pdf.save(str(ruta_salida))
    return True


def tiene_firma_digital(ruta: str | Path) -> bool:
    """Detecta si el documento PDF contiene firmas digitales.

    Comprueba campos de firma (/Sig) en el catálogo (/AcroForm), anotaciones
    de tipo Widget/Sig en las páginas y la presencia de streams /ByteRange.
    Cualquier edición en un documento firmado invalida legalmente la firma.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return False
    try:
        with pikepdf.open(str(ruta)) as doc:
            acro = doc.Root.get("/AcroForm")
            if acro:
                fields = acro.get("/Fields", [])
                for f in fields:
                    if f.get("/FT") == pikepdf.Name("/Sig"):
                        return True
            for pg in doc.pages:
                annots = pg.get("/Annots", [])
                for a in annots:
                    if a.get("/Subtype") == pikepdf.Name("/Widget") and a.get("/FT") == pikepdf.Name("/Sig"):
                        return True
                    if a.get("/Subtype") == pikepdf.Name("/Sig"):
                        return True
        datos = ruta.read_bytes()
        if b"/ByteRange" in datos and b"/Contents" in datos and b"/SubFilter" in datos:
            return True
    except Exception:
        pass
    return False


def rotar_pagina(
    ruta_original: str | Path,
    ruta_salida: str | Path,
    num_pagina: int,
    angulo: int,
    crear_backup: bool = True,
) -> InformeGuardado:
    """Rota una página del documento incrementando su clave /Rotate en 90, 180 o 270 grados.

    No altera ningún stream de dibujo ni reconstruye el documento: redefine únicamente
    el diccionario de la página de forma incremental.
    """
    ruta_original = Path(ruta_original)
    ruta_salida = Path(ruta_salida)
    es_mismo_archivo = False
    try:
        if ruta_salida.exists() and ruta_original.resolve() == ruta_salida.resolve():
            es_mismo_archivo = True
    except Exception:
        pass

    with pikepdf.open(str(ruta_original)) as pdf:
        if num_pagina >= len(pdf.pages):
            raise ErrorGuardado(f"página {num_pagina} fuera de rango (el documento tiene {len(pdf.pages)})")
        pagina = pdf.pages[num_pagina]
        rot_actual = 0
        nodo = pagina.obj
        while nodo:
            if "/Rotate" in nodo:
                rot_actual = int(nodo.Rotate)
                break
            nodo = nodo.get("/Parent")
        nueva_rot = (rot_actual + angulo) % 360

        pagina.Rotate = nueva_rot
        num_pag, gen_pag = pagina.objgen
        cuerpo_pag = pikepdf.Dictionary(pagina.obj).unparse()

    objetos = {(num_pag, gen_pag): cuerpo_pag}

    tmp_salida = ruta_salida.with_name(f".{ruta_salida.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        informe = escribir_incremental(ruta_original, tmp_salida, objetos)
        if es_mismo_archivo and crear_backup:
            backup = ruta_salida.with_name(f"{ruta_salida.name}~")
            try:
                shutil.copy2(ruta_salida, backup)
            except Exception as e:
                tmp_salida.unlink(missing_ok=True)
                raise ErrorGuardado(
                    f"No se pudo crear la copia de seguridad de respaldo ({backup}): {e}. "
                    "Operación cancelada para proteger el archivo original."
                )
        tmp_salida.replace(ruta_salida)
        return informe
    except Exception:
        tmp_salida.unlink(missing_ok=True)
        raise


def extraer_imagen(
    ruta_pdf: str | Path,
    num_pagina: int,
    nombre_xobject: str,
    ruta_salida: str | Path,
) -> Path:
    """Extrae una imagen incrustada (XObject) en su resolución y calidad original a disco.

    Admite exportar a PNG o JPG según la extensión de salida.
    """
    from PIL import Image
    ruta_pdf = Path(ruta_pdf)
    ruta_salida = Path(ruta_salida)

    nombre_normalizado = "/" + nombre_xobject.lstrip("/")
    with pikepdf.open(str(ruta_pdf)) as pdf:
        if num_pagina >= len(pdf.pages):
            raise ErrorGuardado(f"página {num_pagina} fuera de rango")
        pg = pdf.pages[num_pagina]
        xobjs = pg.Resources.get("/XObject")
        if not xobjs or nombre_normalizado not in xobjs:
            # Buscar sin barra o insensible
            encontrado = None
            if xobjs:
                for k in xobjs.keys():
                    if str(k).lstrip("/") == nombre_xobject.lstrip("/"):
                        encontrado = k
                        break
            if not encontrado:
                raise ErrorGuardado(f"XObject {nombre_xobject} no encontrado en la página {num_pagina}")
            nombre_normalizado = encontrado

        xobj = xobjs[nombre_normalizado]
        formato = ruta_salida.suffix.lower()

        # Si el XObject ya está en JPEG (/DCTDecode) y la salida es .jpg/.jpeg,
        # extraemos el flujo binario crudo directamente sin decodificar ni recomprimir
        filtro = xobj.get("/Filter")
        es_dct = (filtro == pikepdf.Name("/DCTDecode") or
                  (isinstance(filtro, pikepdf.Array) and len(filtro) == 1 and filtro[0] == pikepdf.Name("/DCTDecode")))
        if es_dct and formato in (".jpg", ".jpeg"):
            ruta_salida.write_bytes(bytes(xobj.read_raw_bytes()))
            return ruta_salida

        # En cualquier otro caso, decodificar mediante pikepdf/Pillow
        pdf_image = pikepdf.PdfImage(xobj)
        pil_img = pdf_image.as_pil_image()

    if formato in (".jpg", ".jpeg"):
        if pil_img.mode in ("RGBA", "P"):
            pil_img = pil_img.convert("RGB")
        pil_img.save(str(ruta_salida), "JPEG", quality=95)
    else:
        pil_img.save(str(ruta_salida), "PNG")
    return ruta_salida


def reemplazar_imagen(
    ruta_original: str | Path,
    ruta_salida: str | Path,
    num_pagina: int,
    nombre_xobject: str,
    ruta_nueva_imagen: str | Path,
    crear_backup: bool = True,
) -> InformeGuardado:
    """Reemplaza la imagen de un XObject por una nueva imagen desde disco.

    Preserva el 100% de la maquetación (coordenadas, rotación y escala de la matriz Do en el stream)
    y conserva el prefijo original del archivo PDF intacto mediante actualización incremental.
    """
    from PIL import Image
    ruta_original = Path(ruta_original)
    ruta_salida = Path(ruta_salida)
    ruta_nueva_imagen = Path(ruta_nueva_imagen)

    if not ruta_nueva_imagen.exists():
        raise ErrorGuardado(f"La imagen {ruta_nueva_imagen} no existe")

    es_mismo_archivo = False
    try:
        if ruta_salida.exists() and ruta_original.resolve() == ruta_salida.resolve():
            es_mismo_archivo = True
    except Exception:
        pass

    nombre_normalizado = "/" + nombre_xobject.lstrip("/")
    with pikepdf.open(str(ruta_original)) as pdf:
        if num_pagina >= len(pdf.pages):
            raise ErrorGuardado(f"página {num_pagina} fuera de rango")
        pg = pdf.pages[num_pagina]
        xobjs = pg.Resources.get("/XObject")
        if not xobjs or nombre_normalizado not in xobjs:
            encontrado = None
            if xobjs:
                for k in xobjs.keys():
                    if str(k).lstrip("/") == nombre_xobject.lstrip("/"):
                        encontrado = k
                        break
            if not encontrado:
                raise ErrorGuardado(f"XObject {nombre_xobject} no encontrado en la página {num_pagina}")
            nombre_normalizado = encontrado

        xobj = xobjs[nombre_normalizado]
        num_obj, gen_obj = xobj.objgen
        size_trailer = int(pdf.trailer.get("/Size", 0))

    # Cargar y codificar la nueva imagen con Pillow
    with Image.open(str(ruta_nueva_imagen)) as img:
        ancho, alto = img.size
        extra_smask = None
        num_smask = size_trailer + 1

        # Normalizar a RGB, RGBA, L o CMYK
        if img.mode == "L":
            cs = b"/DeviceGray"
            raw_bytes = img.tobytes()
        elif img.mode == "RGBA":
            cs = b"/DeviceRGB"
            r, g, b, a = img.split()
            raw_bytes = Image.merge("RGB", (r, g, b)).tobytes()
            # Si contiene píxeles transparentes, crear Soft Mask (/SMask) estándar ISO 32000
            if a.getextrema()[0] < 255:
                alpha_bytes = a.tobytes()
                alpha_payload = zlib.compress(alpha_bytes, 9)
                extra_smask = (
                    b"<< /Type /XObject /Subtype /Image "
                    b"/Width " + str(ancho).encode("ascii") + b" "
                    b"/Height " + str(alto).encode("ascii") + b" "
                    b"/BitsPerComponent 8 "
                    b"/ColorSpace /DeviceGray "
                    b"/Filter /FlateDecode "
                    b"/Length " + str(len(alpha_payload)).encode("ascii") + b" >>\nstream\n"
                    + alpha_payload + b"\nendstream"
                )
        elif img.mode == "CMYK":
            cs = b"/DeviceCMYK"
            raw_bytes = img.tobytes()
        else:
            cs = b"/DeviceRGB"
            raw_bytes = img.convert("RGB").tobytes()

    payload = zlib.compress(raw_bytes, 9)
    smask_ref = f"/SMask {num_smask} 0 R ".encode("ascii") if extra_smask else b""
    cabecera = (
        b"<< /Type /XObject /Subtype /Image "
        b"/Width " + str(ancho).encode("ascii") + b" "
        b"/Height " + str(alto).encode("ascii") + b" "
        b"/BitsPerComponent 8 "
        b"/ColorSpace " + cs + b" "
        + smask_ref +
        b"/Filter /FlateDecode "
        b"/Length " + str(len(payload)).encode("ascii") + b" >>\nstream\n"
    )
    cuerpo_xobj = cabecera + payload + b"\nendstream"

    objetos = {(num_obj, gen_obj): cuerpo_xobj}
    if extra_smask:
        objetos[(num_smask, 0)] = extra_smask

    tmp_salida = ruta_salida.with_name(f".{ruta_salida.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        informe = escribir_incremental(ruta_original, tmp_salida, objetos)
        if es_mismo_archivo and crear_backup:
            backup = ruta_salida.with_name(f"{ruta_salida.name}~")
            try:
                shutil.copy2(ruta_salida, backup)
            except Exception as e:
                tmp_salida.unlink(missing_ok=True)
                raise ErrorGuardado(
                    f"No se pudo crear la copia de seguridad de respaldo ({backup}): {e}. "
                    "Operación cancelada para proteger el archivo original."
                )
        tmp_salida.replace(ruta_salida)
        return informe
    except Exception:
        tmp_salida.unlink(missing_ok=True)
        raise

