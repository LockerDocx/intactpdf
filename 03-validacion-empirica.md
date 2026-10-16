# Validación empírica: ¿qué pasa realmente al pasar un PDF por LibreOffice Draw?

**Fecha:** 2026-10-15
**Entorno:** sandbox Debian, LibreOffice **25.2.3.2** (headless), pdfium vía `pypdfium2`, `qpdf`, `poppler-utils`.
**Reproducir:** `python3 tools/generar_corpus.py && python3 tools/perfilar_corpus.py && python3 tools/medir_fidelidad.py`

---

## 1. Qué se midió exactamente

Para cada PDF del corpus se hicieron tres operaciones y se comparó el render antes y después (144 dpi, umbral 12 por canal):

| Operación | Qué hace | Para qué sirve |
|---|---|---|
| `identidad` | Compara el PDF consigo mismo | **Control:** si esto no da 0, el arnés está roto |
| `qpdf` | `qpdf --qdf` (round-trip lossless) | **Control:** reescribir el archivo sin tocar la semántica |
| `libreoffice` | `PDF → .odg → PDF` con `soffice --headless` | Lo que hace un editor que **reconstruye** el documento |

**Límite honesto de la medición:** el camino `PDF → .odg → PDF` es el mismo pipeline de importación/exportación que usa la interfaz gráfica de Draw, pero **no he abierto la GUI ni he hecho clics**. Lo que mido es el coste de *pasar por el editor*, no el coste de una edición concreta. Eso es deliberado y es lo interesante: si un round-trip sin editar nada ya falla, ninguna edición hecha así puede cumplir RF7.

---

## 2. Los controles pasan: el arnés no miente

```
identidad   -> IDENTICO  0.000% px   en los 11 PDFs
qpdf        -> IDENTICO  0.000% px   en los 11 PDFs
```

Esto es lo primero que había que comprobar. Reescribir un PDF byte a byte distinto (`--qdf` normaliza y descomprime) **no cambia ni un píxel**. Cualquier diferencia que aparezca más abajo es de la operación, no del arnés.

---

## 3. Resultado principal: Draw no preserva nada

| PDF | px distintos (peor página) | veredicto | tamaño antes → después |
|---|---|---|---|
| 00_baseline (2 líneas de texto) | **0,690 %** | CAMBIOS_MENORES | 25,2 K → 20,8 K (−18 %) |
| 01_texto_fragmentado | **9,775 %** | RECONSTRUIDO | 27,8 K → 23,4 K (−16 %) |
| 02_fuente_subset | 0,400 % | CAMBIOS_MENORES | 78,7 K → 26,6 K (−66 %) |
| 03_vectores_clip_degradado | 0,614 % | CAMBIOS_MENORES | 23,1 K → 33,7 K (+46 %) |
| 04_imagen_smask | **6,375 %** | RECONSTRUIDO | 186,4 K → 56,6 K (−70 %) |
| 05_cmyk_imprenta | **11,797 %** | RECONSTRUIDO | 97,2 K → 55,2 K (−43 %) |
| 06_modos_de_texto | **1,847 %** | RECONSTRUIDO | 42,7 K → 29,1 K (−32 %) |
| 07_paginas_rotadas_mixtas | 0,435 % | CAMBIOS_MENORES | 23,7 K → 22,2 K (−6 %) |
| 08_formularios_anotaciones | **1,848 %** | RECONSTRUIDO | 28,3 K → 19,4 K (−31 %) |
| 10_fuente_completa | 0,744 % | CAMBIOS_MENORES | 375,2 K → 18,0 K (−95 %) |

**32 mediciones: 11 `identidad` + 11 `qpdf` + 10 `libreoffice`.** En LibreOffice, `IDENTICO` aparece **0 veces en 10**. Hasta el PDF de control —dos líneas de texto negro sobre blanco, sin imágenes, sin vectores— sale con el 0,69 % de sus píxeles distintos después de un round-trip en el que no se editó nada.

---

## 4. Los cuatro hallazgos duros

### 4.1 Los formularios y enlaces desaparecen en silencio

```
08_formularios_anotaciones
  antes : AcroForm=True   anotaciones=4
  tras  : AcroForm=False  anotaciones=0
```

Dos campos de texto, un checkbox y un enlace. Después del round-trip: **cero**. Sin aviso, sin error, sin mensaje. El archivo sale más pequeño (−31 %) y aparentemente bien.

Para un usuario que edita un contrato o un formulario administrativo, esto no es un problema estético: es pérdida de datos irreversible y silenciosa.

### 4.2 CMYK se convierte a RGB sin pedirlo

```
05_cmyk_imprenta
  antes : /DeviceCMYK   filtro [ASCII85Decode, DCTDecode]
  tras  : /DeviceRGB    filtro DCTDecode
```

Un PDF de imprenta entra en CMYK y sale en RGB. **11,797 % de los píxeles de la página cambian** — el peor resultado del corpus. Para alguien que prepara artes finales, esto invalida el archivo.

### 4.3 Las imágenes se recodifican con pérdida

```
04_imagen_smask
  antes : [ASCII85Decode, FlateDecode]  (sin pérdida)
  tras  : DCTDecode                      (JPEG, con pérdida)
```

El tamaño cae un 70 %. No es compresión inteligente: es recodificación JPEG. El canal alfa (SMask) sobrevive, pero los datos de la imagen ya no son los mismos.

### 4.4 Una página apaisada cambia de dimensiones

```
07_paginas_rotadas_mixtas
  página 2 antes : 841,89 × 595,28 pt   (A4 apaisado)
  página 2 tras  : 595,28 × 841,89 pt   (A4 vertical)
```

Y el texto extraído pasa de **167 a 189 caracteres**: el round-trip *añadió* contenido. Es el único caso del corpus donde cambia el número de caracteres.

---

## 5. Lo que NO se rompe (importante para no exagerar)

**El texto se conserva en todos los casos.** Los caracteres extraídos son idénticos antes y después en 9 de 10 PDFs (solo `07` cambia, y sube). En `01_texto_fragmentado`, con 1.746 operadores de texto en una página, el texto extraído es **byte a byte idéntico**.

Entonces el titular correcto no es "Draw pierde texto". Es:

> **Draw conserva el texto y reconstruye todo lo demás.**

Y el 9,775 % de píxeles distintos en `01` con el texto intacto significa una cosa concreta: el texto está en las mismas posiciones lógicas pero **se pinta distinto** — sustitución de tipografía, métricas diferentes, espaciado recalculado. Es exactamente el fallo que reportan los usuarios.

También hay que decir que las fuentes se re-subconjuntan sistemáticamente:

```
02_fuente_subset     antes: /Helvetica, /AAAAAA+DejaVuSans, /AAAAAA+DejaVuSans-Bold
                     tras : /BAAAAA+DejaVuSans, /CAAAAA+DejaVuSans-Bold
10_fuente_completa   antes: /DejaVuSans            (completa, 375 K)
                     tras : /BAAAAA+DejaVuSans     (subconjuntada, 18 K = −95 %)
```

---

## 6. Qué significa esto para el proyecto

**Confirma la corrección del documento anterior, y la endurece.** El hueco no es "editar PDFs en Linux". Es:

> Un editor cuyo round-trip **sin editar nada** ya no cumple "todo lo demás sigue igual" no puede cumplirlo cuando el usuario edita algo.

Eso deja una sola arquitectura viable: **edición in-place con guardado incremental** (RF7). No es una preferencia de diseño, es la única que satisface el requisito. Y es precisamente lo que un pipeline `PDF → modelo intermedio → PDF` no puede hacer por construcción.

**Reformula el valor:** no es solo "conserva el layout". Es **"no destruye cosas silenciosamente"**. Un usuario que pierde un formulario o un CMYK sin aviso tiene un problema mucho mayor que uno que ve el texto descuadrado.

**Da el test de aceptación, ya implementado:** `tools/medir_fidelidad.py` con `identidad` y `qpdf` como controles. Cuando exista el editor, se añade una cuarta operación —`linuxpdf: editar objeto X`— y el requisito es que el diff de píxeles sea **cero en todo lo que no sea el objeto editado**. Ese test ya está escrito; solo falta el editor.

---

## 7. Advertencias sobre esta medición

- **El corpus es sintético.** Son 11 PDFs generados por mí para atacar casos concretos. Los PDFs reales suelen ser peores, no mejores. Hace falta ampliarlo con documentos del mundo real (facturas bancarias, contratos, folletos, PDF/A) antes de publicar cifras como definitivas.
- **Es headless, no la GUI.** Mismo pipeline de import/export, pero no he verificado que la interfaz no añada su propia capa de cambios.
- **`06_modos_de_texto` cambió entre pasadas** (1,344 % → 1,847 %) porque añadí los modos `2 Tr` y `3 Tr` al generador. Las cifras de esta tabla son de la pasada final, con los 11 PDFs actuales.
- **Umbral de 12 por canal.** Es tolerante al antialiasing. Con umbral 0 las cifras subirían, pero también subiría el ruido.
- **Solo se comparan las 12 primeras páginas**, por coste. En `09_documento_grande` (300 páginas) no se ejecutó la operación de LibreOffice; por eso son 10 PDFs medidos y no 11.

---

## 8. Artefactos

| Ruta | Qué es |
|---|---|
| `corpus/*.pdf` | 11 PDFs de prueba, cada uno atacando un caso |
| `corpus/manifest.json` | descripción de cada caso |
| `corpus/_tmp_*.{png,jpg}` | imágenes fuente de los casos 04 y 05 (reportlab necesita archivos reales, no bytes en memoria) |
| `corpus/perfil.json` | dificultad estructural medida (no declarada) |
| `resultados/fidelidad.json` | 32 mediciones de diff de píxeles |
| `resultados/muestra_texto.json` | texto extraído antes/después |
| `tools/generar_corpus.py` | generador del corpus |
| `tools/perfilar_corpus.py` | perfilador estructural |
| `tools/medir_fidelidad.py` | arnés de fidelidad (el futuro test de aceptación) |

### Los 11 casos del corpus

| # | Caso | Dificultad medida |
|---|---|---|
| 00 | Control, PDF trivial | 2 ops de texto, sin imágenes ni vectores |
| 01 | Texto fragmentado | **1.746 ops de texto en 1 página** (letra a letra con charSpace) |
| 02 | Fuente subconjuntada | `/AAAAAA+DejaVuSans`, glifos limitados |
| 03 | Vectores con clip y degradado | 143 ops de pintado, 1 clip |
| 04 | Imagen con SMask | 1 imagen RGBA, canal alfa real |
| 05 | CMYK de imprenta | `/DeviceCMYK` en imagen y rellenos |
| 06 | Modos de texto raros | `0 Tr`, `1 Tr`, `2 Tr`, `3 Tr` + texto recortado |
| 07 | Páginas rotadas y mixtas | 4 tamaños, `/Rotate 90` real |
| 08 | Formularios y anotaciones | AcroForm + 4 anotaciones + enlace |
| 09 | Documento grande | 300 páginas, 11.700 ops de texto |
| 10 | Fuente completa sin subconjuntar | TTF completa embebida, 375 K |
