"""Presets: which entries and skills one resume shows, checked against the bank before rendering.

An entry shows its active bullets in bank order unless a preset picks bullets for it, which is
how presets tailor experience to a role. Presets also differ in which entries and skills they pick.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, TypeAdapter, ValidationError, field_validator

from resume_builder.load import read_yaml
from resume_builder.models import Bank, Entry, Reviewable, SkillGroup, Slug, Strict

# Sections a preset can select entries from, in the order the template renders them.
ENTRY_SECTIONS = ("education", "experience", "projects")
DEFAULT_PRESET = "swe"


class Pick(Strict):
    """One entry. `bullets` omitted means its active bullets; [] means the heading alone."""

    id: Slug
    bullets: list[Slug] | None = None


class SkillPick(Strict):
    """One skill group. `skills` omitted means its active skills, in bank order."""

    id: Slug
    skills: list[str] | None = None


class Preset(Strict):
    name: Slug
    # Ends the PDF name: label SWE gives Kymani_Jarrett_ResumeSWE.pdf.
    label: str = Field(pattern=r"^[A-Za-z0-9]+$")
    description: str | None = None
    education: list[Pick] = []
    experience: list[Pick] = []
    projects: list[Pick] = []
    skills: list[SkillPick] = []

    @field_validator("education", "experience", "projects", "skills", mode="before")
    @classmethod
    def _bare_ids(cls, value: Any) -> Any:
        """Let YAML list a plain id instead of {id: ...}."""
        if isinstance(value, list):
            return [{"id": v} if isinstance(v, str) else v for v in value]
        return value


class PresetError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def bullets_of(entry: Entry, pick: Pick) -> list[str]:
    if pick.bullets is not None:
        return list(pick.bullets)
    return [b.id for b in entry.bullets if b.status == "active"]


def skills_of(group: SkillGroup, pick: SkillPick) -> list[str]:
    if pick.skills is not None:
        return list(pick.skills)
    return [s.name for s in group.skills if s.status == "active"]


def load_preset(path: Path) -> Preset:
    try:
        raw = read_yaml(path)
    except FileNotFoundError:
        raise PresetError([f"{path}: file is missing"]) from None
    except yaml.YAMLError as exc:
        raise PresetError([f"{path}: invalid YAML: {exc}"]) from None
    try:
        preset = TypeAdapter(Preset).validate_python(raw)
    except ValidationError as exc:
        problems = [
            f"{path}: {'.'.join(str(p) for p in e['loc']) or '(top level)'}: {e['msg']}"
            for e in exc.errors()
        ]
        raise PresetError(problems) from None
    if preset.name != path.stem:
        raise PresetError([f"{path}: name '{preset.name}' must match the file name"])
    return preset


def _archived(item: Reviewable) -> bool:
    return item.status == "archived"


def check_preset(bank: Bank, preset: Preset) -> list[str]:
    """Every id must exist, sit in the right place, and not be archived."""
    problems: list[str] = []
    where = f"preset '{preset.name}'"

    for section in ENTRY_SECTIONS:
        entries: dict[str, Entry] = {e.id: e for e in getattr(bank, section)}
        seen: set[str] = set()
        for pick in getattr(preset, section):
            entry = entries.get(pick.id)
            if entry is None:
                problems.append(f"{where}: no {section} entry '{pick.id}'")
                continue
            if pick.id in seen:
                problems.append(f"{where}: {section} entry '{pick.id}' is listed twice")
            seen.add(pick.id)
            if _archived(entry):
                problems.append(f"{where}: {section} entry '{pick.id}' is archived")
            chosen = bullets_of(entry, pick)
            if len(set(chosen)) != len(chosen):
                problems.append(f"{where}: '{pick.id}' lists a bullet twice")
            bullets = {b.id: b for b in entry.bullets}
            for bullet_id in chosen:
                bullet = bullets.get(bullet_id)
                if bullet is None:
                    problems.append(f"{where}: '{bullet_id}' is not a bullet of '{pick.id}'")
                elif _archived(bullet):
                    problems.append(f"{where}: bullet '{bullet_id}' is archived")
                elif bullet.variant_of in chosen:
                    problems.append(
                        f"{where}: '{bullet_id}' is a variant of '{bullet.variant_of}'; "
                        "use one or the other"
                    )

    groups = {g.id: g for g in bank.skills}
    ids = [p.id for p in preset.skills]
    if len(set(ids)) != len(ids):
        problems.append(f"{where}: a skill group is listed twice")
    for pick in preset.skills:
        group = groups.get(pick.id)
        if group is None:
            problems.append(f"{where}: no skill group '{pick.id}'")
            continue
        if _archived(group):
            problems.append(f"{where}: skill group '{pick.id}' is archived")
        known = {s.name: s for s in group.skills}
        names = pick.skills or []
        for name in sorted({n for n in names if names.count(n) > 1}):
            problems.append(f"{where}: '{name}' is listed twice in skill group '{pick.id}'")
        for name in names:
            if name not in known:
                problems.append(f"{where}: '{name}' is not a skill in '{pick.id}'")
            elif _archived(known[name]):
                problems.append(f"{where}: skill '{name}' is archived")

    return problems


def load_presets(presets_dir: Path, bank: Bank) -> tuple[list[Preset], list[str]]:
    """Load and check every preset in a directory, collecting all problems."""
    presets: list[Preset] = []
    problems: list[str] = []
    if not presets_dir.is_dir():
        return presets, [f"{presets_dir}: presets directory is missing"]
    paths = sorted(presets_dir.glob("*.yaml"))
    if not paths:
        return presets, [f"{presets_dir}: no presets found"]
    for path in paths:
        try:
            preset = load_preset(path)
        except PresetError as exc:
            problems.extend(exc.problems)
            continue
        presets.append(preset)
        problems.extend(check_preset(bank, preset))
    labels = [p.label for p in presets]
    for label in sorted({x for x in labels if labels.count(x) > 1}):
        problems.append(f"{presets_dir}: two presets share the label '{label}'")
    return presets, problems
