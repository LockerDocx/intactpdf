# Cómo se distribuye IntactPDF

## Resumen en una tabla

Lo primero: **`./instalar.sh`**. Detecta la distribución, elige la vía y lo
deja puesto. Las vías que conoce:

| vía | quién la usa | trae la ventana | necesita root | glibc mínima | estado |
|---|---|---|---|---|---|
| **Flatpak** | todo el mundo | sí | no | la del runtime; el anfitrión da igual | **construido y probado, ventana incluida** |
| **pipx** | quien ya tiene Python y GTK | sí | solo si falta GTK | 2.28 | **probado, ventana incluida** |
| **AppImage** | quien no quiera instalar nada | **no**, solo consola | no | **2.28** (la impone pikepdf) | **construido y probado** |

El instalador elige así, en este orden:

1. si el Flatpak ya está instalado → Flatpak;
2. si hay pipx y el sistema ya tiene GTK 4 → pipx;
3. si el sistema ya tiene GTK 4 → pip (o pipx, si se puede instalar);
4. si la distribución tiene receta de paquetes → instala GTK + pipx y sigue;
5. si no hay receta (void, nixos) → AppImage, que no necesita nada.

La última vía es la respuesta honesta cuando no se sabe el nombre de los
paquetes: mejor algo que funciona seguro, aunque sea sin ventana, que un comando
inventado. Y se dice en voz alta que esa vía no trae la ventana.

## ¿Funciona en openSUSE? Sí, por las tres vías

La pregunta corta se contesta con dos números: **openSUSE Leap 15.6 lleva glibc
2.38** y **Tumbleweed subió a glibc 2.44** en el instantánea de septiembre de
2026. El suelo que impone este programa es **2.28**. Los dos están muy por
encima, así que no hay nada que hacer: funciona.

En openSUSE, el instalador hace esto y no hay que decidir nada:

```bash
./instalar.sh          # o: ./instalar.sh --metodo=flatpak
```

Con el sistema recién instalado, sin Flatpak y sin GTK, la traza es esta:

```
  Vía elegida: deps  (falta la pila de GTK y esta distribución tiene receta)
  → para la ventana hacen falta: python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1
    ✓ simulado: sudo zypper install -y python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1
  Vía elegida: pipx  (ya está la pila de GTK)
    ✓ intactpdf y intactpdf-gui instalados con pipx
    ✓ la ventana puede abrirse: GTK 4.14, libadwaita 1.4, PyGObject 3.44
```

El desglose, vía por vía:

| vía | en openSUSE Leap 15.6 | en Tumbleweed | por qué |
|---|---|---|---|
| **Flatpak** | funciona | funciona | el anfitrión da igual: todo lo que usa el programa está dentro del runtime |
| **AppImage** | funciona | funciona | trae su propio Python 3.14 y sus bibliotecas; solo pide glibc ≥ 2.28 y hay 2.38. **Solo consola** |
| **pipx** | funciona | funciona | wheels `manylinux_2_28_<arch>`; el paquete se instala desde el código y GTK lo pone `zypper`. Hay que instalar `python3-pipx` |
| la ventana (GTK4 + libadwaita) | funciona | funciona | `zypper install python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1` |

**En Leap 15.6 (GNOME 45, libadwaita 1.4) la ventana funciona gracias a
`gui/dialogos.py`**: sin el apaño del `AlertDialog`, esa es la distribución donde
la ventana se caía al primer doble clic. Está explicado arriba.

**Y la versión de Python de la distribución da igual.** Es la parte que suele
preocupar y no debería: el Flatpak lleva su propio intérprete (3.14.7, dentro
del runtime `org.gnome.Platform//51`) y el AppImage también (3.14.8 portátil).
El Python de Leap 15.6 (3.11) o el de Tumbleweed no se usan para nada. Solo
importan en la vía `pipx`, y ahí basta con que sea 3.9 o superior.

Las arquitecturas también están cubiertas: Leap 15.6 tiene glibc 2.38 en
x86_64, aarch64, ppc64le y s390x, y los wheels de `pikepdf` y `pypdfium2` se
publican para las tres primeras. Flatpak va sobretodo en x86_64 y aarch64.

Lo único que no funciona en openSUSE es lo que no funciona en ninguna parte:
glibc por debajo de 2.28 (CentOS 7, Debian 9) y, ahí, solo si se usa la vía
`pip`/AppImage — el Flatpak sigue valiendo.

## Lo que se preguntó primero: ¿se puede a nivel de kernel?

No, y conviene que quede escrito para no volver a darle vueltas.

Un editor de PDF vive en el espacio de usuario. Lo que necesita es: leer y
escribir ficheros, una pila de tipografías con FreeType, un motor que rasterice
páginas (pdfium), y ventanas. El kernel no ofrece nada de eso; ofrece
`read()`/`write()` y poco más que sirva aquí. Meter esto en un módulo del kernel
daría un módulo que:

- no puede llamar a FreeType ni a pdfium sin sacarlos también al kernel, que es
  un sinsentido de tamaño y de seguridad;
- habría que compilar **una vez por distribución y por versión de kernel**, o
  sea exactamente lo contrario de «que funcione en cualquier distribución»;
- y para colmo necesitaría privilegios de root para instalarse.

Lo que la gente llama «problemas de distribución» casi nunca son del kernel: son
de bibliotecas y de versiones de libc. Y eso se resuelve empaquetando.

## La restricción real, medida

No la pone el núcleo del programa (`nucleo/` es solo biblioteca estándar de
Python: ni una dependencia externa, y eso es una decisión de diseño para que el
empaquetado no se complique). La ponen las tres dependencias:

| wheel | etiqueta | glibc mínima | cubre |
|---|---|---|---|
| `pypdfium2` | `manylinux_2_17` | 2.17 | CentOS 7 (2014) en adelante |
| `fontTools` | `manylinux_2_17` | 2.17 | idem |
| **`pikepdf`** | **`manylinux_2_28`** | **2.28** | RHEL/Rocky 8+, Debian 10+, Ubuntu 20.04+ |

Los wheels son **autocontenidos**: `pikepdf` trae dentro su propia
`libqpdf-*.so` y su `libjpeg-*.so`, y `pypdfium2` trae `libpdfium.so` (7,8 MB).
De todo el sistema solo piden `libc`, `libstdc++`, `libz`, `libgcc_s`, `libm` y
`libpthread`. Por eso el AppImage de 61 MB funciona sin instalar nada.

Se descartó la idea de «un binario único que corra en glibc 2.17»: habría que
construirlo dentro de un contenedor con glibc 2.28 de todas formas (porque
`pikepdf` no baja de ahí), así que no ganaría nada sobre el AppImage y añadiría
un contenedor de construcción al proyecto.

## Flatpak: la vía principal

El motivo para elegirla es que **el sandbox cambia el problema de sitio**. Dentro
de un Flatpak, el programa ve el runtime (`org.gnome.Platform//51`), no las
bibliotecas del anfitrión. Da igual que el usuario tenga Alpine, Arch o RHEL 7:
lo que hay dentro está fijado. Es la única vía que cumple «da igual la
distribución» de verdad.

### Los dos ficheros

- `packaging/io.github.lockerdocx.IntactPDF.json` — el manifiesto.
- `packaging/python3-deps.json` — los wheels, con URL y sha256. Se genera con
  `python3 packaging/generar_deps_pip.py`; no se escribe a mano porque un
  manifiesto de Flatpak **no puede descargar nada durante la construcción**, y
  nueve hashes copiados a mano son nueve oportunidades de equivocarse sin
  enterarse hasta que el build falla en Flathub.

### Construirlo

```bash
flatpak --user remote-add --if-not-exists flathub \
    https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak --user install flathub org.gnome.Sdk//51 org.gnome.Platform//51
cd intactpdf
flatpak-builder --user --install --force-clean build-dir packaging/io.github.lockerdocx.IntactPDF.json
flatpak run io.github.lockerdocx.IntactPDF                                # la ventana
flatpak run --command=intactpdf io.github.lockerdocx.IntactPDF doctor      # la consola
```

### Dos trampas que ya están resueltas en el manifiesto

**1. El runtime usa Python 3.14, no 3.12 ni 3.13.** `org.gnome.Platform//51` va
sobre Freedesktop SDK 26.08 e incluye Python 3.14. Un manifiesto con wheels
`cp313` no llega ni a instalar; y el error que da pip en ese caso («no matching
distribution») no dice nada de la versión de Python del runtime, que es la causa
real. `generar_deps_pip.py` pide las `cp314`.

**2. El sandbox no ve `/usr/share/fonts` del anfitrión.** Esto es importante
porque la edición de texto **nivel 2** (escribir un carácter que no está en el
subconjunto de la fuente incrustada) resuelve el problema incrustando un
subconjunto de la tipografía **del sistema**. Sin fuentes dentro del paquete, esa
operación fallaría en Flatpak y funcionaría fuera de él: un programa que se
comporta distinto según cómo se instaló es un programa que nadie puede depurar.

Por eso el manifiesto instala DejaVu en `/app/share/fonts`, que es el directorio
estándar y llega al código por `XDG_DATA_DIRS` (Flatpak ya mete `/app/share`
ahí), sin nada especial en el código. Licencia: Bitstream Vera, permisiva, se
puede redistribuir; el texto va en `fuentes/LICENSE.DejaVu`.

### Permisos

El manifiesto **no pide el directorio personal**. Pide esto y nada más:

```
--socket=fallback-x11 --socket=wayland --share=ipc --device=dri
--filesystem=xdg-run/gvfsd      # para que el portal de ficheros funcione
```

El acceso a los ficheros lo concede el **portal** (`Gtk.FileDialog`), que da
permiso al documento concreto que el usuario elige en el diálogo y solo a ese.
Es lo que un editor de PDF necesita: no ver el resto del disco para trabajar, y
es también el permiso por el que un revisor de Flathub mira mal un paquete.

Lo medido a mano, que es lo que hace que esto esté escrito así:

- Pedir `home:ro` **y además** `xdg-documents` **NO deja escribir en
  Documentos**: el permiso de solo lectura sobre el directorio padre anula el
  específico, y guardar fallaba con «Read-only file system» con el manifiesto
  puesto así. Por eso no hay una versión «estrecha» a base de carpetas sueltas.
- Con el portal no hace falta nada de eso, pero **el portal solo existe en un
  escritorio con sesión gráfica**. En un servidor, en un contenedor o en una
  sesión mínima no hay `org.freedesktop.portal.Desktop`, y entonces:

```bash
# Para usar la consola del Flatpak sobre ficheros del anfitrión:
flatpak override --user --filesystem=home io.github.lockerdocx.IntactPDF
# o, con un portal presente, sin dar permiso permanente:
flatpak run --command=intactpdf --file-forwarding io.github.lockerdocx.IntactPDF @@ /ruta/x.pdf @@ list
```

Sin nada de eso, la consola dentro del Flatpak contesta «no existe el fichero»,
que es exactamente lo que pasa: el fichero existe, pero fuera del sandbox.

Comprobado en el entorno de pruebas, que **no tiene portal**: quitando el
permiso `home`, la consola del Flatpak deja de ver los ficheros (error claro) y
`--file-forwarding` responde «Can't get document portal mount path». La ventana,
en cambio, arranca y dibuja igual, porque para dibujar un PDF que ya tiene
abierto no necesita el portal. Lo que no se ha podido probar aquí es el diálogo
de ficheros de verdad, porque no hay portal que lo sirva.

### Publicar en Flathub

Antes de enviar nada hay que cerrar tres cosas:

1. ~~**El identificador.**~~ Hecho: `io.github.lockerdocx.IntactPDF`, bajo el
   usuario de GitHub que envía el paquete, que es lo que exige Flathub.
2. ~~**La URL.**~~ Hecha: el `metainfo.xml`, el `pyproject.toml` y la ventana
   apuntan a `https://github.com/LockerDocx/intactpdf`. Flathub rechaza los
   marcadores tipo `example.invalid`, y ya no queda ninguno en lo que se
   empaqueta.
3. **Capturas de pantalla** en el `metainfo.xml`. Las imágenes ya están hechas
   (`docs/capturas/`, diez, generadas con `tools/capturas_gui.py`), pero
   AppStream no acepta ficheros locales: hay que servirlas desde una URL, y esa
   URL sale del punto 2.

Y al publicar, una línea: `PUBLICADO_EN_FLATHUB=0` → `1` en `instalar.sh`. Con
eso, el instalador deja de intentar construir el Flatpak desde el código (cuando
no hay manifiesto al lado) y ofrece bajarlo de Flathub.

## La ventana (GTK4 + libadwaita)

El paquete trae **dos comandos**, declarados los dos en `pyproject.toml`:

| comando | qué es |
|---|---|
| `intactpdf-gui` | la ventana. Es lo que abre el icono del menú |
| `intactpdf` | la consola, para guiones y servidores |

Se separan a propósito: `intactpdf` tiene que funcionar en un servidor sin
pantalla y sin GTK instalado, y arrancar la ventana desde ahí fallaría.

**Dentro del Flatpak no hay que añadir nada de GTK.** El runtime
`org.gnome.Platform//51` ya trae PyGObject 3.58.0, GTK 4.24.0 y libadwaita
1.10.0 — comprobado ejecutando el intérprete del runtime, no leyendo la
documentación. Las dependencias de `python3-deps.json` son solo las del núcleo
(pikepdf, pypdfium2, fontTools y sus compañeras); GTK no se empaqueta.

Fuera del Flatpak, PyGObject **no se instala con pip**: va atado a las
bibliotecas de GTK del sistema y se instala con el gestor de paquetes de la
distribución. Por eso hay un extra `.[gui]` que lo declara y el README dice los
nombres de los paquetes en Debian, Fedora y openSUSE.

### La cinta de opciones

La ventana lleva una cinta como la de Word: cinco pestañas (Inicio, Objeto,
Texto, Página, Ver), grupos con su nombre debajo, y **lo que no aplica apagado en
vez de escondido**. Es mucho para los tres botones que había antes, y el motivo
de hacerlo así es que un editor de imágenes y vectores se maneja con el ratón:
una barra de iconos obliga a pasar el ratón por encima para saber qué hace cada
uno.

Dos reglas que se comprueban con tests, porque son las que mantienen la cinta
útil con el tiempo:

- **ninguna pestaña puede pedir más ancho del que tiene la ventana.** Una cinta
  que se sale deja opciones fuera de la vista sin decirlo. Al medirlo, la
  pestaña «Texto» pedía 1486 px de 1170: las dos frases que lo causaban se
  movieron a la ayuda emergente.
- **todo botón dice qué hace al pasar el ratón por encima**, y **todo icono
  existe en el tema.** Un nombre de icono que no existe no revienta nada: se
  dibuja un hueco y se queda ahí sin que nadie se entere.

### Probado de verdad

La ventana se ha ejecutado **dentro del Flatpak construido** con un servidor X
virtual, abriendo un PDF CMYK del corpus: se dibuja la página con los colores
correctos, la cinta con sus cinco pestañas, la lista lateral con sus cuatro
objetos y la barra de estado. Las capturas de `docs/capturas/` (diez) las genera
`tools/capturas_gui.py` con el modo `--captura`, que dibuja el árbol de la
ventana en un `Gtk.Snapshot` y lo rasteriza: no depende del servidor X ni de
hacer una foto de pantalla.

Con un límite que conviene saber: **el modo captura no sirve para fotografiar un
panel oculto**. La instantánea dibuja el árbol entero, y un widget que está en el
árbol pero sin mapear sale pintado igual, en una banda oscura que en la ventana
real no está. Se descubrió midiendo el píxel. Que el panel se oculta de verdad se
comprueba con el estado del widget, no con píxeles.

### Guardar, con el portal de por medio

La ventana guarda con `Gtk.FileDialog`, que dentro de un sandbox pasa por el
portal de ficheros. Eso **encaja con cómo guarda este programa**: el guardado es
incremental y escribe **solo el fichero elegido**, sin dejar copias ni ficheros
temporales al lado —el temporal va al directorio temporal del sistema—, y el
portal concede justo ese fichero. (El `.bak` existe, pero es cosa de la consola,
donde hay permiso de escritura en la carpeta.)

## El instalador (`instalar.sh`)

Es `sh` puro —funciona en cualquier distribución, incluido Alpine con busybox— y
hace cinco cosas: leer `/etc/os-release`, mirar qué hay disponible, elegir vía,
instalarla y **comprobar que funciona de verdad** (no que se ha copiado).

### Lo que se puede probar sin tener la distribución delante

```bash
./instalar.sh --simular=opensuse-leap --si
```

`--simular` finge el sistema **y finge que está limpio**, sin Flatpak, sin pipx y
sin GTK. Eso no es un detalle: la primera versión del simulador consultaba lo que
había instalado de verdad en la máquina, así que en el equipo de desarrollo —que
tiene el Flatpak puesto— elegía «flatpak» para las seis distribuciones y no
probaba nada. Hay un test por distribución que comprueba la decisión.

### Dos trampas que costaron una tarde cada una

**1. `pipx` sin `--system-site-packages` da una consola que funciona y una
ventana que no.** PyGObject no se puede instalar con pip: va atado a las
bibliotecas de GTK de la distribución. El entorno virtual de pipx nace aislado,
así que ve el paquete pero no ve PyGObject, y la ventana contesta «no está
instalado PyGObject» **cuando sí lo está**. Se descubrió instalando de verdad con
pipx en la máquina de desarrollo y ejecutando lo instalado. Por eso el instalador
pasa `--system-site-packages` siempre, y por eso el propio lanzador de la ventana
detecta ese caso concreto y dice cómo arreglarlo en vez de mentir.

**2. `Adw.AlertDialog` no existe en libadwaita 1.4.** Se añadió en la 1.5, y
openSUSE Leap 15.6 trae GNOME 45, o sea libadwaita 1.4. Sin esto, en Leap la
ventana arrancaría, dibujaría la página entera y reventaría **al primer doble
clic**, que es cuando se abre un diálogo. Y hay un tercer caso: en libadwaita 1.6
o posterior `Adw.MessageDialog` se reimplementó sobre `Adw.Dialog` y su
`present()` ya no acepta padre, mientras que en la 1.4 el padre era obligatorio.
Los tres casos están cubiertos en `gui/dialogos.py` y los tres tienen test.

### El PATH, que es el aviso que llega de una instalación de verdad

La primera instalación en un equipo ajeno a este taller —un **Ubuntu 26.04**,
GTK 4.22.4, libadwaita 1.9.1, PyGObject 3.56.2— funcionó entera, y terminó con un
aviso repetido dos veces:

```
! /home/isard/.local/bin no está en el PATH; añádelo o usa la ruta completa
```

Avisar no arregla nada: quien lo lee no sabe si tiene que hacer algo. `pipx`
deja los comandos en `~/.local/bin`, que en muchas distribuciones no está en el
PATH, así que ahora el instalador lo resuelve:

1. le pide a **`pipx ensurepath`** que lo haga, pero sólo si el prefijo es el
   suyo (`~/.local`): con `--prefijo=` distinto, `ensurepath` escribiría la
   carpeta equivocada;
2. y si eso no vale o falla, escribe un bloque en **`~/.profile`** con **la
   carpeta de verdad**. La primera versión escribía `$HOME/bin`, que no existe
   —se vio ejecutándolo, no leyéndolo—, y se corregido mirando el prefijo real;
3. antes de escribir nada busca **la carpeta** en el perfil, no la marca, porque
   si ya la añadió `ensurepath` volver a escribirla sumaría líneas en cada
   ejecución. El primer intento de esta comprobación era
   `sed -n "/marca/d"`, que no imprime nada nunca: no detectaba nada y duplicaba
   el bloque cada vez;
4. `--desinstalar` quita el bloque que puso él, y **deja el de pipx**: ese puede
   estar haciendo falta para otras aplicaciones de pipx del usuario.

Y en modo simulado no se toca nada, ni el fichero de arranque del shell de quien
lo ejecuta. Es el mismo error que ya se había cometido con la caché de descargas
—un modo que dice «esto es lo que haría» y luego hace—, así que tiene test.

### La vía Flatpak, en tres casos

La decisión de usar Flatpak estaba mal de raíz, y no se vio hasta que se ejecutó
el instalador **solo, en una carpeta vacía** (o sea, como con `curl | sh`):

```sh
flatpak_listo() {          # versión anterior
    hay flatpak || return 1
    flatpak info "$ID_APP"  # ¿está INSTALADA?
}
```

Pedía que la aplicación **ya estuviera instalada** para elegir la vía que sirve
para instalarla. Y cuando estaba instalada y no había manifiesto al lado —el caso
de `curl | sh`—, se iba a Flathub a buscar algo que todavía no está publicado:

```
error: Nothing matches io.github.lockerdocx.IntactPDF in remote flathub
```

Ese error lo veía el usuario y no decía ni qué había pasado ni qué hacer. Ahora
la vía se ofrece sólo si lleva a una acción que existe, y son tres casos:

| caso | qué hace |
|---|---|
| hay manifiesto al lado y `flatpak-builder` | **construye** el Flatpak desde el código |
| ya está instalada y no hay manifiesto | comprueba que responde y lo dice: no hay nada que hacer |
| está publicada en Flathub (`PUBLICADO_EN_FLATHUB=1`) | la instala desde Flathub |

Si no se cumple ninguno, la vía no se elige y se sigue con pipx, las
dependencias de la distribución o el AppImage. El día que se publique en Flathub,
**se cambia una sola línea** —`PUBLICADO_EN_FLATHUB=0` → `1`— y la vía se ofrece
sola. La constante existe para que el instalador no mande a nadie a un sitio
donde la aplicación todavía no está: un error ajeno es peor que una negativa
explicada.

### Una aplicación por proceso, y un solo `run()` (lo destapó el CI)

El primer flujo de integración continua que se escribió para este proyecto falló
en la primera ejecución, y el fallo era de verdad, no del CI:

```
ERROR test_soltar_un_pdf_encima_de_la_ventana_lo_abre:
  Error: g-io-error-quark: An object is already exported for the interface
  org.gtk.Application at /io/github/lockerdocx/IntactPDF
```

Son dos reglas de GLib que se pagan con un fallo silencioso, y las dos estaban
mal usadas:

| regla | qué pasa si se salta |
|---|---|
| una `Gio.Application` por proceso e identificador | registrar la segunda **lanza** donde hay bus de sesión; sin bus devuelve False y no pasa nada |
| un solo `run()` por proceso | la segunda llamada no abre nada: imprime «Failed to register…» y devuelve 1 |

Lo peor no es el fallo, es **dónde se ve**: el entorno de pruebas no tenía bus de
sesión, así que registrar de más no hacía nada y todo parecía correcto. Las
pruebas que creaban su propia aplicación se saltaban en silencio en cuanto otra
se hubiera registrado antes —una prueba que no prueba nada y sale en verde—, y la
herramienta de capturas generaba la primera imagen y ninguna más.

Arreglado en tres sitios: las pruebas comparten una sola aplicación (y ya no
registran ninguna, no les hace falta), la captura de la prueba corre **en su
propio proceso** por el mismo motivo por el que las capturas de verdad se generan
una por proceso (`tools/capturas_gui.py --solo=NOMBRE`), y `Aplicacion.registrar()`
está para quien necesite registrar sin reventar. El CI se queda como está: es
justo lo que tiene que hacer, ejecutar las cosas como las ejecuta la gente.

### Cómo se comprueba que una instalación quedó bien

```bash
intactpdf doctor                   # dependencias, fuentes y pila de GTK
intactpdf-gui --comprobar          # ¿podría abrirse la ventana? (no la abre)
```

`--comprobar` existe para los sitios donde no hay pantalla: un contenedor, un CI,
un servidor. Dice las versiones de GTK, libadwaita y PyGObject y sale, sin abrir
nada. Es lo que usa el instalador en su último paso.

## AppImage: la alternativa sin instalar nada

**Está construido y probado de verdad**, no es un script teórico.
`packaging/appimage/construir.sh` y el resultado en
`dist/IntactPDF-0.1.0-x86_64.AppImage` (61 MB).

```bash
packaging/appimage/construir.sh
dist/IntactPDF-0.1.0-x86_64.AppImage doctor
```

Cómo funciona: descarga un Python portátil de `python-build-standalone` (URL y
sha256 fijadas en el script, y comprobadas), instala las dependencias y la
aplicación dentro, mete las fuentes DejaVu, y empaqueta con `appimagetool`.

Dos cosas que se aprendieron construyéndolo:

- **El script de consola que genera pip lleva un shebang con la ruta absoluta del
  intérprete que lo instaló.** Durante la construcción eso es `/tmp/tmp.XXXX`,
  que dentro del AppImage ya no existe: el AppRun fallaba con un «not found»
  desconcertante, porque el fichero estaba ahí y lo que faltaba era el
  intérprete. Se reescribe el shebang a `#!/usr/bin/env python3` y, además, el
  AppRun invoca `python3 -m nucleo.cli` en vez del script.
- **`appimagetool` se ejecuta con `--appimage-extract-and-run`.** No es un
  capricho: en un contenedor de construcción no hay FUSE, y el propio
  `appimagetool` es un AppImage. El resultado sí funciona sin FUSE en el equipo
  del usuario.

**El límite, dicho claro:** un AppImage no arregla el problema de glibc. Hereda
la glibc 2.28 que exige `pikepdf`. Funciona en RHEL/Rocky 8+, Debian 10+ y
Ubuntu 20.04+, y **no** en CentOS 7 ni Debian 9. Ese es, exactamente, el motivo
por el que la vía principal es Flatpak.

## pip y pipx

Para quien ya tiene Python y prefiere no instalar un runtime entero:

```bash
pipx install .            # recomienda esto: aísla la aplicación
# o bien
pip install --user .
```

Las dos vías están probadas (el CLI se ha estado usando así durante todo el
desarrollo). Necesitan Python 3.9+ y glibc 2.28+.

## Cómo comprobar que una instalación funciona

```bash
intactpdf doctor            # dependencias, fuentes y estado de la pila de GTK
intactpdf-gui --comprobar   # ¿podría abrirse la ventana? Sale sin abrirla
```

`doctor` dice la versión de cada dependencia, cuántas fuentes ve y en qué
directorios, si está todo listo, y **qué falta para la ventana con el comando
exacto de esta distribución**. Si `doctor` no encuentra fuentes, el nivel 2 de la
edición de texto no puede funcionar, y el aviso lo explica.

Su parte de interfaz gráfica es opcional a propósito: la consola tiene que
funcionar en un servidor sin pantalla, y decir «falta PyGObject» cuando el
programa que se está usando no lo necesita sería ruido. Así se ve en un Debian
sin la pila de GTK:

```
      interfaz gráfica (opcional, para la ventana)
      PyGObject    FALTA (ModuleNotFoundError)
        sistema detectado: Debian GNU/Linux 13 (trixie)
        → para la ventana: sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
        (el editor de consola no los necesita)
```

La tabla de paquetes está en `nucleo/dependencias.py` y **duplicada a propósito**
en `instalar.sh`: el instalador tiene que ser un fichero suelto que se pueda
bajar y ejecutar sin el resto del código. Para que no se separen, hay un test que
lee las dos y las compara campo a campo. Ese test ya encontró una divergencia de
verdad: el modo simulado escribía «pacman install», que no es una orden de
pacman.

## Publicar: cómo se llega a un `curl | sh`

El objetivo es que instalar sea **una línea que se pueda copiar y pegar sin
entenderla**:

```bash
curl -sSL https://github.com/LockerDocx/intactpdf/releases/latest/download/instalar.sh | sh
```

Para eso hacen falta cuatro ficheros en una URL pública, y un script que los
suba y, sobre todo, que **compruebe antes de subir**:

```bash
tools/publicar.sh --comprobar                      # ¿está todo listo?
tools/publicar.sh --github=usuario/repo   --si     # publicar en GitHub
tools/publicar.sh --servidor=yo@host:/var/www/pdf  --si
tools/publicar.sh --github=usuario/repo --simular  # decir qué haría, sin subir
```

Lo que sube es `dist/publico/`:

| fichero | para qué |
|---|---|
| `instalar.sh` | el que se ejecuta con `curl \| sh` |
| `IntactPDF-0.1.0-x86_64.AppImage` | 61 MB, la vía «sin instalar nada» |
| `intactpdf-0.1.0-py3-none-any.whl` | 85 KB, la vía pipx/pip |
| `SHA256SUMS` | las sumas, en formato `sha256sum` |

### La dirección viaja dentro del script

Un script que llega por `curl` (o por una tubería) **no puede saber de dónde lo
han bajado**: no hay ninguna variable que se lo diga. Así que se lo escribe quien
publica, en la constante `BASE_URL_DEFECTO`, que en el repositorio está vacía:

```sh
BASE_URL_DEFECTO="https://github.com/usuario/repo/releases/latest/download"
```

De ahí sale que el `curl | sh` de la página de descargas funciona **sin
argumentos**. `tools/publicar.sh` la escribe al publicar, y luego comprueba dos
cosas: que el fichero publicado **es el del repositorio salvo esa línea** (que es
la única diferencia admisible) y que la dirección que lleva dentro es la buena,
no la de una prueba anterior.

En un simulacro **no se escribe nada**: dejar una dirección de mentira dentro del
fichero que se va a publicar es exactamente el fallo que la herramienta tiene que
evitar. Ya se dio una vez, y se detectó porque las sumas dejaron de cuadrar.

### Qué comprueba antes de subir

Comprueba tres cosas, y **no sube si alguna falla**: que las sumas
cuadren con los ficheros, que el `instalar.sh` publicado sea byte a byte el mismo
que el del repositorio, y que el instalador **arranque desde una carpeta vacía**
sin el proyecto al lado. La tercera es la que quita el miedo: es exactamente lo
que pasa cuando alguien hace `curl | sh`, y es un caso distinto del de ejecutarlo
en el repositorio, donde tiene el código al lado.

### Las trampas del `curl | sh`

Ninguna de las tres se veía leyendo el script: las tres salieron de **ejecutarlo
de verdad** con un servidor delante.

**1. `sh` no tiene variables locales, y una subcáscara no protege.** La primera
versión de la descarga usaba `destino` como variable interna, y al llamar a la
función de sumas la de dentro machacó la de fuera: el instalador copió
`SHA256SUMS` como si fuera el AppImage. Se arregló renombrando cada variable a su
nombre propio (`sumas_destino`, `desc_destino`). En `sh` no hay forma de declarar
una variable local, así que la única defensa es no repetir nombres.

**2. Un `trap … EXIT` se lleva por delante la descarga que acabas de hacer.** El
directorio temporal se creaba con `mktemp -d` y se borraba al salir. Pero la
descarga se hacía dentro de `$( … )`, o sea en una **subcáscara**: al terminar la
subcáscara, el `EXIT` del trap borraba el fichero recién bajado (61 MB) y el paso
siguiente decía «no existe el AppImage». Se cambió por una **caché que
persiste**: `~/.cache/intactpdf/descargas`, y la descarga se hace en el flujo
principal, no en una subcáscara.

**3. `sh -n` no valida la lógica.** Las dos trampas anteriores pasaban
`sh -n` sin decir nada, porque la sintaxis era correcta: lo que estaba mal era el
comportamiento. La única prueba que las encontró fue lanzar el instalador de
verdad contra un servidor, y volver a lanzarlo **después de cada cambio** —
también porque durante un rato el servidor sirvió una copia vieja del script,
que da un fallo idéntico al de un script roto.

**4. `sh /ruta/al/repo/instalar.sh` desde una carpeta vacía no reproduce un
`curl | sh`, aunque lo parezca.** El instalador localiza el proyecto **a partir
de su propio fichero** (`$0`), no del directorio actual, así que ejecutándolo
desde su ruta original encuentra el proyecto aunque estés en `/tmp`. El primer
test que escribí para esto no probaba nada: pasaba por casualidad. Hay que
**copiar el script** a la carpeta vacía y ejecutarlo desde dentro, que es lo que
pasa de verdad con `curl | sh`. Igual hizo falta en la comprobación de
`tools/publicar.sh`, y fue al arreglarlo cuando apareció la trampa 5.

**5. La vía Flatpak no podía funcionar en un `curl | sh`.** Se elegía sólo si la
aplicación ya estaba instalada, y sin manifiesto al lado iba a Flathub a buscar
algo que no está publicado. Está contado arriba, en «La vía Flatpak, en tres
casos». Es el ejemplo de manual de por qué hay que ejecutar el programa como lo
va a ejecutar la gente, y no como es cómodo probarlo.

### Lo que está verificado, y lo que no

Verificado ejecutando, no leyendo:

- `curl -sS http://127.0.0.1:8123/instalar.sh | sh -s -- --si --metodo=pipx --base-url=…`
  → descarga, suma comprobada, `pipx install`, y `--comprobar` al final dice
  GTK 4.18.6 y libadwaita 1.7.6. La ventana abre.
- **Y sin pasar ninguna dirección**: se publicó a una carpeta servida por HTTP
  (con `--servidor=`), y

  ```bash
  curl -sS http://127.0.0.1:8125/instalar.sh | sh -s -- --si --metodo=appimage
  ```

  bajó el AppImage de `http://127.0.0.1:8125`, comprobó la suma e instaló, **sin
  decirle dónde estaba el servidor**: la dirección viaja dentro del propio
  `instalar.sh` (ver abajo).
- La misma orden con `--metodo=appimage` → AppImage descargado, suma comprobada,
  instalado en `~/.local` con lanzador y `.desktop`, y `intactpdf doctor` dice que
  todo está listo.
- **La descarga manipulada**: se sirvió una rueda con 49 bytes de más. El
  instalador dijo «la suma NO cuadra», se paró, y `pipx list` confirmó que no se
  instaló nada. El fichero malo se borra de la caché, para que un reintento no
  tropiece dos veces con lo mismo.
- **Sin el fichero de sumas, no descarga**: no hay modo «por si acaso». Si el
  servidor no da `SHA256SUMS`, se para. `--sin-verificar` lo salta, pero hay que
  escribirlo a propósito.

Y está **publicado**: el repositorio es
[github.com/LockerDocx/intactpdf](https://github.com/LockerDocx/intactpdf) y la
versión 0.1.0 tiene los cuatro ficheros. La dirección de descarga de una versión
en GitHub es estable (`/releases/latest/download/`), así que el `curl | sh` de la
documentación no cambia al publicar la siguiente.

Antes, la dirección estaba **vacía a propósito** en el código
(`BASE_URL_DEFECTO`), porque publicar es meter los ficheros en una cuenta que es
de alguien y esa decisión no la puede tomar el programa. Ese hueco sigue ahí para
quien publique en otro sitio:

```bash
# Desde el repositorio, con el código al lado
./instalar.sh

# Publicado en otro sitio, con los ficheros en una carpeta
python3 -m http.server 9999
curl -sSL http://127.0.0.1:9999/instalar.sh | sh -s -- --base-url=http://127.0.0.1:9999
```

### Lo que se comprobó al publicar

Publicar no es subir ficheros: es que a otra persona le funcione. Se comprobó
desde fuera, bajando el script de GitHub y ejecutándolo como lo haría un
desconocido, sin pasarle ninguna dirección:

```bash
curl -sSL https://github.com/LockerDocx/intactpdf/releases/latest/download/instalar.sh | sh
```

- **Vía pipx**: bajó la rueda de la versión, comprobó la suma, instaló con
  `pipx`, y al final `doctor` dijo que todo estaba listo con GTK 4.18.6 y
  libadwaita 1.7.6. Luego se abrió la ventana instalada, con un PDF, y siguió
  abierta (que es lo que tiene que pasar).
- **Vía AppImage**: bajó 61 MB de la versión, comprobó la suma, lo dejó en
  `~/.local` con su lanzador y su entrada de menú, y `doctor` conforme.

## El nombre, comprobado con datos

Publicar es irreversible en el nombre: el identificador de Flathub y el de PyPI
**no se pueden cambiar** después sin dejar tirados a quienes ya lo tengan
instalado. Así que antes de publicar nada, cinco candidatos comprobados contra
los cuatro sitios que deciden:

```bash
python3 tools/comprobar_nombres.py
```

| nombre | paquete (PyPI) | GitHub | identificador Flathub | dominios `.org` / `.dev` |
|---|---|---|---|---|
| **IntactPDF** | libre | libre | libre | libres |
| AsIsPDF | libre | libre | libre | libres |
| IntactPDF *(provisional)* | libre | libre | libre | libres |
| PDFByte | **cogido** | libre | libre | libres |
| PDFQuill | libre | libre | libre | libres |

Lo que sale de aquí no es «el bueno»: es qué se puede elegir sin chocar. `PDFByte`
queda descartado por PyPI.

**Elegido: IntactPDF** (16 de octubre de 2026). Describe la única promesa que
este programa cumple y los demás no: lo que no editas queda **intacto**. Los
otros cuatro o describen algo que ya hacen otros («PDF», «Studio») o piden una
explicación. De ahí salen los cuatro nombres que hay que escribir en todos los
sitios:

| dónde | qué | se puede cambiar después |
|---|---|---|
| GitHub | `LockerDocx/intactpdf` | sí, pero rompe la URL de descarga |
| pip | `intactpdf` | **no**: hay gente que ya lo tiene instalado |
| Flatpak | `io.github.lockerdocx.IntactPDF` | **no**: lo mismo |
| comandos | `intactpdf` y `intactpdf-gui` | no sin dejar a nadie tirado |

El identificador de Flathub usa el usuario de GitHub, que es lo que exige
Flathub: así el paquete está bajo el control de quien lo publica y se puede
comprobar sin depender de un dominio. Si algún día hay dominio propio
(`intactpdf.org` está libre), se puede migrar, pero el identificador se queda.

Dos avisos sobre lo que esta comprobación **no** dice. Un nombre que no resuelve
por DNS puede estar registrado igual, y uno que resuelve está casi seguro
ocupado; para saberlo de verdad hay que consultar el registrador. Y GitHub
permite crear usuarios u organizaciones sin coste, así que «libre» en la tabla
significa que está libre **hoy**: reservarlo es un clic.

## Lo que falta

- **Guardar encima del original desde la ventana.** Hoy la ventana siempre
  guarda copia («-editado.pdf»); el guardado in situ está en la consola. La
  decisión de Flatpak obliga a GTK4 con PyGObject, no a webkit ni a Chromium
  embebido: dentro de un sandbox, meter un navegador para dibujar una ventana es
  pagar 100 MB y una superficie de ataque enorme a cambio de nada.
- **La compactación del fichero** (fase F5): hoy cada guardado añade al final,
  que es lo que da la garantía del prefijo, pero el fichero crece.
- **El identificador y el nombre definitivos**: los cinco candidatos ya están
  comprobados contra PyPI, GitHub, Flathub y DNS (tabla arriba, `PDFByte` queda
  fuera). Falta **elegir** y, con eso, crear la cuenta y el repositorio.
- **La firma de los AppImage** con GPG y `appimagetool --sign`. Hoy hay un
  `.sha256` que viaja por el mismo sitio que el fichero: sirve contra una
  descarga truncada, no contra quien controle el servidor.
- **El AppImage con ventana.** Hoy el AppImage lleva solo la consola, porque
  dentro habría que meter la pila entera de GTK (PyGObject compilado contra el
  Python del propio AppImage, GTK 4, libadwaita, pango, cairo...). Es factible y
  es trabajo de empaquetado puro; hasta entonces, la ventana sin instalar nada es
  el Flatpak.
- **Flathub**: el nombre y el identificador ya están elegidos y el manifiesto
  apunta al runtime correcto; falta enviar el paquete y, antes, servir las
  capturas desde una URL (AppStream no acepta ficheros locales).
- **Que cada etiqueta construya y publique sola**: hoy `.github/workflows/pruebas.yml`
  pasa las pruebas, el instalador y el AppStream en cada cambio, pero los
  artefactos se construyen y se suben a mano con `tools/publicar.sh`. Lo que
  falta es que una etiqueta `v*` lance la construcción del AppImage y la
  publicación, para no depender de que alguien se acuerde. Los pasos ya están
  escritos y probados: sólo hay que llevarlos al flujo.
- **Firmar el AppImage** con GPG, para que se pueda comprobar que viene de quien
  dice que viene. Hoy la garantía es el sha256, que viaja por el mismo sitio que
  el fichero: sirve contra una descarga truncada o manipulada en el camino, no
  contra alguien que controle el servidor.
