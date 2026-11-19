"""Load the YAML bank into validated models, collecting every problem instead of stopping at one."""

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from resume_builder.models import (
    Award,
    Bank,
    Education,
    Experience,
    Leadership,
    Profile,
    Project,
    SkillGroup,
    check_bank,
)

# File stem -> model. Every file except profile.yaml holds a list of entries.
BANK_FILES: dict[str, type[BaseModel]] = {
    "profile": Profile,
    "education": Education,
    "experience": Experience,
    "secondary": Experience,
    "projects": Project,
    "leadership": Leadership,
    "awards": Award,
    "skills": SkillGroup,
}


class _Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans, so `status: off` stays the string "off".

    PyYAML follows YAML 1.1, where yes/no/on/off are booleans too.
    """


def _no_duplicate_keys(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> Any:
    """A repeated key would silently replace the first value, so reject it."""
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"found duplicate key '{key}'", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)

_BOOL = "tag:yaml.org,2002:bool"
_Loader.yaml_implicit_resolvers = {
    first: [r for r in resolvers if r[0] != _BOOL]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    _BOOL, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def read_yaml(path: Path) -> Any:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


class BankError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def _describe(path: Path, raw: Any, exc: ValidationError) -> list[str]:
    """Turn pydantic's `[3].bullets.0.text` locations into `halden-freight.bullets.0.text`."""
    lines = []
    for err in exc.errors():
        loc = list(err["loc"])
        if loc and isinstance(loc[0], int) and isinstance(raw, list):
            item = raw[loc[0]]
            if isinstance(item, dict) and "id" in item:
                loc[0] = item["id"]
        where = ".".join(str(part) for part in loc) or "(top level)"
        lines.append(f"{path}: {where}: {err['msg']}")
    return lines


def load_bank(bank_dir: Path) -> Bank:
    problems: list[str] = []
    sections: dict[str, Any] = {}
    for stem, model in BANK_FILES.items():
        path = bank_dir / f"{stem}.yaml"
        try:
            raw = read_yaml(path)
        except FileNotFoundError:
            problems.append(f"{path}: file is missing")
            continue
        except yaml.YAMLError as exc:
            problems.append(f"{path}: invalid YAML: {exc}")
            continue
        adapter = TypeAdapter(model if stem == "profile" else list[model])
        try:
            sections[stem] = adapter.validate_python(raw)
        except ValidationError as exc:
            problems.extend(_describe(path, raw, exc))

    # Cross-entry checks only make sense once every file parsed.
    if problems:
        raise BankError(problems)
    bank = Bank(**sections)
    if problems := check_bank(bank):
        raise BankError(problems)
    return bank
