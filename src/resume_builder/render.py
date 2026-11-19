"""Render a preset to LaTeX through the Jinja template, then compile it to PDF."""

import calendar
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from resume_builder.latex import escape, to_latex
from resume_builder.models import Bank, Dates, Entry
from resume_builder.presets import Pick, Preset, PresetError, bullets_of, check_preset, skills_of

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
# Tectonic is the supported engine; the others are fallbacks for machines without it.
ENGINES = ("tectonic", "pdflatex", "xelatex")


class BuildError(Exception):
    pass


def _month(year_month: str) -> tuple[str, str]:
    year, month = year_month.split("-")
    return calendar.month_name[int(month)], year


def format_dates(dates: Dates | list[Dates] | None, display: str | None = None) -> str:
    """'May – August 2026', 'August 2025 – May 2026', or the entry's dates_display.

    Several ranges join with commas; seasonal ones that repeat the same months collapse to
    'March – April 2024, 2025, 2026'.
    """
    if display is not None:
        return display
    if isinstance(dates, list):
        return _format_ranges(dates)
    if dates is None or dates.start is None:
        return ""
    start_month, start_year = _month(dates.start)
    if dates.end is None:
        return f"{start_month} {start_year}"
    if dates.end == "present":
        return f"{start_month} {start_year} – Present"
    end_month, end_year = _month(dates.end)
    if dates.end == dates.start:
        return f"{start_month} {start_year}"
    if end_year == start_year:
        return f"{start_month} – {end_month} {end_year}"
    return f"{start_month} {start_year} – {end_month} {end_year}"


def _format_ranges(ranges: list[Dates]) -> str:
    seasonal = len(ranges) > 1 and all(
        r.start and r.end and r.end != "present" and r.start[:4] == r.end[:4] for r in ranges
    )
    if seasonal and len({(r.start[5:], r.end[5:]) for r in ranges}) == 1:
        first = format_dates(ranges[0])
        return ", ".join([first, *(r.start[:4] for r in ranges[1:])])
    return ", ".join(format_dates(r) for r in ranges)


def _url(url: str) -> str:
    """URLs go to \\href inside a macro argument, where only # and % need escaping."""
    return url.replace("%", r"\%").replace("#", r"\#")


def _bullets(entry: Entry, pick: Pick) -> list[str]:
    by_id = {b.id: b for b in entry.bullets}
    return [to_latex(by_id[bullet_id].text) for bullet_id in bullets_of(entry, pick)]


def context(bank: Bank, preset: Preset) -> dict:
    """Everything the template needs, already escaped for LaTeX."""
    if problems := check_preset(bank, preset):
        raise PresetError(problems)

    def picked(section: str):
        entries = {e.id: e for e in getattr(bank, section)}
        for pick in getattr(preset, section):
            yield entries[pick.id], pick

    profile = bank.profile
    contact = []
    if profile.phone:
        contact.append(escape(profile.phone))
    if profile.email:
        contact.append(rf"\href{{mailto:{profile.email}}}{{\underline{{{escape(profile.email)}}}}}")
    for link in profile.links:
        contact.append(rf"\href{{{_url(link.url)}}}{{\underline{{{escape(link.display)}}}}}")

    projects = []
    for project, pick in picked("projects"):
        heading = [rf"\textbf{{{escape(project.name)}}}"]
        if project.links.website:
            heading.append(rf"\emph{{\href{{{_url(project.links.website)}}}{{Website}}}}")
        if project.links.source:
            heading.append(rf"\emph{{\href{{{_url(project.links.source)}}}{{Source Code}}}}")
        projects.append(
            {
                "heading": " $|$ ".join(heading),
                "stack": " $|$ ".join(rf"\textbf{{{escape(s)}}}" for s in project.stack),
                "bullets": _bullets(project, pick),
            }
        )

    groups = {g.id: g for g in bank.skills}
    skills = []
    for pick in preset.skills:
        group = groups[pick.id]
        names = skills_of(group, pick)
        skills.append({"label": escape(group.label), "skills": escape(", ".join(names))})

    return {
        "profile": {
            "name": escape(profile.name),
            "contact": " $|$\n    ".join(contact),
        },
        "education": [
            {
                "school": escape(school.school),
                "degree": escape(
                    " | ".join(f"{school.degree_short} in {m.name}" for m in school.majors)
                ),
                "location": escape(school.location or ""),
                "dates": escape(format_dates(school.dates, school.dates_display)),
                "bullets": _bullets(school, pick),
            }
            for school, pick in picked("education")
        ],
        "experience": [
            {
                "title": escape(job.title),
                "org": escape(job.org),
                "location": escape(job.location or ""),
                "dates": escape(format_dates(job.dates, job.dates_display)),
                "bullets": _bullets(job, pick),
            }
            for job, pick in picked("experience")
        ],
        "projects": projects,
        "skills": skills,
    }


def environment(templates: Path = TEMPLATES) -> Environment:
    return Environment(
        loader=FileSystemLoader(templates),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((=",
        comment_end_string="=))",
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        autoescape=False,  # values are escaped for LaTeX in context(), not for HTML
    )


def render_tex(bank: Bank, preset: Preset) -> str:
    return environment().get_template("resume.tex.j2").render(**context(bank, preset))


def find_engine(requested: str = "auto") -> str:
    """Return the engine to use: the requested one, or the first installed one for 'auto'."""
    if requested != "auto":
        if requested not in ENGINES:
            raise BuildError(f"unknown engine '{requested}'; choose from {', '.join(ENGINES)}")
        if shutil.which(requested) is None:
            raise BuildError(f"{requested} is not installed")
        return requested
    for engine in ENGINES:
        if shutil.which(engine):
            return engine
    raise BuildError("no LaTeX engine found; install Tectonic (see README)")


def compile_pdf(tex: Path, engine: str = "auto") -> Path:
    """Compile tex next to itself and return the PDF path."""
    engine = find_engine(engine)
    out = tex.parent
    if engine == "tectonic":
        cmd = ["tectonic", "--chatter", "minimal", "--outdir", str(out), str(tex)]
    else:
        cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={out}"]
        cmd.append(str(tex))
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=out)
    pdf = tex.with_suffix(".pdf")
    if result.returncode != 0 or not pdf.exists():
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-30:])
        raise BuildError(f"{engine} failed on {tex}:\n{tail}")
    return pdf


def pdf_stem(bank: Bank, preset: Preset) -> str:
    """The file name a recruiter sees: Kymani_Jarrett_ResumeSWE."""
    return "_".join(bank.profile.name.split()) + "_Resume" + preset.label


def build(
    bank: Bank,
    preset: Preset,
    out_dir: Path = Path("build"),
    engine: str = "auto",
    check_one_page: bool = False,
) -> Path:
    """Write <out_dir>/<stem>.tex and <stem>.pdf, named by pdf_stem().

    The build runs in a scratch directory and only moves into out_dir once it passes, so a
    failed build leaves no rejected PDF behind and keeps any earlier good one.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_stem(bank, preset)
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".staging-") as staging:
        tex = Path(staging).resolve() / f"{stem}.tex"
        tex.write_text(render_tex(bank, preset), encoding="utf-8")
        pdf = compile_pdf(tex, engine)
        if check_one_page and (pages := page_count(pdf)) != 1:
            raise BuildError(f"{out_dir / pdf.name} is {pages} pages; a resume must fit on one")
        tex.replace(out_dir / tex.name)
        pdf.replace(out_dir / pdf.name)
    return out_dir / pdf.name


def page_count(pdf: Path) -> int:
    if shutil.which("pdfinfo") is None:
        raise BuildError("pdfinfo is not installed (install poppler)")
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True)
    if info.returncode != 0:
        raise BuildError(f"pdfinfo could not read {pdf}: {info.stderr.strip()}")
    match = re.search(r"^Pages:\s+(\d+)", info.stdout, re.M)
    if match is None:
        raise BuildError(f"pdfinfo did not report a page count for {pdf}")
    return int(match.group(1))
