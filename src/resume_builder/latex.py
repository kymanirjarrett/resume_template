"""Turn bank text into LaTeX: escape special characters and convert **bold** to \\textbf{}."""

import re

_ESCAPES = (
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
)
# Typography LaTeX writes as ligatures or math; the bank stores the plain characters.
_TYPOGRAPHY = (
    ("—", "---"),
    ("–", "--"),
    ("|", "$|$"),
)
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ESCAPE_ONE = {char: tex for char, tex in _ESCAPES}
_SPECIALS = re.compile("|".join(re.escape(char) for char, _ in _ESCAPES))


def escape(text: str) -> str:
    """Escape LaTeX specials, then write dashes and pipes as LaTeX expects them."""
    # One pass, so a replacement's own braces and backslashes are never escaped again.
    text = _SPECIALS.sub(lambda m: _ESCAPE_ONE[m.group()], text)
    for char, tex in _TYPOGRAPHY:
        text = text.replace(char, tex)
    return text


def to_latex(text: str) -> str:
    """Escape bank text and turn each **bold** span into \\textbf{...}."""
    if text.count("**") % 2:
        raise ValueError(f"unbalanced ** in: {text}")
    return _BOLD.sub(r"\\textbf{\1}", escape(text))
