"""A preset picks entries and skills; every id must exist and nothing archived gets through."""

import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from resume_builder.cli import app
from resume_builder.load import load_bank, read_yaml
from resume_builder.models import Skill, SkillGroup
from resume_builder.presets import (
    Pick,
    Preset,
    PresetError,
    SkillPick,
    bullets_of,
    check_preset,
    load_preset,
    skills_of,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def bank():
    return load_bank(FIXTURES / "bank")


@pytest.fixture
def presets_dir(tmp_path) -> Path:
    target = tmp_path / "presets"
    shutil.copytree(FIXTURES / "presets", target)
    return target


def write_swe(presets_dir: Path, change) -> Path:
    path = presets_dir / "swe.yaml"
    data = read_yaml(path)
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def problems_for(bank, presets_dir, change) -> str:
    return "\n".join(check_preset(bank, load_preset(write_swe(presets_dir, change))))


def test_every_fixture_preset_is_valid(bank):
    for path in sorted((FIXTURES / "presets").glob("*.yaml")):
        assert check_preset(bank, load_preset(path)) == [], path.name


def test_the_presets_are_cyber_swe_data_ml_and_quant():
    assert sorted(p.stem for p in (FIXTURES / "presets").glob("*.yaml")) == [
        "cyber",
        "data-eng",
        "ml",
        "quant",
        "swe",
    ]


def test_bullets_default_to_active_ones_in_bank_order(bank):
    internship = next(e for e in bank.experience if e.id == "lockfield-analytics")
    assert bullets_of(internship, Pick(id="lockfield-analytics")) == [
        "lockfield-analytics-preview",
        "lockfield-analytics-a11y",
        "lockfield-analytics-tests",
    ]
    assert bullets_of(internship, Pick(id="lockfield-analytics", bullets=[])) == []


def test_every_preset_shows_every_job(bank):
    """Presets tailor which bullets a job shows, but every job appears with at least one."""
    presets = [load_preset(p) for p in sorted((FIXTURES / "presets").glob("*.yaml"))]
    experience = {e.id: e for e in bank.experience}
    for p in presets:
        assert [pick.id for pick in p.experience] == list(experience), p.name
        assert all(bullets_of(experience[pick.id], pick) for pick in p.experience), p.name


def test_bare_ids_and_mappings_both_work():
    preset = Preset(
        name="x", label="X", projects=["ledger-lens", {"id": "resume-as-code", "bullets": []}]
    )
    assert preset.projects == [Pick(id="ledger-lens"), Pick(id="resume-as-code", bullets=[])]


def test_archived_bullet_fails(bank, presets_dir, tmp_path):
    bank_dir = tmp_path / "bank"
    shutil.copytree(FIXTURES / "bank", bank_dir)
    path = bank_dir / "experience.yaml"
    path.write_text(
        path.read_text().replace(
            "    - id: lockfield-analytics-a11y\n",
            "    - id: lockfield-analytics-a11y\n      status: archived\n",
        )
    )
    archived = load_bank(bank_dir)
    message = problems_for(
        archived,
        presets_dir,
        lambda d: d["experience"].__setitem__(
            2,
            {
                "id": "lockfield-analytics",
                "bullets": ["lockfield-analytics-preview", "lockfield-analytics-a11y"],
            },
        ),
    )
    assert "bullet 'lockfield-analytics-a11y' is archived" in message


def test_bullet_from_another_entry_fails(bank, presets_dir):
    message = problems_for(
        bank,
        presets_dir,
        lambda d: d["experience"].__setitem__(
            0, {"id": "halden-freight", "bullets": ["lockfield-analytics-a11y"]}
        ),
    )
    assert "'lockfield-analytics-a11y' is not a bullet of 'halden-freight'" in message


def test_unknown_entry_fails(bank, presets_dir):
    message = problems_for(bank, presets_dir, lambda d: d["projects"].append("nope"))
    assert "no projects entry 'nope'" in message


def test_secondary_experience_is_not_a_preset_section(bank, presets_dir):
    message = problems_for(bank, presets_dir, lambda d: d["experience"].append("campus-it"))
    assert "no experience entry 'campus-it'" in message


def test_unknown_skill_fails(bank, presets_dir):
    message = problems_for(
        bank,
        presets_dir,
        lambda d: d["skills"].__setitem__(0, {"id": "languages", "skills": ["Python", "Rust"]}),
    )
    assert "'Rust' is not a skill in 'languages'" in message


def test_off_skills_can_be_named(bank):
    """An off skill is left out of a group's defaults, but a preset may still name it."""
    tools = next(g for g in bank.skills if g.id == "tools")
    off = tools.model_copy(
        update={
            "skills": [
                s.model_copy(update={"status": "off"}) if s.name == "JSON Schema" else s
                for s in tools.skills
            ]
        }
    )
    bank = bank.model_copy(update={"skills": [off if g.id == "tools" else g for g in bank.skills]})
    assert "JSON Schema" not in skills_of(off, SkillPick(id="tools"))
    preset = Preset(name="x", label="X", skills=[{"id": "tools", "skills": ["JSON Schema"]}])
    assert check_preset(bank, preset) == []
    assert skills_of(off, preset.skills[0]) == ["JSON Schema"]


def test_name_must_match_file(presets_dir):
    path = write_swe(presets_dir, lambda d: d.update(name="other"))
    with pytest.raises(PresetError, match="must match the file name"):
        load_preset(path)


def test_validate_command_rejects_a_bad_preset(presets_dir):
    write_swe(presets_dir, lambda d: d["projects"].append("nope"))
    result = CliRunner().invoke(
        app, ["validate", "--bank", str(FIXTURES / "bank"), "--presets", str(presets_dir)]
    )
    assert result.exit_code == 1
    assert "no projects entry 'nope'" in result.stderr


def test_validate_command_reports_presets():
    result = CliRunner().invoke(
        app,
        ["validate", "--bank", str(FIXTURES / "bank"), "--presets", str(FIXTURES / "presets")],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "Presets OK: cyber, data-eng, ml, quant, swe." in result.stdout


def test_a_skill_listed_twice_fails(bank, presets_dir):
    def twice(data):
        tools = next(p for p in data["skills"] if isinstance(p, dict) and p["id"] == "tools")
        tools["skills"] = ["Git", "Docker", "Git"]

    message = problems_for(bank, presets_dir, twice)
    assert "preset 'swe': 'Git' is listed twice in skill group 'tools'" in message


def test_skill_selection_defaults_and_explicit_order():
    """Defaults are active skills in bank order; an explicit list is used as written."""
    group = SkillGroup(
        id="tools",
        label="Tools",
        skills=[Skill(name="Git"), Skill(name="JSON Schema", status="off"), Skill(name="Docker")],
    )
    assert skills_of(group, SkillPick(id="tools")) == ["Git", "Docker"]
    assert skills_of(group, SkillPick(id="tools", skills=["JSON Schema", "Git"])) == [
        "JSON Schema",
        "Git",
    ]


def validate_presets(presets_dir: Path):
    return CliRunner().invoke(
        app, ["validate", "--bank", str(FIXTURES / "bank"), "--presets", str(presets_dir)]
    )


def test_a_duplicate_yaml_key_fails(presets_dir):
    """The loader must not keep the second `projects:` and drop the first."""
    path = presets_dir / "swe.yaml"
    path.write_text(path.read_text() + "projects: []\n")
    result = validate_presets(presets_dir)
    assert result.exit_code == 1
    assert "found duplicate key 'projects'" in result.stderr


def test_malformed_preset_yaml_is_reported_without_a_traceback(presets_dir):
    (presets_dir / "swe.yaml").write_text("name: swe\nlabel: [unclosed\n")
    (presets_dir / "ml.yaml").write_text("name: ml\nlabel: SWE2\nprojects: [nope]\n")
    result = validate_presets(presets_dir)
    assert result.exit_code == 1
    assert "swe.yaml: invalid YAML" in result.stderr
    assert "no projects entry 'nope'" in result.stderr  # the other presets were still checked
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", ["validate", "build"])
@pytest.mark.parametrize("kind", ["missing", "empty"])
def test_a_missing_or_empty_presets_directory_fails(tmp_path, command, kind):
    presets = tmp_path / "presets"
    if kind == "empty":
        presets.mkdir()
    args = ["--bank", str(FIXTURES / "bank"), "--presets", str(presets)]
    if command == "build":
        args += ["--all", "--out", str(tmp_path / "out")]
    result = CliRunner().invoke(app, [command, *args])
    assert result.exit_code == 1
    message = "presets directory is missing" if kind == "missing" else "no presets found"
    assert f"{presets}: {message}" in result.stderr
    assert not list(tmp_path.glob("out/*.pdf"))
