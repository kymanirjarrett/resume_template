"""Pydantic models for the bullet bank, plus the cross-entry checks one model can't see."""

from collections.abc import Iterator
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["active", "off", "archived"]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class Strict(BaseModel):
    # Unknown keys are errors, so a typo like `staus:` fails instead of being ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class Reviewable(Strict):
    """Entries, bullets, and skills. `off` bullets and skills are left out unless a preset
    names them; `archived` ones can never be used."""

    status: Status = "active"


class Dates(Strict):
    start: YearMonth | None = None
    end: YearMonth | Literal["present"] | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "Dates":
        # YYYY-MM strings sort chronologically, so plain string comparison works.
        if self.start and self.end and self.end != "present" and self.end < self.start:
            raise ValueError(f"end {self.end} is before start {self.start}")
        return self


class Bullet(Reviewable):
    id: Slug
    text: str = Field(min_length=1)
    variant_of: Slug | None = None

    @model_validator(mode="after")
    def _variants_off(self) -> "Bullet":
        if self.variant_of and self.status == "active":
            raise ValueError("a variant cannot be active; a preset can list it instead")
        return self


class Entry(Reviewable):
    id: Slug
    location: str | None = None
    # One range, or several for seasonal or repeated stints.
    dates: Dates | list[Dates] | None = None
    # Overrides the formatted date range when the resume words it differently.
    dates_display: str | None = None
    bullets: list[Bullet] = []


class Major(Strict):
    name: str
    track: str | None = None


class Education(Entry):
    school: str
    degree: str
    # How the resume abbreviates the degree: "B.S." renders "B.S. in <major>" per major.
    degree_short: str
    majors: list[Major]


class Experience(Entry):
    title: str
    org: str


class Leadership(Entry):
    org: str
    role: str | None = None
    note: str | None = None


class Links(Strict):
    website: str | None = None
    source: str | None = None


class Project(Entry):
    name: str
    links: Links = Links()
    stack: list[str] = []
    summary: str | None = None


class Award(Entry):
    name: str
    details: str | None = None


class Skill(Reviewable):
    name: str


class SkillGroup(Reviewable):
    id: Slug
    label: str
    skills: list[Skill]


class ProfileLink(Strict):
    id: Slug
    url: str
    display: str


class Profile(Strict):
    """Contact details are rendered; `about` holds optional background notes for reference.
    Phone and email are optional, so a public copy can show just a name and links."""

    name: str
    phone: str | None = None
    email: str | None = None
    links: list[ProfileLink]
    about: list[str]


class Bank(Strict):
    profile: Profile
    education: list[Education]
    experience: list[Experience]
    secondary: list[Experience]
    projects: list[Project]
    leadership: list[Leadership]
    awards: list[Award]
    skills: list[SkillGroup]

    def entries(self) -> Iterator[tuple[str, Entry]]:
        for section in ("education", "experience", "secondary", "projects", "leadership", "awards"):
            for entry in getattr(self, section):
                yield section, entry

    def bullets(self) -> Iterator[Bullet]:
        for _, entry in self.entries():
            yield from entry.bullets


def check_bank(bank: Bank) -> list[str]:
    """Checks that need the whole bank: unique ids and variant references."""
    problems: list[str] = []
    owners: dict[str, str] = {}

    def claim(item_id: str, where: str) -> None:
        if item_id in owners:
            problems.append(
                f"duplicate id '{item_id}' in {where} (first used in {owners[item_id]})"
            )
        else:
            owners[item_id] = where

    for section, entry in bank.entries():
        where = f"{section}/{entry.id}"
        claim(entry.id, section)
        by_id = {b.id: b for b in entry.bullets}
        for bullet in entry.bullets:
            claim(bullet.id, where)
            if bullet.variant_of is None:
                continue
            target = by_id.get(bullet.variant_of)
            if bullet.variant_of == bullet.id:
                problems.append(f"{where}: bullet '{bullet.id}' is a variant of itself")
            elif target is None:
                problems.append(
                    f"{where}: bullet '{bullet.id}' is a variant of '{bullet.variant_of}', "
                    "which is not a bullet in this entry"
                )
            elif target.variant_of is not None:
                problems.append(
                    f"{where}: bullet '{bullet.id}' is a variant of '{target.id}', which is "
                    f"itself a variant; point it at '{target.variant_of}' instead"
                )

    group_ids: set[str] = set()
    skill_names: dict[str, str] = {}
    for group in bank.skills:
        if group.id in group_ids:
            problems.append(f"duplicate skill group id '{group.id}'")
        group_ids.add(group.id)
        for skill in group.skills:
            key = skill.name.casefold()
            if key in skill_names:
                problems.append(
                    f"skill '{skill.name}' appears in both '{skill_names[key]}' and '{group.id}'"
                )
            skill_names.setdefault(key, group.id)

    return problems
