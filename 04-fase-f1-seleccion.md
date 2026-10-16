# Fase F1 — Selección de objetos: la puerta de viabilidad

**Fecha:** 2026-10-15
**Estado:** F1 implementada y medida sobre los 11 PDFs del corpus. **La puerta se abre.**

---

## 1. Qué había que demostrar

En `01-idea-raw.md` la fase F1 se marcó como *la puerta de viabilidad*: parsear el
content stream, identificar objetos y permitir seleccionarlos. Si esto no se puede
hacer con precisión, no hay editor in-place, y sin edición in-place el proyecto no
tiene razón de existir.

Tres preguntas concretas:

1. ¿Se puede recorrer el content stream interpretando el estado gráfico y agrupar
   operadores en objetos con sentido para un usuario?
2. ¿Se puede saber **dónde está cada carácter** de un texto, que es lo que exige
   editarlo sin rehacer la línea?
3. ¿Es lo bastante rápido para que un clic se sienta instantáneo?

Respuestas medidas: **sí, sí, y sí** (con una optimización obligatoria que detallo
en la sección 5).

---

## 2. Qué se ha construido

Sin dependencias AGPL, coherente con la decisión B1. El núcleo es propio; pdfium
se usa solo para posiciones y renderizado, y el día que haya que sustituirlo está
aislado en un módulo.

| fichero | líneas | qué hace |
|---|---|---|
| `nucleo/parser.py` | 294 | Lexer y parser del content stream. Tokens con su offset para poder reescribir, agrupación en instrucciones. |
| `nucleo/geometria.py` | 180 | Matrices afines, cajas, transformación a coordenadas de página (incluido `/Rotate`). |
| `nucleo/fuentes.py` | 207 | Resolución de fuentes: bytes por código, CMap `/ToUnicode`, detección de subconjuntos. |
| `nucleo/objetos.py` | 610 | El corazón: recorre el stream con el estado gráfico y extrae objetos. |
| `nucleo/alinear_texto.py` | 324 | Empareja los runs con las posiciones reales de carácter de pdfium. |

**Tipos de objeto extraídos:** `TextoRun`, `Imagen`, `Vector`, `Sombreado`.
Cada uno lleva su caja, su CTM, los recortes que le aplican y una lista
`razones_no_editable` que dice **por qué** no se puede editar con seguridad.

**Cobertura medida en los 11 PDFs: 149 objetos** — 84 de texto, 63 vectoriales,
2 de imagen.

---

## 3. El resultado que importa

```
  archivo                        runs alineados   chars sin posición
  00_baseline                          2/2               0
  01_texto_fragmentado                18/18              0
  02_fuente_subset                     4/4               0
  03_vectores_clip_degradado           3/3               0
  04_imagen_smask                      2/2               0
  05_cmyk_imprenta                     2/2               0
  06_modos_de_texto                    6/6               0
  07_paginas_rotadas_mixtas            1/1               0
  08_formularios_anotaciones           4/4               0
  09_documento_grande                 39/39             38
  10_fuente_completa                   3/3               0
  ------------------------------------------------------------------
  TOTAL                               84/84             38
```

**84 de 84 runs alineados.** El caso que se diseñó para ser el más difícil —
`01_texto_fragmentado`, 1.746 operadores de texto en una sola página por culpa de
un `charSpace` manual— se alinea entero y carácter a carácter, y el texto sale
legible (`El rápido zorro ñandú saltó sobre...`).

Vale la pena subrayar lo que implica: **editar texto sin rehacer la línea deja de
ser un problema abierto.** Se sabe dónde está cada carácter. Lo que falta no es
información, es la lógica de re-subsetting de fuentes (fase F4).

### Los 38 caracteres sin posición no son un fallo

En la página de 300 líneas pdfium devuelve 2.856 caracteres donde el parser cuenta
2.894. La diferencia son **38 espacios dobles**: el PDF escribe `1.1··El` y pdfium
entrega `1.1·El`, porque colapsa espacios consecutivos.

El alineador declara esos 38 caracteres como *sin posición* en vez de repartirlos
mal. La cuenta cuadra exactamente:

```
  chars_sin_posicion (38) == chars_que_cuenta_el_parser - chars_reales (2894 - 2856)
```

Eso es lo correcto: 38 caracteres que no se pueden posicionar con certeza quedan
marcados, y la UI podrá permitir mover o borrar esa línea sin ofrecer edición
carácter a carácter. **Un editor que no sabe dónde es fiable tiene que decirlo.**

---

## 4. Errores que costaron tiempo, por si reaparecen

Cinco, y cuatro de ellos producían fallos silenciosos. Los anoto porque son el
tipo de cosa que se repite.

**1. `pikepdf.Object.__getattr__` interpreta cualquier atributo como clave PDF.**
Esto rompía todo `_get()` sin lanzar nada visible:

```python
hasattr(un_nombre_pdf, "get_object")
# ValueError: pikepdf.Object is not a Dictionary or Stream
# (y hasattr NO lo captura, porque solo traga AttributeError)
```

Solución: buscar el método en la **clase**, no en la instancia
(`getattr(type(obj), "get_object", None)`).

**2. En pikepdf las claves de diccionario llevan la barra inicial.** Al revés de
lo que dice la especificación PDF (donde la clave es `Subtype`, sin barra).
Así que `d["Subtype"]` lanza `KeyError` y `d["/Subtype"]` funciona. Esto hacía
que el caso 10 se resolviera como fuente de 1 byte cuando es Type0/Identity-H de
2 bytes, y por tanto que el parser contara **el doble** de caracteres.

**3. `/BaseFont` llega como `/AAAAAA+DejaVuSans`, con barra.** El regex de
detección de subconjuntos `^[A-Z]{6}\+` nunca casaba.

**4. pdfium inventa caracteres y omite otros.** Añade `\r\n` sintéticos entre
bloques de texto (34 en el caso 01) y se come los espacios finales de línea y los
consecutivos. Nada de eso está en el PDF. Cualquier alineación que asuma conteos
iguales entre parser y pdfium está rota de base.

**5. La alineación voraz sin verificación asigna caracteres equivocados.** Este
fue el peor. La primera versión alineaba secuencialmente y reportaba **39/39 runs
alineados** en la página de 300 líneas… estando todos mal, porque a partir del
primer desfase repartía caracteres desplazados. Ahora cada run se verifica contra
el texto que descodificó el parser y se rechaza si no coincide.

**Un bug de diseño, no de código:** el hit-test usaba la caja envolvente del clip.
Un círculo trazado con Béziers tiene su caja *fuera* de la curva, así que hacer
clic en la esquina de un degradado circular seleccionaba uno de los 60
rectángulos que el clip recorta y que **visualmente no están ahí**. Corregido
aplanando las Béziers y probando la trayectoria real con point-in-polygon.

---

## 5. Rendimiento: hacía falta una optimización, y era gorda

Primera medición, página de 300 líneas del caso `09_documento_grande`:

| etapa | antes | después |
|---|---|---|
| extraer objetos | 4,9 ms | 4,9 ms |
| alinear | **421 ms** | **12,7 ms** |
| renderizar | 4,3 ms | 4,3 ms |
| **total por página** | **431 ms** | **22 ms** |

El culpable era `difflib.SequenceMatcher` sobre ~2.900 caracteres: 402 ms de los
421. Y era innecesario, porque las dos únicas diferencias que introduce pdfium son
espacios. Un escaneo lineal de dos punteros lo resuelve en O(n) con el mismo
resultado exacto (84/84 y los mismos 38 huecos). `difflib` queda solo como
reserva si el emparejamiento lineal reconoce menos de la mitad del texto.

Segunda mejora: pedir el texto de la página en una sola llamada
(`get_text_range(0, n)`) en vez de carácter a carácter — 0,1 ms frente a 17,7 ms,
**177 veces menos**.

Resultado en los 11 PDFs:

```
  archivo                         págs   extraer   alinear    render    total
  00_baseline                        1      1.4ms      2.4ms      5.1ms      9ms
  01_texto_fragmentado               1     23.3ms     10.0ms      8.2ms     41ms
  02_fuente_subset                   1      1.4ms      1.3ms      2.3ms      5ms
  03_vectores_clip_degradado         1      3.2ms      1.4ms      3.2ms      8ms
  04_imagen_smask                    1      0.8ms      1.2ms      6.6ms      9ms
  05_cmyk_imprenta                   1      0.9ms      1.1ms      7.4ms      9ms
  06_modos_de_texto                  1      1.7ms      1.9ms      3.5ms      7ms
  07_paginas_rotadas_mixtas          5      0.7ms      0.3ms      1.5ms      3ms
  08_formularios_anotaciones         1      0.9ms      1.2ms      2.0ms      4ms
  09_documento_grande              300      4.9ms     12.7ms      4.3ms     22ms
  10_fuente_completa                 1      0.6ms      4.3ms      2.4ms      7ms
  -----------------------------------------------------------------------------
  peor página: 41 ms          presupuesto: 100 ms          veredicto: pasa
```

La peor página es `01_texto_fragmentado`, y ahora el cuello de botella es el
**parser** (23 ms de 41) por culpa de sus 1.746 instrucciones, no la alineación.
Sigue sobrando margen.

---

## 6. Tests: 34, todos en verde

```
  tests/test_parser.py     11   lexer, escapes, offsets, arrays, corpus completo
  tests/test_objetos.py    23   geometría, fuentes, extracción, alineación, hit-test
```

Los que de verdad vigilan la puerta:

- `test_corpus_completo_alinea_todos_los_runs` — exige 84/84. Si alguien rompe la
  alineación, esto lo dice.
- `test_09_declara_los_huecos_en_vez_de_inventarlos` — exige que los 38 caracteres
  sin posición coincidan **exactamente** con la discrepancia de conteo. Verifica
  que el alineador no está inventando.
- `test_hit_test_respeta_el_clip` — un clic en la zona recortada de un degradado
  circular no selecciona nada recortado.
- `test_texto_invisible_no_se_alinea_a_ciegas` — el texto con `Tr 3` no lo extrae
  pdfium; no debe alinearse contra el de otro objeto.
- `test_fuente_type0_identity_h_usa_dos_bytes` — el caso que hacía contar el doble.

```bash
python3 tests/test_parser.py     # 0 fallos
python3 tests/test_objetos.py    # 0 fallos, imprime la tabla de alineación
```

---

## 7. Demostración visible

```bash
python3 tools/inspeccionar.py corpus/04_imagen_smask.pdf --clic 220,660 --png /tmp/x.png
```

Lista los objetos, resuelve un clic, dice cuáles son editables y por qué no los
que no, y dibuja las cajas sobre la página renderizada
(`resultados/f1/01_seleccion.png`, `03_seleccion.png`, `04_clic.png`).

Lo que se ve: las cajas azules ajustan el texto al píxel, la imagen seleccionada
por clic lleva marco naranja, los 60 rectángulos del degradado van boxeados uno a
uno y la estrella de 14 segmentos tiene el suyo.

---

## 8. Límites de lo medido

Lo mismo que en la validación empírica, y por las mismas razones: no conviene
citar estos números como definitivos.

- **El corpus es sintético.** 11 PDFs fabricados por mí. Son duros a propósito en
  las dimensiones que importan, pero no sustituyen a PDFs reales. El default D1
  pide ~20 reales y siguen faltando.
- **No hay interfaz gráfica.** `inspeccionar.py` dibuja cajas sobre una imagen ya
  renderizada. La selección funciona y está medida; la experiencia de clicar y
  arrastrar, no.
- **La alineación depende de pdfium.** Es correcto y es rápido, pero es una
  dependencia real: si algún día se sustituye, este módulo se reescribe. Está
  aislado para eso.
- **El hit-test de vectores usa caja envolvente**, no la trayectoria, salvo para
  los recortes. Es el comportamiento de D5 (tolerante, del más pequeño al más
  grande) y es lo que hacen Inkscape y compañía. Tiene una consecuencia conocida:
  hacer clic en la esquina de la caja de un círculo selecciona el círculo aunque
  el píxel sea blanco. Con el aro del caso 03 pasa exactamente eso.
- **Sólo se mide la primera página** de cada documento en los tests de alineación.
  El caso 09 tiene 300 idénticas por construcción, así que no aporta medir más.

---

## 9. Qué cambia en el plan

**La puerta F1 está abierta**, así que el orden de trabajo no cambia pero sí se
confirma la estimación: F2 (mover y borrar imagen y vector) es viable porque los
objetos ya están identificados con su caja y sus instrucciones, y el guardado
incremental puede reescribir exactamente el rango de bytes que ocupa el objeto.

**F4 (edición de texto) sigue siendo la más cara**, pero por una razón más
estrecha de lo que parecía: ya no es «saber dónde está cada carácter», es
**re-subsetting de fuentes** — construir un subconjunto nuevo que incluya el glifo
que el usuario escribe y no estaba. Eso es acotado y es trabajo conocido.

**Una decisión de producto que sale de aquí y conviene fijar:** los objetos con
`razones_no_editable` no vacías deben mostrarse en la UI con la razón a la vista,
no desaparecer ni fallar en silencio. El caso 06 (texto invisible) y los 38
caracteres del caso 09 son exactamente el escenario: el usuario tiene que poder
mover y borrar, y saber que no puede reescribir ahí.

---

## Reproducir

```bash
cd linuxpdf
python3 tests/test_parser.py
python3 tests/test_objetos.py
python3 tools/benchmark_f1.py
python3 tools/inspeccionar.py corpus/04_imagen_smask.pdf --clic 220,660
```
