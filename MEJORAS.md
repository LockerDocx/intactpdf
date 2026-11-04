# Mejoras aplicadas sobre IntactPDF

**Versión base:** [LockerDocx/intactpdf](https://github.com/LockerDocx/intactpdf), rama `main` (octubre de 2026), de **Gerard Morales**, licencia **AGPL-3.0-or-later**.

Este documento es el aviso de modificación que pide la AGPL (§5): describe qué
se cambió, por qué y cómo se verificó. El proyecto original, su autoría y su
licencia se conservan intactos; estas mejoras se distribuyen bajo la misma
licencia AGPL-3.0-or-later y con la misma atribución al autor original.

Todas las cifras de verificación son reproducibles: `python3 -m pytest tests/`
(138 pruebas: 127 originales + 11 nuevas) y `python3 tools/test_aceptacion.py`
(19/19 casos, 0 píxeles alterados fuera de la región permitida).

---

## 1. Bug corregido: la CLI guardaba siempre en la página 0

`nucleo/cli.py:_guardar` llamaba a `guardar_pagina_editada(..., 0, ...)` con el
número de página fijo a cero, aunque el usuario hubiera pasado `--pagina N`.
El resultado: editar la página 3 escribía el contenido editado **en los streams
de la página 0**. La verificación de tinta solía rechazar ese guardado (la
página 0 cambiaba de aspecto de golpe), pero la edición de cualquier página que
no fuera la primera estaba rota de facto.

**Corrección:** `_guardar` recibe `num_pagina` y todos los comandos pasan
`args.pagina`. Cubierto por `test_cli_move_respeta_la_pagina`, que edita la
página 1 y exige la página 0 renderizada **byte a byte idéntica**.

## 2. El preludio de borrado ya no destruye estado compartido

Al borrar un objeto, el código eliminaba también los operadores de estado
contiguos anteriores (`rg`, `w`, `gs`…) razonando que «pertenecían» al objeto
borrado. Pero ese razonamiento tiene un agujero: esos operadores **ya estaban
vigentes cuando se pintó el objeto siguiente** en el documento original.
Borrarlos cambia el color/grosor de todo lo que venga detrás que no fije su
propio estado — píxeles alterados fuera de la zona editada, justo lo que el
proyecto promete no hacer.

```pdf
0.5 0.5 0.5 rg  5 5 5 5 re f      <- vector gris
1 0 0 rg        10 10 50 50 re f  <- vector rojo (se borra)
                20 20 40 40 re f  <- NO fija color: en el original sale ROJO
```

Con el comportamiento anterior, borrar el vector rojo dejaba el tercero gris.

**Corrección:** `edicion_borrar(..., datos=...)` reemite el preludio **al final**
de la región borrada. La longitud del stream no cambia (el preludio ocupa el
sitio de los espacios de relleno), el objeto desaparece y el estado que hereda
el resto de la página es idéntico. `borrar_objeto` pasa `datos`
automáticamente; llamar a `edicion_borrar` sin `datos` conserva el
comportamiento histórico por compatibilidad. Cubierto por
`test_borrar_reemite_el_preludio_y_conserva_el_estado`.

## 3. `EditorPagina`: encadenar ediciones sin romper la regla de oro

Las `Edicion` son offsets absolutos de **un** snapshot del stream. Calcular una
edición sobre el resultado de otra sin volver a parsear corrompe el documento
en silencio (reproducido durante el análisis: al mover una imagen y luego
borrar un texto con los offsets viejos, se borró la geometría de un vector y
el texto siguiente heredó su color). Nada en la API avisaba de la trampa.

**Novedad:** `nucleo/editar.py:EditorPagina` guarda stream y contenido una vez
y acumula las ediciones contra ese snapshot, aplicándolas en una sola pasada:

```python
ed = EditorPagina(datos, contenido)
ed.mover(imagen, 50, 0).borrar(texto).escalar(vector, 1.2, 1.2, centro)
nuevo_stream = ed.aplicar()
```

Además, `aplicar_ediciones` ahora **rechaza rangos solapados** con un mensaje
que explica la causa probable (ediciones calculadas sobre snapshots
distintos), en lugar de escribir dos veces sobre el mismo byte. Cubierto por
cuatro pruebas nuevas.

## 4. Fidelidad píxel a píxel verificada en CADA guardado

El proyecto medía «0 píxeles fuera de la región editada» solo en su arnés de
tests (`tools/`), que no se instala. En tiempo de guardado solo existía la
comprobación de tinta (una página en blanco), que no detecta efectos
colaterales parciales.

**Novedad:** `nucleo/guardar.py:verificar_fidelidad` renderiza antes/después
con pdfium y compara muestra a muestra fuera de unas zonas editadas dadas —
sin numpy ni Pillow, con el mismo criterio de muestreo que `_tinta`.
`guardar_pagina_editada(..., zonas_editadas=[...])` la ejecuta en cada
escritura y **descarta el fichero si algo cambió fuera de la zona**. Los
comandos de edición de la CLI (`move`, `scale`, `delete`, `edit`) pasan sus
zonas automáticamente (incluyendo el desborde de texto en `edit`), así que la
promesa del proyecto se verifica en cada guardado real, no solo en CI.
Cubierto por tres pruebas nuevas, incluida una que exige que el fichero
descartado **no quede escrito**.

## 5. Nuevo comando `intactpdf diff`

El «¿cambió algo más?» llevado al CLI instalable:

```
intactpdf diff original.pdf editado.pdf
# página 1: 12.606 de 500.000 muestras distintas (2.521 %)
# resultado: HAY DIFERENCIAS visuales          (código de salida 1)

intactpdf diff original.pdf original.pdf
# resultado: IDÉNTICOS                          (código de salida 0)
```

Compara renders de pdfium página a página (`--paginas`, `--escala`,
`--tolerancia`). Sirve para auditar cualquier guardado, de este editor o de
otro. Cubierto por `test_cli_diff_identicos_y_distintos`.

## 6. Limpieza

- `editar.py:_dentro_de_texto`: eliminada una expresión muerta
  (`... - 1 if False else ...`) dejada de una refactorización; comportamiento
  idéntico, intención legible.

---

## Resumen de verificación

| Comprobación | Resultado |
|---|---|
| Suite original del proyecto | 127/127 (3 omitidas de empaquetado) |
| Pruebas nuevas de estas mejoras | 11/11 |
| Aceptación visual del proyecto (`tools/test_aceptacion.py`) | 19/19, 0 píxeles fuera |
| Prefijo binario idéntico | 19/19 |

## Lo que NO se ha tocado (a propósito)

- La GUI (`gui/`): hereda automáticamente el preludio seguro (usa
  `borrar_objeto`), pero no se le han cableado zonas de fidelidad estricta
  porque sus guardados agrupan varias operaciones del historial de deshacer;
  es el siguiente candidato natural para `zonas_editadas`.
- El escritor incremental, la escalera de edición de texto (1a/1b/2/0), la
  conjugación de matrices y el subsistema de fuentes: correctos según el
  análisis, no necesitaban cambios.
- Cifrado en guardado incremental: sigue rechazado, como en el original.
