"""La cinta de opciones, al estilo de Word.

Por qué una cinta y no la barra de iconos suelta que había antes: en un editor
de PDF se hacen pocas cosas, pero se hacen a menudo y con el ratón, y una barra
de iconos obliga a pasar el ratón por encima de cada uno para saber qué hace.
La cinta **enseña los nombres**, los agrupa por para qué sirven y —esto es lo
importante— **desactiva en lugar de esconder** lo que en ese momento no se puede
usar. Es exactamente lo que hace Word: con una imagen seleccionada se encienden
las herramientas de imagen; sin nada seleccionado están apagadas, pero se ven.

Lo que NO hay aquí: botones de cosas que el programa no sabe hacer. La cinta
enseña las opciones que existen. Un botón muerto, o uno que promete algo que no
está, es peor que no tenerlo: enseña a desconfiar de todos los demás.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

# Estilo propio de la cinta. Se usan los colores con nombre de libadwaita
# (@borders, @accent_bg_color...) y no valores a mano, para que el modo oscuro y
# cualquier tema salgan bien sin tocar nada. Los tamaños sí van en píxeles:
# son medidas de la disposición, no del tema.
_CSS = b"""
.cinta-pestanas { padding: 4px 6px 0 6px; }
.cinta-pestana {
    padding: 3px 12px;
    margin: 0 1px;
    border-radius: 6px 6px 0 0;
    font-weight: normal;
}
.cinta-pestana:checked {
    box-shadow: inset 0 -2px 0 0 @accent_bg_color;
    font-weight: bold;
}
.cinta-banda {
    border-top: 1px solid @borders;
    border-bottom: 1px solid @borders;
    padding: 4px 4px 2px 4px;
}
.cinta-grupo { margin: 0 2px; }
.cinta-grande { padding: 4px 8px; min-width: 58px; }
.cinta-pista { opacity: 0.7; }
"""

_proveedor = None


def _cargar_css() -> None:
    """Carga la hoja de estilo una sola vez, aunque haya varias ventanas."""
    global _proveedor
    if _proveedor is not None:
        return
    from gi.repository import Gdk

    pantalla = Gdk.Display.get_default()
    if pantalla is None:
        # Sin pantalla todavía no hay dónde cargarlo. No es un caso raro: los
        # tests de la cinta construyen widgets sin abrir ventana, y ahí
        # adelantarse daría un error que no tiene nada que ver con lo que se
        # está probando.
        return
    _proveedor = Gtk.CssProvider()
    _proveedor.load_from_data(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        pantalla, _proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def _icono(nombre: str, tam: int) -> Gtk.Image:
    imagen = Gtk.Image.new_from_icon_name(nombre)
    imagen.set_pixel_size(tam)
    return imagen


class Grupo:
    """Un grupo de botones con su nombre debajo, como los de Word.

    No es un widget: es quien construye el widget. Se encarga de que todos los
    grupos midan lo mismo (la etiqueta abajo, alineada con las de los demás) y
    de no dejar que uno se estire más que otro.
    """

    def __init__(self, titulo: str):
        self.titulo = titulo
        self.caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.caja.add_css_class("cinta-grupo")
        # OJO con la orientación: esto son las COLUMNAS del grupo, o sea las
        # filas apiladas una debajo de otra. Cada `fila()` que cuelga de aquí es
        # horizontal. Al revés, las filas salen pegadas en horizontal y textos
        # que deberían ir uno debajo de otro aparecen en la misma línea, que es
        # exactamente lo que pasaba en el grupo «Documento» de la pestaña Página.
        self.columnas = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        # Centrado como BLOQUE y sin repartir el espacio sobrante: un Gtk.Box
        # vertical al que le sobra altura reparte el hueco entre sus hijos, y
        # las tres líneas de «Tipografía» acababan separadas una de otra en vez
        # de ser tres líneas seguidas.
        self.columnas.set_valign(Gtk.Align.CENTER)
        # El grupo entero ocupa toda la altura de la banda y el rótulo se queda
        # abajo: sin esto, los rótulos de los grupos cortos salen centrados y
        # quedan a distinta altura que los de los grupos largos. En Word están
        # todos a la misma línea, abajo.
        self.caja.set_valign(Gtk.Align.FILL)
        self.caja.append(self.columnas)
        self._filas: list[Gtk.Box] = []
        self.fila()
        etiqueta = Gtk.Label(label=titulo)
        etiqueta.add_css_class("caption")
        etiqueta.add_css_class("cinta-pista")
        etiqueta.set_halign(Gtk.Align.CENTER)
        etiqueta.set_margin_top(1)
        self.caja.append(etiqueta)

    def fila(self) -> Gtk.Box:
        """Abre una fila nueva dentro del grupo y devuelve dónde meter cosas."""
        fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        fila.set_valign(Gtk.Align.CENTER)
        self.columnas.append(fila)
        self._filas.append(fila)
        return fila

    # -- botones ----------------------------------------------------------

    def _colocar(self, widget: Gtk.Widget) -> None:
        self._filas[-1].append(widget)

    def grande(self, icono: str, texto: str, punta: str,
               fn) -> Gtk.Button:
        """El botón principal del grupo: icono encima del nombre, como en Word."""
        b = Gtk.Button()
        b.add_css_class("flat")
        b.add_css_class("cinta-grande")
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        caja.set_valign(Gtk.Align.CENTER)
        caja.append(_icono(icono, 22))
        etiqueta = Gtk.Label(label=texto)
        etiqueta.add_css_class("caption")
        caja.append(etiqueta)
        b.set_child(caja)
        b.set_tooltip_text(punta)
        b.set_valign(Gtk.Align.CENTER)
        b.connect("clicked", lambda _b: fn())
        self._colocar(b)
        return b

    def pequeno(self, icono: str, texto: str, punta: str,
                fn) -> Gtk.Button:
        """Botón de los que van en fila: icono y nombre, en una línea."""
        b = Gtk.Button()
        b.add_css_class("flat")
        caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        caja.append(_icono(icono, 16))
        caja.append(Gtk.Label(label=texto))
        b.set_child(caja)
        b.set_tooltip_text(punta)
        b.connect("clicked", lambda _b: fn())
        self._colocar(b)
        return b

    def icono(self, icono: str, punta: str, fn) -> Gtk.Button:
        """Botón de solo icono, para lo que se repite mucho (mover, zoom)."""
        b = Gtk.Button.new_from_icon_name(icono)
        b.add_css_class("flat")
        b.set_tooltip_text(punta)
        b.connect("clicked", lambda _b: fn())
        self._colocar(b)
        return b

    def texto(self, etiqueta: str, mono: bool = False,
              ancho: int = 0) -> Gtk.Label:
        """Un dato, no un botón: medidas, nombre de la fuente, posición."""
        l = Gtk.Label(label=etiqueta)
        l.set_xalign(0)
        l.add_css_class("caption")
        if mono:
            l.add_css_class("monospace")
        if ancho:
            l.set_width_chars(ancho)
            l.set_xalign(0.5)
        l.set_valign(Gtk.Align.CENTER)
        self._colocar(l)
        return l

    def meter(self, widget: Gtk.Widget) -> Gtk.Widget:
        """Para meter algo que no es ninguno de los anteriores (un SpinButton)."""
        widget.set_valign(Gtk.Align.CENTER)
        self._colocar(widget)
        return widget

    def separador(self) -> None:
        col = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        col.set_margin_top(4)
        col.set_margin_bottom(4)
        col.set_margin_start(4)
        col.set_margin_end(4)
        self.columnas.append(col)


class Pagina:
    """Una pestaña de la cinta: sus grupos, en fila."""

    def __init__(self, clave: str, titulo: str):
        self.clave = clave
        self.titulo = titulo
        self.grupos: list[Grupo] = []
        self.caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        contenedor = Gtk.ScrolledWindow()
        # Nunca hacia arriba ni hacia abajo: la cinta tiene una altura fija, y
        # si apareciese una barra de desplazamiento vertical cambiaría de alto
        # al cambiar de pestaña.
        contenedor.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        contenedor.set_child(self.caja)
        self.widget = contenedor

    def grupo(self, titulo: str) -> Grupo:
        g = Grupo(titulo)
        if self.grupos:
            self.grupos[-1].separador()
        self.caja.append(g.caja)
        self.grupos.append(g)
        return g


class Cinta(Gtk.Box):
    """Pestañas arriba, banda de grupos debajo.

    Cada botón puede llevar una condición («¿tiene sentido ahora?») que la
    ventana reevalúa cada vez que algo cambia. Los botones no se esconden: se
    apagan. Si algo no se ve nunca, el usuario no sabe que existe.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _cargar_css()
        self._paginas: dict[str, Pagina] = {}
        self._condiciones: list[tuple[Gtk.Widget, object]] = []
        self._pestanas: dict[str, Gtk.ToggleButton] = {}
        self._primera: Gtk.ToggleButton | None = None

        self.pestanas = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.pestanas.add_css_class("cinta-pestanas")
        self.append(self.pestanas)

        self.pila = Gtk.Stack()
        self.pila.set_transition_type(Gtk.StackTransitionType.NONE)
        self.pila.add_css_class("cinta-banda")
        self.append(self.pila)

    # -- construcción -----------------------------------------------------

    def pagina(self, clave: str, titulo: str,
               al_activar=None) -> Pagina:
        pagina = Pagina(clave, titulo)
        self._paginas[clave] = pagina
        self.pila.add_named(pagina.widget, clave)

        boton = Gtk.ToggleButton(label=titulo)
        boton.add_css_class("flat")
        boton.add_css_class("cinta-pestana")
        boton.set_focus_on_click(False)
        if self._primera is not None:
            # set_group hace que sean excluyentes: pulsar una desmarca las
            # demás, sin llevar la cuenta a mano.
            boton.set_group(self._primera)
        else:
            self._primera = boton
        boton.connect("toggled", self._pestana_pulsada, clave)
        self.pestanas.append(boton)
        self._pestanas[clave] = boton

        if self._primera is boton:
            boton.set_active(True)
            self.pila.set_visible_child_name(clave)
        return pagina

    def _pestana_pulsada(self, boton: Gtk.ToggleButton, clave: str) -> None:
        # Se responde al activar, no al pulsar: si se responde a los dos, al
        # desmarcar la pestaña vieja se volvería a ella.
        if boton.get_active():
            self.pila.set_visible_child_name(clave)

    def pagina_activa(self) -> str:
        return self.pila.get_visible_child_name()

    def activar(self, clave: str) -> None:
        if clave in self._pestanas:
            self._pestanas[clave].set_active(True)
        self.pila.set_visible_child_name(clave)

    # -- estado -----------------------------------------------------------

    def vigilar(self, widget: Gtk.Widget, condicion) -> Gtk.Widget:
        """Apaga el widget cuando la condición se cumpla al revés.

        La condición recibe la sesión y devuelve True si el widget sirve para
        algo en ese momento. Una ventana sin documento abierto deja la cinta
        casi entera apagada, que es lo que hace Word.
        """
        self._condiciones.append((widget, condicion))
        return widget

    def refrescar(self, sesion) -> None:
        for widget, condicion in self._condiciones:
            try:
                activo = bool(condicion(sesion))
            except Exception:
                # Una condición que revienta no puede tumbar el repintado de la
                # ventana entera; se apaga el botón y se sigue.
                activo = False
            if isinstance(widget, Gtk.ToggleButton):
                # Los interruptores nunca se apagan: enseñan un estado.
                continue
            widget.set_sensitive(activo)

    def botones(self):
        """Todos los botones de la cinta, para poder recorrerlos en un test.

        En GTK4 un contenedor NO es iterable (eso era GTK3): hay que ir
        encadenando hermanos con `get_first_child()` y `get_next_sibling()`.
        """
        for pagina in self._paginas.values():
            for grupo in pagina.grupos:
                fila = grupo.columnas.get_first_child()
                while fila is not None:
                    hijo = fila.get_first_child()
                    while hijo is not None:
                        yield hijo
                        hijo = hijo.get_next_sibling()
                    fila = fila.get_next_sibling()
