"""Genera la animación bilingüe del perfil (dist/intro.svg).

Lee las frases en español de intro.txt, las traduce al inglés con la API
gratuita de MyMemory y dibuja un SVG con efecto de escritura que alterna
cada frase en español y en inglés, sin etiquetas de idioma. Solo usa la biblioteca estándar de Python.

Uso:  python scripts/intro.py [archivo_entrada] [archivo_salida]
"""
import html
import json
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "intro.txt")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "dist/intro.svg")

# Paleta del perfil
CORAL, TURQ, OCEAN, CREAM, INDIGO = "#E3566A", "#73B3B9", "#1E89AB", "#F2E6D6", "#5C5579"

W, H = 720, 56
FONT_SIZE = 22
CHAR_W = FONT_SIZE * 0.6          # ancho aproximado de un carácter monoespaciado
TYPE, DELETE = 0.065, 0.03        # segundos por carácter al escribir / borrar
HOLD, GAP = 1.7, 0.35             # pausa con la frase completa / pausa entre frases


def read_lines(path: Path) -> list[str]:
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    return [l for l in lines if l and not l.startswith("#")]


def translate(text: str) -> str | None:
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
        {"q": text, "langpair": "es|en"})
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.load(r)
        out = (data.get("responseData") or {}).get("translatedText", "").strip()
        if data.get("responseStatus") == 200 and out and "MYMEMORY WARNING" not in out.upper():
            return html.unescape(out)
    except Exception as e:  # la animación se genera igual, solo sin esa traducción
        print(f"Aviso: no se pudo traducir «{text}»: {e}", file=sys.stderr)
    return None


def width_units(text: str) -> list[float]:
    """Ancho acumulado (en caracteres) después de cada carácter; los emojis cuentan doble."""
    acc, out = 0.0, []
    for ch in text:
        if unicodedata.category(ch) in ("Mn", "Cf") or ch == "️":
            out.append(acc)
            continue
        acc += 2 if ord(ch) > 0x2500 and unicodedata.category(ch) == "So" else 1
        out.append(acc)
    return out


def build(pairs: list[tuple[str, str]]) -> str:
    seq = []
    for es, en in pairs:
        seq.append(("ES", es))
        if en:
            seq.append(("EN", en))

    # Línea de tiempo: inicio y duración de cada frase
    spans, t = [], 0.0
    for _, text in seq:
        n = len(text)
        dur = n * TYPE + HOLD + n * DELETE + GAP
        spans.append((t, dur))
        t += dur
    total = t

    parts = []
    for i, ((lang, text), (start, dur)) in enumerate(zip(seq, spans)):
        cum = width_units(text)
        text_w = (cum[-1] if cum else 0) * CHAR_W
        x0 = (W - text_w) / 2
        # fotogramas: (tiempo, ancho visible)
        frames = [(start, 0)]
        for k, c in enumerate(cum):
            frames.append((start + (k + 1) * TYPE, c * CHAR_W))
        t_full = start + len(text) * TYPE + HOLD
        frames.append((t_full, text_w))
        for k in range(len(cum) - 1, -1, -1):
            prev = cum[k - 1] * CHAR_W if k > 0 else 0
            frames.append((t_full + (len(cum) - k) * DELETE, prev))
        frames.append((start + dur, 0))
        if start > 0:
            frames.insert(0, (0, 0))
        if start + dur < total:
            frames.append((total, 0))
        key_times = ";".join(f"{ft / total:.5f}" for ft, _ in frames)
        widths = ";".join(f"{w:.1f}" for _, w in frames)
        xs = ";".join(f"{x0 + w + 2:.1f}" for _, w in frames)

        # visibilidad del cursor
        vis_times = sorted({0.0, start / total, (start + dur - GAP) / total, 1.0})
        vis_vals = ["1" if start / total <= v < (start + dur - GAP) / total else "0" for v in vis_times]
        vt, vv = ";".join(f"{v:.5f}" for v in vis_times), ";".join(vis_vals)

        parts.append(f'''
  <clipPath id="c{i}"><rect x="{x0:.1f}" y="0" height="{H}" width="0">
    <animate attributeName="width" values="{widths}" keyTimes="{key_times}" dur="{total:.2f}s" calcMode="discrete" repeatCount="indefinite"/>
  </rect></clipPath>
  <g opacity="0">
    <animate attributeName="opacity" values="{vv}" keyTimes="{vt}" dur="{total:.2f}s" calcMode="discrete" repeatCount="indefinite"/>
    <rect y="{H / 2 - 13}" width="3" height="26" fill="{TURQ}">
      <animate attributeName="x" values="{xs}" keyTimes="{key_times}" dur="{total:.2f}s" calcMode="discrete" repeatCount="indefinite"/>
      <animate attributeName="fill-opacity" values="1;0" dur="0.9s" calcMode="discrete" repeatCount="indefinite"/>
    </rect>
  </g>
  <text x="{x0:.1f}" y="{H / 2 + 7.5}" class="t" clip-path="url(#c{i})">{html.escape(text)}</text>''')

    alt = " / ".join(f"{t}" for _, t in seq)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(alt)}">
  <title>{html.escape(alt)}</title>
  <style>
    .t {{ font: 600 {FONT_SIZE}px 'Fira Code','JetBrains Mono',Consolas,'Courier New',monospace; fill: {CORAL}; }}
  </style>{"".join(parts)}
</svg>
'''


def main() -> None:
    lines = read_lines(SRC)
    pairs = []
    for line in lines:
        es, _, en = (part.strip() for part in line.partition("|"))
        pairs.append((es, en or translate(es)))
    for es, en in pairs:
        print(f"ES: {es}\nEN: {en or '(sin traducción)'}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(pairs), encoding="utf-8")
    print(f"Generado {OUT}")


if __name__ == "__main__":
    main()
