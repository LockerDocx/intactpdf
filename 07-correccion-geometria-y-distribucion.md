# 07 — Corrección de geometría y distribución

**Fecha:** 2026-10-15
**Estado:** cerrado. 58 tests, 19/19 casos de aceptación, 16/16 páginas validadas
contra pdfium, Flatpak y AppImage construidos y probados.

Este informe cuenta dos cosas que salieron en la misma sesión y que están
relacionadas aunque lo parezcan poco: un **error de unidades** que estaba
corrompiendo documentos mientras el test de aceptación lo aprobaba, y el
**empaquetado** para que la aplicación llegue a cualquier distribución.

## 1. El test de aceptación aprobaba documentos destruidos

### Lo que pasó

Se escribió el CLI y, al probarlo a mano, escalar una imagen al 60 % la dejaba en
`x = 29768`. Fuera de la página. Para siempre.

La causa: el `cm` que se inserta para mover o escalar un objeto se aplica en el
**espacio local del objeto**, no en el de la página. Y ese espacio casi nunca es
el de la página: una imagen se pinta siempre en un cuadrado unidad, y su tamaño y
posición los pone el CTM que la precede. En el corpus de la imagen CMYK:

```
320 0 0 200 72 580 cm        <- el emplazamiento, fuera del objeto
q 0.6 0 0 0.6 92.8 272 cm    <- lo que se insertaba
Do
```

`92,8 × 320 + 72 = 29768`. La traslación se multiplicaba por la escala de
emplazamiento.

### Por qué el test no lo veía

Porque comparaba los píxeles contra una región **permitida** construida con las
cajas **de nuestro propio parser**. La región permitida era la unión de la caja
vieja y la caja nueva. Con la imagen volando:

- los píxeles de su sitio viejo cambiaban, y eso estaba permitido (el objeto se
  había ido);
- en el sitio nuevo no había nada que comparar.

Cero píxeles fuera de la región permitida. **Aprobar la desaparición del objeto
no es aprobar la edición.**

Y no era un caso suelto: el `move` tenía exactamente el mismo defecto desde F2.
Al reintroducir el bug a propósito, fallan los seis casos que mueven o escalan
algo. Tres de los diez casos que F2 dio por buenos estaban lanzando la imagen a
entre 15.919 y 65.949 puntos de su sitio.

### El arreglo

La matriz se conjuga por el CTM del objeto: `L = C · T · C⁻¹`. Con el caso real
sale `(0,6, 0, 0, 0,6, 0,2, 0,2)`, que es «escala 0,6 alrededor de (0,5, 0,5)» y
devuelve la esquina exactamente a `(136, 620)`.

Verificado de tres maneras:

1. **Algebraicamente**, con la identidad `C∘L = T∘C` en 205 puntos aleatorios:
   0 discrepancias.
2. **Con el oráculo** (pdfium): la imagen queda en `(136,0, 620,0, 328,0, 740,0)`
   y los otros tres objetos de la página, exactamente donde estaban.
3. **Reintroduciendo el bug**: el oráculo lo caza en los 6 casos.

### La cuarta comprobación del test de aceptación

Se añadió una comprobación que no depende de nuestro código: pdfium mide dónde
está cada objeto antes y después, y se le exige que

- **A.** ningún objeto aparezca fuera de donde ya había objetos más donde hemos
  dicho que iría el editado (esto caza el `x = 29768` solo, porque la unión de
  las imágenes se dispara); y
- **B.** el objeto editado esté de verdad en la posición predicha.

Para el texto la regla B exige **solape**, no igualdad de caja: pdfium crea un
objeto por glifo cuando el generador emite un `Tj` por carácter, así que un run
nuestro son 1.746 objetos suyos y ninguno coincide con la caja del run. La regla
A es la que cubre los desplazamientos.

### Y una validación que faltaba desde F1

`tools/validar_geometria.py` compara, página a página, las cajas de nuestro
parser con las de pdfium. **16/16 páginas coinciden** (tolerancia por tipo; para
el texto es proporcional al tamaño de la caja, porque en un run rotado los
extremos bailan un 5 %).

Las imágenes y los vectores coinciden al decimal en todo el corpus: es la
validación independiente que el parser no tenía.

El caso 01 se compara por la unión de cada tipo, no objeto a objeto: pdfium hace
un objeto de texto por carácter (1.746) y nosotros agrupamos runs (18). Los dos
están bien; es la agrupación heurística de la decisión C3.

## 2. El error de unidades en la edición de texto

Al arreglar lo anterior se buscó el mismo patrón en el resto del código. Aparecía
dos veces más, las dos en el ajuste de espaciado:

**a) El `Tc` está en espacio de texto, no en puntos de página.** La matriz del
texto y el CTM lo escalan igual que escalan los glifos. Un run dentro de
`q 2 0 0 2 0 0 cm` necesita la **mitad** de `Tc` para separar lo mismo en la
página. Arreglado con `escala_de_run()`.

**b) `ancho_nuevo` se leía antes de asignarse.** En el camino del nivel 1b, el
informe calculaba el `Tc` con `ancho_nuevo = 0` porque la asignación estaba
detrás del `return`. «Ajustar espaciado» compensaba el ancho **entero** del texto
en vez de la diferencia: el texto acababa midiendo más del doble.

Ninguno de los dos se podía ver con el corpus anterior, porque **todos** sus
textos se escriben con la matriz identidad. Se añadió el caso 11
(`11_texto_transformado.pdf`): texto bajo `cm` con escala 2 y 0,5, texto rotado
30 grados y texto con la `Tm` escalada 1,8.

Medido después del arreglo, para el run escalado x2: el avance final en la página
es 322,00 pt, exactamente el de partida. Antes, 402,14.

## 3. Un detalle de método que apareció dos veces

Al escribir «aqui» en un run que solo tenía letras sin cola, 14 píxeles caían
fuera de la región permitida: el descendente de la `q` baja por debajo de la caja
de la tinta vieja. Es la misma lección que el acento de la `ó` en F4. La región
de tolerancia tiene que ser la **extensión tipográfica** del texto (0,35 em
alrededor), no la tinta concreta de la frase anterior. Corregido y documentado en
el arnés.

## 4. Distribución

Decisión y detalles en `docs/distribucion.md`. Resumen:

| vía | estado | glibc mínima |
|---|---|---|
| Flatpak `org.gnome.Platform//51` | **construido y probado aquí** | la del runtime |
| AppImage | **construido y probado aquí** (61 MB) | 2.28 |
| pip / pipx | probado | 2.28 |

La restricción la marca `pikepdf` (`manylinux_2_28`), no el núcleo, que sigue
siendo biblioteca estándar pura. Se descartó el binario único «compatible con
glibc 2.17»: habría que construirlo en un contenedor con glibc 2.28 de todas
formas.

### Lo que se aprendió construyéndolos

- **El runtime 51 trae Python 3.14**, no 3.13. Un manifiesto con wheels `cp313`
  no instala, y el error de pip no menciona la versión de Python del runtime.
- **El sandbox no ve `/usr/share/fonts` del anfitrión**, así que las fuentes
  DejaVu viajan dentro del paquete, en `/app/share/fonts`, que llega al código
  por `XDG_DATA_DIRS` sin nada especial. Sin esto, el nivel 2 funciona fuera de
  Flatpak y falla dentro: un programa que se comporta distinto según cómo se
  instaló es un programa que nadie puede depurar.
- **`home:ro` anula `xdg-documents`.** El permiso de solo lectura sobre el
  directorio padre gana, y guardar da «Read-only file system». Comprobado a mano
  con el manifiesto puesto así. Ahora se concede `home` entero.
- **El script de consola de pip lleva la ruta absoluta del intérprete en el
  shebang**, que dentro del AppImage ya no existe: el error que sale es «not
  found» con el fichero presente. Se reescribe y el AppRun invoca
  `python3 -m nucleo.cli`.
- **`check` ya no necesita el binario `qpdf`.** Dentro del Flatpak no está, y el
  programa se limitaba a decir «no se puede validar». Ahora usa pikepdf, que
  lleva libqpdf dentro, y el render de pdfium como segunda opinión. Un fichero
  truncado a propósito se detecta.

## 5. Estado tras esta sesión

```
12 PDFs en el corpus (el 11 es nuevo)
16/16 páginas con la geometría validada contra pdfium
58 tests unitarios, 0 fallos
19/19 casos de aceptación, 0 píxeles fuera, prefijo intacto 19/19
Flatpak: construido, instalado y probado dentro del sandbox
AppImage: construido y probado, 61 MB
```

### Sigue abierto

- **La interfaz gráfica.** Es lo que más falta; sin ella no se puede publicar en
  Flathub (no hay capturas que enseñar) ni llegar a un usuario no técnico.
- El identificador y el nombre definitivos, y las cinco alternativas con dominio
  libre que hay que proponer antes de publicar nada.
- ~20 PDFs reales (D1) y los 5 nombres alternativos.
- El escritor incremental sin probar con `/XRefStm`, cifrado u `ObjStm`.
- La compactación bajo demanda.
- Que el CI construya el Flatpak y el AppImage en cada etiqueta, y que el test de
  aceptación corra **contra el AppImage**, no solo contra el código fuente.
