"""Rendering: dates, the degree line, the build command, and the one-page rule."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resume_builder.cli import app
from resume_builder.load import load_bank
from resume_builder.models import Dates
from resume_builder.presets import load_preset
from resume_builder.render import ENGINES, BuildError, format_dates, page_count, render_tex

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRESETS = sorted((FIXTURES / "presets").glob("*.yaml"))
HAVE_ENGINE = any(shutil.which(e) for e in ENGINES)
HAVE_POPPLER = shutil.which("pdftotext") and shutil.which("pdfinfo")
# CI sets REQUIRE_TEX so these tests fail instead of silently skipping when the tools are missing.
needs_tex = pytest.mark.skipif(
    not (HAVE_ENGINE and HAVE_POPPLER) and not os.environ.get("REQUIRE_TEX"),
    reason="needs a LaTeX engine and poppler-utils",
)


@pytest.mark.parametrize(
    ("dates", "display", "expected"),
    [
        (Dates(start="2026-05", end="2026-08"), None, "May – August 2026"),
        (Dates(start="2025-08", end="2026-05"), None, "August 2025 – May 2026"),
        (Dates(start="2025-07", end="2025-07"), None, "July 2025"),
        (Dates(start="2026-08", end="present"), None, "August 2026 – Present"),
        (Dates(start="2023-08", end="2028-05"), "Expected Graduation: May 2028", None),
        (None, None, ""),
        (
            [Dates(start=f"{y}-03", end=f"{y}-04") for y in (2024, 2025, 2026)],
            None,
            "March – April 2024, 2025, 2026",
        ),
        (
            [Dates(start="2024-04", end="2025-08"), Dates(start="2026-08", end="present")],
            None,
            "April 2024 – August 2025, August 2026 – Present",
        ),
    ],
)
def test_format_dates(dates, display, expected):
    assert format_dates(dates, display) == (expected if expected is not None else display)


def pages(pdf: Path) -> int:
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True)
    return int(re.search(r"^Pages:\s+(\d+)", info.stdout, re.M).group(1))


EXPECTED = {
    "swe": "Kymani_Jarrett_ResumeSWE.pdf",
    "data-eng": "Kymani_Jarrett_ResumeDE.pdf",
    "ml": "Kymani_Jarrett_ResumeML.pdf",
    "quant": "Kymani_Jarrett_ResumeQuant.pdf",
    "cyber": "Kymani_Jarrett_ResumeSecurity.pdf",
}


def build_cli(*args: str, out: Path):
    return CliRunner().invoke(
        app,
        ["build", *args, "--bank", str(FIXTURES / "bank"), "--presets", str(FIXTURES / "presets"),
         "--out", str(out)],
    )  # fmt: skip


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """Build every preset once, the way CI does."""
    out = tmp_path_factory.mktemp("build")
    result = build_cli("--all", out=out)
    assert result.exit_code == 0, result.output
    return out


@needs_tex
def test_build_all_names_each_pdf_by_its_label(built):
    assert sorted(p.name for p in built.glob("*.pdf")) == sorted(EXPECTED.values())


@needs_tex
@pytest.mark.parametrize("preset", [p.stem for p in PRESETS])
def test_every_preset_is_one_page(built, preset):
    assert pages(built / EXPECTED[preset]) == 1


@needs_tex
@pytest.mark.parametrize("preset", EXPECTED)
def test_every_pdf_has_sample_contact_details(built, preset):
    pdf = built / EXPECTED[preset]
    text = pdf_text(pdf)
    contacts = ("Kymani Jarrett", "linkedin.com/in/kymanirjarrett", "github.com/kymanirjarrett")
    for contact in contacts:
        assert contact.casefold() in text.casefold(), f"{pdf.name}: missing {contact}"


def test_phone_and_email_are_optional_header_fields():
    bank = load_bank(FIXTURES / "bank")
    preset = load_preset(FIXTURES / "presets/swe.yaml")
    header = render_tex(bank, preset).split("begin{document}")[1].split("Education")[0]
    assert "mailto" not in header
    profile = bank.profile.model_copy(update={"phone": "(614) 555-0100", "email": "me@mail.com"})
    header = render_tex(bank.model_copy(update={"profile": profile}), preset)
    assert r"(614) 555-0100 $|$" in header
    assert r"\href{mailto:me@mail.com}{\underline{me@mail.com}} $|$" in header


@needs_tex
def test_entries_without_bullets_still_build(tmp_path):
    """A heading-only pick must not emit an empty itemize, which LaTeX rejects."""
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "headings.yaml").write_text(
        "name: headings\n"
        "label: H\n"
        "education: [{id: kessler-state, bullets: []}]\n"
        "experience: [{id: halden-freight, bullets: []}, "
        "{id: meridian-health, bullets: [meridian-health-cache]}]\n"
        "projects: [{id: resume-as-code, bullets: []}, {id: ledger-lens, bullets: []}]\n"
        "skills: [languages]\n"
    )
    result = CliRunner().invoke(
        app,
        ["build", "--preset", "headings", "--bank", str(FIXTURES / "bank"),
         "--presets", str(presets), "--out", str(tmp_path / "out")],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    tex = (tmp_path / "out/Kymani_Jarrett_ResumeH.tex").read_text()
    body = tex.split("begin{document}")[1].split("Work Experience")[0]
    assert "resumeItemListStart" not in body


def make_overflow_preset(path: Path) -> Path:
    """Force a page break with a large fixture bank independent of sample bullet lengths."""
    bank = path.parent / "bank"
    shutil.copytree(FIXTURES / "bank", bank)
    lines = ["- id: long-project", "  name: Long Project", "  bullets:"]
    for number in range(75):
        lines += [f"    - id: long-bullet-{number}", f"      text: Sample bullet {number}."]
    (bank / "projects.yaml").write_text("\n".join(lines) + "\n")
    path.write_text(f"name: {path.stem}\nlabel: X\nprojects: [long-project]\n")
    return bank


@needs_tex
def test_a_two_page_preset_fails_the_build(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    bank = make_overflow_preset(presets / "long.yaml")
    result = CliRunner().invoke(
        app,
        ["build", "--preset", "long", "--bank", str(bank),
         "--presets", str(presets), "--out", str(tmp_path / "out")],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "a resume must fit on one" in result.stderr
    assert not list((tmp_path / "out").glob("*.pdf")), "the rejected PDF was left behind"


@needs_tex
def test_a_failed_rebuild_keeps_the_earlier_good_pdf(tmp_path):
    """Building good, then overflowing under the same label, must leave the good PDF in place."""
    presets = tmp_path / "presets"
    presets.mkdir()
    path = presets / "x.yaml"
    path.write_text("name: x\nlabel: X\neducation: [kessler-state]\nprojects: [ledger-lens]\n")
    args = ["build", "--preset", "x", "--presets", str(presets), "--out", str(tmp_path / "out")]
    assert CliRunner().invoke(app, [*args, "--bank", str(FIXTURES / "bank")]).exit_code == 0
    pdf = tmp_path / "out/Kymani_Jarrett_ResumeX.pdf"
    good = pdf.read_bytes()
    bank = make_overflow_preset(path)
    result = CliRunner().invoke(app, [*args, "--bank", str(bank)])
    assert result.exit_code == 1
    assert "a resume must fit on one" in result.stderr
    assert pdf.read_bytes() == good
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "Kymani_Jarrett_ResumeX.pdf",
        "Kymani_Jarrett_ResumeX.tex",
    ]


def test_an_unreadable_pdf_is_a_build_error(tmp_path, monkeypatch):
    fake = tmp_path / "pdfinfo"
    fake.write_text("#!/bin/sh\necho 'Syntax Error: broken file' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(BuildError, match="pdfinfo could not read .*broken file"):
        page_count(tmp_path / "broken.pdf")


def test_build_rejects_both_preset_and_all():
    result = CliRunner().invoke(app, ["build", "--preset", "swe", "--all"])
    assert result.exit_code == 1
    assert "not both" in result.stderr


@needs_tex
def test_build_defaults_to_swe(tmp_path, monkeypatch):
    for name in ("bank", "presets"):
        shutil.copytree(FIXTURES / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["build"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "build/Kymani_Jarrett_ResumeSWE.pdf").exists()


def test_two_presets_cannot_share_a_label(tmp_path):
    presets = tmp_path / "presets"
    shutil.copytree(FIXTURES / "presets", presets)
    path = presets / "ml.yaml"
    path.write_text(path.read_text().replace("label: ML", "label: SWE"))
    result = CliRunner().invoke(
        app, ["validate", "--bank", str(FIXTURES / "bank"), "--presets", str(presets)]
    )
    assert result.exit_code == 1
    assert "two presets share the label 'SWE'" in result.stderr


def test_degree_renders_one_line_per_major():
    tex = render_tex(load_bank(FIXTURES / "bank"), load_preset(FIXTURES / "presets/swe.yaml"))
    assert r"{B.S. in Computer Science $|$ B.S. in Mathematics}" in tex


# A few skills each PDF must show and must not show, read from the Technical Skills section.
SKILL_MARKERS = {
    "cyber": (["Open Policy Agent", "JSON Schema"], ["DuckDB", "Docker"]),
    "data-eng": (["PostgreSQL", "dbt"], ["Open Policy Agent", "React"]),
    "quant": (["NumPy", "DuckDB"], ["PostgreSQL", "scikit-learn"]),
    "ml": (["scikit-learn", "pytest"], ["DuckDB", "Open Policy Agent"]),
    "swe": (["TypeScript", "React"], ["DuckDB", "JSON Schema"]),
}
SECTIONS = ["Education", "Work Experience", "Projects", "Technical Skills"]


def pdf_text(pdf: Path) -> str:
    return " ".join(subprocess.check_output(["pdftotext", str(pdf), "-"], text=True).split())


def test_skill_markers_cover_every_preset():
    assert sorted(SKILL_MARKERS) == sorted(EXPECTED)


@needs_tex
@pytest.mark.parametrize("preset", EXPECTED)
def test_every_pdf_has_its_sections_in_order(built, preset):
    text = pdf_text(built / EXPECTED[preset])
    positions = [text.find(section) for section in SECTIONS]
    assert -1 not in positions, f"{preset}: missing {SECTIONS[positions.index(-1)]}"
    assert positions == sorted(positions)


@needs_tex
@pytest.mark.parametrize("preset", EXPECTED)
def test_every_pdf_shows_its_skills(built, preset):
    text = pdf_text(built / EXPECTED[preset])
    assert "Technical Skills" in text
    skills = text.split("Technical Skills", 1)[1]
    included, excluded = SKILL_MARKERS[preset]
    for name in included:
        assert name in skills, f"{preset}: missing {name}"
    for name in excluded:
        assert name not in skills, f"{preset}: should not list {name}"
