# 8 · PDFs reales: qué destaparon

Todo lo que había probado hasta aquí eran PDFs hechos por mí, y un corpus que uno
escribe tiende a parecerse a lo que su programa sabe leer. Así que pedí documentos
de servidores públicos de verdad, los descargué y pasé el editor por encima. Tres
de ellos rompieron el programa, cada uno por un motivo distinto y ninguno previsible
desde dentro.

## Los documentos

Descargados el 16 de octubre de 2026, todos con respuesta `200` y tipo
`application/pdf`. Están en `/home/user/PDFs-reales/` (fuera del repositorio).

| documento | tamaño | qué tiene dentro |
|---|---|---|
| `arxiv.org/pdf/1706.03762` (Attention Is All You Need) | 2,2 MB | 15 páginas, 113 anotaciones, **2 streams de contenido** |
| `irs.gov/pub/irs-pdf/f1040.pdf` (formulario 1040) | 216 K | **229 campos de formulario**, 199 anotaciones, 8 streams |
| `govinfo.gov/content/pkg/GPO-CONAN-2017/pdf/GPO-CONAN-2017.pdf` | 19,8 MB | **2.882 páginas**, 26.688 anotaciones, 8 streams |
| `boe.es/buscar/pdf/1978/BOE-A-1978-31229-consolidado.pdf` (Constitución) | 324 K | 39 páginas, 87 anotaciones |
| `ohchr.org/.../UDHR_Translations/spn.pdf` (Declaración Universal) | 184 K | 9 páginas |
| `w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf` | 13 K | el mínimo de siempre |
| `unec.edu.az/application/uploads/2014/12/pdf-sample.pdf` | 8 K | una página |
| `orimi.com/pdf-test.pdf` | 20 K | **cifrado** con contraseña vacía y linearizado |

Dos que se suelen recomendar en los tutoriales **han dejado de existir** (dan 404):
`nasa.gov/wp-content/uploads/2023/03/earth-observations.pdf` y
`africau.edu/images/default/sample.pdf`. No los busques.

## Lo que destaparon, por orden de gravedad

### 1. «Una página = un stream de contenido» es falso

El editor exigía **un** stream de contenido por página y abortaba con «la página
tiene 8 streams de contenido y se han pasado 1 contenidos». Le pasaba a arXiv, al
IRS y al documento del Gobierno: exactamente los tres documentos más interesantes
de la lista.

El error estaba en el modelo, no en el código. La especificación (§7.8.2) dice que
el contenido de una página es la **concatenación** de sus streams: ocho trozos son
un solo programa. Con varios streams y una edición, ahora el contenido entero va al
primero y los demás quedan vacíos; la concatenación sigue siendo la editada y el
objeto de página no se toca.

### 2. El `Q` se llevaba por delante el texto de toda la página

El más grave, y el que más costó entender, porque **todo decía que iba bien**: el
prefijo intacto, las páginas y los campos igual, qpdf sin una queja nueva, poppler
renderizando el resultado. Lo que no se veía era el texto: la portada del documento
del Gobierno aparecía en blanco, con el escudo flotando en medio.

El objeto editado se envuelve en `q … cm … Q` para escalarlo. El `Q` devuelve el
estado gráfico al valor que tenía antes del `q`, y **el estado de texto forma parte
del estado gráfico** (§9.3). Ese documento pone la fuente una sola vez, en el
primer objeto de texto, y todo lo demás escribe sin volver a ponerla. Al cerrar el
`q … Q` en mitad del texto, la fuente desaparecía y **todo el texto de la página se
quedaba sin dibujar**.

La solución es reponer el estado de texto después del `Q` — la fuente sobre todo,
y también el espaciado (que este documento sí usa). Y hay un detalle que hizo falta
un segundo intento: el estado que hay que reponer es el que el documento tenía **al
salir** de la región editada, no al entrar. Mirando al entrar no se reponía nada,
porque el objeto empieza precisamente poniendo la fuente.

Medido en el documento real: la tinta de la página pasa de 7,01 % a **6,97 %**
(antes del arreglo: 1,55 %), y los píxeles que cambian fuera de la cabecera editada
son **0,00 %**.

### 3. Un documento cifrado no se puede escribir en claro

`orimi.com/pdf-test.pdf` va cifrado con contraseña vacía. Se abre sin pedir nada
—pikepdf no se queja— y el guardado incremental escribía el stream nuevo **en
claro** dentro de un fichero que dice estar cifrado. Un lector que respeta el
cifrado descifra esos bytes y obtiene basura: la página en blanco.

Conservar el cifrado al escribir es un pendiente de verdad (hay que cifrar el
stream nuevo con la misma clave). Mientras tanto el documento se rechaza **al
abrir**, con el motivo delante, en la consola y en la ventana. Es mejor decir «esto
no lo sé hacer todavía» que devolver un fichero que abre vacío.

## La lección que se queda

El prefijo intacto garantiza que **nada más ha cambiado**, pero no que el fichero
**se vea**. Son dos promesas distintas. A partir de ahora el guardado las comprueba
las dos: antes de dar por bueno un fichero, renderiza la página con pdfium (el motor
de la propia vista previa) y compara la tinta con la del original; si el original
tenía contenido y la salida no tiene casi nada, **se borra lo escrito y se dice por
qué**. Un fichero a medias es peor que ningún fichero: parece que el trabajo está
hecho.

## Cómo repetirlo

```bash
python3 tools/prueba_real.py        # borra antes los *-editado.pdf de la carpeta
```

El guion mide, para cada documento: páginas, campos de formulario y anotaciones
antes y después, que el original esté al principio byte a byte, que la página siga
teniendo tinta y que qpdf no diga nada que no dijera ya del original. Ese último
matiz importa: el documento del Gobierno ya viene con un stream sin `/Length` y el
cifrado con tabla híbrida, y son avisos **suyos**, no nuestros.

## Lo que sigue faltando

- **Conservar el cifrado** al escribir (hoy se rechaza el documento).
- **Más documentos reales**: ocho es una muestra, y los tres fallos de arriba
  salieron de tres de ellos. Cuantos más, menos cosas quedan por descubrir.
