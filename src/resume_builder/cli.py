"""Command-line entry point: `resume validate` and `resume build`."""

from pathlib import Path
from typing import Annotated

import typer

from resume_builder import __version__
from resume_builder.load import BankError, load_bank
from resume_builder.presets import DEFAULT_PRESET, PresetError, load_preset, load_presets
from resume_builder.render import ENGINES, BuildError, build

app = typer.Typer(help="Build resumes from the bullet bank.", no_args_is_help=True)

BankDir = Annotated[Path, typer.Option(help="Directory holding the bank YAML files.")]
PresetsDir = Annotated[Path, typer.Option(help="Directory holding the preset YAML files.")]
OutDir = Annotated[Path, typer.Option(help="Output directory.")]
Engine = Annotated[str, typer.Option(help=f"auto, or one of: {', '.join(ENGINES)}.")]


@app.callback()
def main() -> None:
    """Keep `resume` a command group so subcommands like `resume validate` work."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def _fail(problems: list[str]) -> None:
    for problem in problems:
        typer.echo(f"error: {problem}", err=True)
    typer.echo(f"{len(problems)} problem(s) found.", err=True)
    raise typer.Exit(1)


@app.command()
def validate(bank: BankDir = Path("bank"), presets: PresetsDir = Path("presets")) -> None:
    """Check the bank (schema, ids, variants) and every preset."""
    try:
        loaded = load_bank(bank)
    except BankError as exc:
        _fail(exc.problems)

    entries = list(loaded.entries())
    bullets = list(loaded.bullets())
    active = sum(b.status == "active" for b in bullets)
    typer.echo(f"Bank OK: {len(entries)} entries, {len(bullets)} bullets ({active} active).")

    found, problems = load_presets(presets, loaded)
    if problems:
        _fail(problems)
    typer.echo(f"Presets OK: {', '.join(p.name for p in found)}.")


@app.command("build")
def build_cmd(
    preset: Annotated[
        str | None, typer.Option(help=f"Preset name; {DEFAULT_PRESET} when none is given.")
    ] = None,
    all_presets: Annotated[bool, typer.Option("--all", help="Build every preset.")] = False,
    bank: BankDir = Path("bank"),
    presets: PresetsDir = Path("presets"),
    out: OutDir = Path("build"),
    engine: Engine = "auto",
) -> None:
    """Build presets to <out>/Kymani_Jarrett_Resume<label>.pdf, e.g. ...ResumeSWE.pdf."""
    if preset is not None and all_presets:
        _fail(["pass --preset or --all, not both"])
    try:
        loaded = load_bank(bank)
        if all_presets:
            chosen, problems = load_presets(presets, loaded)
            if problems:
                _fail(problems)
        else:
            chosen = [load_preset(presets / f"{preset or DEFAULT_PRESET}.yaml")]
        for item in chosen:
            typer.echo(f"Built {build(loaded, item, out, engine, check_one_page=True)}")
    except (BankError, PresetError) as exc:
        _fail(exc.problems)
    except BuildError as exc:
        _fail([str(exc)])


if __name__ == "__main__":
    app()
