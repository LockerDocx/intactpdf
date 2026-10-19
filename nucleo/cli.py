"""
Interfaz de línea de comandos de IntactPDF.

**Hay dos programas, y este es el de consola**: la ventana se abre con
`intactpdf-gui` (o desde la entrada «IntactPDF» del menú de aplicaciones). Este
hace lo mismo sin ventana, que es lo que hace falta en un servidor, en un guion o
en una tubería.

    intactpdf doctor                             diagnóstico del entorno
    intactpdf info    documento.pdf              resumen del documento
    intactpdf list    documento.pdf              objetos de la página, con índice
    intactpdf fonts   documento.pdf              fuentes y qué se puede editar
    intactpdf delete  documento.pdf --object 12 -o salida.pdf
    intactpdf move    documento.pdf --object 12 --dx 20 --dy -10 -o salida.pdf
    intactpdf scale   documento.pdf --object 12 --factor 1.5 -o salida.pdf
    intactpdf edit    documento.pdf --object 3 --text "otra cosa" -o salida.pdf
    intactpdf check   salida.pdf                 valida la salida

Todas las operaciones de edición guardan de forma INCREMENTAL: el fichero de
salida empieza por los bytes del original. Si eso no se cumple, el comando falla.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

from .alinear_texto import alinear, chars_de_pagina
from .editar import borrar_objeto, escalar_objeto, mover_objeto
from .editar_texto import plan_editar_texto
from .fuentes import resolver_fuentes
from .guardar import ErrorGuardado, guardar_pagina_editada
from .objetos import Imagen, Sombreado, TextoRun, Vector, extraer_objetos

# Códigos de salida: distinguir "no se pudo" de "no se debe" importa en un
# programa que se puede usar desde un script.
EXITO = 0
ERROR = 1
RECHAZADO = 2


# ---------------------------------------------------------------------------
# Apertura
# ---------------------------------------------------------------------------

class Documento:
    def __init__(self, ruta: Path, num_pagina: int = 0):
        self.ruta = ruta
        self.num_pagina = num_pagina
        self.pdf = pikepdf.open(str(ruta))
        if self.pdf.is_encrypted:
            # Se comprueba AL ABRIR y no al guardar: es más barato decirlo antes
            # de que nadie trabaje, y en la ventana evita llegar a pintar una
            # vista previa que saldría en blanco.
            self.pdf.close()
            raise SystemExit(
                f"{ruta.name}: el documento está cifrado, así que no se puede "
                f"editar sin romperlo (el cifrado todavía no se conserva al "
                f"escribir). El original no se ha tocado.")
        if not (0 <= num_pagina < len(self.pdf.pages)):
            raise SystemExit(f"la página {num_pagina} no existe "
                             f"(el documento tiene {len(self.pdf.pages)})")
        pg = self.pdf.pages[num_pagina]
        c = pg.get("/Contents")
        if c is None:
            raise SystemExit(f"la página {num_pagina} no tiene contenido")
        if isinstance(c, pikepdf.Array):
            self.datos = b"\n".join(s.read_bytes() for s in c)
        else:
            self.datos = c.read_bytes()
        self.fuentes = resolver_fuentes(pg)
        self.contenido = extraer_objetos(self.datos, self.fuentes)

        doc = pdfium.PdfDocument(str(ruta))
        try:
            chars = chars_de_pagina(doc[num_pagina].get_textpage())
        finally:
            doc.close()
        self.informe_alineacion = alinear(self.contenido, chars)

    def cerrar(self):
        self.pdf.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.cerrar()

    def objeto(self, indice: int):
        n = len(self.contenido.objetos)
        if not (-n <= indice < n):
            raise SystemExit(f"el objeto {indice} no existe en esta página "
                             f"(hay {n} objetos, de 0 a {n - 1})")
        return self.contenido.objetos[indice]

    def paginas(self) -> int:
        return len(self.pdf.pages)


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------

def _texto_truncado(t: str, n: int = 46) -> str:
    t = t.replace("\n", " ").replace("\r", " ")
    return repr(t[:n] + ("…" if len(t) > n else ""))


def _caja(o) -> str:
    if o.caja is None:
        return "—"
    c = o.caja
    return f"({c.x0:6.1f},{c.y0:6.1f})-({c.x1:6.1f},{c.y1:6.1f})"


def _detalle(o) -> str:
    if isinstance(o, TextoRun):
        return _texto_truncado(o.texto)
    if isinstance(o, Imagen):
        return f"XObject {o.nombre_xobject}"
    if isinstance(o, Vector):
        return f"{o.n_segmentos} segmentos, '{o.operado}'"
    if isinstance(o, Sombreado):
        return f"sombreado {o.nombre}"
    return ""


def cmd_list(args) -> int:
    with Documento(Path(args.archivo), args.pagina) as d:
        objetos = d.contenido.objetos
        if args.tipo != "todos":
            objetos = [o for o in objetos if o.tipo == args.tipo]
        if args.json:
            print(json.dumps([
                {
                    "indice": i,
                    "tipo": o.tipo,
                    "caja": o.caja.como_tupla() if o.caja else None,
                    "texto": o.texto if isinstance(o, TextoRun) else None,
                    "fuente": o.fuente_nombre if isinstance(o, TextoRun) else None,
                    "editable": not o.razones_no_editable,
                    "bloqueos": o.razones_no_editable,
                    "avisos": o.avisos,
                }
                for i, o in enumerate(d.contenido.objetos)
                if o in objetos
            ], indent=2, ensure_ascii=False))
            return EXITO

        print(f"\n  {d.ruta.name} — página {args.pagina + 1} de {d.paginas()}")
        print(f"  {d.contenido.resumen()}")
        al = d.informe_alineacion
        extra = ""
        if al.get("chars_sin_posicion"):
            extra = f", {al['chars_sin_posicion']} sin posición"
        print(f"  texto alineado: {al['runs_alineados']}/{al['runs']} runs{extra}")
        print()
        print(f"  {'#':>4} {'tipo':10} {'caja':34} {'editar':>7}  detalle")
        print("  " + "─" * 96)
        for i, o in enumerate(d.contenido.objetos):
            if o not in objetos:
                continue
            razones = o.razones_no_editable
            avisos = o.avisos
            marca = "sí" if not razones else "no"
            print(f"  {i:>4} {o.tipo:10} {_caja(o):34} {marca:>7}  {_detalle(o)}")
            for r in razones:
                print(f"  {'':>4} {'':10} {'':34} {'':>7}  ✖ {r}")
            for a in avisos:
                print(f"  {'':>4} {'':10} {'':34} {'':>7}  · {a}")
        print()
        print("  Para operar sobre uno: --object N")
        print()
    return EXITO


def cmd_fonts(args) -> int:
    with Documento(Path(args.archivo), args.pagina) as d:
        usadas = {}
        for o in d.contenido.objetos:
            if isinstance(o, TextoRun) and o.fuente_nombre:
                usadas.setdefault(o.fuente_nombre, o)
        if not usadas:
            print("  esta página no usa ninguna fuente")
            return EXITO
        print(f"\n  Fuentes de la página {args.pagina + 1} de {d.ruta.name}")
        print()
        for nombre, run in sorted(usadas.items()):
            f = d.fuentes.get(nombre)
            if f is None:
                print(f"  /{nombre}: no resuelta")
                continue
            print(f"  /{nombre}  {f.base_font or '(sin BaseFont)'}")
            print(f"      tipo: {f.subtipo or '?'}"
                  f"{'  (Type0: 2 bytes por código)' if f.es_type0 else ''}")
            print(f"      incrustada: {'sí' if f.incrustada else 'no'}"
                  f"   subconjuntada: {'sí' if f.subconjuntada else 'no'}")
            print(f"      códigos con ToUnicode: {len(f.a_unicode)}"
                  f"   anchos: {len(f.anchos)}")
            letras = "".join(sorted(f.mapa_inverso()))
            print(f"      caracteres que ya se pueden usar: "
                  f"{_texto_truncado(letras, 70)}")
            print()
    return EXITO


def cmd_info(args) -> int:
    ruta = Path(args.archivo)
    datos = ruta.read_bytes()
    with Documento(ruta, 0) as d:
        if args.json:
            print(json.dumps({
                "archivo": str(ruta),
                "bytes": len(datos),
                "paginas": d.paginas(),
                "objetos_pagina_1": d.contenido.resumen(),
                "fuentes": {n: (f.base_font, f.incrustada, f.subconjuntada)
                            for n, f in d.fuentes.items()},
            }, indent=2, ensure_ascii=False))
            return EXITO

        print(f"\n  {ruta.name}")
        print(f"      {len(datos):,} bytes   {d.paginas()} página(s)")
        print(f"      objetos en la página 1: {d.contenido.resumen()}")
        print()
        print("      fuentes:")
        for n, f in sorted(d.fuentes.items()):
            marcas = []
            if f.incrustada:
                marcas.append("incrustada")
            if f.subconjuntada:
                marcas.append("subconjuntada")
            if not f.a_unicode:
                marcas.append("SIN ToUnicode")
            print(f"        /{n:10} {f.base_font or '?':28} "
                  f"{', '.join(marcas) or 'no incrustada'}")
        print()
        if b"%%EOF" in datos[-64:]:
            print("      marca %%EOF al final: sí")
        print()
    return EXITO


def _comando_gui() -> str | None:
    """El comando para instalar PyGObject y GTK 4 en esta distribución."""
    from . import dependencias
    return dependencias.comando(dependencias.detectar()["familia"])


def cmd_doctor(args) -> int:
    print("\n  Diagnóstico del entorno de IntactPDF\n")
    ok = True

    print(f"      python: {sys.version.split()[0]}  ({sys.executable})")
    for mod in ("pikepdf", "pypdfium2", "fontTools"):
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "?")
            print(f"      {mod:12} {v}")
        except Exception as e:
            ok = False
            print(f"      {mod:12} FALTA ({e})")

    ruta_qpdf = shutil.which("qpdf")
    print(f"      {'qpdf':12} {ruta_qpdf or 'FALTA (opcional, solo para check)'}")

    # La interfaz gráfica es opcional: el editor de consola funciona en un
    # servidor sin pantalla y sin GTK. Pero si no está, hay que decirlo con el
    # comando exacto de ESTA distribución, no con un «instala PyGObject».
    print()
    print("      interfaz gráfica (opcional, para la ventana)")
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
        print(f"      {'PyGObject':12} {getattr(gi, '__version__', '?')}")
        print(f"      {'GTK':12} "
              f"{Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}.{Gtk.MICRO_VERSION}")
        try:
            gi.require_version("Adw", "1")
            from gi.repository import Adw
            adw = (f"{Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}."
                   f"{Adw.MICRO_VERSION}")
            extra = "" if hasattr(Adw, "AlertDialog") else \
                "  (sin Adw.AlertDialog: es anterior a 1.5, se usa MessageDialog)"
            print(f"      {'libadwaita':12} {adw}{extra}")
        except Exception as e:
            ok = False
            print(f"      {'libadwaita':12} FALTA ({e})")
            print(f"        → {_comando_gui() or 'instala libadwaita con tu gestor de paquetes'}")
        print(f"        {sys.executable}")
        # Decía las versiones de GTK y no decía cómo abrir la ventana, que es lo
        # único que se viene a buscar aquí. El caso real: alguien instaló el
        # programa, ejecutó `doctor`, vio «interfaz gráfica ... GTK 4.22.4» y
        # siguió sin saber que tenía una ventana puesta.
        print()
        print("        → para abrir la ventana:  intactpdf-gui")
        print("          (o la entrada «IntactPDF» del menú de aplicaciones)")
    except Exception as e:
        from . import dependencias
        d = dependencias.detectar()
        print(f"      PyGObject    FALTA ({type(e).__name__})")
        print(f"        sistema detectado: {d['nombre']}")
        cmd = dependencias.comando(d["familia"])
        if cmd:
            print(f"        → para la ventana: {cmd}")
        else:
            print("        → para la ventana: instala PyGObject y GTK 4 con el")
            print("          gestor de paquetes de tu distribución, o usa el")
            print("          Flatpak, que ya los trae dentro.")
        if d["familia"]:
            print("        (el editor de consola no los necesita)")

    try:
        from .sustitucion_fuente import _directorios, fuentes_disponibles
        dirs = _directorios()
        fuentes = fuentes_disponibles()
        print(f"\n      fuentes: {len(fuentes)} en {len(dirs)} directorio(s)")
        for x in dirs:
            print(f"        {x}")
        dejavu = [f for f in fuentes if "dejavu" in f.name.lower()]
        print(f"      DejaVu (la que usa el corpus): {len(dejavu)} fichero(s)")
        if not dejavu:
            print("        AVISO: sin DejaVu, el nivel 2 de la edición de texto")
            print("        rechazará la mayoría de ediciones. Instala")
            print("        fonts-dejavu-core (Debian/Ubuntu),")
            print("        dejavu-sans-fonts (Fedora/RHEL) o ttf-dejavu (Arch).")
            ok = False
    except Exception as e:
        ok = False
        print(f"      fuentes: ERROR {e}")

    print()
    print(f"      resultado: {'todo listo' if ok else 'hay avisos'}")
    print()
    return EXITO if ok else ERROR


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------

def _destino(args, origen: Path) -> tuple[Path, bool]:
    """Devuelve (ruta de salida, si hay que hacer copia de seguridad).

    Nunca se sobrescribe el original sin pedirlo explícitamente, y cuando se
    pide se deja un .bak. Un editor de PDF que machaca el original sin avisar es
    una mala herramienta.
    """
    if args.salida:
        return Path(args.salida), False
    if not args.in_place:
        raise SystemExit(
            "hay que indicar dónde guardar con -o/--salida, o usar --in-place "
            "para sobrescribir el original (se dejará un .bak)")
    return origen, True


def _guardar(origen: Path, destino: Path, datos: bytes, objetos: dict,
             contenido_original: bytes) -> int:
    """Escribe y verifica la propiedad que define al proyecto."""
    backup = destino.with_suffix(destino.suffix + ".bak")
    if destino == origen:
        shutil.copy2(origen, backup)
    info = guardar_pagina_editada(origen, destino, 0, [datos], objetos)
    if not info.prefijo_intacto:
        print("  ERROR: el fichero guardado NO empieza por el original.", file=sys.stderr)
        print("  El guardado incremental no se ha podido verificar; no se puede", file=sys.stderr)
        print("  garantizar que no haya cambiado nada más.", file=sys.stderr)
        return ERROR
    print(f"  guardado: {destino}")
    print(f"      {info.bytes_original:,} -> {info.bytes_salida:,} bytes "
          f"(+{info.bytes_anadidos:,}, "
          f"{100.0 * info.bytes_anadidos / info.bytes_original:.2f} %)")
    print(f"      objetos escritos: {info.objetos_redefinidos}")
    print(f"      el fichero empieza por el original: sí")
    if destino == origen:
        print(f"      copia de seguridad: {backup}")
    return EXITO


def _cabecera(args, d: Documento, o) -> None:
    print(f"\n  {d.ruta.name} — página {args.pagina + 1}")
    print(f"      objeto {args.objeto}: {o.tipo}  {_caja(o)}  {_detalle(o)}")


def cmd_delete(args) -> int:
    origen = Path(args.archivo)
    destino, _ = _destino(args, origen)
    with Documento(origen, args.pagina) as d:
        o = d.objeto(args.objeto)
        _cabecera(args, d, o)
        for a in o.avisos:
            print(f"      aviso: {a}")
        if o.razones_no_editable and not args.forzar:
            print("      este objeto tiene bloqueos:")
            for r in o.razones_no_editable:
                print(f"        ✖ {r}")
            print("      borrar suele ser seguro igualmente; usa --forzar "
                  "para continuar")
            return RECHAZADO
        nuevos = borrar_objeto(d.datos, d.contenido, o,
                               incluir_preludio=not args.sin_preludio)
        extras = {}
        if args.dry_run:
            print("      --dry-run: no se escribe nada")
            return EXITO
        return _guardar(origen, destino, nuevos, extras, d.datos)


def cmd_move(args) -> int:
    origen = Path(args.archivo)
    destino, _ = _destino(args, origen)
    with Documento(origen, args.pagina) as d:
        o = d.objeto(args.objeto)
        _cabecera(args, d, o)
        antes = o.caja
        nuevos = mover_objeto(d.datos, d.contenido, o, args.dx, args.dy)
        if antes is not None:
            print(f"      caja: {antes.como_tupla()} -> "
                  f"({antes.x0 + args.dx:.1f}, {antes.y0 + args.dy:.1f}, "
                  f"{antes.x1 + args.dx:.1f}, {antes.y1 + args.dy:.1f})")
        if args.dry_run:
            print("      --dry-run: no se escribe nada")
            return EXITO
        return _guardar(origen, destino, nuevos, {}, d.datos)


def cmd_scale(args) -> int:
    origen = Path(args.archivo)
    destino, _ = _destino(args, origen)
    fx = args.fx if args.fx is not None else args.factor
    fy = args.fy if args.fy is not None else args.factor
    if fx is None or fy is None:
        raise SystemExit("indica --factor, o bien --fx y --fy")
    with Documento(origen, args.pagina) as d:
        o = d.objeto(args.objeto)
        _cabecera(args, d, o)
        if o.caja is None:
            raise SystemExit("el objeto no tiene caja: no se puede escalar")
        centro = o.caja.centro
        nuevos = escalar_objeto(d.datos, d.contenido, o, fx, fy, centro)
        print(f"      escala x{fx:g} ×{fy:g} alrededor de "
              f"({centro[0]:.1f}, {centro[1]:.1f})")
        print(f"      caja: {o.caja.como_tupla()} -> "
              f"({centro[0] + (o.caja.x0 - centro[0]) * fx:.1f}, "
              f"{centro[1] + (o.caja.y0 - centro[1]) * fy:.1f}, "
              f"{centro[0] + (o.caja.x1 - centro[0]) * fx:.1f}, "
              f"{centro[1] + (o.caja.y1 - centro[1]) * fy:.1f})")
        if args.dry_run:
            print("      --dry-run: no se escribe nada")
            return EXITO
        return _guardar(origen, destino, nuevos, {}, d.datos)


def cmd_edit(args) -> int:
    origen = Path(args.archivo)
    destino, _ = _destino(args, origen)
    with Documento(origen, args.pagina) as d:
        o = d.objeto(args.objeto)
        _cabecera(args, d, o)
        if not isinstance(o, TextoRun):
            raise SystemExit(f"el objeto {args.objeto} es un {o.tipo}, no texto")

        plan = plan_editar_texto(d.datos, origen, args.pagina, d.contenido, o,
                                 args.texto,
                                 ajustar_espaciado=args.ajustar,
                                 permitir_fuente_nueva=not args.sin_fuente_nueva)
        inf = plan.informe

        print(f"      texto actual : {_texto_truncado(o.texto, 60)}")
        print(f"      texto nuevo  : {_texto_truncado(args.texto, 60)}")
        print()
        if not inf.ok:
            print(f"      NO SE PUEDE EDITAR (nivel {inf.nivel})", file=sys.stderr)
            print(f"      {inf.motivo}", file=sys.stderr)
            print()
            return RECHAZADO

        print(f"      nivel {inf.nivel}: {inf.motivo}")
        print(f"      ancho: {inf.ancho_original:.0f} -> {inf.ancho_nuevo:.0f} "
              f"milésimas de em ({inf.delta_en_puntos:+.2f} pt)")
        if inf.fuente_nueva:
            print(f"      fuente nueva: {inf.fuente_nueva}")
        if inf.espaciado_aplicado is not None:
            print(f"      ajuste de espaciado aplicado: Tc "
                  f"{inf.espaciado_aplicado:+.3f}")
        if inf.desborde:
            print()
            print("      AVISO: el texto nuevo es más ancho que el original.")
            print(f"      Desborda {inf.delta_en_puntos:+.1f} pt. Nada se "
                  f"recoloca automáticamente, pero puede solaparse con lo de "
                  f"al lado.")
            print("      Opciones: --ajustar (comprime el espaciado) o acortar "
                  "el texto.")

        if args.dry_run:
            print("\n      --dry-run: no se escribe nada")
            return EXITO
        return _guardar(origen, destino, plan.contenido, plan.objetos, d.datos)


def cmd_check(args) -> int:
    ruta = Path(args.archivo)
    datos = ruta.read_bytes()
    print(f"\n  {ruta.name}  ({len(datos):,} bytes)")

    # Validación. Hay dos caminos y los dos acaban en el mismo motor, libqpdf:
    #
    #   - el binario `qpdf`, si está, que es lo que usa el test de aceptación;
    #   - y si no está, pikepdf, que LLEVA libqpdf dentro. Esto importa porque
    #     dentro de un Flatpak el binario no existe (el runtime no lo trae) y
    #     antes el programa se limitaba a decir «no se puede validar», que es
    #     justo lo que no se quiere oír al comprobar un fichero.
    #
    # Por qué no se usa `pikepdf.Job(['check'])`: en pikepdf 10 la clase Job
    # modela la CLI de qpdf y exige fichero de salida, así que no sirve para
    # preguntar «¿está bien esto?». Se abre con pikepdf, que es donde libqpdf
    # parsea el xref y los objetos y donde protesta si algo está mal.
    qpdf = shutil.which("qpdf")
    if qpdf:
        r = subprocess.run([qpdf, "--check", str(ruta)],
                           capture_output=True, text=True)
        estado = "sin errores" if r.returncode == 0 else "CON ERRORES"
        print(f"      qpdf --check: {estado}")
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            return ERROR
    else:
        try:
            with pikepdf.open(ruta) as pdf:
                n = len(pdf.pages)
                reconstruido = bool(getattr(pdf, "is_reconstructed", False))
            print(f"      libqpdf (vía pikepdf): abre sin errores, "
                  f"{n} página(s)")
            if reconstruido:
                print("      AVISO: libqpdf tuvo que reconstruir el xref, la "
                      "tabla del fichero no estaba bien")
        except Exception as e:
            print(f"      libqpdf (vía pikepdf) NO puede abrirlo: "
                  f"{type(e).__name__}: {e}")
            return ERROR

    incremental = False
    pos = datos.find(b"/Prev")
    if pos > 0:
        incremental = True
    print(f"      actualización incremental: {'sí' if incremental else 'no'}")
    if incremental:
        print("      (lleva un /Prev: se construyó añadiendo al final)")
    try:
        doc = pdfium.PdfDocument(str(ruta))
        print(f"      páginas legibles: {len(doc)}")
        tp = doc[0].get_textpage()
        print(f"      caracteres en la página 1: {tp.count_chars()}")
        doc.close()
    except Exception as e:
        print(f"      NO se puede abrir con pdfium: {e}")
        return ERROR
    print()
    return EXITO


def cmd_compact(args) -> int:
    from .guardar import compactar_pdf
    ruta = Path(args.archivo)
    if not ruta.exists():
        print(f"error: {ruta} no existe")
        return ERROR
    salida = Path(args.salida) if args.salida else ruta.with_name(ruta.stem + "-compactado.pdf")
    try:
        res = compactar_pdf(ruta, salida)
    except Exception as e:
        print(f"error al compactar {ruta}: {e}")
        return ERROR
    print(f"\n  Compactación y purga completada: {salida}")
    print(f"      original:    {res.bytes_original:,} bytes")
    print(f"      compactado:  {res.bytes_salida:,} bytes")
    pct = (res.bytes_ahorrados / res.bytes_original * 100) if res.bytes_original else 0
    print(f"      ahorro:      {res.bytes_ahorrados:,} bytes ({pct:.1f} %)")
    print(f"      páginas:     {res.paginas}")
    print("      historial de revisiones previas purgado (redacción segura)\n")
    return EXITO


def cmd_decrypt(args) -> int:
    from .guardar import descifrar_pdf
    ruta = Path(args.archivo)
    if not ruta.exists():
        print(f"error: {ruta} no existe")
        return ERROR
    salida = Path(args.salida) if args.salida else ruta.with_name(ruta.stem + "-descifrado.pdf")
    try:
        descifrar_pdf(ruta, salida, password=args.password or "")
        print(f"\n  Documento descifrado correctamente: {salida}")
        print("  Ya puede editarse con intactpdf o intactpdf-gui sin restricciones de cifrado.\n")
        return EXITO
    except Exception as e:
        print(f"\n  error al descifrar {ruta.name}: {e}")
        if not args.password:
            print("  (si requiere contraseña, pásala con -p / --password)\n")
        return ERROR


def cmd_rotate(args) -> int:
    from .guardar import rotar_pagina
    ruta = Path(args.archivo)
    if not ruta.exists():
        print(f"error: {ruta} no existe")
        return ERROR
    salida = ruta if args.in_place else (Path(args.salida) if args.salida else ruta.with_name(ruta.stem + "-rotado.pdf"))
    try:
        inf = rotar_pagina(ruta, salida, args.pagina, args.angulo, crear_backup=args.in_place)
        print(f"\n  Página {args.pagina + 1} rotada {args.angulo}° en {salida.name}")
        print(f"  {inf.bytes_anadidos:,} bytes añadidos de forma incremental (prefijo intacto: {inf.prefijo_intacto})\n")
        return EXITO
    except Exception as e:
        print(f"\n  error al rotar {ruta.name}: {e}\n")
        return ERROR


def cmd_extract_image(args) -> int:
    from .guardar import extraer_imagen
    ruta = Path(args.archivo)
    if not ruta.exists():
        print(f"error: {ruta} no existe")
        return ERROR
    salida = Path(args.salida) if args.salida else Path(f"{args.xobject.lstrip('/')}.png")
    try:
        extraer_imagen(ruta, args.pagina, args.xobject, salida)
        print(f"\n  Imagen {args.xobject} extraída a {salida}\n")
        return EXITO
    except Exception as e:
        print(f"\n  error al extraer imagen: {e}\n")
        return ERROR


def cmd_replace_image(args) -> int:
    from .guardar import reemplazar_imagen
    ruta = Path(args.archivo)
    if not ruta.exists():
        print(f"error: {ruta} no existe")
        return ERROR
    img = Path(args.imagen)
    if not img.exists():
        print(f"error: la imagen {img} no existe")
        return ERROR
    salida = ruta if args.in_place else (Path(args.salida) if args.salida else ruta.with_name(ruta.stem + "-editado.pdf"))
    try:
        inf = reemplazar_imagen(ruta, salida, args.pagina, args.xobject, img, crear_backup=args.in_place)
        print(f"\n  Imagen {args.xobject} reemplazada con {img.name} en {salida.name}")
        print(f"  {inf.bytes_anadidos:,} bytes añadidos de forma incremental (prefijo intacto: {inf.prefijo_intacto})\n")
        return EXITO
    except Exception as e:
        print(f"\n  error al reemplazar imagen: {e}\n")
        return ERROR



# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="intactpdf",
        description="IntactPDF — editar un PDF sin reconstruirlo",
        epilog="La VENTANA (con cinta de opciones, para trabajar con el ratón) se "
               "abre con «intactpdf-gui», o desde la entrada «IntactPDF» del menú "
               "de aplicaciones.\n\n"
               "Lo de aquí es lo mismo sin ventana: para guiones, servidores y "
               "quien prefiera la línea de órdenes.\n\n"
               "Todas las ediciones se guardan de forma incremental: el fichero "
               "de salida empieza por los bytes del original.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="orden", required=True)

    p = sub.add_parser("doctor", help="diagnóstico del entorno")
    p.set_defaults(func=cmd_doctor)

    for nombre, fn, ayuda in (("info", cmd_info, "resumen del documento"),
                              ("check", cmd_check, "valida un PDF de salida")):
        p = sub.add_parser(nombre, help=ayuda)
        p.add_argument("archivo")
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=fn)

    p = sub.add_parser("compact", help="eliminar historial previo y compactar (redacción segura)")
    p.add_argument("archivo")
    p.add_argument("-o", "--salida", help="fichero de salida")
    p.set_defaults(func=cmd_compact)

    p = sub.add_parser("decrypt", help="descifrar un PDF para permitir su edición")
    p.add_argument("archivo")
    p.add_argument("-p", "--password", default="", help="contraseña del PDF (si la tiene)")
    p.add_argument("-o", "--salida", help="fichero de salida")
    p.set_defaults(func=cmd_decrypt)

    p = sub.add_parser("rotate", help="rotar una página (90, 180, 270 grados)")
    p.add_argument("archivo")
    p.add_argument("--angulo", type=int, choices=[90, 180, 270], default=90, help="grados de rotación")
    p.add_argument("--pagina", type=int, default=0, help="0 = primera página")
    p.add_argument("-o", "--salida", help="fichero de salida")
    p.add_argument("--in-place", action="store_true", help="sobrescribir el original con backup .pdf~")
    p.set_defaults(func=cmd_rotate)

    p = sub.add_parser("extract-image", help="extraer una imagen a fichero PNG o JPEG")
    p.add_argument("archivo")
    p.add_argument("--xobject", required=True, help="nombre del XObject (/Im1 o Im1)")
    p.add_argument("--pagina", type=int, default=0, help="0 = primera página")
    p.add_argument("-o", "--salida", help="ruta del archivo de imagen de salida (.png o .jpg)")
    p.set_defaults(func=cmd_extract_image)

    p = sub.add_parser("replace-image", help="reemplazar una imagen por otra conservando posición")
    p.add_argument("archivo")
    p.add_argument("--xobject", required=True, help="nombre del XObject a sustituir (/Im1 o Im1)")
    p.add_argument("--imagen", required=True, help="ruta a la nueva imagen (PNG/JPG)")
    p.add_argument("--pagina", type=int, default=0, help="0 = primera página")
    p.add_argument("-o", "--salida", help="fichero de salida")
    p.add_argument("--in-place", action="store_true", help="sobrescribir el original con backup .pdf~")
    p.set_defaults(func=cmd_replace_image)

    p = sub.add_parser("list", help="objetos de una página, con índice")
    p.add_argument("archivo")
    p.add_argument("--pagina", type=int, default=0, help="0 = primera (por omisión)")
    p.add_argument("--tipo", choices=["todos", "texto", "imagen", "vector",
                                      "sombreado"], default="todos")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("fonts", help="fuentes de una página y qué admiten")
    p.add_argument("archivo")
    p.add_argument("--pagina", type=int, default=0)
    p.set_defaults(func=cmd_fonts)

    def comunes(p, con_objeto=True):
        p.add_argument("archivo")
        if con_objeto:
            p.add_argument("--object", dest="objeto", type=int, required=True,
                           help="índice del objeto tal como lo da `list`")
        p.add_argument("--pagina", type=int, default=0)
        p.add_argument("-o", "--salida", help="fichero de salida")
        p.add_argument("--in-place", action="store_true",
                       help="sobrescribir el original (deja un .bak)")
        p.add_argument("--dry-run", action="store_true",
                       help="decir qué se haría sin escribir nada")

    p = sub.add_parser("delete", help="borrar un objeto")
    comunes(p)
    p.add_argument("--sin-preludio", action="store_true",
                   help="no borrar los operadores de estado que lo preparan")
    p.add_argument("--forzar", action="store_true",
                   help="borrar aunque esté marcado como no editable")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("move", help="mover un objeto")
    comunes(p)
    p.add_argument("--dx", type=float, required=True)
    p.add_argument("--dy", type=float, required=True)
    p.set_defaults(func=cmd_move)

    p = sub.add_parser("scale", help="redimensionar un objeto")
    comunes(p)
    p.add_argument("--factor", type=float, help="escala uniforme")
    p.add_argument("--fx", type=float, help="escala horizontal")
    p.add_argument("--fy", type=float, help="escala vertical")
    p.set_defaults(func=cmd_scale)

    p = sub.add_parser("edit", help="cambiar el texto de un run")
    comunes(p)
    p.add_argument("--texto", required=True, help="el texto nuevo")
    p.add_argument("--ajustar", action="store_true",
                   help="comprimir el espaciado para conservar el ancho")
    p.add_argument("--sin-fuente-nueva", action="store_true",
                   help="fallar en vez de incrustar un subconjunto del sistema")
    p.set_defaults(func=cmd_edit)

    return ap


def main(argv=None) -> int:
    ap = construir_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        # Sin argumentos, argparse escupe «the following arguments are required:
        # orden», que no ayuda a nadie. Y el caso real que lo motivó: alguien
        # instaló el programa, abrió la consola, y no sabía que tenía una ventana
        # puesta, con su entrada en el menú de aplicaciones. Aquí se dice lo de la
        # ventana primero y lo de la consola después.
        print("\n  IntactPDF tiene dos formas de usarse, y esta es la de consola.\n")
        print("    Para la VENTANA (con cinta de opciones, para el ratón):\n")
        print("        intactpdf-gui                  (o la entrada «IntactPDF» del")
        print("                                        menú de aplicaciones)\n")
        print("    Aquí, en la consola:\n")
        print("        intactpdf doctor               ¿está todo listo?")
        print("        intactpdf info documento.pdf   qué hay dentro")
        print("        intactpdf list documento.pdf   objetos de la página")
        print("        intactpdf --help               todo lo que sabe hacer\n")
        print("    Las dos hacen lo mismo: borrar objetos, moverlos,")
        print("    redimensionarlos y cambiar el texto, guardando de forma")
        print("    incremental para que lo que no toques quede intacto.\n")
        return EXITO
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as e:
        # `SystemExit` con texto es la forma corta de decir «esto no se puede
        # hacer, y este es el motivo»: Python sólo lo imprime si nadie lo
        # captura, y aquí se captura, así que se imprime a mano. Antes esta
        # línea hacía `int(e.code)`, que con un texto revienta con un ValueError
        # encima del mensaje bueno.
        if isinstance(e.code, str):
            print(f"\n  {e.code}\n", file=sys.stderr)
            return ERROR
        return int(e.code or 0)
    except ErrorGuardado as e:
        # Un fallo al guardar es lo más importante que puede decir este
        # programa: no se ha escrito nada y hay que explicar por qué, sin
        # volcar una traza de Python encima de quien lo está leyendo.
        print(f"\n  NO se ha guardado: {e}\n", file=sys.stderr)
        return ERROR
    except FileNotFoundError as e:
        print(f"  no existe el fichero: {e.filename}", file=sys.stderr)
        return ERROR
    except (ValueError, KeyError) as e:
        print(f"  error: {type(e).__name__}: {e}", file=sys.stderr)
        return ERROR
    except BrokenPipeError:
        return EXITO


if __name__ == "__main__":
    sys.exit(main())
