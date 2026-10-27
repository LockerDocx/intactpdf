"""
La ventana de IntactPDF: GTK4 con libadwaita.

Qué hace y qué no. Aquí no hay ni una decisión sobre el PDF: abrir, mover,
escalar, borrar, editar texto y guardar los hace `gui.modelo.Sesion`, que son
las mismas funciones del núcleo que usa el CLI. Esta capa traduce clics a
coordenadas y estado a píxeles, y nada más. Es lo que permite que un test
compruebe que guardar desde la ventana produce exactamente los mismos bytes que
guardar desde la línea de comandos.

Por qué GTK4 y no otra cosa. La vía principal de distribución es Flatpak sobre
`org.gnome.Platform`, que ya trae GTK4, libadwaita y PyGObject dentro. Cualquier
otra opción (un navegador embebido, Electron, Qt) implicaría meter en el paquete
entre 60 y 150 MB de cosas que el runtime ya tiene, y una superficie de ataque
mucho mayor, para dibujar una ventana. Dentro de un sandbox eso se paga dos
veces.
"""
from __future__ import annotations

import os
import sys
from argparse import Namespace
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import cairo  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gui import dialogos  # noqa: E402
from gui.cinta import Cinta  # noqa: E402
from gui.modelo import Sesion  # noqa: E402
from nucleo.cli import cmd_check, cmd_fonts, cmd_info  # noqa: E402
from nucleo.i18n import (IDIOMAS_DISPONIBLES, fijar_idioma,  # noqa: E402
                         idioma_actual, t)
from nucleo.geometria import (Caja, aplicar, invertir,  # noqa: E402
                              matriz_pagina, multiplicar)

APP_ID = "io.github.lockerdocx.IntactPDF"
COLOR_SELECCION = (1.0, 0.62, 0.0)
COLOR_OTROS = (0.35, 0.55, 0.90, 0.45)


class Lienzo(Gtk.DrawingArea):
    """La página y los marcadores encima.

    El fondo (la página rasterizada) se cachea y solo se regenera cuando cambia
    el documento o el zoom. El marcador de selección y la previsualización del
    arrastre se dibujan encima en cada repintado, que es barato.
    """

    def __init__(self, ventana: "Ventana", **kw):
        super().__init__(**kw)
        self.ventana = ventana
        self.zoom = 1.5
        self._sup = None
        self._sup_version = -1
        self._sup_zoom = -1.0
        self._buf = None

        self._arrastrando = False
        self._arrastre_ini = (0.0, 0.0)
        self._arrastre_actual = (0.0, 0.0)

        self.set_draw_func(self._dibujar)
        self.set_size_request(200, 200)

        arrastre = Gtk.GestureDrag()
        arrastre.connect("drag-begin", self._drag_begin)
        arrastre.connect("drag-update", self._drag_update)
        arrastre.connect("drag-end", self._drag_end)
        self.add_controller(arrastre)

        clic = Gtk.GestureClick()
        clic.connect("pressed", self._pulsado)
        self.add_controller(clic)

        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL | Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._al_hacer_scroll)
        self.add_controller(scroll)

    def _al_hacer_scroll(self, ctrl, _dx, dy):
        """Ctrl + rueda del ratón: zoom continuo centrado en el documento."""
        estado = ctrl.get_current_event_state()
        if bool(estado & Gdk.ModifierType.CONTROL_MASK):
            factor = 1.15 if dy < 0 else (1.0 / 1.15)
            self.ventana.cambiar_zoom(factor)
            return True
        return False

    # -- geometría --------------------------------------------------------

    def _matriz(self):
        """Matriz de espacio PDF a espacio de la página (origen arriba).

        Delega en la ventana, que la tiene cacheada. No es un detalle: esta
        función se llama dos veces por objeto en cada repintado y varias veces
        por evento de arrastre, así que recalcularla cada vez abriendo el
        documento con pdfium haría el arrastre inusable.
        """
        return self.ventana.geometria()

    def a_pixel(self, x: float, y: float) -> tuple[float, float]:
        m, _, _ = self._matriz()
        if m is None:
            return 0.0, 0.0
        px, py = aplicar(m, x, y)
        return px * self.zoom, py * self.zoom

    def a_pdf(self, px: float, py: float) -> tuple[float, float]:
        """Inversa: del píxel del lienzo al espacio del PDF.

        Se invierte la matriz de la página en vez de restar cosas a mano,
        porque la página puede estar rotada con /Rotate y entonces el signo del
        «menos uno» no es el mismo en los cuatro casos.
        """
        m, _, _ = self._matriz()
        if m is None:
            return 0.0, 0.0
        inv = invertir(m)
        if inv is None:
            return 0.0, 0.0
        z = max(self.zoom, 0.001)
        return aplicar(inv, px / z, py / z)

    # -- superficie cacheada ---------------------------------------------

    def _superficie(self):
        sesion = self.ventana.sesion
        if sesion.version == self._sup_version and self.zoom == self._sup_zoom:
            return self._sup
        self._sup = None
        self._sup_version = sesion.version
        self._sup_zoom = self.zoom
        r = sesion.render_datos(self.zoom)
        if r is None:
            return None
        buf, ancho, alto, stride = r
        self._sup = cairo.ImageSurface.create_for_data(
            buf, cairo.FORMAT_RGB24, ancho, alto, stride)
        # El búfer tiene que seguir vivo mientras cairo lo use: cairo NO copia
        # los datos, los referencia. Si se deja que lo recoja el recolector de
        # basura, la imagen sale con ruido o el programa revienta.
        self._buf = buf
        self.set_content_width(ancho)
        self.set_content_height(alto)
        return self._sup

    # -- pintado ----------------------------------------------------------

    def _dibujar(self, _area, ctx, ancho, alto):
        ctx.set_source_rgb(0.16, 0.16, 0.18)
        ctx.paint()

        sup = self._superficie()
        if sup is not None:
            ctx.set_source_surface(sup, 0, 0)
            ctx.paint()

        sesion = self.ventana.sesion
        if not sesion.abierto:
            return

        # contorno tenue de todos los objetos: ayuda a ver qué es seleccionable
        if self.ventana.mostrar_cajas:
            ctx.set_line_width(1.0)
            for o in sesion.objetos():
                if o.caja is None:
                    continue
                self._rect(ctx, o.caja)
                ctx.set_source_rgba(*COLOR_OTROS)
                ctx.stroke()

        sel = sesion.seleccion
        if sel is not None and sel.caja is not None:
            caja = sel.caja
            if self._arrastrando:
                dx = self._arrastre_actual[0] - self._arrastre_ini[0]
                dy = self._arrastre_actual[1] - self._arrastre_ini[1]
                caja = Caja(caja.x0 + dx, caja.y0 + dy,
                            caja.x1 + dx, caja.y1 + dy)
            self._rect(ctx, caja)
            ctx.set_source_rgb(*COLOR_SELECCION)
            ctx.set_line_width(2.0)
            ctx.stroke()
            self._asas(ctx, caja)

    def _rect(self, ctx, caja):
        x0, y1 = self.a_pixel(caja.x0, caja.y0)
        x1, y0 = self.a_pixel(caja.x1, caja.y1)
        ctx.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

    def _asas(self, ctx, caja):
        """Cuadraditos en las esquinas: dicen que el objeto se puede agarrar."""
        x0, y1 = self.a_pixel(caja.x0, caja.y0)
        x1, y0 = self.a_pixel(caja.x1, caja.y1)
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            ctx.rectangle(cx - 3, cy - 3, 6, 6)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill_preserve()
        ctx.set_source_rgb(*COLOR_SELECCION)
        ctx.set_line_width(1.5)
        ctx.stroke()

    # -- interacción ------------------------------------------------------

    def _pulsado(self, gesto, n_pulsaciones, x, y):
        sesion = self.ventana.sesion
        if not sesion.abierto:
            return
        if n_pulsaciones == 2:
            obj = sesion.seleccion
            if obj is not None and obj.tipo == "texto":
                self.ventana.dialogo_texto()
            elif obj is not None:
                self.ventana.dialogo_escalar()
            return
        px, py = self.a_pdf(x, y)
        z = max(self.zoom, 0.01)
        sesion.seleccionar_en(px, py, tolerancia=6.0 / z)
        self.ventana.actualizar()
        self.queue_draw()

    def _drag_begin(self, _g, x, y):
        self._arrastrando = True
        self._arrastre_ini = (x, y)
        self._arrastre_actual = (x, y)

    def _drag_update(self, _g, dx, dy):
        if not self._arrastrando:
            return
        self._arrastre_actual = (self._arrastre_ini[0] + dx,
                                 self._arrastre_ini[1] + dy)
        self.queue_draw()

    def _drag_end(self, _g, dx, dy):
        self._arrastrando = False
        sesion = self.ventana.sesion
        if sesion.seleccion is None or (abs(dx) < 2 and abs(dy) < 2):
            self.queue_draw()
            return
        # El desplazamiento se convierte de píxeles a puntos del PDF en los DOS
        # ejes por separado: con la página rotada, arrastrar hacia la derecha no
        # siempre es +x en el PDF.
        x0, y0 = self.a_pdf(0, 0)
        x1, y1 = self.a_pdf(dx, dy)
        sesion.mover(x1 - x0, y1 - y0)
        self.ventana.actualizar()
        self.queue_draw()


class Ventana(Adw.ApplicationWindow):
    def __init__(self, app, sesion: Sesion, **kw):
        super().__init__(application=app, **kw)
        self.sesion = sesion
        self.mostrar_cajas = True
        self.set_default_size(1180, 820)
        self.set_title("IntactPDF")

        # Bandera para que `actualizar()` pueda tocar la lista sin que el
        # propio cambio de fila vuelva a llamar a `actualizar()`. Sin esto se
        # entra en recursión infinita: actualizar -> select_row -> "row-selected"
        # -> _fila_elegida -> actualizar -> ... Lo destapó el test de la ventana,
        # que reventaba con RecursionError al seleccionar algo.
        self._actualizando = False
        self._doc = None
        self._doc_version = -1
        self._doc_buf = None
        self._geo = None
        self._rot = 0
        # Cuánto ocupa el fichero original, para poder decir cuántos bytes ha
        # añadido la edición. Se lee una vez, al abrir.
        self._datos_originales = b""
        self._filas: list = []
        # Un botón que enseña un estado (las casillas de la cinta) no se puede
        # sincronizar sin una bandera: al ponerlo en hora se dispara su señal,
        # que vuelve a poner en hora el otro, que... y así sin fin.
        self._sincronizando = False
        self._condiciones: dict = {}
        self.etiquetas: dict = {}
        self.controles: dict = {}
        self._construir()
        self.actualizar()

    # -- construcción -----------------------------------------------------

    def _construir(self):
        self.cinta = self._construir_cinta()
        self.cinta_contenedor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.cinta_contenedor.append(self.cinta)

        self.vista = Adw.ToolbarView()
        self.vista.add_top_bar(self._cabecera())
        # Banner de advertencia de firma digital existente
        self.banner_firma = Adw.Banner.new(t("banner_firma"))
        self.banner_firma.set_revealed(False)
        self.vista.add_top_bar(self.banner_firma)
        # La cinta va DEBAJO de la barra de título, como en Word: primero el
        # nombre del fichero, y debajo todas las opciones.
        self.vista.add_top_bar(self.cinta_contenedor)

        self.lienzo = Lienzo(self)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_child(self.lienzo)
        self.scroll.set_hexpand(True)
        self.scroll.set_vexpand(True)

        self.marco = Gtk.Frame()
        self.marco.add_css_class("view")
        self.marco.set_child(self.scroll)
        self.marco.set_margin_top(8)
        self.marco.set_margin_bottom(8)
        self.marco.set_margin_start(8)
        self.marco.set_margin_end(8)

        self.vacio = Adw.StatusPage()
        self.vacio.set_icon_name("x-office-document-symbolic")
        self.vacio.set_title(t("bienvenida_titulo"))
        self.vacio.set_description(t("bienvenida_subtitulo"))

        # Controles y guía rápida de bienvenida
        caja_vacio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        caja_vacio.set_halign(Gtk.Align.CENTER)
        caja_vacio.set_margin_top(12)

        caja_botones = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        caja_botones.set_halign(Gtk.Align.CENTER)

        self.btn_abrir_vacio = Gtk.Button.new_with_label(t("btn_abrir_pdf"))
        self.btn_abrir_vacio.add_css_class("suggested-action")
        self.btn_abrir_vacio.add_css_class("pill")
        self.btn_abrir_vacio.set_icon_name("document-open-symbolic")
        self.btn_abrir_vacio.connect("clicked", lambda *_: self.accion_abrir())
        caja_botones.append(self.btn_abrir_vacio)

        self.btn_tut_vacio = Gtk.Button.new_with_label(t("btn_guia_tutorial"))
        self.btn_tut_vacio.add_css_class("pill")
        self.btn_tut_vacio.set_icon_name("help-faq-symbolic")
        self.btn_tut_vacio.connect("clicked", lambda *_: self.mostrar_tutorial())
        caja_botones.append(self.btn_tut_vacio)

        caja_vacio.append(caja_botones)

        self.grupo_pasos = Adw.PreferencesGroup()
        self.grupo_pasos.set_title(t("bienvenida_titulo"))
        self.grupo_pasos.set_margin_top(16)

        self.row_paso1 = Adw.ActionRow()
        self.row_paso1.set_title(t("paso1_tit"))
        self.row_paso1.set_subtitle(t("paso1_desc"))
        self.row_paso1.add_prefix(Gtk.Image.new_from_icon_name("document-open-symbolic"))
        self.grupo_pasos.add(self.row_paso1)

        self.row_paso2 = Adw.ActionRow()
        self.row_paso2.set_title(t("paso2_tit"))
        self.row_paso2.set_subtitle(t("paso2_desc"))
        self.row_paso2.add_prefix(Gtk.Image.new_from_icon_name("edit-find-symbolic"))
        self.grupo_pasos.add(self.row_paso2)

        self.row_paso3 = Adw.ActionRow()
        self.row_paso3.set_title(t("paso3_tit"))
        self.row_paso3.set_subtitle(t("paso3_desc"))
        self.row_paso3.add_prefix(Gtk.Image.new_from_icon_name("emblem-default-symbolic"))
        self.grupo_pasos.add(self.row_paso3)

        caja_vacio.append(self.grupo_pasos)
        self.vacio.set_child(caja_vacio)

        self.pila = Gtk.Stack()
        self.pila.add_named(self.vacio, "vacio")
        self.pila.add_named(self.marco, "documento")
        self.pila.set_vexpand(True)

        self.split = Adw.OverlaySplitView()
        self.split.set_content(self.pila)
        self.split.set_sidebar(self._lateral())
        self.split.set_min_sidebar_width(240)
        self.split.set_max_sidebar_width(340)
        self.split.set_sidebar_width_fraction(0.26)
        self.split.set_vexpand(True)

        self.vista.set_content(self.split)
        self.vista.add_bottom_bar(self._barra_estado())

        ayuda = Gtk.ShortcutController()
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("Delete"),
            Gtk.CallbackAction.new(lambda *_: self.accion_borrar())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>z"),
            Gtk.CallbackAction.new(lambda *_: self.accion_deshacer())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control><Shift>z"),
            Gtk.CallbackAction.new(lambda *_: self.accion_rehacer())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>y"),
            Gtk.CallbackAction.new(lambda *_: self.accion_rehacer())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>c"),
            Gtk.CallbackAction.new(lambda *_: self.accion_copiar())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>plus"),
            Gtk.CallbackAction.new(lambda *_: self.cambiar_zoom(1.25))))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>equal"),
            Gtk.CallbackAction.new(lambda *_: self.cambiar_zoom(1.25))))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>minus"),
            Gtk.CallbackAction.new(lambda *_: self.cambiar_zoom(1 / 1.25))))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>0"),
            Gtk.CallbackAction.new(lambda *_: self.zoom_real())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>s"),
            Gtk.CallbackAction.new(lambda *_: self.accion_guardar())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control><Shift>s"),
            Gtk.CallbackAction.new(lambda *_: self.accion_guardar_como())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>o"),
            Gtk.CallbackAction.new(lambda *_: self.accion_abrir())))
        ayuda.add_shortcut(Gtk.Shortcut.new(
            Gtk.ShortcutTrigger.parse_string("<Control>e"),
            Gtk.CallbackAction.new(lambda *_: self.dialogo_texto())))
        self.add_controller(ayuda)

        # Soltar un PDF encima de la ventana. Es lo primero que intenta mucha
        # gente al abrir un programa de estos, y sale casi gratis: GTK entrega
        # los ficheros soltados y el camino de apertura ya existe.
        soltar = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        soltar.connect("drop", self._al_soltar)
        self.add_controller(soltar)

        self.set_content(self.vista)

    def _cabecera(self) -> Adw.HeaderBar:
        """La barra de título: el nombre del fichero y poco más.

        Los botones de acción se han ido a la cinta. Aquí queda lo que en Word
        está en la barra de título: qué documento es y el menú de la aplicación.
        """
        barra = Adw.HeaderBar()
        self.titulo = Adw.WindowTitle(title=t("app_titulo"),
                                      subtitle="Sin documento")
        barra.set_title_widget(self.titulo)

        menu = Gio.Menu()
        menu.append(t("btn_abrir") + "…", "app.abrir")
        menu.append(t("btn_guardar_como") + "…", "app.guardar")
        menu.append(t("tut_titulo"), "app.tutorial")
        menu.append(t("btn_comprobar"), "app.check")
        menu.append(t("btn_fuentes"), "app.fonts")
        menu.append(t("btn_diagnostico"), "app.doctor")
        menu.append(t("app_titulo"), "app.acerca")

        b_ayuda = Gtk.Button()
        b_ayuda.set_icon_name("help-about-symbolic")
        b_ayuda.set_tooltip_text(t("btn_ayuda_tip"))
        b_ayuda.connect("clicked", lambda *_: self.mostrar_tutorial())
        barra.pack_end(b_ayuda)

        b_menu = Gtk.MenuButton()
        b_menu.set_icon_name("open-menu-symbolic")
        b_menu.set_menu_model(menu)
        b_menu.set_tooltip_text(t("app_titulo"))
        barra.pack_end(b_menu)
        return barra

    def cambiar_idioma(self, cod: str):
        """Cambia el idioma activo de la interfaz (es, en, de, zh)."""
        if cod not in IDIOMAS_DISPONIBLES:
            return
        fijar_idioma(cod)
        self.vacio.set_title(t("bienvenida_titulo"))
        self.vacio.set_description(t("bienvenida_subtitulo"))
        if hasattr(self, "btn_abrir_vacio"):
            self.btn_abrir_vacio.set_label(t("btn_abrir_pdf"))
        if hasattr(self, "btn_tut_vacio"):
            self.btn_tut_vacio.set_label(t("btn_guia_tutorial"))
        if hasattr(self, "row_paso1"):
            self.row_paso1.set_title(t("paso1_tit"))
            self.row_paso1.set_subtitle(t("paso1_desc"))
        if hasattr(self, "row_paso2"):
            self.row_paso2.set_title(t("paso2_tit"))
            self.row_paso2.set_subtitle(t("paso2_desc"))
        if hasattr(self, "row_paso3"):
            self.row_paso3.set_title(t("paso3_tit"))
            self.row_paso3.set_subtitle(t("paso3_desc"))
        if hasattr(self, "banner_firma"):
            self.banner_firma.set_title(t("banner_firma"))

        # Reemplazar la cinta con los textos traducidos
        if hasattr(self, "cinta_contenedor") and hasattr(self, "cinta"):
            self.cinta_contenedor.remove(self.cinta)
            self.etiquetas.clear()
            self.controles.clear()
            self.cinta = self._construir_cinta()
            self.cinta_contenedor.append(self.cinta)

        self.actualizar()
        self.lienzo.queue_draw()

    # -- la cinta ---------------------------------------------------------

    def _dato(self, grupo, clave: str, inicial: str = "—",
               mono: bool = False, ancho: int = 0) -> Gtk.Label:
        """Una etiqueta con dato, apuntada por clave para poder refrescarla.

        Casi todos los datos salen repetidos en dos pestañas (el zoom, la
        página), así que se guardan en lista y `_poner` los pone todos a la vez.
        """
        etiqueta = grupo.texto(inicial, mono=mono, ancho=ancho)
        self.etiquetas.setdefault(clave, []).append(etiqueta)
        return etiqueta

    def _poner(self, clave: str, texto: str) -> None:
        for etiqueta in self.etiquetas.get(clave, []):
            etiqueta.set_text(texto)

    def _control(self, grupo, clave: str, widget):
        self.controles.setdefault(clave, []).append(widget)
        return widget

    def _grupo_zoom(self, cinta: Cinta, grupo) -> None:
        """Alejar, acercar, tamaño real y ajustar. Sale en Inicio y en Ver."""
        g = grupo(t("grp_zoom"))
        g.icono("zoom-out-symbolic", "-",
                lambda: self.cambiar_zoom(1 / 1.25))
        g.icono("zoom-in-symbolic", "+",
                lambda: self.cambiar_zoom(1.25))
        self._dato(g, "zoom", "150 %", mono=True, ancho=5)
        g.pequeno("zoom-original-symbolic", t("btn_zoom_real"),
                  t("btn_zoom_real_tip"), self.zoom_real)
        g.pequeno("zoom-fit-best-symbolic", t("btn_zoom_ancho"),
                  t("btn_zoom_ancho_tip"), self.zoom_ajustado)

    def _grupo_pagina(self, cinta: Cinta, grupo) -> None:
        """Navegación de páginas, igual en Inicio y en Página."""
        g = grupo(t("tab_pagina"))
        b_ant = g.icono("go-previous-symbolic", "Anterior",
                        lambda: self.cambiar_pagina(-1))
        cinta.vigilar(b_ant, lambda s: s.abierto and s.num_pagina > 0)
        b_sig = g.icono("go-next-symbolic", "Siguiente",
                        lambda: self.cambiar_pagina(+1))
        cinta.vigilar(b_sig, lambda s: s.abierto and s.num_pagina + 1 < s.n_paginas)
        self._dato(g, "pagina", "— / —", mono=True, ancho=9)
        ir = Gtk.SpinButton.new_with_range(1, 1, 1)
        ir.set_width_chars(3)
        ir.set_numeric(True)
        ir.set_tooltip_text("Página")
        self._control(g, "ir", ir)
        cinta.vigilar(ir, lambda s: s.abierto and s.n_paginas > 1)
        b_ir = g.pequeno("go-jump-symbolic", "Ir", "Ir",
                         self.ir_a_pagina_escrita)
        self.controles.setdefault("ir_boton", []).append(b_ir)
        cinta.vigilar(b_ir, lambda s: s.abierto and s.n_paginas > 1)

    def _construir_cinta(self) -> Cinta:
        cinta = Cinta()

        # ---------------------------------------------------------------- Inicio
        inicio = cinta.pagina("inicio", t("tab_inicio"))

        g = inicio.grupo(t("grp_documento"))
        b = g.grande("document-open-symbolic", t("btn_abrir"),
                     t("btn_abrir_tip"), self.accion_abrir)
        cinta.vigilar(b, lambda s: True)
        b = g.grande("document-save-symbolic", t("btn_guardar"),
                     t("btn_guardar_tip"),
                     self.accion_guardar)
        cinta.vigilar(b, lambda s: s.abierto)
        b = g.grande("document-save-as-symbolic", t("btn_guardar_como"),
                     t("btn_guardar_como_tip"),
                     self.accion_guardar_como)
        cinta.vigilar(b, lambda s: s.abierto)
        b = g.grande("edit-undo-symbolic", t("btn_deshacer"),
                     t("btn_deshacer_tip"), self.accion_deshacer)
        cinta.vigilar(b, lambda s: s.puede_deshacer)

        g = inicio.grupo(t("grp_objeto"))
        b = g.grande("user-trash-symbolic", t("btn_borrar"),
                     t("btn_borrar_tip"), self.accion_borrar)
        cinta.vigilar(b, lambda s: s.seleccion is not None)
        b = g.grande("insert-text-symbolic", t("btn_editar_texto"),
                     t("btn_editar_texto_tip"), self.dialogo_texto)
        cinta.vigilar(b, lambda s: bool(s.seleccion and s.seleccion.tipo == "texto"))
        b = g.grande("object-flip-horizontal-symbolic", t("btn_escalar"),
                     t("btn_escalar_tip"),
                     self.dialogo_escalar)
        cinta.vigilar(b, lambda s: s.seleccion is not None)

        self._grupo_pagina(cinta, inicio.grupo)
        self._grupo_zoom(cinta, inicio.grupo)

        # ---------------------------------------------------------------- Objeto
        objeto = cinta.pagina("objeto", t("tab_objeto"))

        g = objeto.grupo(t("grp_mover"))
        for icono, punta, dx, dy in (
                ("go-up-symbolic", "+Y", 0, 10),
                ("go-down-symbolic", "-Y", 0, -10),
                ("go-previous-symbolic", "-X", -10, 0),
                ("go-next-symbolic", "+X", 10, 0)):
            b = g.icono(icono, punta, lambda dx=dx, dy=dy: self.mover_pt(dx, dy))
            cinta.vigilar(b, lambda s: s.seleccion is not None)
        g.fila()
        for clave, valor in (("dx", "10"), ("dy", "0")):
            campo = Gtk.Entry()
            campo.set_text(valor)
            campo.set_width_chars(4)
            campo.set_max_width_chars(5)
            campo.set_input_purpose(Gtk.InputPurpose.NUMBER)
            campo.set_tooltip_text("pt")
            g.meter(campo)
            self._control(g, clave, campo)
        b = g.pequeno("go-jump-symbolic", t("grp_mover"),
                      t("grp_mover"), self.mover_exacto)
        cinta.vigilar(b, lambda s: s.seleccion is not None)

        g = objeto.grupo(t("grp_tamano"))
        b = g.grande("object-flip-horizontal-symbolic", t("btn_escalar"),
                     t("btn_escalar_tip"),
                     self.dialogo_escalar)
        cinta.vigilar(b, lambda s: s.seleccion is not None)
        for texto, factor in (("50 %", 0.5), ("100 %", 1.0), ("200 %", 2.0)):
            b = g.pequeno("zoom-fit-best-symbolic", texto,
                          f"{t('btn_escalar')} ({texto})",
                          lambda f=factor: self.escalar_a(f))
            cinta.vigilar(b, lambda s: s.seleccion is not None)

        g = objeto.grupo(t("grp_imagen"))
        b = g.grande("image-x-generic-symbolic", t("btn_anadir_imagen"),
                     t("btn_anadir_imagen_tip"),
                     self.dialogo_anadir_imagen)
        cinta.vigilar(b, lambda s: s.abierto)
        b = g.grande("document-save-symbolic", t("btn_extraer"),
                     t("btn_extraer_tip"),
                     self.accion_extraer_imagen)
        cinta.vigilar(b, lambda s: bool(s.seleccion and s.seleccion.tipo == "imagen"))
        b = g.grande("document-revert-symbolic", t("btn_reemplazar"),
                     t("btn_reemplazar_tip"),
                     self.accion_reemplazar_imagen)
        cinta.vigilar(b, lambda s: bool(s.seleccion and s.seleccion.tipo == "imagen"))

        g = objeto.grupo(t("grp_borrar"))
        b = g.grande("user-trash-symbolic", t("btn_borrar"),
                     t("btn_borrar_tip"), self.accion_borrar)
        cinta.vigilar(b, lambda s: s.seleccion is not None)

        g = objeto.grupo(t("grp_seleccion"))
        g.fila()
        self._dato(g, "sel_tipo", t("sel_nada"), mono=True)
        g.fila()
        self._dato(g, "sel_caja", "", mono=True)
        g.fila()
        self._dato(g, "sel_tam", "", mono=True)

        # ---------------------------------------------------------------- Texto
        texto = cinta.pagina("texto", t("tab_texto"))

        g = texto.grupo(t("grp_edicion"))
        b = g.grande("list-add-symbolic", t("btn_anadir_texto"),
                     t("btn_anadir_texto_tip"), self.dialogo_anadir_texto)
        cinta.vigilar(b, lambda s: s.abierto)
        b = g.grande("insert-text-symbolic", t("btn_editar_texto"),
                     t("btn_editar_texto_tip"),
                     self.dialogo_texto)
        cinta.vigilar(b, lambda s: bool(s.seleccion and s.seleccion.tipo == "texto"))
        self.sw_ajustar = Gtk.CheckButton(label=t("chk_ajustar_espaciado"))
        self.sw_ajustar.set_active(False)
        self.sw_ajustar.set_tooltip_text(t("chk_ajustar_espaciado_tip"))
        g.meter(self.sw_ajustar)
        cinta.vigilar(self.sw_ajustar,
                      lambda s: bool(s.seleccion and s.seleccion.tipo == "texto"))

        g = texto.grupo(t("grp_tipografia"))
        g.fila()
        self._dato(g, "txt_fuente", "—")
        g.fila()
        self._dato(g, "txt_tam", "—")
        g.fila()
        self._dato(g, "txt_escala", "—")

        g = texto.grupo(t("grp_reglas"))
        l = g.texto(t("regla_tipografia_titulo"))
        l.add_css_class("cinta-pista")
        l.set_tooltip_text(t("regla_tipografia_desc"))

        # ---------------------------------------------------------------- Página
        pagina = cinta.pagina("pagina", t("tab_pagina"))

        self._grupo_pagina(cinta, pagina.grupo)

        g = pagina.grupo(t("grp_medidas"))
        g.fila()
        self._dato(g, "pag_tam", "—")
        g.fila()
        self._dato(g, "pag_rot", "—")

        g = pagina.grupo(t("grp_documento"))
        g.fila()
        self._dato(g, "doc_nombre", "—")
        g.fila()
        self._dato(g, "doc_paginas", "—")
        g.fila()
        self._dato(g, "doc_objetos", "—")

        g = pagina.grupo(t("grp_girar"))
        b = g.icono("object-rotate-right-symbolic", t("btn_girar_der_tip"),
                    lambda: self.accion_rotar(90))
        cinta.vigilar(b, lambda s: s.abierto)
        b = g.icono("object-rotate-left-symbolic", t("btn_girar_izq_tip"),
                    lambda: self.accion_rotar(270))
        cinta.vigilar(b, lambda s: s.abierto)

        g = pagina.grupo(t("grp_herramientas"))
        b = g.grande("dialog-information-symbolic", t("btn_info"),
                     t("btn_info_tip"), self.ver_informacion)
        cinta.vigilar(b, lambda s: s.abierto)
        b = g.grande("font-x-generic-symbolic", t("btn_fuentes"),
                     t("btn_fuentes_tip"), self.ver_fuentes)
        cinta.vigilar(b, lambda s: s.abierto)
        b = g.grande("system-search-symbolic", t("btn_comprobar"),
                     t("btn_comprobar_tip"), self.comprobar)
        cinta.vigilar(b, lambda s: s.abierto)
        b = g.grande("edit-clear-all-symbolic", t("btn_compactar"),
                     t("btn_compactar_tip"),
                     self.accion_compactar)
        cinta.vigilar(b, lambda s: s.abierto)

        # ---------------------------------------------------------------- Ver
        ver = cinta.pagina("ver", t("tab_ver"))

        self._grupo_zoom(cinta, ver.grupo)

        g = ver.grupo(t("grp_paneles"))
        self.b_panel = Gtk.CheckButton(label=t("chk_panel_objetos"))
        self.b_panel.set_active(True)
        self.b_panel.set_tooltip_text(t("chk_panel_objetos_tip"))
        self.b_panel.connect("toggled", self._alternar_panel)
        g.meter(self.b_panel)
        self.b_cajas = Gtk.CheckButton(label=t("chk_marcar_todo"))
        self.b_cajas.set_active(True)
        self.b_cajas.set_tooltip_text(t("chk_marcar_todo_tip"))
        self.b_cajas.connect("toggled", self._alternar_cajas)
        g.meter(self.b_cajas)

        g = ver.grupo(t("grp_entorno"))
        g.grande("preferences-system-symbolic", t("btn_diagnostico"),
                 t("btn_diagnostico_tip"),
                 self.diagnostico)

        g = ver.grupo(t("grp_idioma"))
        for cod, nom in (("es", "ES"), ("en", "EN"), ("de", "DE"), ("zh", "ZH")):
            b = g.pequeno("preferences-desktop-locale-symbolic", nom,
                          f"{IDIOMAS_DISPONIBLES[cod]}",
                          lambda c=cod: self.cambiar_idioma(c))

        return cinta

    def _lateral(self) -> Gtk.Widget:
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cab = Adw.HeaderBar()
        cab.set_title_widget(Gtk.Label(label=t("panel_lateral_titulo")))
        cab.add_css_class("flat")
        caja.append(cab)

        self.lista = Gtk.ListBox()
        self.lista.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.lista.add_css_class("navigation-sidebar")
        self.lista.connect("row-selected", self._fila_elegida)

        scroll = Gtk.ScrolledWindow()
        scroll.set_child(self.lista)
        scroll.set_vexpand(True)
        caja.append(scroll)

        grupo = Gtk.ListBox()
        grupo.add_css_class("boxed-list")
        grupo.set_margin_top(6)
        grupo.set_margin_bottom(6)
        grupo.set_margin_start(6)
        grupo.set_margin_end(6)
        self.fila_cajas = Adw.SwitchRow(
            title=t("fila_cajas_titulo"),
            subtitle=t("fila_cajas_sub"))
        self.fila_cajas.set_active(True)
        self.fila_cajas.connect("notify::active", self._cambiar_cajas)
        grupo.append(self.fila_cajas)
        caja.append(grupo)
        return caja

    def _barra_estado(self) -> Gtk.Widget:
        barra = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        barra.set_margin_top(4)
        barra.set_margin_bottom(4)
        barra.set_margin_start(10)
        barra.set_margin_end(10)
        self.l_estado = Gtk.Label(label="")
        self.l_estado.set_xalign(0)
        self.l_estado.set_ellipsize(Pango.EllipsizeMode.END)
        barra.append(self.l_estado)
        self.l_aviso = Gtk.Label(label="")
        self.l_aviso.set_xalign(1)
        self.l_aviso.add_css_class("dim-label")
        self.l_aviso.set_ellipsize(Pango.EllipsizeMode.END)
        self.l_aviso.set_hexpand(True)
        barra.append(self.l_aviso)
        return barra

    # -- estado -----------------------------------------------------------

    def _asegurar_doc(self):
        """El documento de pdfium para el estado ACTUAL, no el del disco.

        Se rehace cuando cambia la versión de la sesión. Y se rehace desde
        `bytes_actuales()`, o sea desde las ediciones pendientes: si se leyera
        del fichero, la pantalla seguiría enseñando el PDF sin editar.
        """
        if self._doc is not None and self._doc_version == self.sesion.version:
            return self._doc
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None
        self._geo = None
        self._rot = 0
        self._doc_version = self.sesion.version
        datos = self.sesion.bytes_actuales()
        if datos:
            import pypdfium2 as pdfium
            # El búfer tiene que seguir referenciado: pypdfium2 lee de ahí.
            self._doc_buf = datos
            self._doc = pdfium.PdfDocument(datos)
        return self._doc

    def geometria(self):
        """(matriz PDF->página, ancho visible, alto visible). Cacheada."""
        if self._geo is not None:
            return self._geo
        doc = self._asegurar_doc()
        if doc is None:
            return None, 0, 0
        try:
            pagina = doc[self.sesion.num_pagina]
        except Exception:
            return None, 0, 0
        try:
            mb = list(pagina.get_mediabox())
        except Exception:
            mb = [0, 0, *pagina.get_size()]
        rot = pagina.get_rotation() if hasattr(pagina, "get_rotation") else 0
        self._rot = rot
        self._geo = matriz_pagina(mb, rot)
        return self._geo

    def actualizar(self):
        if self._actualizando:
            return
        self._actualizando = True
        try:
            self._actualizar_impl()
        finally:
            self._actualizando = False

    def _actualizar_impl(self):
        s = self.sesion
        abierto = s.abierto
        self.pila.set_visible_child_name("documento" if abierto else "vacio")
        self._poner("zoom", f"{int(round(self.lienzo.zoom * 100))} %")

        # La cinta se refresca SIEMPRE, también sin documento abierto: es justo
        # el caso en el que tiene que quedarse casi entera apagada.
        self.cinta.refrescar(s)

        if not abierto:
            self.banner_firma.set_revealed(False)
            self.l_estado.set_text("Abre un PDF para empezar.")
            self.l_aviso.set_text("")
            for clave in ("pagina", "sel_tipo", "sel_caja", "sel_tam", "txt_fuente",
                          "txt_tam", "txt_escala", "pag_tam", "pag_rot",
                          "doc_nombre", "doc_paginas", "doc_bytes", "doc_objetos"):
                self._poner(clave, "—")
            self._poner("sel_tipo", "nada seleccionado")
            return

        self.banner_firma.set_revealed(getattr(s, "tiene_firma", False))
        self.set_title(f"{s.ruta.name} — IntactPDF")
        self.titulo.set_subtitle(f"{s.ruta.name}  ·  página "
                                 f"{s.num_pagina + 1} de {s.n_paginas}")

        # lista lateral
        while (fila := self.lista.get_row_at_index(0)) is not None:
            self.lista.remove(fila)
        self._filas = []
        for i, o in enumerate(s.objetos()):
            fila = Gtk.ListBoxRow()
            caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            caja.set_margin_top(6)
            caja.set_margin_bottom(6)
            caja.set_margin_start(10)
            caja.set_margin_end(10)
            titulo = Gtk.Label(label=f"{i}  {o.tipo}")
            titulo.set_xalign(0)
            titulo.add_css_class("heading")
            detalle = Gtk.Label(label=s.descripcion_de(o))
            detalle.set_xalign(0)
            detalle.set_ellipsize(Pango.EllipsizeMode.END)
            detalle.add_css_class("dim-label")
            caja.append(titulo)
            caja.append(detalle)
            fila.set_child(caja)
            fila.objeto = o
            self.lista.append(fila)
            self._filas.append(fila)
            if o is s.seleccion:
                self.lista.select_row(fila)

        # -- los datos de la cinta ---------------------------------------
        sel = s.seleccion
        self._poner("pagina", f"{s.num_pagina + 1} / {s.n_paginas}")
        for ir in self.controles.get("ir", []):
            ir.set_range(1, max(1, s.n_paginas))
            # No se le cambia el número al usuario mientras lo está escribiendo:
            # eso pasa cada vez que se repinta, y le borraría lo tecleado.
            if not ir.has_focus() and int(ir.get_value()) != s.num_pagina + 1:
                ir.set_value(s.num_pagina + 1)

        _, ancho_pt, alto_pt = self.geometria()
        self._poner("pag_tam", f"{ancho_pt:.0f} × {alto_pt:.0f} pt")
        self._poner("pag_rot", f"girada {self._rot}°" if self._rot
                    else "sin girar")

        anadidos = self._bytes_de_mas(s)
        self._poner("doc_nombre", s.ruta.name)
        self._poner("doc_paginas",
                    f"{s.n_paginas} página{'s' if s.n_paginas != 1 else ''} · "
                    f"{len(s.bytes_actuales()):,} bytes "
                    f"({'+' if anadidos else ''}{anadidos:,} sobre el original)")
        self._poner("doc_objetos", f"{len(s.objetos())} objeto(s) en la página")

        if sel is None:
            self._poner("sel_tipo", "nada seleccionado")
            self._poner("sel_caja", "")
            self._poner("sel_tam", "")
        else:
            caja = sel.caja
            # Textos cortos a propósito: la cinta es una banda horizontal y
            # una frase larga empuja los demás grupos fuera de la ventana.
            # Aquí el detalle completo ya está en el panel de objetos.
            self._poner("sel_tipo", f"{sel.tipo}")
            self._poner("sel_caja", f"x {caja.x0:.0f}   y {caja.y0:.0f}")
            self._poner("sel_tam", f"{caja.ancho:.0f} × {caja.alto:.0f} pt")

        if sel is not None and sel.tipo == "texto":
            escala = s.escala_de_run(sel)
            tam = getattr(sel, "fuente_tam", 0.0)
            self._poner("txt_fuente", f"fuente: {sel.fuente_base or '—'}")
            self._poner("txt_tam", f"tamaño en el texto: {tam:.1f} pt")
            self._poner("txt_escala",
                        f"escala del run: ×{escala:.2f} → "
                        f"{tam * escala:.1f} pt en la página")
        else:
            self._poner("txt_fuente", "selecciona un texto para ver su tipografía")
            self._poner("txt_tam", "")
            self._poner("txt_escala", "")

        n = len(s.objetos())
        trozos = [f"{n} objeto{'s' if n != 1 else ''}",
                  f"página {s.num_pagina + 1}"]
        if sel is not None:
            trozos.append(f"seleccionado: {sel.tipo} — {s.descripcion_de(sel)}")
        if s.hay_cambios:
            trozos.append("cambios sin guardar")
        self.l_estado.set_text("  ·  ".join(trozos))
        self.l_aviso.set_text(s.ultimo_aviso or s.ultimo_mensaje or "")

    # -- acciones ---------------------------------------------------------

    def accion_abrir(self):
        dlg = Gtk.FileDialog()
        dlg.set_title("Abrir un PDF")
        filtro = Gtk.FileFilter()
        filtro.set_name("Documentos PDF")
        filtro.add_mime_type("application/pdf")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(filtro)
        dlg.set_filters(filtros)
        dlg.open(self, None, self._abierto)

    def _al_soltar(self, _destino, valor, _x, _y) -> bool:
        """Abre el primer PDF que se haya soltado sobre la ventana.

        Devuelve True si se ha abierto alguno. Si lo soltado no es un PDF se
        dice algo: soltar un fichero y que no pase absolutamente nada hace
        pensar que el programa está colgado.
        """
        for fichero in valor.get_files():
            ruta = fichero.get_path()
            if ruta and ruta.lower().endswith(".pdf"):
                self.abrir_fichero(ruta)
                return True
        self.error("Eso no es un PDF",
                   "Solo se pueden abrir documentos PDF en esta ventana.")
        return False

    def _abierto(self, dlg, resultado):
        try:
            fichero = dlg.open_finish(resultado)
        except GLib.Error:
            return
        self.abrir_fichero(fichero.get_path())

    def abrir_fichero(self, ruta: str):
        self.sesion.abrir(ruta)
        try:
            self._datos_originales = Path(ruta).read_bytes()
        except OSError:
            self._datos_originales = b""
        self._asegurar_doc()
        self.actualizar()
        self.lienzo.queue_draw()

    def accion_guardar(self):
        if not self.sesion.abierto:
            return
        if self.sesion.ruta:
            try:
                self.sesion.guardar()
                self.actualizar()
                self.lienzo.queue_draw()
                return
            except Exception as e:
                self.error("No se pudo guardar", str(e))
                return
        self.accion_guardar_como()

    def accion_guardar_como(self):
        if not self.sesion.abierto:
            return
        dlg = Gtk.FileDialog()
        dlg.set_title("Guardar el PDF como")
        nombre = (self.sesion.ruta.stem + "-editado.pdf") if self.sesion.ruta else "documento.pdf"
        dlg.set_initial_name(nombre)
        dlg.save(self, None, self._guardado)

    def accion_compactar(self):
        if not self.sesion.abierto:
            return
        dlg = Gtk.FileDialog()
        dlg.set_title("Guardar PDF compactado (sin historial previo)")
        nombre = (self.sesion.ruta.stem + "-compactado.pdf") if self.sesion.ruta else "compactado.pdf"
        dlg.set_initial_name(nombre)
        dlg.save(self, None, self._compactado)

    def _guardado(self, dlg, resultado):
        try:
            fichero = dlg.save_finish(resultado)
        except GLib.Error:
            return
        ruta = Path(fichero.get_path())
        if not ruta.name.lower().endswith(".pdf"):
            ruta = ruta.with_suffix(".pdf")
        try:
            mensaje = self.sesion.guardar(ruta)
        except Exception as e:
            self.error("No se pudo guardar", str(e))
            return
        self.actualizar()

    def _compactado(self, dlg, resultado):
        try:
            fichero = dlg.save_finish(resultado)
        except GLib.Error:
            return
        ruta = Path(fichero.get_path())
        if not ruta.name.lower().endswith(".pdf"):
            ruta = ruta.with_suffix(".pdf")
        from nucleo.guardar import compactar_pdf
        try:
            import uuid
            tmp_para_compactar = ruta.with_name(f".{ruta.name}.{uuid.uuid4().hex[:8]}.tmp.pdf")
            self.sesion.guardar(tmp_para_compactar, crear_backup=False)
            res = compactar_pdf(tmp_para_compactar, ruta)
            tmp_para_compactar.unlink(missing_ok=True)
            self.sesion.ultimo_mensaje = (
                f"Compactado {ruta.name}: {res.bytes_salida:,} bytes "
                f"({res.bytes_ahorrados:,} bytes purgados del historial)")
            self.actualizar()
        except Exception as e:
            self.error("No se pudo compactar", str(e))

    def accion_copiar(self):
        s = self.sesion
        if not s.abierto or not s.seleccion:
            return
        if s.seleccion.tipo == "texto":
            texto = getattr(s.seleccion, "texto", "") or ""
            if texto:
                clipboard = Gdk.Display.get_default().get_clipboard()
                clipboard.set(texto)
                s.ultimo_mensaje = f"Copiado al portapapeles: “{texto[:40]}{'…' if len(texto) > 40 else ''}”"
                self.actualizar()

    def accion_rotar(self, angulo: int = 90):
        if not self.sesion.abierto:
            return
        try:
            if self.sesion.rotar(angulo):
                self.actualizar()
                self.lienzo.queue_draw()
        except Exception as e:
            self.error("No se pudo girar la página", str(e))

    def accion_extraer_imagen(self):
        s = self.sesion
        if not s.abierto or not s.seleccion or s.seleccion.tipo != "imagen":
            return
        dlg = Gtk.FileDialog()
        dlg.set_title("Extraer imagen a archivo")
        nombre_base = s.seleccion.nombre_xobject.lstrip("/") or "imagen"
        dlg.set_initial_name(f"{nombre_base}.png")
        filtro_png = Gtk.FileFilter()
        filtro_png.set_name("Imagen PNG (*.png)")
        filtro_png.add_pattern("*.png")
        filtro_jpg = Gtk.FileFilter()
        filtro_jpg.set_name("Imagen JPEG (*.jpg, *.jpeg)")
        filtro_jpg.add_pattern("*.jpg")
        filtro_jpg.add_pattern("*.jpeg")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(filtro_png)
        filtros.append(filtro_jpg)
        dlg.set_filters(filtros)
        dlg.save(self, None, self._extraer_imagen_guardada)

    def _extraer_imagen_guardada(self, dlg, resultado):
        try:
            fichero = dlg.save_finish(resultado)
        except GLib.Error:
            return
        ruta = Path(fichero.get_path())
        try:
            self.sesion.extraer_imagen_seleccionada(ruta)
            self.sesion.ultimo_mensaje = f"Imagen extraída correctamente a {ruta.name}"
            self.actualizar()
        except Exception as e:
            self.error("No se pudo extraer la imagen", str(e))

    def accion_reemplazar_imagen(self):
        s = self.sesion
        if not s.abierto or not s.seleccion or s.seleccion.tipo != "imagen":
            return
        dlg = Gtk.FileDialog()
        dlg.set_title("Seleccionar nueva imagen")
        filtro = Gtk.FileFilter()
        filtro.set_name("Archivos de imagen (PNG, JPG, TIFF, WebP)")
        for m in ("image/png", "image/jpeg", "image/webp", "image/tiff"):
            filtro.add_mime_type(m)
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(filtro)
        dlg.set_filters(filtros)
        dlg.open(self, None, self._reemplazar_imagen_abierta)

    def _reemplazar_imagen_abierta(self, dlg, resultado):
        try:
            fichero = dlg.open_finish(resultado)
        except GLib.Error:
            return
        ruta = Path(fichero.get_path())
        try:
            if self.sesion.reemplazar_imagen_seleccionada(ruta):
                self.actualizar()
                self.lienzo.queue_draw()
        except Exception as e:
            self.error("No se pudo reemplazar la imagen", str(e))

    def accion_borrar(self):
        if self.sesion.borrar():
            self._doc = None
            self._geo = None
            self.actualizar()
            self.lienzo.queue_draw()

    def accion_deshacer(self):
        if self.sesion.deshacer():
            self.actualizar()
            self.lienzo.queue_draw()

    def accion_rehacer(self):
        if self.sesion.rehacer():
            self.actualizar()
            self.lienzo.queue_draw()

    def cambiar_pagina(self, salto: int):
        s = self.sesion
        if not s.abierto:
            return
        nueva = s.num_pagina + salto
        if 0 <= nueva < s.n_paginas:
            s.ir_a_pagina(nueva)
            self.actualizar()
            self.lienzo.queue_draw()

    def cambiar_zoom(self, factor: float):
        self._fijar_zoom(self.lienzo.zoom * factor)

    def zoom_real(self):
        """Al 100 %: un punto del PDF, un píxel en pantalla."""
        self._fijar_zoom(1.0)

    def zoom_ajustado(self):
        """Que la página entera quepa en lo ancho de la ventana."""
        _, ancho_pt, _ = self.geometria()
        disponible = self.scroll.get_width() - 28
        if ancho_pt > 1 and disponible > 40:
            self._fijar_zoom(disponible / ancho_pt)

    def _fijar_zoom(self, valor: float):
        self.lienzo.zoom = max(0.25, min(6.0, valor))
        self._poner("zoom", f"{int(round(self.lienzo.zoom * 100))} %")
        self.lienzo.queue_draw()

    def mover_pt(self, dx: float, dy: float):
        if self.sesion.mover(dx, dy):
            self.actualizar()
            self.lienzo.queue_draw()

    def mover_exacto(self):
        try:
            dx = float(self.controles["dx"][-1].get_text().replace(",", "."))
            dy = float(self.controles["dy"][-1].get_text().replace(",", "."))
        except ValueError:
            self.error("Eso no es un número",
                       "El desplazamiento se escribe en puntos del PDF, por "
                       "ejemplo 10 o -2.5.")
            return
        self.mover_pt(dx, dy)

    def escalar_a(self, factor: float):
        if self.sesion.escalar(factor):
            self.actualizar()
            self.lienzo.queue_draw()

    def ir_a_pagina_escrita(self):
        s = self.sesion
        if not s.abierto:
            return
        destino = int(self.controles["ir"][-1].get_value()) - 1
        if 0 <= destino < s.n_paginas and destino != s.num_pagina:
            s.ir_a_pagina(destino)
            self.actualizar()
            self.lienzo.queue_draw()

    def _alternar_panel(self, boton):
        self.split.set_show_sidebar(boton.get_active())

    def _bytes_de_mas(self, s) -> int:
        """Cuántos bytes se han añadido sobre el original, para enseñarlo."""
        if not s.hay_cambios or not self._datos_originales:
            return 0
        return len(s.bytes_actuales()) - len(self._datos_originales)

    # -- lo que reutiliza la consola --------------------------------------

    def _dialogo_largo(self, titulo: str, cuerpo: str) -> None:
        """Un diálogo con texto largo en monoespaciada, con scroll.

        Es el mismo widget para el resumen del documento, las fuentes y el
        resultado de comprobar el fichero, porque los tres son «soltar texto y
        que se pueda leer».
        """
        dlg = dialogos.nuevo(titulo)
        vista = Gtk.TextView()
        vista.set_editable(False)
        vista.set_monospace(True)
        vista.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        vista.get_buffer().set_text(cuerpo.strip() or "(sin salida)")
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(vista)
        scroll.set_min_content_height(340)
        scroll.set_min_content_width(560)
        dlg.set_extra_child(scroll)
        dlg.add_response("cerrar", "Cerrar")
        dialogos.presentar(dlg, self)

    def diagnostico(self):
        """El diagnóstico del entorno, que vive en la aplicación.

        La ventana lo enseña en la cinta, pero quien lo sabe hacer es la
        aplicación (es lo mismo que sale por la consola con `intactpdf doctor`).
        """
        app = self.get_application()
        if app is not None:
            app.diagnostico()

    def ver_informacion(self):
        s = self.sesion
        if not s.abierto:
            return
        texto = _capturar(lambda: cmd_info(_args(archivo=str(s.ruta))))
        self._dialogo_largo(f"Qué hay dentro de {s.ruta.name}", texto)

    def ver_fuentes(self):
        s = self.sesion
        if not s.abierto:
            return
        texto = _capturar(lambda: cmd_fonts(_args(archivo=str(s.ruta),
                                                  pagina=s.num_pagina)))
        self._dialogo_largo(f"Fuentes de la página {s.num_pagina + 1}", texto)

    def comprobar(self):
        """Valida el documento con libqpdf, tal y como está ahora mismo.

        Se comprueba el estado ACTUAL, no el fichero del disco: si hay cambios
        sin guardar, se escriben en un temporal y se valida eso. Comprobar el
        fichero viejo y dar el visto bueno sería mentir.
        """
        s = self.sesion
        if not s.abierto:
            return
        import tempfile

        fd, nombre = tempfile.mkstemp(suffix=".pdf", prefix="intactpdf-check-")
        os.close(fd)
        tmp = Path(nombre)
        try:
            tmp.write_bytes(s.bytes_actuales())
            titulo = "Comprobación"
            if s.hay_cambios:
                titulo += " (del estado actual, sin guardar)"
            texto = _capturar(lambda: cmd_check(_args(archivo=str(tmp))))
        finally:
            tmp.unlink(missing_ok=True)
        self._dialogo_largo(titulo, texto)

    def _cambiar_cajas(self, fila, _param=None):
        self.mostrar_cajas = fila.get_active()
        if not self._sincronizando:
            # La casilla de la cinta enseña lo mismo que el interruptor del
            # panel: si se cambia uno, el otro tiene que seguirle.
            self._sincronizando = True
            try:
                self.b_cajas.set_active(self.mostrar_cajas)
            finally:
                self._sincronizando = False
        self.lienzo.queue_draw()

    def _alternar_cajas(self, boton):
        if self._sincronizando:
            return
        self.fila_cajas.set_active(boton.get_active())

    def _fila_elegida(self, _lista, fila):
        if fila is None or self._actualizando:
            return
        self.sesion.seleccionar(getattr(fila, "objeto", None))
        self.actualizar()
        self.lienzo.queue_draw()

    # -- diálogos ---------------------------------------------------------

    def dialogo_anadir_texto(self):
        """Diálogo interactivo para añadir una nueva línea de texto al documento."""
        s = self.sesion
        if not s.abierto:
            return

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        caja.set_margin_top(6)

        entrada = Gtk.Entry()
        entrada.set_placeholder_text("Introduce el nuevo texto...")
        entrada.set_hexpand(True)
        caja.append(entrada)

        fila_pos = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl_x = Gtk.Label(label="X:")
        spin_x = Gtk.SpinButton.new_with_range(0, 2000, 10)
        spin_x.set_value(100.0)
        lbl_y = Gtk.Label(label="Y:")
        spin_y = Gtk.SpinButton.new_with_range(0, 2000, 10)
        spin_y.set_value(500.0)
        lbl_tam = Gtk.Label(label="Tamaño:")
        spin_tam = Gtk.SpinButton.new_with_range(6, 120, 1)
        spin_tam.set_value(12.0)

        for w in (lbl_x, spin_x, lbl_y, spin_y, lbl_tam, spin_tam):
            fila_pos.append(w)
        caja.append(fila_pos)

        def insertar():
            txt = entrada.get_text()
            if not txt.strip():
                return
            x = spin_x.get_value()
            y = spin_y.get_value()
            tam = spin_tam.get_value()
            if not s.anadir_texto(txt, x=x, y=y, tamano=tam):
                self.error("No se pudo añadir el texto", s.ultimo_aviso or "Error desconocido")
            else:
                self.actualizar()
                self.lienzo.queue_draw()

        dialogos.confirmacion(
            t("btn_anadir_texto"),
            "Inserta un nuevo bloque de texto con tipografía incrustada de forma incremental.",
            t("btn_guardar"),
            insertar,
            extra=caja,
            padre=self
        )

    def dialogo_anadir_imagen(self):
        """Selector de archivos para añadir una nueva imagen al documento."""
        s = self.sesion
        if not s.abierto:
            return

        dlg = Gtk.FileDialog()
        dlg.set_title(t("btn_anadir_imagen"))
        filtro = Gtk.FileFilter()
        filtro.set_name("Imágenes (PNG, JPG, JPEG, WEBP)")
        filtro.add_mime_type("image/png")
        filtro.add_mime_type("image/jpeg")
        filtro.add_mime_type("image/webp")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(filtro)
        dlg.set_filters(filtros)
        dlg.set_default_filter(filtro)
        dlg.open(self, None, self._anadir_imagen_abierta)

    def _anadir_imagen_abierta(self, dlg, resultado):
        try:
            fichero = dlg.open_finish(resultado)
        except Exception:
            return
        if not fichero:
            return
        ruta = Path(fichero.get_path())
        s = self.sesion
        # Insertar imagen en (100, 400) con tamaño estándar de 150x100 pt
        if not s.anadir_imagen(ruta, x=100, y=400, ancho=150, alto=100):
            self.error("No se pudo añadir la imagen", s.ultimo_aviso or "Error al procesar la imagen")
        else:
            self.actualizar()
            self.lienzo.queue_draw()

    def dialogo_texto(self):
        s = self.sesion
        obj = s.seleccion
        if obj is None or obj.tipo != "texto":
            return
        escala = s.escala_de_run(obj)
        tam = getattr(obj, "fuente_tam", 0.0)

        caja_dialogo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        caja_dialogo.set_margin_top(6)

        entrada = Gtk.Entry()
        entrada.set_text(obj.texto or "")
        entrada.set_hexpand(True)
        caja_dialogo.append(entrada)

        chk_ajustar = Gtk.CheckButton(label=t("dlg_editar_texto_sw"))
        chk_ajustar.set_active(self.sw_ajustar.get_active())
        chk_ajustar.set_tooltip_text(t("dlg_editar_texto_sw_sub"))
        caja_dialogo.append(chk_ajustar)

        def cambiar():
            nuevo = entrada.get_text()
            if nuevo == (obj.texto or ""):
                return
            ajustar = chk_ajustar.get_active()
            self.sw_ajustar.set_active(ajustar)
            if not s.editar_texto(nuevo, ajustar_espaciado=ajustar):
                self.error("No se puede cambiar ese texto",
                           s.ultimo_aviso or "el núcleo no ha dado un motivo")
            else:
                self.actualizar()
                self.lienzo.queue_draw()

        dialogos.confirmacion(
            t("dlg_editar_texto_tit"),
            (f"Fuente: {obj.fuente_base or '—'}   ·   "
             f"tamaño en el texto: {tam:.1f} pt   ·   "
             f"en la página: {tam * escala:.1f} pt"),
            t("btn_guardar"), cambiar, extra=caja_dialogo, padre=self)

    def mostrar_tutorial(self):
        """Muestra una guía visual interactiva y didáctica de uso en el idioma activo."""
        dlg = Adw.PreferencesWindow()
        dlg.set_transient_for(self)
        dlg.set_modal(True)
        dlg.set_title(t("tut_titulo"))
        dlg.set_default_size(600, 520)

        # Selector de idioma en el propio tutorial
        pag_lang = Adw.PreferencesPage()
        pag_lang.set_title(t("grp_idioma"))
        pag_lang.set_icon_name("preferences-desktop-locale-symbolic")

        grp_l = Adw.PreferencesGroup()
        grp_l.set_title(t("grp_idioma"))
        grp_l.set_description("Selecciona tu idioma / Select language / Sprache wählen / 选择语言")

        for cod, nom in IDIOMAS_DISPONIBLES.items():
            r = Adw.ActionRow()
            r.set_title(nom)
            r.set_subtitle(f"Code: {cod.upper()}")
            btn_sel = Gtk.Button.new_with_label("Activar" if cod != idioma_actual() else "✓ Activo")
            btn_sel.add_css_class("suggested-action" if cod == idioma_actual() else "flat")
            btn_sel.connect("clicked", lambda _, c=cod: (self.cambiar_idioma(c), dlg.close(), self.mostrar_tutorial()))
            r.add_suffix(btn_sel)
            grp_l.add(r)
        pag_lang.add(grp_l)
        dlg.add(pag_lang)

        # Página 1: Primeros Pasos
        pag1 = Adw.PreferencesPage()
        pag1.set_title(t("tut_pag1_tit"))
        pag1.set_icon_name("help-faq-symbolic")

        grp_basico = Adw.PreferencesGroup()
        grp_basico.set_title(t("tut_pag1_grp_tit"))
        grp_basico.set_description(t("tut_pag1_grp_desc"))

        row_sel = Adw.ActionRow()
        row_sel.set_title(t("tut_row_sel_tit"))
        row_sel.set_subtitle(t("tut_row_sel_sub"))
        row_sel.add_prefix(Gtk.Image.new_from_icon_name("input-mouse-symbolic"))
        grp_basico.add(row_sel)

        row_txt = Adw.ActionRow()
        row_txt.set_title(t("tut_row_txt_tit"))
        row_txt.set_subtitle(t("tut_row_txt_sub"))
        row_txt.add_prefix(Gtk.Image.new_from_icon_name("insert-text-symbolic"))
        grp_basico.add(row_txt)

        row_mov = Adw.ActionRow()
        row_mov.set_title(t("tut_row_mov_tit"))
        row_mov.set_subtitle(t("tut_row_mov_sub"))
        row_mov.add_prefix(Gtk.Image.new_from_icon_name("transform-move-symbolic"))
        grp_basico.add(row_mov)

        pag1.add(grp_basico)
        dlg.add(pag1)

        # Página 2: Imágenes y Páginas
        pag2 = Adw.PreferencesPage()
        pag2.set_title(t("tut_pag2_tit"))
        pag2.set_icon_name("image-x-generic-symbolic")

        grp_img = Adw.PreferencesGroup()
        grp_img.set_title(t("tut_pag2_grp_tit"))

        row_rep = Adw.ActionRow()
        row_rep.set_title(t("tut_row_rep_tit"))
        row_rep.set_subtitle(t("tut_row_rep_sub"))
        row_rep.add_prefix(Gtk.Image.new_from_icon_name("document-revert-symbolic"))
        grp_img.add(row_rep)

        row_ext = Adw.ActionRow()
        row_ext.set_title(t("tut_row_ext_tit"))
        row_ext.set_subtitle(t("tut_row_ext_sub"))
        row_ext.add_prefix(Gtk.Image.new_from_icon_name("document-save-symbolic"))
        grp_img.add(row_ext)

        row_rot = Adw.ActionRow()
        row_rot.set_title(t("tut_row_rot_tit"))
        row_rot.set_subtitle(t("tut_row_rot_sub"))
        row_rot.add_prefix(Gtk.Image.new_from_icon_name("object-rotate-right-symbolic"))
        grp_img.add(row_rot)

        pag2.add(grp_img)
        dlg.add(pag2)

        # Página 3: Atajos de teclado
        pag3 = Adw.PreferencesPage()
        pag3.set_title(t("tut_pag3_tit"))
        pag3.set_icon_name("preferences-desktop-keyboard-shortcuts-symbolic")

        grp_atajos = Adw.PreferencesGroup()
        grp_atajos.set_title(t("tut_pag3_grp_tit"))

        for atajo, desc_clave in (
            ("Ctrl + O", "tut_sh_abrir"),
            ("Ctrl + S", "tut_sh_guardar"),
            ("Ctrl + Mayús + S", "tut_sh_guardar_como"),
            ("Ctrl + E", "tut_sh_editar"),
            ("Ctrl + Z", "tut_sh_deshacer"),
            ("Ctrl + Mayús + Z / Ctrl + Y", "tut_sh_rehacer"),
            ("Ctrl + C", "tut_sh_copiar"),
            ("Ctrl + Scroll", "tut_sh_zoom_scroll"),
            ("Ctrl + +, Ctrl + -, Ctrl + 0", "tut_sh_zoom_keys"),
            ("Supr / Delete", "tut_sh_borrar"),
            ("Doble clic", "tut_sh_doble_clic"),
        ):
            r = Adw.ActionRow()
            r.set_title(t(desc_clave))
            r.add_suffix(Gtk.Label(label=atajo, css_classes=["dim-label", "monospace"]))
            grp_atajos.add(r)

        pag3.add(grp_atajos)
        dlg.add(pag3)

        dlg.present()

    def dialogo_escalar(self):
        s = self.sesion
        obj = s.seleccion
        if obj is None or obj.caja is None:
            return
        caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        caja.set_halign(Gtk.Align.CENTER)
        ajuste = Gtk.SpinButton.new_with_range(10, 400, 5)
        ajuste.set_value(150)
        caja.append(ajuste)
        caja.append(Gtk.Label(label=t("dlg_escalar_pct")))

        def escalar():
            if s.escalar(ajuste.get_value() / 100.0):
                self.actualizar()
                self.lienzo.queue_draw()

        dialogos.confirmacion(
            t("dlg_escalar_tit"),
            (f"{obj.tipo.capitalize()} de "
             f"{obj.caja.ancho:.0f} × {obj.caja.alto:.0f} pt. "
             f"Se escala alrededor de su centro; nada más se mueve."),
            t("btn_escalar"), escalar, extra=caja, padre=self)

    def error(self, titulo: str, detalle: str):
        dialogos.aviso(titulo, detalle, padre=self)


class Aplicacion(Adw.Application):
    """La aplicación GTK. **Una sola por proceso, y un solo `run()`.**
    Cada ventana no lleva su aplicación: la ventana se construye con la que ya
    existe (`Ventana(app, sesion)`). Las dos reglas son de GLib, no nuestras, y
    las dos se pagan con un fallo silencioso en vez de con una excepción:

    - crear una segunda `Aplicacion` con el mismo identificador y llamar a
      `register()` **lanza** `GLib.Error: An object is already exported…`, donde
      hay bus de sesión (o sea, en cualquier escritorio de verdad); sin bus
      devuelve False y no pasa nada, así que el fallo no se ve donde se prueba;
    - llamar a `run()` **dos veces en el proceso** no abre nada: imprime
      «Failed to register: An object is already exported…» y devuelve 1. Medido:
      con el mismo objeto y con uno nuevo, y con y sin bus de sesión.

    Lo destapó el CI, que ejecuta las pruebas y las capturas en un proceso: el
    primer intento se arregló sólo en parte porque en el entorno de pruebas no
    había bus de sesión y el fallo era invisible. Las capturas se generan ahora
    una por proceso (`tools/capturas_gui.py`), y las pruebas comparten la suya.
    """

    # Registrar una aplicación es algo que sólo se puede hacer UNA VEZ por
    # proceso y por identificador. Aquí se recuerda si ya se hizo, para poder
    # contestar sin depender de lo que diga GLib.
    _registrada = False

    def registrar(self) -> bool:
        """Registrar en el bus de sesión, sin reventar si ya había una.

        Registrar sirve para que abrir un PDF desde el gestor de ficheros mande
        el documento a la ventana que ya está abierta en vez de abrir otra. Es
        opcional: sin registro, la aplicación funciona igual, sólo que sin eso.

        **Medido, y sólo se ve donde hay bus de sesión**: la segunda vez que se
        registra el mismo identificador en un proceso, `Gio.Application.register()`
        no devuelve False, sino que **lanza** `GLib.Error: An object is already
        exported for the interface org.gtk.Application`. Sin bus de sesión
        (contenedor, Xvfb pelado) devuelve False y no pasa nada, así que el fallo
        era invisible en el sitio donde se probaba y aparecía en cualquier
        escritorio de verdad, que es donde hay bus. Lo destapó el CI: tres pruebas
        de la ventana y, a partir de la segunda captura, la herramienta que genera
        las capturas para Flathub.
        """
        if Aplicacion._registrada:
            return False
        try:
            hecho = bool(self.register(None))
        except GLib.Error:
            hecho = False
        Aplicacion._registrada = Aplicacion._registrada or hecho
        return hecho
    def __init__(self, sesion: Sesion, captura: str | None = None,
                 al_abrir=None):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.sesion = sesion
        self.captura = captura
        # `al_abrir` recibe la ventana ya construida, antes de la captura. Es
        # para las herramientas: cambiar de pestaña de la cinta, ocultar el
        # panel... y poder fotografiar cada parte de la interfaz.
        self.al_abrir = al_abrir
        for nombre, fn in (("doctor", lambda *_: self.diagnostico()),
                           ("acerca", lambda *_: self.acerca()),
                           ("abrir", lambda *_: self.en_ventana("accion_abrir")),
                           ("guardar", lambda *_: self.en_ventana("accion_guardar")),
                           ("guardar_como", lambda *_: self.en_ventana("accion_guardar_como")),
                           ("compactar", lambda *_: self.en_ventana("accion_compactar")),
                           ("check", lambda *_: self.en_ventana("comprobar")),
                           ("fonts", lambda *_: self.en_ventana("ver_fuentes"))):
            accion = Gio.SimpleAction.new(nombre, None)
            accion.connect("activate", fn)
            self.add_action(accion)

    def en_ventana(self, metodo: str):
        """Ejecuta un método de la ventana activa, si hay alguna.

        Las acciones de la aplicación (`app.abrir`, `app.check`...) se registran
        al construir la aplicación, cuando todavía no hay ventana: por eso se
        busca en el momento de usarlas y no antes.
        """
        ventana = self.props.active_window
        if ventana is not None:
            getattr(ventana, metodo)()

    def do_activate(self):
        ventana = self.props.active_window
        if not ventana:
            ventana = Ventana(self, self.sesion)
        ventana.present()
        if self.al_abrir:
            self.al_abrir(ventana)
        if self.captura:
            # Modo captura: se espera a que la ventana esté colocada y se guarda
            # una imagen de su contenido. Sirve para dos cosas: comprobar que la
            # interfaz se dibuja sin pantalla (con Xvfb) y generar las capturas
            # que Flathub exige para publicar.
            GLib.timeout_add(1200, self._capturar, ventana)

    def _capturar(self, ventana) -> bool:
        try:
            _guardar_captura(ventana, self.captura)
            print(f"  captura guardada en {self.captura}")
        except Exception as e:
            print(f"  no se pudo capturar: {type(e).__name__}: {e}",
                  file=sys.stderr)
            self.quit()
            return False
        self.quit()
        return False

    def do_open(self, ficheros, _n, _punta):
        ruta = ficheros[0].get_path()
        ventana = self.props.active_window or Ventana(self, self.sesion)
        ventana.present()
        if ruta:
            ventana.abrir_fichero(ruta)

    def diagnostico(self):
        from nucleo.cli import cmd_doctor
        ventana = self.props.active_window
        if ventana is not None:
            ventana._dialogo_largo("Diagnóstico",
                                   _capturar(lambda: cmd_doctor(None)))

    def acerca(self):
        dlg = Adw.AboutDialog(
            application_name="IntactPDF",
            application_icon=APP_ID,
            version="0.1.0",
            developer_name="IntactPDF",
            license_type=Gtk.License.MIT_X11,
            comments=("Edita el texto, las imágenes y los vectores de un PDF y "
                      "guarda añadiendo al final del fichero. La salida empieza "
                      "por los bytes del original: lo que no se ha editado es "
                      "imposible que haya cambiado."),
            website="https://github.com/LockerDocx/intactpdf")
        dlg.present(self.props.active_window)


def _guardar_captura(widget: Gtk.Widget, ruta: str) -> None:
    """Guarda el contenido del widget como PNG, sin depender del servidor X.

    Se dibuja el árbol de la ventana en un `Gtk.Snapshot` y se rasteriza con el
    renderizador de GTK. Así no hace falta ni una herramienta externa de
    capturas, y el resultado es la ventana de verdad, no una maqueta.
    """
    paintable = Gtk.WidgetPaintable.new(widget)
    ancho = max(1, widget.get_width())
    alto = max(1, widget.get_height())
    instantanea = Gtk.Snapshot.new()
    paintable.snapshot(instantanea, ancho, alto)
    nodo = instantanea.to_node()
    if nodo is None:
        raise RuntimeError("GTK no produjo ningún nodo que dibujar")
    nativo = widget.get_native()
    if nativo is None:
        raise RuntimeError("la ventana no está realizada")
    textura = nativo.get_renderer().render_texture(nodo, None)
    if textura is None:
        raise RuntimeError("el renderizador devolvió un vacío")
    textura.save_to_png(ruta)


def _args(**kw) -> Namespace:
    """Un Namespace con los valores por omisión de la consola.

    La ventana reutiliza los comandos `info`, `fonts` y `check` del programa de
    consola en vez de tener su propia versión de lo mismo: si se arregla uno, se
    arreglan los dos, y lo que enseña la ventana es exactamente lo que sale por
    la terminal.
    """
    base = {"archivo": "", "pagina": 0, "json": False}
    base.update(kw)
    return Namespace(**base)


def _capturar(fn) -> str:
    """Recoge lo que imprime una función del CLI que escribe en stdout."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    captura = None
    if "--captura" in argv:
        i = argv.index("--captura")
        if i + 1 >= len(argv):
            print("--captura necesita una ruta", file=sys.stderr)
            return 2
        captura = argv[i + 1]
        del argv[i:i + 2]
    rutas = [a for a in argv[1:] if not a.startswith("-")]
    sesion = Sesion()
    if rutas:
        try:
            sesion.abrir(rutas[0])
        except Exception as e:
            print(f"no se pudo abrir {rutas[0]}: {e}", file=sys.stderr)
    app = Aplicacion(sesion, captura=captura)
    return app.run([argv[0]] if argv else ["intactpdf-gui"])


if __name__ == "__main__":
    raise SystemExit(main())
