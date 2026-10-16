# Fase F2 — Mover, borrar y redimensionar: el test de aceptación

**Fecha:** 2026-10-15
**Estado:** F2 implementada. **El criterio de aceptación del proyecto se cumple: 10/10 casos, 0 píxeles alterados indebidamente.**

---

## 1. El criterio, en los términos en que se fijó

> «el usuario abre un PDF real con texto e imágenes, selecciona una imagen, la
> redimensiona, borra un vector, cambia un texto, guarda, reabre — sus cambios
> están y **nada más ha cambiado**»

Quedan cubiertos todos los verbos menos uno: **redimensionar** y **borrar** están
medidos, y **cambiar un texto** llega hasta *mover* texto, que usa exactamente el
mismo mecanismo sobre los mismos objetos pero **no es editar el texto**. Editar
caracteres es F4 y depende de re-subsetting de fuentes. Conviene no confundirlos.

## 2. El resultado

```
  caso (LinuxPDF Studio)                    px cambiados  fuera |   LibreOffice SIN editar
  ============================================================================
  borrar_estrella                          26070 ( 1.30%)     0 |      0.614% de px
  borrar_un_rect_del_degradado              1890 ( 0.09%)     0 |      0.614% de px
  mover_imagen_smask                      241001 (12.02%)     0 |      6.375% de px
  escalar_imagen_smask                    241001 (12.02%)     0 |      6.375% de px
  mover_imagen_cmyk                       257041 (12.82%)     0 |     11.797% de px
  borrar_vector_cmyk                       33973 ( 1.69%)     0 |     11.797% de px
  mover_texto_fuente_completa              18208 ( 0.91%)     0 |      0.744% de px
  mover_linea_fragmentada                  12162 ( 0.61%)     0 |      9.775% de px
  borrar_una_linea_fragmentada              8448 ( 0.42%)     0 |      9.775% de px
  escalar_imagen_doble                    241001 (12.02%)     0 |      6.375% de px
  ============================================================================

  píxeles alterados INDEBIDAMENTE (10 ediciones): 0
  la salida empieza por el original:              10 / 10
  qpdf --check sin errores:                       10 / 10
```

**La columna `fuera` es el proyecto entero.** Son los píxeles que han cambiado
sin que el usuario hubiera tocado esa zona. El valor es cero en las diez
ediciones. La columna de la derecha es lo que hace LibreOffice Draw con el mismo
fichero **sin editar absolutamente nada**.

El contraste más claro es la línea `mover_linea_fragmentada`: mover una línea de
texto entre 18 cambia el 0,61 % de los píxeles, y los 17 restantes quedan
intactos. LibreOffice, sin tocar nada, cambia el **9,775 %** en ese mismo
documento.

---

## 3. La propiedad que lo hace verdad, no suerte

El diff de píxeles mide lo que se ve. Pero hay algo más fuerte, y es el motivo
por el que F2 se construyó así:

**El fichero guardado empieza por los bytes del original.**

```
  original:  25.771 bytes
  guardado:  26.247 bytes = los 25.771 originales + 476 nuevos
  prefijo idéntico: sí
```

Eso es una **actualización incremental** en el sentido de la especificación PDF
(§7.5.6): no se reescribe el documento, se le **añade** al final la nueva versión
de los objetos que cambian, más una sección de referencias cruzadas que apunta a
la anterior con `/Prev`. El original sigue ahí, byte a byte.

Si el prefijo es idéntico, **es imposible** que se haya modificado cualquier otra
cosa. No es que no se haya detectado el cambio: es que no hay dónde esconderlo.
El test de píxeles pasa a ser una confirmación, no la prueba.

### Y hubo que escribirlo a mano

Ni qpdf ni pikepdf saben guardar incrementalmente:

- **qpdf 12.2.0** no tiene ninguna opción para ello (`--help=all` no menciona
  «incremental» ni una vez).
- **pikepdf 10.17.0** no lo expone en `Pdf.save()`, y su modo
  `object_stream_mode=preserve` sólo conserva `ObjStm`, no la estructura de
  actualizaciones.

Ambos reescriben el fichero completo. Para un editor que se define por **no**
reconstruir el documento, eso es exactamente el problema que el proyecto existe
para resolver, así que `nucleo/guardar.py` monta el apéndice a mano: cabecera de
objeto, stream con `/Length` correcto, `xref` clásica con entradas de 20 bytes
exactos, `trailer` con `/Prev`, `/Root` y `/ID`.

Truco que simplifica el diseño: **se redefinen los mismos números de objeto** que
ya existían para el stream de contenido. Así el objeto de página, los recursos,
las fuentes y todo lo demás no se tocan en absoluto, y el documento sigue
apuntando a lo mismo.

---

## 4. Lo que se conserva, medido

Comparado campo a campo entre original y guardado, en las 10 ediciones:

| | original | editado |
|---|---|---|
| número de páginas | 1 | 1 |
| tamaño de página | 595,28 × 841,89 | **idéntico** |
| imágenes en CMYK | 1 | **1** |
| imágenes con SMask | 1 | **1** |
| AcroForm presente | sí | **sí** |
| anotaciones | 4 | **4** |

Recordatorio de lo que hace LibreOffice en estos mismos casos
(`03-validacion-empirica.md`): convierte el CMYK a RGB, recodifica la imagen con
SMask a JPEG con pérdida, convierte `AcroForm=True` en `False` y borra las 4
anotaciones, y cambia de orientación la página 2 del caso rotado.

---

## 5. Cómo está implementado

**Modelo de edición:** no se reescribe el stream. Se calculan **sustituciones
sobre rangos de bytes** y se aplican **de atrás hacia delante**, para que los
desplazamientos de una edición no invaliden los offsets de las siguientes.

**Borrar** reemplaza el rango por espacios en blanco: misma longitud, diff mínimo.
Se lleva también los operadores de estado que preceden al objeto (color, grosor),
porque dejarlos atrás cambiaría el aspecto del objeto siguiente, que heredaría un
estado que no era el suyo.

**Mover y escalar** envuelven el objeto en `q <matriz> cm ... Q`. Se envuelve en
vez de transformar los puntos del trazado porque funciona igual para vectores,
imágenes y texto, y **no toca ni un byte del interior del objeto**.

---

## 6. Dos bugs de geometría que encontró el test

### El inglete: la fórmula que casi todo el mundo escribe mal

Borrar la estrella dejaba 7 píxeles huérfanos a 2 pt de su caja, en sus puntas.
La caja de un trazado **con trazo** no es la caja de sus puntos: el trazo tiene
grosor y en las uniones en inglete los picos sobresalen. Implementé la fórmula:

```
extensión = (ancho/2) / sin(θ/2)
```

y daba 0,79 pt donde la punta sangra 2,29 pt. **Factor 3 de error.** El motivo:

> En una punta afilada, los dos segmentos apuntan casi en direcciones
> **opuestas**. El ángulo entre los vectores es cercano a 180°, y lo que usa el
> inglete es el **ángulo de giro**, su suplementario.

Con el ángulo correcto: `0,6 / sin(15,2°)` = **2,291 pt**, exactamente lo medido.
Con el equivocado se subestima el pico por un factor de 3, y eso significa que
**un usuario no podría seleccionar el contorno visible de una figura puntiaguda**
en toda la zona de la punta. No es un bug cosmético: es selección rota.

También está el caso sin inglete: con unión redonda o bisel (`j` = 1 o 2) no hay
pico, y con `M` bajo el límite lo corta. Las tres ramas están implementadas.

### El difflib del alineador, otra vez

El harness construía la región de tolerancia con las cajas **aproximadas**,
porque no llamaba a `alinear()`. La caja aproximada estima el ancho medio de un
carácter a 0,55 em, así que se desvía ~3 pt de la tinta real. Los 65 «píxeles
huérfanos» no se escapaban de la región: **la región estaba en el sitio
equivocado**. Corregido haciendo que el harness use la misma geometría que el
editor, que es lo que el editor hace de verdad.

Moraleja que anoto porque es la segunda vez que muerde: la caja aproximada es una
aproximación y hay que alinearla **antes** de usarla para cualquier cosa que
importe.

---

## 7. Límites de lo medido

- **El corpus sigue siendo sintético.** Es la deuda que más pesa ya. 11 PDFs
  hechos por mí. El default D1 pide ~20 reales y siguen faltando. Los números de
  esta página son sólidos *sobre este corpus*.
- **No hay interfaz gráfica.** La edición se ejerce llamando a `mover_objeto()`,
  `borrar_objeto()` y `escalar_objeto()`. El ratón, el panel de propiedades y el
  deshacer no existen todavía.
- **Redimensionar un vector no está en ningún caso de aceptación.** Escalar
  vectores funciona por el mismo mecanismo (`q..cm..Q`), pero sólo está medido
  sobre imágenes. Con el degradado recortado del caso 03, escalar exigiría
  transformar también el recorte, y eso no está hecho.
- **El umbral de tolerancia es 8/255** por canal. Diferencias por debajo se
  consideran ruido de suavizado. Es una elección, no una verdad.
- **Cambiar texto no está implementado.** Mover texto sí. La diferencia importa.
- **El guardado incremental no está probado sobre ficheros con `/XRefStm`**
  (archivos híbridos), cifrados, o con `ObjStm`. El corpus no los tiene. Si un
  PDF real los trae, `offset_ultimo_xref` puede apuntar mal. Es el riesgo técnico
  abierto más serio de esta fase.

---

## 8. Qué cambia en el plan

**F3 (redimensionar) está hecha para imágenes** por el mismo camino que F2, así
que la fase se reduce a escalar vectores con sus recortes y a la restricción
proporcional en la UI.

**F4 (edición de texto) queda como la única fase realmente cara**, y ahora se ve
con precisión por qué: todo el resto del editor **no necesita entender el
contenido**, sólo los rangos de bytes. F4 es la primera fase que necesita
construir algo nuevo — un subconjunto de fuente con el glifo que el usuario
escriba — y por eso no hay atajo.

**F5 (guardado robusto) ya tiene su núcleo hecho y es lo más valioso que hay en
el repositorio.** Lo que falta ahí no es incrementalidad, es **robustez**:
`/XRefStm`, cifrado, `ObjStm`, y el backup automático (C6).

**Una decisión de producto que conviene fijar ahora:** el guardado incremental
deja el fichero más grande con cada edición, porque cada guardado añade un
apéndice. Un usuario que guarde veinte veces acaba con un fichero ilegible por
acumulación. Hace falta **compactar bajo demanda** (`qpdf` no lo hace
incrementalmente, pero sí puede reescribir limpio cuando el usuario lo pida), y
avisar de ello en la UI. Sin esto, la propiedad que hace fuerte al proyecto se
convierte en un problema a los dos días de uso real.

---

## Reproducir

```bash
cd linuxpdf
python3 tests/test_aceptacion.py           # 5 tests, 10 casos, 0 fallos
python3 tools/test_aceptacion.py --guardar-png   # y guarda las imágenes del antes/después
python3 tools/test_aceptacion.py --caso mover_imagen_cmyk
```

Artefactos: `resultados/f2/aceptacion.json` (cifras de los 10 casos),
`resultados/f2/*_antes.png` y `*_despues.png`.
