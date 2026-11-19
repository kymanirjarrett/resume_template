"""Escaping and **bold** conversion."""

import pytest

from resume_builder.latex import escape, to_latex


@pytest.mark.parametrize(
    ("text", "tex"),
    [
        ("R&D", r"R\&D"),
        ("30%", r"30\%"),
        ("$5", r"\$5"),
        ("C#", r"C\#"),
        ("snake_case", r"snake\_case"),
        ("{x}", r"\{x\}"),
        ("~40", r"\textasciitilde{}40"),
        ("x^2", r"x\textasciicircum{}2"),
        ("a\\b", r"a\textbackslash{}b"),
    ],
)
def test_specials_are_escaped(text, tex):
    assert escape(text) == tex


def test_escapes_are_not_escaped_twice():
    assert escape("\\{&}") == r"\textbackslash{}\{\&\}"


def test_dashes_and_pipes_are_written_like_the_source():
    assert escape("May – August 2026") == "May -- August 2026"
    assert escape("a—b") == "a---b"
    assert escape("IT | Cyber") == "IT $|$ Cyber"


def test_literal_double_hyphen_is_kept():
    assert escape("0--100") == "0--100"


def test_bold_becomes_textbf():
    assert to_latex("Built **two** things with **React & Zod**") == (
        r"Built \textbf{two} things with \textbf{React \& Zod}"
    )


def test_bold_around_escaped_characters():
    assert to_latex("cut by **30%**") == r"cut by \textbf{30\%}"


def test_unbalanced_bold_fails():
    with pytest.raises(ValueError, match="unbalanced"):
        to_latex("**oops")
