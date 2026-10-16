# Fase F4 — Edición de texto: el último verbo del criterio

**Fecha:** 2026-10-15
**Estado:** F4 implementada. **El criterio de aceptación completo se cumple: 15/15 casos, 0 píxeles alterados indebidamente.**

---

## 1. El criterio, cerrado

> «el usuario abre un PDF real con texto e imágenes, selecciona una imagen, la
> redimensiona, borra un vector, **cambia un texto**, guarda, reabre — sus cambios
> están y nada más ha cambiado»

Los cuatro verbos están cubiertos y medidos, y el guardado sigue siendo
incremental en los 15 casos: el fichero de salida **empieza por los bytes del
original**.

```
  caso (LinuxPDF Studio)                 px cambiados  fuera  añadido  prefijo
  ==============================================================================
  borrar_estrella                       26070 ( 1.30%)     0   1095B     True
  borrar_un_rect_del_degradado           1890 ( 0.09%)     0   1219B     True
  mover_imagen_smask                   241001 (12.02%)     0    498B     True
  escalar_imagen_smask                 241001 (12.02%)     0    502B     True
  mover_imagen_cmyk                    257041 (12.82%)     0    503B     True
  borrar_vector_cmyk                    33973 ( 1.69%)     0    489B     True
  mover_texto_fuente_completa           18208 ( 0.91%)     0    545B     True
  mover_linea_fragmentada               12162 ( 0.61%)     0   2446B     True
  borrar_una_linea_fragmentada           8448 ( 0.42%)     0   2363B     True
  texto_misma_longitud                    638 ( 0.03%)     0    474B     True   <- F4
  texto_mas_corto                        3839 ( 0.19%)     0    476B     True   <- F4
  texto_glifo_ausente                    4573 ( 0.23%)     0   8167B     True   <- F4
  texto_glifo_ausente_ajustado           8812 ( 0.44%)     0   8607B     True   <- F4
  texto_linea_fragmentada                9484 ( 0.47%)     0  10428B     True   <- F4
  escalar_imagen_doble                 241001 (12.02%)     0    506B     True
  ==============================================================================
  casos: 15/15  |  px alterados indebidamente: 0  |  prefijo intacto: 15/15
```

---

## 2. El problema real de F4, que no era el que parecía

En F1 quedó escrito que «ya no es saber dónde está cada carácter, es
re-subsetting». Cierto a medias. El problema de verdad tiene una pinta distinta:

**Los PDFs llevan subconjuntos.** Un PDF que sólo dice «El rápido zorro» no lleva
la letra «k» dentro. Si el usuario escribe una «k», esa letra no existe en el
fichero y **no hay forma de sacarla de ahí**. No es un problema de índices ni de
geometría: es que falta el dibujo.

De dónde sale entonces, en orden de preferencia:

| | situación | qué se hace | coste |
|---|---|---|---|
| **1a** | misma longitud y todos los códigos existen | sustituir bytes en cada operador | el stream no cambia de longitud ni de estructura |
| **1b** | longitud distinta, códigos existentes | colapsar los operadores de texto del run en uno | el ancho del run cambia |
| **2** | falta el glifo, la fuente está en el sistema | subconjunto nuevo con fontTools, incrustado como fuente **nueva** | +3 objetos, ~8 KB |
| **0** | falta el glifo y la fuente no está | **rechazar** diciendo qué fuente hace falta | — |

El nivel 0 es una decisión de producto, no una limitación: **no se sustituye una
fuente por otra parecida en silencio.** Eso cambiaría el aspecto del documento sin
avisar, que es exactamente lo que LibreOffice hace y este proyecto existe para no
hacer. Un PDF con `DejaVuSans` y otro con `LiberationSans` son documentos
distintos aunque se parezcan.

### Lo que se midió con cada nivel

```
  texto_misma_longitud        nivel 1a; ancho 24876 -> 24877 (+0 milésimas)
  texto_mas_corto             nivel 1b; ancho 24876 -> 11472; -398.02 pt
  texto_glifo_ausente         nivel 2; fuente nueva DejaVuSans (16 KB); DESBORDA
  texto_glifo_ausente_ajustado nivel 2; Tc -2.180; el texto encaja
  texto_linea_fragmentada     nivel 2; 97 operadores colapsados
```

En el nivel 1a el stream conserva **la misma longitud y los mismos operadores**.
Es la edición más barata y más segura que puede existir sobre un PDF.

---

## 3. El bug que casi se cuela, y era grave

Los primeros casos de texto en el test de aceptación **fallaron**: 7.758 y 13.232
píxeles cambiados fuera de la región. No era tolerancia. Era un filtrado de
estado gráfico.

En estos PDFs el `Tc` (espaciado entre caracteres) se emite **después** de cada
`Tj`:

```
BT 1 0 0 1 72 780 Tm /F2+0 13 Tf 15.6 TL (Documento...) Tj  .35 Tc (l) Tj 0 Tc ...
```

Detrás de la línea. Y eso quiere decir que ese `Tc` fija el espaciado del
**carácter siguiente**, no del anterior. Es estado gráfico y **sobrevive al
`ET`**, que sólo cierra el objeto de texto, no el estado.

Dos consecuencias, y las dos eran bugs míos:

1. **Mi rango de edición se extendía hacia delante** para tragarse los operadores
   de estado que van pegados detrás del último `Tj`. Eso se comía el `Tc` que la
   línea siguiente necesitaba. La línea siguiente salía con otro espaciado.

2. **Mi reemplazo emitía `Tc` y no lo restauraba.** Todo lo que venía debajo
   heredaba el espaciado de la línea editada.

El arreglo son las dos mitades: el rango llega **sólo** del primer operador de
texto al último, y quien reemplace el rango **debe restaurar** el `Tc` que había
en efecto. Hay una función para calcularlo, `_tc_en_efecto()`, que recorre el
stream hacia atrás respetando la pila `q`/`Q` (un `Tc` dentro de un bloque cerrado
ya no está vigente). Y se emite el cierre `0 Tc` o `-2.1802 Tc` al final del
reemplazo.

Sin esto, «cambiar un texto» cambiaba además todas las líneas de debajo. Que es
literalmente el fallo que el test de aceptación existe para detectar, y lo
detectó.

---

## 4. Cómo funciona el nivel 2 por dentro

Se construye el subconjunto con fontTools a partir de la fuente del sistema
—`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` en este entorno— y se emite
como **Type0 / Identity-H**:

- El código **es** el identificador de glifo. No hay tabla de codificación que
  reconstruir, y los anchos se declaran explícitos en el array `/W`.
- Se genera un `/ToUnicode` nuevo, sin el cual el texto no se podría copiar ni
  buscar en el PDF resultante. **Verificado**: el texto extraído del PDF editado
  incluye la «ó» correctamente.
- Todo va dentro del diccionario de fuentes menos los dos streams (`FontFile2` y
  `ToUnicode`), que por definición tienen que ser indirectos. Son **3 objetos
  nuevos**: 1 redefine el diccionario de fuentes y 2 se añaden.

Y lo importante: **la fuente original no se toca.** El diccionario pasa a tener
dos entradas, la vieja y la nueva; el resto de la página sigue apuntando a la
vieja y es inmune. Hay un test que lo comprueba campo a campo
(`test_nivel_2_no_toca_la_fuente_original`).

---

## 5. Lo que se avisa y no se esconde

**El desborde.** Nivel 1b y 2 cambian el ancho del texto. En vez de dejarlo pasar
en silencio —como hace Draw al re-maquetar— se calcula y se reporta:

```
  texto_glifo_ausente   ancho 16652 -> 20786; +74.41 pt; DESBORDA
```

Y hay una opción `ajustar_espaciado` que emite un `Tc` negativo para compensar,
útil para no mover nada más. Pero es **opt-in** y se reporta el valor aplicado,
porque comprimir el espaciado cambia el aspecto: el usuario tiene que decidirlo,
no el editor.

**Lo que no se puede editar, con motivo.** De F1 viene `razones_no_editable`, y
F4 añade dos entradas nuevas: fuente sin `/ToUnicode` (no se sabe qué carácter es
cada código) y glifo ausente sin fuente disponible.

---

## 6. Tests: 54, todos en verde

```
  tests/test_parser.py      11   lexer, escapes, offsets, arrays, corpus
  tests/test_objetos.py     23   geometría, fuentes, extracción, alineación, hit-test
  tests/test_texto.py       15   estado de texto, niveles 1a/1b/2/0, regresión de Tc
  tests/test_aceptacion.py   5   15 casos, estructura intacta, qpdf --check
  TOTAL                     54
```

Los que vigilan de verdad:

- `test_el_tc_no_se_filtra_a_la_linea_siguiente` — el bug de la sección 3, ahora
  con la aserción puesta **por debajo** de la línea editada, que es donde se vería
  el filtrado.
- `test_nivel_1a_no_cambia_la_longitud_del_stream` — exige la misma longitud y la
  misma secuencia de operadores.
- `test_nivel_2_el_texto_nuevo_se_extrae_con_su_acento` — sin `/ToUnicode`
  correcto el PDF quedaría bien visualmente y **no se podría copiar**.
- `test_nivel_2_no_toca_la_fuente_original` — compara `/BaseFont` y el tamaño del
  `/ToUnicode` de cada fuente antes y después.
- `test_nivel_0_rechaza_y_dice_que_fuente_hace_falta`.

---

## 7. Límites de lo medido

- **El corpus sigue siendo sintético.** Es la deuda que no se ha pagado en toda la
  sesión y ya pesa: 11 PDFs hechos por mí. D1 pide ~20 reales.
- **No hay interfaz gráfica.** La edición se ejerce llamando a las funciones. El
  cursor de texto, la selección de rango, el deshacer: nada de eso existe.
- **Nivel 1b recompone la línea.** Al colapsar los operadores en uno, el
  espaciado por carácter del original se pierde: el texto se recompone con el
  espaciado natural de la fuente. El ancho resultante se avisa, pero un texto
  justificado o con kerning fino cambiará de aspecto. El nivel 1a no tiene este
  problema porque no toca la estructura.
- **La referencia a `/Size` es frágil.** Al añadir objetos se usa
  `trailer /Size` para numerarlos. Si un PDF real tiene `/Size` mayor que el
  máximo en uso —legal y frecuente— esos números podrían estar ocupados. Funciona
  en el corpus; hace falta comprobarlo contra `/XRefStm`, `ObjStm` y cifrado, que
  es el mismo riesgo abierto que dejó F2.
- **Sólo se probó con fuentes TrueType.** Nada de CFF/OpenType (`/FontFile3`), ni
  Type1, ni fuentes con subconjuntos sin `/ToUnicode`. El corpus no los tiene.
- **El nivel 2 no cubre fuentes CJK**, ni por diseño: si el glifo no está en la
  fuente del sistema, se rechaza. Eso es coherente con el default C9 (sólo latín
  en v1), pero conviene tenerlo presente.
- **El `Tc` de restauración se calcula, no se conserva.** Si el original tenía un
  `Tc` dentro de un `Tz` o un `TL` raro, la restauración puede no ser exacta. En
  el corpus lo es.

---

## 8. Estado del proyecto

```
  nucleo/   parser · geometria · fuentes · objetos · alinear_texto
            editar · editar_texto · sustitucion_fuente · guardar
  tools/    corpus · perfil · fidelidad · inspeccionar · benchmark
            preparar_entorno.sh · test_aceptacion
  tests/    54 tests, 0 fallos
  01 · 02 · 03 · 04 · 05 · 06 (este informe)
```

**Las cinco fases del MVP están cubiertas.** F0 (abrir y renderizar), F1
(selección), F2 (mover y borrar), F3 (redimensionar), F4 (edición de texto) y F5
(guardado incremental) están implementadas y medidas sobre el corpus completo.

Lo que queda por delante no es ninguna de esas fases: es **lo que convierte esto
en un programa que alguien puede usar**.

---

## 9. Qué haría falta ahora, por orden

1. **Ampliar el corpus con PDFs reales.** 20 facturas, contratos y artículos.
   Todo lo medido es sólido *sobre el corpus sintético*, y los PDFs reales son
   más sucios. Es la deuda más antigua y la que más puede invalidar.
2. **Robustez del guardado incremental**: `/XRefStm`, `ObjStm`, cifrado, y la
   compactación bajo demanda que dejó pendiente F2.
3. **Interfaz gráfica.** Sin ella no hay producto, y hay decisiones de UI que ya
   están forzadas por el núcleo: los objetos con `razones_no_editable` tienen que
   mostrarse con la razón a la vista, y el desborde avisarse antes de guardar.
4. **Memoria de trabajo y deshacer.** Ahora mismo cada edición recalcula sobre el
   stream original; falta el modelo de documento con estado.

---

## Reproducir

```bash
cd linuxpdf
bash tools/preparar_entorno.sh          # dependencias (no persisten entre sesiones)
python3 tests/test_texto.py             # 15 tests, 0 fallos
python3 tests/test_aceptacion.py        # 15 casos, 0 fallos
python3 tools/test_aceptacion.py        # con el detalle en pantalla
```

Artefactos: `resultados/f4/niveles_de_edicion.png` (los tres niveles, antes y
después), `resultados/f2/aceptacion.json` (las cifras de los 15 casos).
