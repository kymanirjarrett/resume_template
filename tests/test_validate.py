"""`resume validate` must reject a broken bank with a message that names the problem."""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from resume_builder.cli import app
from resume_builder.load import BankError, load_bank, read_yaml


@pytest.fixture
def bank_dir(tmp_path, sample) -> Path:
    target = tmp_path / "bank"
    shutil.copytree(sample / "bank", target)
    return target


def edit(bank_dir: Path, stem: str, change: Callable[[Any], None]) -> None:
    path = bank_dir / f"{stem}.yaml"
    data = read_yaml(path)
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def entry(data: list[dict], entry_id: str) -> dict:
    return next(e for e in data if e["id"] == entry_id)


def problems(bank_dir: Path) -> str:
    with pytest.raises(BankError) as exc:
        load_bank(bank_dir)
    return "\n".join(exc.value.problems)


def test_unquoted_off_stays_a_string(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("status: off\nverify: true\n")
    assert read_yaml(path) == {"status": "off", "verify": True}


def test_duplicate_ids_fail(bank_dir):
    edit(
        bank_dir,
        "projects",
        lambda d: entry(d, "ledger-lens")["bullets"][0].update(id="halden-freight"),
    )
    assert "duplicate id 'halden-freight'" in problems(bank_dir)


def test_errors_name_the_entry(bank_dir):
    edit(
        bank_dir,
        "experience",
        lambda d: entry(d, "halden-freight")["bullets"][0].update(tags=["web"]),
    )
    message = problems(bank_dir)
    assert (
        "experience.yaml: halden-freight.bullets.0.tags: Extra inputs are not permitted" in message
    )


def test_unknown_field_fails(bank_dir):
    edit(bank_dir, "experience", lambda d: entry(d, "halden-freight").update(staus="off"))
    assert "Extra inputs are not permitted" in problems(bank_dir)


def add_variant(bank_dir: Path, **fields: str) -> None:
    """Append an off variant of the first bullet with optional field overrides."""

    def change(data):
        bullets = entry(data, "halden-freight")["bullets"]
        variant = {"id": "halden-freight-test-variant", "text": "Variant wording", "status": "off"}
        variant["variant_of"] = bullets[0]["id"]
        bullets.append({**variant, **fields})

    edit(bank_dir, "experience", change)


def test_dangling_variant_fails(bank_dir):
    add_variant(bank_dir, variant_of="no-such-bullet")
    assert "'no-such-bullet', which is not a bullet in this entry" in problems(bank_dir)


def test_variant_of_a_variant_fails(bank_dir):
    add_variant(bank_dir)

    def chain(data):
        bullets = entry(data, "halden-freight")["bullets"]
        bullets.append(
            {"id": "halden-freight-test-chain", "text": "x", "status": "off",
             "variant_of": "halden-freight-test-variant"}
        )  # fmt: skip

    edit(bank_dir, "experience", chain)
    assert "itself a variant" in problems(bank_dir)


def test_active_variant_fails(bank_dir):
    add_variant(bank_dir, status="active")
    assert "a variant cannot be active" in problems(bank_dir)


def test_dates_out_of_order_fail(bank_dir):
    edit(
        bank_dir,
        "experience",
        lambda d: entry(d, "halden-freight").update(dates={"start": "2026-08", "end": "2026-05"}),
    )
    assert "end 2026-05 is before start 2026-08" in problems(bank_dir)


def test_duplicate_skill_fails(bank_dir):
    edit(bank_dir, "skills", lambda d: d[1]["skills"].append({"name": "python"}))
    assert "skill 'python' appears in both 'languages' and 'frameworks'" in problems(bank_dir)


def test_missing_file_fails(bank_dir):
    (bank_dir / "awards.yaml").unlink()
    assert "awards.yaml: file is missing" in problems(bank_dir)


def test_review_fields_are_gone(bank_dir):
    edit(bank_dir, "experience", lambda d: entry(d, "halden-freight").update(verify=True))
    assert "Extra inputs are not permitted" in problems(bank_dir)


def test_secondary_experience_loads(sample):
    bank = load_bank(sample / "bank")
    assert [e.id for e in bank.secondary] == ["campus-it"]


def test_workshop_lead_is_leadership(sample):
    bank = load_bank(sample / "bank")
    assert bank.leadership[0].id == "acm-chapter"
    assert bank.leadership[0].role == "Workshop Lead"


def test_cli_reports_ok(sample):
    result = CliRunner().invoke(
        app, ["validate", "--bank", str(sample / "bank"), "--presets", str(sample / "presets")]
    )
    assert result.exit_code == 0
    assert result.stdout.startswith("Bank OK:")


def test_cli_exits_nonzero_on_problems(bank_dir):
    edit(bank_dir, "experience", lambda d: entry(d, "halden-freight").update(staus="off"))
    result = CliRunner().invoke(app, ["validate", "--bank", str(bank_dir)])
    assert result.exit_code == 1
    assert "error:" in result.stderr


def test_majors_take_a_track(sample):
    school = load_bank(sample / "bank").education[0]
    assert school.majors[0].track == "Software Systems"


@pytest.mark.parametrize(
    ("stem", "change", "field"),
    [
        (
            "education",
            lambda d: entry(d, "kessler-state")["majors"][0].update(focus="Software"),
            "education.yaml: kessler-state.majors.0.focus",
        ),
        (
            "experience",
            lambda d: entry(d, "halden-freight")["bullets"][0].update(skills=["Python"]),
            "experience.yaml: halden-freight.bullets.0.skills",
        ),
    ],
)
def test_retired_fields_are_rejected(bank_dir, stem, change, field):
    edit(bank_dir, stem, change)
    result = CliRunner().invoke(app, ["validate", "--bank", str(bank_dir)])
    assert result.exit_code == 1
    assert f"{field}: Extra inputs are not permitted" in result.stderr


def test_a_duplicate_key_in_the_bank_fails(bank_dir):
    path = bank_dir / "awards.yaml"
    path.write_text(
        path.read_text().replace(
            "name: 1st Place, KesslerHacks 2025",
            "name: 1st Place, KesslerHacks 2025\n  name: 2nd Place",
            1,
        )
    )
    assert "found duplicate key 'name'" in problems(bank_dir)
