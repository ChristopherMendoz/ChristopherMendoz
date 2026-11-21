"""Genera el texto animado del banner (assets/banner.svg).

Tres animaciones del perfil, todas con efecto de escritura:
  1. intro.svg (scripts/intro.py): «Bienvenidos» en español e inglés.
  2. El nombre, que se escribe una vez al cargar.
  3. La carrera, que alterna español e inglés.

Cada letra es un <tspan> que aparece y desaparece con «display», así el cursor
siempre queda justo después de la última letra visible, sin importar la fuente.
Reemplaza el bloque entre TEXTO:INICIO y TEXTO:FIN del banner.

Uso:  python scripts/banner.py
"""
import html
from pathlib import Path

BANNER = Path(__file__).resolve().parent.parent / "assets" / "banner.svg"

NAME = "Christopher Mendoza"
ROLE = [("ES", "Estudiante de Ingeniería en Sistemas"),
        ("EN", "Systems Engineering Student")]

CORAL, TURQ, OCEAN, ORANGE, CREAM, INDIGO, INK = (
    "#E3566A", "#73B3B9", "#1E89AB", "#F0AB72", "#F2E6D6", "#5C5579", "#4A4466")
SANS = "'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "'JetBrains Mono','Fira Code',Consolas,'Courier New',monospace"

NAME_START, NAME_TYPE = 0.4, 0.075           # segundos: inicio y tiempo por letra del nombre
ROLE_TYPE, ROLE_DELETE = 0.06, 0.025         # tiempo por letra al escribir / borrar la carrera
HOLD, GAP = 2.6, 0.4                         # pausa con la frase completa / entre frases


def ch(c: str) -> str:
    return "\u00a0" if c == " " else html.escape(c)


def name_block() -> tuple[str, float]:
    spans = []
    for k, c in enumerate(NAME):
        t = NAME_START + (k + 1) * NAME_TYPE
        spans.append(f'<tspan display="none">{ch(c)}<set attributeName="display" to="inline" begin="{t:.3f}s" fill="freeze"/></tspan>')
    end = NAME_START + len(NAME) * NAME_TYPE
    cursor = (f'<tspan fill="{OCEAN}" font-weight="400" display="none">_'
              f'<set attributeName="display" to="inline" begin="{NAME_START:.2f}s" end="{end + 0.5:.2f}s"/>'
              f'<animate attributeName="fill-opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="0.9s" repeatCount="indefinite"/></tspan>')
    return (f'      <text x="70" y="190" font-size="64" font-weight="700" fill="{INK}" letter-spacing="-1">'
            + "".join(spans) + cursor + "</text>"), end


def role_block(begin: float) -> str:
    # Línea de tiempo de un ciclo: cada frase se escribe, espera y se borra.
    spans_t, t = [], 0.0
    for _, text in ROLE:
        n = len(text)
        spans_t.append(t)
        t += n * ROLE_TYPE + HOLD + n * ROLE_DELETE + GAP
    total = t
    kt = lambda x: f"{x / total:.5f}"

    chars = []
    for (_, text), start in zip(ROLE, spans_t):
        n = len(text)
        full = start + n * ROLE_TYPE
        gone = full + HOLD + n * ROLE_DELETE
        for k, c in enumerate(text):
            show = start + (k + 1) * ROLE_TYPE
            hide = full + HOLD + (n - k) * ROLE_DELETE
            chars.append(f'<tspan display="none">{ch(c)}<animate attributeName="display" values="none;inline;none" '
                         f'keyTimes="0;{kt(show)};{kt(hide)}" dur="{total:.2f}s" begin="{begin:.2f}s" calcMode="discrete" repeatCount="indefinite"/></tspan>')
    cursor = (f'<tspan dx="4" fill="{OCEAN}" font-weight="400" display="none">_'
              f'<set attributeName="display" to="inline" begin="{begin:.2f}s"/>'
              f'<animate attributeName="fill-opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="1.1s" repeatCount="indefinite"/></tspan>')
    text = (f'      <text x="72" y="262" font-size="26" font-weight="500" fill="{INDIGO}">'
            + "".join(chars) + cursor + "</text>")
    return text


def main() -> None:
    name, name_end = name_block()
    bars = "\n".join(
        f'      <rect x="{x}" y="214" width="0" height="4" rx="2" fill="{c}">'
        f'<animate attributeName="width" from="0" to="{w}" begin="{name_end + 0.15 + i * 0.12:.2f}s" dur="0.45s" fill="freeze"/></rect>'
        for i, (x, w, c) in enumerate([(72, 56, CORAL), (134, 22, ORANGE), (162, 10, TURQ)]))
    block = f'''    <!-- TEXTO:INICIO (generado por scripts/banner.py) -->
    <g font-family="{SANS}">
      <text x="72" y="118" font-family="{MONO}" font-size="18" fill="{OCEAN}" letter-spacing="1">$ whoami</text>
{name}
{bars}
{role_block(name_end + 0.7)}
    </g>
    <!-- TEXTO:FIN -->'''
    svg = BANNER.read_text(encoding="utf-8")
    a = svg.index("    <!-- TEXTO:INICIO")
    b = svg.index("<!-- TEXTO:FIN -->") + len("<!-- TEXTO:FIN -->")
    BANNER.write_text(svg[:a] + block + svg[b:], encoding="utf-8")
    print(f"Actualizado {BANNER}")


if __name__ == "__main__":
    main()
