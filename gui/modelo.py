"""
El modelo de la interfaz gráfica: estado del documento y operaciones.

Por qué está separado de la ventana. Todo lo que decide QUÉ le pasa al PDF vive
aquí y no importa GTK. Eso permite dos cosas que de otra forma serían caras:

  - probarlo sin pantalla, en un test normal y corriente;
  - y sobre todo, comprobar que la GUI no se desvía del CLI. El test abre el
    mismo PDF, hace la misma operación por los dos caminos y compara los bytes
    de salida. Si no son idénticos, falla. Una interfaz gráfica que guarda un
    fichero distinto del que guarda su propia línea de comandos es un error que
    se descubre tarde y duele.

Las operaciones son las mismas funciones del núcleo que usa el CLI
(`mover_objeto`, `escalar_objeto`, `borrar_objeto`, `plan_editar_texto`): aquí no
hay lógica de edición duplicada, solo el estado de la sesión encima.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

from nucleo.alinear_texto import alinear, chars_de_pagina, filtrar_sinteticos
from nucleo.editar import (borrar_objeto, escalar_objeto, mover_objeto)
from nucleo.editar_texto import escala_de_run, plan_editar_texto
from nucleo.fuentes import resolver_fuentes
from nucleo.geometria import Caja
from nucleo.guardar import (ErrorGuardado, guardar_pagina_editada,
                            tiene_firma_digital, rotar_pagina,
                            extraer_imagen, reemplazar_imagen)
from nucleo.objetos import ContenidoPagina, Objeto, extraer_objetos


@dataclass
class Paso:
    """Un estado anterior, para poder deshacer."""
    datos: bytes
    objetos_nuevos: dict
    num_pagina: int
    descripcion: str


@dataclass
class Sesion:
    """Un PDF abierto y lo que se le ha hecho desde que se abrió.

    No escribe nada en disco hasta `guardar()`. Todo lo que se ve en pantalla
    sale de `bytes_actuales()`, que construye en memoria el fichero tal y como
    quedaría si se guardara ahora mismo. Así lo que se ve es exactamente lo que
    se va a obtener, y no una aproximación que hay que creerse.
    """
    ruta: Path | None = None
    num_pagina: int = 0
    datos: bytes = b""
    contenido: ContenidoPagina | None = None
    seleccion: Objeto | None = None
    objetos_nuevos: dict = field(default_factory=dict)
    historial: list[Paso] = field(default_factory=list)
    pila_rehacer: list[Paso] = field(default_factory=list)
    ultimo_mensaje: str = ""
    _datos_al_abrir: bytes = b""
    ultimo_aviso: str = ""
    tiene_firma: bool = False
    # Contador que sube con cada cambio: la ventana lo usa para saber cuándo
    # volver a renderizar sin tener que comparar nada.
    version: int = 0
    _cache_version: int = -1
    _cache_bytes: bytes = b""
    _candidatos: list = field(default_factory=list)
    _ultimo_punto: tuple | None = None

    # -- apertura ---------------------------------------------------------

    def abrir(self, ruta: Path | str, num_pagina: int = 0) -> None:
        self.ruta = Path(ruta)
        self.num_pagina = num_pagina
        self.historial.clear()
        self.pila_rehacer.clear()
        self.objetos_nuevos.clear()
        self.tiene_firma = False
        self.version += 1
        self._recargar()
        self.seleccion = None
        self.ultimo_mensaje = ""
        self.ultimo_aviso = ""

    def _recargar(self) -> None:
        """Relee el stream de la página y vuelve a extraer y alinear objetos."""
        self.tiene_firma = tiene_firma_digital(self.ruta)
        with pikepdf.open(str(self.ruta)) as pdf:
            if pdf.is_encrypted:
                # Se rechaza AL ABRIR, no al pintar: un error dentro del bucle
                # de dibujo de GTK no se ve, cuelga la ventana hasta el tiempo
                # límite y no dice nada. Aquí se avisa y no se abre.
                raise ErrorGuardado(
                    f"{self.ruta.name}: el documento está cifrado, así que no se "
                    f"puede editar sin romperlo (el cifrado todavía no se "
                    f"conserva al escribir). El original no se toca.")
            if self.num_pagina >= len(pdf.pages):
                self.num_pagina = 0
            pagina = pdf.pages[self.num_pagina]
            c = pagina.get("/Contents")
            if c is None:
                self.datos = b""
            elif isinstance(c, pikepdf.Array):
                self.datos = b"\n".join(s.read_bytes() for s in c)
            else:
                self.datos = c.read_bytes()
            try:
                fuentes = resolver_fuentes(pagina)
            except Exception:
                fuentes = {}
            self.contenido = extraer_objetos(self.datos, fuentes)
        self._datos_al_abrir = self.datos

        # Alinear es lo que hace que las cajas de texto coincidan con la tinta
        # real. Sin esto, pinchar en una letra no selecciona la línea.
        doc = pdfium.PdfDocument(str(self.ruta))
        try:
            chars, _ = filtrar_sinteticos(
                chars_de_pagina(doc[self.num_pagina].get_textpage()))
            alinear(self.contenido, chars)
        finally:
            doc.close()

    @property
    def abierto(self) -> bool:
        return self.ruta is not None and self.contenido is not None

    @property
    def n_paginas(self) -> int:
        if not self.ruta:
            return 0
        doc = pdfium.PdfDocument(str(self.ruta))
        try:
            return len(doc)
        finally:
            doc.close()

    def ir_a_pagina(self, n: int) -> None:
        if not self.ruta:
            return
        self.num_pagina = max(0, n)
        self.version += 1
        self._recargar()
        self.seleccion = None

    # -- estado derivado --------------------------------------------------

    def objetos(self) -> list[Objeto]:
        return list(self.contenido.objetos) if self.contenido else []

    def objetos_de(self, tipo: str) -> list[Objeto]:
        return [o for o in self.objetos() if o.tipo == tipo]

    def indice_de(self, objeto: Objeto) -> int:
        try:
            return self.objetos().index(objeto)
        except ValueError:
            return -1

    def caja_de(self, objeto: Objeto) -> Caja | None:
        return objeto.caja

    # -- selección --------------------------------------------------------

    def seleccionar_en(self, x: float, y: float,
                       tolerancia: float = 2.0) -> Objeto | None:
        """El objeto que hay en ese punto, en coordenadas del PDF.

        El hit-test es el del núcleo, y no una caja a ojo: `en_punto` descarta
        los Bézier que salen de su caja envolvente y respeta los recortes, así
        que pinchar en la esquina de un degradado circular no coge un
        rectángulo que visualmente no está ahí.

        `en_punto` devuelve los candidatos del más pequeño al más grande. Se
        coge el más pequeño, que es lo que espera cualquiera: si hay una
        etiqueta encima de una foto, se quiere la etiqueta. Y si se vuelve a
        pinchar exactamente en el mismo sitio, se pasa al siguiente candidato,
        que es la forma de llegar a lo que hay debajo sin tener que buscarlo.
        """
        if not self.contenido:
            return None
        mismo_sitio = (self._ultimo_punto is not None
                       and abs(self._ultimo_punto[0] - x) < 1.0
                       and abs(self._ultimo_punto[1] - y) < 1.0)
        if not mismo_sitio:
            self._candidatos = self.contenido.en_punto(x, y, tolerancia)
            self._ultimo_punto = (x, y)
            self.seleccion = self._candidatos[0] if self._candidatos else None
        elif self._candidatos:
            i = self._candidatos.index(self.seleccion) if self.seleccion in self._candidatos else -1
            self.seleccion = self._candidatos[(i + 1) % len(self._candidatos)]
        self.version += 1
        return self.seleccion

    def seleccionar(self, objeto: Objeto | None) -> None:
        self.seleccion = objeto
        self.version += 1

    # -- edición ----------------------------------------------------------

    def _apuntar(self, descripcion: str) -> None:
        """Guarda el estado anterior para poder deshacer y vacía rehacer."""
        self.historial.append(Paso(self.datos, dict(self.objetos_nuevos),
                                   self.num_pagina, descripcion))
        self.pila_rehacer.clear()

    def _aplicar(self, nuevos: bytes, objetos: dict | None = None,
                 mensaje: str = "") -> bool:
        self.datos = nuevos
        if objetos:
            self.objetos_nuevos.update(objetos)
        self.version += 1
        self.ultimo_mensaje = mensaje
        self.ultimo_aviso = ""
        self._recargar_manteniendo_datos()
        return True

    def _recargar_manteniendo_datos(self) -> None:
        """Reextrae los objetos del documento tal y como está AHORA.

        Se hace sobre los bytes que se guardarían en este momento —ediciones
        incluidas— y no sobre el fichero del disco, que todavía no las tiene.
        Con el fichero salían dos cosas mal, las dos visibles:

        - La fuente nueva del nivel 2 no está en el disco hasta que se guarda,
          así que los códigos del texto editado no se podían traducir a
          caracteres y la lista lateral enseñaba «\x00\x07\x00\x0e...».
        - Las cajas de texto se alinean contra la tinta que ve pdfium, y esa
          tinta se pedía al fichero original: un texto movido se pintaba en su
          sitio nuevo pero su caja —y con ella el clic— volvía al viejo.

        `bytes_actuales()` está cacheado por versión, así que esto no cuesta
        nada de más: la vista previa ya lo había construido para dibujar.
        """
        if not self.ruta:
            return
        datos = self.bytes_actuales()
        if not datos:
            return
        pdf = pikepdf.open(io.BytesIO(datos))
        try:
            pagina = pdf.pages[self.num_pagina]
            try:
                fuentes = resolver_fuentes(pagina)
            except Exception:
                fuentes = {}
            self.contenido = extraer_objetos(self.datos, fuentes)
        finally:
            pdf.close()
        doc = pdfium.PdfDocument(datos)
        try:
            chars, _ = filtrar_sinteticos(
                chars_de_pagina(doc[self.num_pagina].get_textpage()))
            alinear(self.contenido, chars)
        finally:
            doc.close()

    def mover(self, dx: float, dy: float) -> bool:
        if not self.seleccion or not self.contenido:
            return False
        obj = self.seleccion
        self._apuntar(f"mover {obj.tipo} ({dx:+.0f}, {dy:+.0f})")
        nuevos = mover_objeto(self.datos, self.contenido, obj, dx, dy)
        return self._aplicar(nuevos, mensaje=f"Movido {obj.tipo} "
                                             f"({dx:+.0f}, {dy:+.0f}) pt")

    def escalar(self, factor: float) -> bool:
        if not self.seleccion or not self.contenido or not self.seleccion.caja:
            return False
        obj = self.seleccion
        centro = obj.caja.centro
        self._apuntar(f"escalar {obj.tipo} x{factor:.2f}")
        nuevos = escalar_objeto(self.datos, self.contenido, obj, factor, factor,
                                centro)
        return self._aplicar(nuevos,
                             mensaje=f"Escalado {obj.tipo} x{factor:.2f}")

    def borrar(self) -> bool:
        if not self.seleccion or not self.contenido:
            return False
        obj = self.seleccion
        self._apuntar(f"borrar {obj.tipo}")
        nuevos = borrar_objeto(self.datos, self.contenido, obj)
        self.seleccion = None
        return self._aplicar(nuevos, mensaje=f"Borrado {obj.tipo}")

    def editar_texto(self, nuevo: str, ajustar_espaciado: bool = False) -> bool:
        """Cambia el texto del run seleccionado. Devuelve False si no se puede.

        El motivo se deja en `ultimo_aviso`, porque el usuario tiene derecho a
        saber POR QUÉ no se puede, no solo que no se puede.
        """
        if not self.seleccion or not self.contenido or not self.ruta:
            return False
        if self.seleccion.tipo != "texto":
            self.ultimo_aviso = "el objeto seleccionado no es texto"
            return False
        obj = self.seleccion
        plan = plan_editar_texto(self.datos, self.ruta, self.num_pagina,
                                 self.contenido, obj, nuevo,
                                 ajustar_espaciado=ajustar_espaciado)
        inf = plan.informe
        self.ultimo_aviso = inf.motivo if not inf.ok else ""
        if not inf.ok:
            self.version += 1
            return False
        self._apuntar(f"editar texto {inf.nivel}")
        aviso = ""
        if inf.desborde:
            aviso = (f"el texto ocupa {inf.delta_en_puntos:+.1f} pt más: "
                     f"nada se recoloca solo, puede solaparse con lo de al lado")
        self._aplicar(plan.contenido, plan.objetos,
                      mensaje=f"Texto cambiado ({inf.resumen()})")
        self.ultimo_aviso = aviso
        return True

    # -- deshacer y rehacer -----------------------------------------------

    @property
    def puede_deshacer(self) -> bool:
        return bool(self.historial)

    @property
    def puede_rehacer(self) -> bool:
        return bool(self.pila_rehacer)

    def deshacer(self) -> bool:
        if not self.historial:
            return False
        paso = self.historial.pop()
        # Guardar estado actual en la pila de rehacer antes de revertir
        self.pila_rehacer.append(Paso(self.datos, dict(self.objetos_nuevos),
                                      self.num_pagina, paso.descripcion))
        self.datos = paso.datos
        self.objetos_nuevos = paso.objetos_nuevos
        self.num_pagina = paso.num_pagina
        self.seleccion = None
        self.version += 1
        self._recargar_manteniendo_datos()
        self.ultimo_mensaje = f"Deshecho: {paso.descripcion}"
        return True

    def rehacer(self) -> bool:
        if not self.pila_rehacer:
            return False
        paso = self.pila_rehacer.pop()
        # Guardar en historial antes de volver a aplicar
        self.historial.append(Paso(self.datos, dict(self.objetos_nuevos),
                                   self.num_pagina, paso.descripcion))
        self.datos = paso.datos
        self.objetos_nuevos = paso.objetos_nuevos
        self.num_pagina = paso.num_pagina
        self.seleccion = None
        self.version += 1
        self._recargar_manteniendo_datos()
        self.ultimo_mensaje = f"Rehecho: {paso.descripcion}"
        return True

    # -- salida -----------------------------------------------------------

    @property
    def hay_cambios(self) -> bool:
        """¿Se ha tocado algo desde que se abrió?

        Se compara el content stream con el que se leyó al abrir, y no solo la
        lista de objetos nuevos. Mover, escalar y borrar NO añaden objetos
        nuevos —reescriben el stream de la página—, así que mirando solo esa
        lista la aplicación creía que no había cambios y la vista previa seguía
        enseñando el documento original después de editar. Se vio al comprobar
        el tamaño del PDF en memoria tras un escalado: cuadraba con el original.
        """
        return self.datos != self._datos_al_abrir or bool(self.objetos_nuevos)

    def bytes_actuales(self) -> bytes:
        """El PDF tal y como quedaría si se guardara ahora. En memoria.

        Se cachea por `version`: mientras no se edite nada, no se vuelve a
        construir. Sin la caché, mover el ratón por encima de la ventana
        reconstruiría el fichero entero en cada repintado.
        """
        if not self.ruta:
            return b""
        if self._cache_version == self.version:
            return self._cache_bytes
        if not self.hay_cambios:
            self._cache_bytes = Path(self.ruta).read_bytes()
        else:
            # El temporal va al directorio temporal del sistema, no junto al
            # original: abrir un PDF de una carpeta de solo lectura es lo más
            # normal del mundo, y guardar ahí el estado intermedio rompería la
            # vista previa justo en ese caso.
            import tempfile
            fd, nombre = tempfile.mkstemp(suffix=".pdf", prefix="intactpdf-vis-")
            os.close(fd)
            tmp = Path(nombre)
            try:
                # Sin verificar: esto es para la VISTA PREVIA, que se rehace
                # con cada clic. La comprobación de que la página se ve se hace
                # al guardar de verdad, que es cuando importa y se paga una vez.
                guardar_pagina_editada(self.ruta, tmp, self.num_pagina,
                                       [self.datos], self.objetos_nuevos,
                                       verificar=False)
                self._cache_bytes = tmp.read_bytes()
            finally:
                tmp.unlink(missing_ok=True)
        self._cache_version = self.version
        return self._cache_bytes

    def render_datos(self, escala: float = 1.5):
        """Rasteriza la página actual: (bytes BGRA, ancho, alto, stride).

        Se piden cuatro canales a propósito. pdfium devuelve por omisión BGR de
        tres bytes por píxel, y cairo necesita cuatro por píxel para poder pintar
        sobre el búfer sin copiarlo. Con BGRA, el búfer de pdfium se le entrega a
        cairo tal cual.

        Y no se usa Pillow en ningún punto: no hace falta para dibujar, y así la
        interfaz no arrastra una dependencia más de las que ya lleva el núcleo.
        """
        datos = self.bytes_actuales()
        if not datos:
            return None
        from pypdfium2 import PdfBitmap

        def fabricante(ancho, alto, *_a, **_kw):
            return PdfBitmap.new_native(ancho, alto, 4)     # 4 = BGRA

        doc = pdfium.PdfDocument(datos)
        try:
            bmp = doc[self.num_pagina].render(scale=escala,
                                              bitmap_maker=fabricante)
            return bytearray(bmp.buffer), bmp.width, bmp.height, bmp.stride
        finally:
            doc.close()

    def render(self, escala: float = 1.5):
        """La página como imagen de Pillow. Solo para herramientas y tests.

        La ventana no usa esto: dibuja directamente sobre el búfer con cairo.
        Se mantiene porque los scripts de inspección y las capturas van cómodos
        con una imagen de Pillow, y ahí sí está disponible.
        """
        from PIL import Image
        r = self.render_datos(escala)
        if r is None:
            return None
        buf, ancho, alto, stride = r
        return Image.frombuffer("RGBA", (ancho, alto), bytes(buf), "raw", "BGRA",
                                stride, 1).convert("RGB")

    def guardar(self, destino: Path | str | None = None, crear_backup: bool = True) -> str:
        """Escribe el resultado. Devuelve el mensaje para la barra de estado."""
        if not self.ruta:
            raise ValueError("no hay ningún documento abierto")
        if destino is None:
            destino = self.ruta
        destino = Path(destino)
        es_mismo = False
        try:
            if destino.exists() and destino.resolve() == self.ruta.resolve():
                es_mismo = True
        except Exception:
            pass

        info = guardar_pagina_editada(self.ruta, destino, self.num_pagina,
                                      [self.datos], self.objetos_nuevos,
                                      crear_backup=crear_backup)
        if not info.prefijo_intacto:
            # No debería pasar nunca. Si pasa, hay que decirlo en voz alta en
            # lugar de dar el guardado por bueno.
            self.ultimo_aviso = ("AVISO: el fichero guardado NO empieza por el "
                                 "original. Algo ha ido mal.")
            return self.ultimo_aviso
        self.ultimo_aviso = ""
        if es_mismo:
            self._datos_al_abrir = self.datos
            self.objetos_nuevos.clear()
            self.historial.clear()
            self._cache_version = -1
            self.version += 1
            self.ultimo_mensaje = (
                f"Guardado en {destino.name} (copia previa en {destino.name}~): "
                f"{info.bytes_anadidos:,} bytes añadidos de forma incremental")
        else:
            self.ultimo_mensaje = (
                f"Guardado {destino.name}: {info.bytes_anadidos:,} bytes añadidos "
                f"a los {info.bytes_original:,} del original, que siguen intactos")
        return self.ultimo_mensaje

    # -- ayudas para la ventana ------------------------------------------

    def descripcion_de(self, objeto: Objeto) -> str:
        """Una línea para la lista lateral."""
        if objeto.tipo == "texto":
            t = (objeto.texto or "").replace("\n", " ")
            return f"“{t[:46]}{'…' if len(t) > 46 else ''}”"
        if objeto.tipo == "imagen":
            return objeto.nombre_xobject or "imagen"
        if objeto.tipo == "vector":
            return f"{objeto.n_segmentos} segmento(s), ‘{objeto.operado}’"
        return objeto.tipo

    def caja_de_seleccion(self):
        return self.seleccion.caja if self.seleccion else None

    def escala_de_run(self, objeto: Objeto) -> float:
        return escala_de_run(objeto) if objeto.tipo == "texto" else 1.0

    # -- operaciones de página e imagen ----------------------------------

    def rotar(self, angulo: int = 90) -> bool:
        """Gira la página actual sumando `angulo` grados de forma incremental."""
        if not self.ruta:
            return False
        self._apuntar(f"rotar página {angulo}°")
        info = rotar_pagina(self.ruta, self.ruta, self.num_pagina, angulo, crear_backup=True)
        self.version += 1
        self._recargar()
        self.ultimo_mensaje = f"Página rotada {angulo}° ({info.bytes_anadidos:,} bytes añadidos de forma incremental)"
        return True

    def extraer_imagen_seleccionada(self, ruta_destino: Path | str) -> Path | None:
        """Exporta la imagen actualmente seleccionada a archivo PNG o JPEG."""
        if not self.ruta or not self.seleccion or self.seleccion.tipo != "imagen":
            self.ultimo_aviso = "No hay ninguna imagen seleccionada para extraer"
            return None
        nombre = getattr(self.seleccion, "nombre_xobject", "")
        if not nombre:
            self.ultimo_aviso = "El objeto imagen no tiene nombre de XObject válido"
            return None
        return extraer_imagen(self.ruta, self.num_pagina, nombre, ruta_destino)

    def reemplazar_imagen_seleccionada(self, ruta_nueva_imagen: Path | str) -> bool:
        """Sustituye la imagen seleccionada por otra de disco, preservando posición y escala."""
        if not self.ruta or not self.seleccion or self.seleccion.tipo != "imagen":
            self.ultimo_aviso = "No hay ninguna imagen seleccionada para reemplazar"
            return False
        nombre = getattr(self.seleccion, "nombre_xobject", "")
        if not nombre:
            self.ultimo_aviso = "El objeto imagen no tiene nombre de XObject válido"
            return False
        self._apuntar(f"reemplazar imagen {nombre}")
        info = reemplazar_imagen(self.ruta, self.ruta, self.num_pagina, nombre,
                                 ruta_nueva_imagen, crear_backup=True)
        self.version += 1
        self._recargar()
        self.ultimo_mensaje = f"Imagen {nombre} reemplazada ({info.bytes_anadidos:,} bytes añadidos de forma incremental)"
        return True

