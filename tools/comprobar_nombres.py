#!/usr/bin/env python3
"""Comprueba si un nombre está libre, en los sitios donde importa.

Antes de publicar nada hay que elegir nombre, y elegirlo mal se paga caro: el
identificador de una aplicación publicada **no se puede cambiar** en Flathub ni
en PyPI, porque hay gente que ya lo tiene instalado. Así que este script mira
los cuatro sitios que deciden, para cinco candidatos, y saca una tabla:

  - **PyPI**: si el nombre está cogido, `pip install` no puede usarlo.
  - **GitHub**: el usuario u organización; de él sale la URL de descarga y el
    identificador de Flathub (`io.github.usuario.Nombre`).
  - **Flathub**: si ya hay una aplicación con ese nombre.
  - **Dominio**: si `.org`, `.dev` o `.io` resuelven. Resolver no significa que
    esté libre (puede estar aparcado) y no resolver no lo garantiza del todo,
    pero para descartar sirve: quien busca un nombre quiere descartar rápido.

Lo que NO hace: reservar nada, ni decir «este es el bueno». Eso es una decisión
de quien publica.
"""
from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TIEMPO = 12          # segundos
AGENTE = "linuxpdf-studio-comprobador-nombres/0.1"

# Los candidatos. El orden es el de preferencia de quien escribe esto, y el
# criterio está explicado al lado: los que describen la promesa del programa
# (que lo que no se toca queda intacto) son mejores que los que describen lo
# que ya hacen otros.
CANDIDATOS = {
    "IntactPDF": {
        "pypi": "intactpdf", "github": "intactpdf", "flathub": "intactpdf",
        "dominios": ["intactpdf.org", "intactpdf.dev"],
        "por_que": "Dice exactamente lo que hace el programa: lo que no editas "
                   "queda intacto. Corto, se pronuncia igual en español y en "
                   "inglés, y no se parece a ningún editor de PDF que exista.",
    },
    "AsIsPDF": {
        "pypi": "asispdf", "github": "asispdf", "flathub": "asispdf",
        "dominios": ["asispdf.org", "asispdf.dev"],
        "por_que": "«Tal cual» en inglés, que es la promesa del guardado "
                   "incremental y se entiende en una palabra. En español "
                   "«así» también se dice así, que no estorba.",
    },
    "LinuxPDF Studio": {
        "pypi": "linuxpdf-studio", "github": "linuxpdf",
        "flathub": "linuxpdf", "dominios": ["linuxpdf.org", "linuxpdf.dev"],
        "por_que": "El nombre provisional de ahora. Es descriptivo y no se "
                   "confunde con nada, pero mete «Linux» en el nombre: si algún "
                   "día se porta a otro sistema, hay que cambiarlo, y eso en "
                   "Flathub significa identificador nuevo.",
    },
    "PDFByte": {
        "pypi": "pdfbyte", "github": "pdfbyte", "flathub": "pdfbyte",
        "dominios": ["pdfbyte.org", "pdfbyte.dev"],
        "por_que": "Alude a la garantía del prefijo de bytes, que es lo "
                   "técnicamente único de este programa. Más para técnicos que "
                   "para el público general.",
    },
    "PDFQuill": {
        "pypi": "pdfquill", "github": "pdfquill", "flathub": "pdfquill",
        "dominios": ["pdfquill.org", "pdfquill.dev"],
        "por_que": "Pluma: sugiere tocar poco y escribir sobre lo que ya hay, "
                   "que es exactamente la filosofía. Nombre bonito, pero no "
                   "dice nada técnico.",
    },
}


def pedir(url: str) -> tuple[int, str]:
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(peticion, timeout=TIEMPO) as r:
            return r.status, r.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:                       # red, DNS, tiempo agotado
        return 0, f"{type(e).__name__}: {e}"


def libre_pypi(nombre: str) -> str:
    codigo, _ = pedir(f"https://pypi.org/pypi/{nombre}/json")
    if codigo == 404:
        return "libre"
    if codigo == 200:
        return "COGIDO"
    return f"? ({codigo})"


def libre_github(nombre: str) -> str:
    codigo, _ = pedir(f"https://api.github.com/users/{nombre}")
    if codigo == 404:
        return "libre"
    if codigo == 200:
        return "COGIDO"
    if codigo == 403:
        return "? (límite de la API)"
    return f"? ({codigo})"


def buscar_flathub(consulta: str) -> str:
    # La búsqueda de Flathub es POST (probado: con GET contesta 405 y con
    # POST devuelve {"hits": […]}, cada hit con id y name). Devuelve el nombre
    # y el identificador de las tres primeras coincidencias: no es lo mismo que
    # un identificador libre, pero si ya hay algo parecido conviene saberlo
    # antes de enviar el paquete, no después.
    cuerpo = json.dumps({"query": consulta}).encode()
    peticion = urllib.request.Request(
        "https://flathub.org/api/v2/search", data=cuerpo,
        headers={"User-Agent": AGENTE, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=TIEMPO) as r:
            datos = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return f"? ({type(e).__name__})"
    hits = datos.get("hits") or []
    if not hits:
        return "nada parecido"
    return "hay: " + ", ".join(
        f"{h.get('name') or '?'} ({h.get('id') or '?'})" for h in hits[:3])


def libre_flathub(identificador: str) -> str:
    # El identificador exacto es lo que de verdad no se puede repetir. Un
    # programa nuevo se publica como io.github.<usuario>.<Nombre>, así que eso
    # es lo que se comprueba aquí.
    codigo, _ = pedir(f"https://flathub.org/api/v2/appstream/{identificador}")
    if codigo == 404:
        return "libre el identificador"
    if codigo == 200:
        return "COGIDO el identificador"
    return f"? ({codigo})"


def resuelve(dominio: str) -> str:
    try:
        socket.getaddrinfo(dominio, None)
        return "resuelve (probablemente cogido)"
    except socket.gaierror:
        return "libre"
    except Exception as e:
        return f"? ({type(e).__name__})"


def comprobar(nombre: str, datos: dict) -> dict:
    identificador = f"io.github.{datos['github']}.{nombre.replace(' ', '')}"
    return {
        "nombre": nombre,
        "pypi": libre_pypi(datos["pypi"]),
        "github": libre_github(datos["github"]),
        "flathub": f"{libre_flathub(identificador)}  ·  {buscar_flathub(datos['pypi'])}",
        "flathub_id": identificador,
        "dominios": {d: resuelve(d) for d in datos["dominios"]},
        "por_que": datos["por_que"],
    }


def main() -> int:
    print("\n  Comprobando cinco nombres en PyPI, GitHub, Flathub y DNS.")
    print("  Esto hace unas cuantas peticiones a internet; tarda unos segundos.\n")

    with ThreadPoolExecutor(max_workers=5) as pool:
        resultados = list(pool.map(lambda kv: comprobar(*kv), CANDIDATOS.items()))

    for r in resultados:
        print(f"  {'─' * 70}")
        print(f"  {r['nombre']}")
        print(f"    PyPI:    {r['pypi']}")
        print(f"    GitHub:  {r['github']}")
        print(f"    Flathub: {r['flathub']}")
        print(f"             se publicaría como {r['flathub_id']}")
        for dominio, estado in r["dominios"].items():
            print(f"    {dominio:22} {estado}")
        print(f"    por qué: {r['por_que']}")

    print(f"  {'─' * 70}")
    listos = [r["nombre"] for r in resultados
              if r["pypi"] == "libre" and r["github"] == "libre"]
    print(f"\n  Con el nombre de paquete y el de GitHub libres: "
          f"{', '.join(listos) if listos else 'ninguno'}")
    print("  (GitHub y PyPI son los que no se pueden cambiar después: la URL de")
    print("   descarga y el nombre que instala pip salen de ahí. El identificador")
    print("   de Flathub tampoco: quien lo tenga instalado no se entera si cambia.)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
