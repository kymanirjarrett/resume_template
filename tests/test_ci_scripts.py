"""The CI scripts: the exact-set check on built PDFs, and the draft-verify-promote publisher.

The publisher runs against fake `gh` and `git` commands that keep releases in a JSON file, so
every failure path can be exercised without touching GitHub.
"""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_build = load_script("check_build")
publish_release = load_script("publish_release")
PDFS = [
    "Kymani_Jarrett_ResumeDE.pdf",
    "Kymani_Jarrett_ResumeML.pdf",
    "Kymani_Jarrett_ResumeQuant.pdf",
    "Kymani_Jarrett_ResumeSWE.pdf",
    "Kymani_Jarrett_ResumeSecurity.pdf",
]


# ---------- check_build ----------


class PAGES_HOLDER:  # noqa: N801
    pages: dict[str, int] = {}


@pytest.fixture
def build_dir(tmp_path, monkeypatch) -> Path:
    """One fake PDF per preset; page counts come from PAGES instead of a real PDF."""
    out = tmp_path / "build"
    out.mkdir()
    for name in PDFS:
        (out / name).write_bytes(name.encode())
    monkeypatch.setattr(PAGES_HOLDER, "pages", {name: 1 for name in PDFS})
    monkeypatch.setattr(check_build, "page_count", lambda pdf: PAGES_HOLDER.pages[pdf.name])
    return out


def problems(build_dir: Path) -> list[str]:
    return check_build.check(build_dir, FIXTURES / "bank", FIXTURES / "presets")


def test_a_complete_build_passes_and_writes_sums(build_dir):
    assert problems(build_dir) == []
    sums = (build_dir / "SHA256SUMS").read_text().split()
    assert sums[1::2] == PDFS
    assert sums[0] == hashlib.sha256(PDFS[0].encode()).hexdigest()


def test_a_missing_pdf_fails(build_dir):
    (build_dir / PDFS[0]).unlink()
    assert problems(build_dir) == [f"missing {PDFS[0]}"]
    assert not (build_dir / "SHA256SUMS").exists()


def test_a_stale_extra_pdf_fails(build_dir):
    (build_dir / "Kymani_Jarrett_ResumeOLD.pdf").write_bytes(b"old")
    assert problems(build_dir) == ["unexpected Kymani_Jarrett_ResumeOLD.pdf"]


def test_a_two_page_pdf_fails(build_dir):
    PAGES_HOLDER.pages[PDFS[0]] = 2
    assert problems(build_dir) == [f"{PDFS[0]} is 2 pages"]


def test_an_empty_presets_directory_fails(build_dir, tmp_path):
    empty = tmp_path / "presets"
    empty.mkdir()
    assert check_build.check(build_dir, FIXTURES / "bank", empty) == [f"{empty}: no presets found"]


# ---------- publish_release ----------

FAKE_GH = r"""
import json, os, sys
from pathlib import Path
state_path = Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())
releases = state["releases"]
args = sys.argv[1:]
assert args[0] == "release", args
cmd, tag = args[1], args[2]

def save():
    state_path.write_text(json.dumps(state))

if cmd == "view":
    if tag not in releases:
        print("release not found", file=sys.stderr); sys.exit(1)
    print(json.dumps(releases[tag]))
elif cmd == "create":
    files = [a for a in args[3:] if a.endswith(".pdf")]
    releases[tag] = {"isDraft": "--draft" in args, "assets": [],
                     "title": args[args.index("--title") + 1]}
    for f in files:
        name = Path(f).name
        if name == os.environ.get("FAKE_FAIL_UPLOAD"):
            save(); print("upload failed", file=sys.stderr); sys.exit(1)
        data = Path(f).read_bytes()
        if name == os.environ.get("FAKE_CORRUPT"):
            data += b"x"
        import hashlib
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        releases[tag]["assets"].append({"name": name, "size": len(data), "digest": digest})
    save()
elif cmd == "delete":
    releases.pop(tag, None)
    if state.get("latest") == tag:
        state["latest"] = None
    save()
elif cmd == "edit":
    releases[tag]["isDraft"] = False
    state["latest"] = tag
    save()
"""

FAKE_GIT = r"""
import json, os, sys
from pathlib import Path
state_path = Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())
if sys.argv[1] == "diff":
    code = state["diffs"].pop(0) if state["diffs"] else 0
    state_path.write_text(json.dumps(state))
    sys.exit(code)
"""

SHA = "abc1234def5678"
TAG = "resumes-abc1234"
OLD = {"isDraft": False, "assets": [{"name": "old.pdf", "size": 1}]}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """Fake gh and git on PATH, a previous latest release, and a checked build directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, source in (("gh", FAKE_GH), ("git", FAKE_GIT)):
        (bin_dir / f"{name}.py").write_text(source)
        script = bin_dir / name
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bin_dir / name}.py" "$@"\n')
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_STATE", str(state_path))

    build = tmp_path / "build"
    build.mkdir()
    sums = []
    for name in PDFS:
        (build / name).write_bytes(name.encode())
        sums.append(f"{hashlib.sha256(name.encode()).hexdigest()}  {name}")
    (build / "SHA256SUMS").write_text("\n".join(sums) + "\n")

    def state(**changes):
        if changes:
            current = json.loads(state_path.read_text())
            current.update(changes)
            state_path.write_text(json.dumps(current))
        return json.loads(state_path.read_text())

    state_path.write_text(json.dumps({"releases": {"resumes-old": OLD}, "latest": "resumes-old"}))
    state(diffs=[])
    return build, state


def publish(build: Path) -> int:
    return publish_release.main([SHA, str(build)])


def test_publish_promotes_a_complete_release(fake):
    build, state = fake
    assert publish(build) == 0
    after = state()
    assert after["latest"] == TAG
    assert after["releases"][TAG]["isDraft"] is False
    assert sorted(a["name"] for a in after["releases"][TAG]["assets"]) == PDFS
    assert after["releases"][TAG]["title"] == "Latest Resumes"


def test_a_failed_upload_keeps_the_previous_release_and_a_retry_recovers(fake, monkeypatch):
    build, state = fake
    monkeypatch.setenv("FAKE_FAIL_UPLOAD", PDFS[-1])
    assert publish(build) == 1
    after = state()
    assert after["latest"] == "resumes-old"
    assert after["releases"]["resumes-old"] == OLD
    assert after["releases"][TAG]["isDraft"] is True

    monkeypatch.delenv("FAKE_FAIL_UPLOAD")
    assert publish(build) == 0
    after = state()
    assert after["latest"] == TAG
    assert sorted(a["name"] for a in after["releases"][TAG]["assets"]) == PDFS


def test_a_corrupted_upload_is_not_promoted(fake, monkeypatch):
    build, state = fake
    monkeypatch.setenv("FAKE_CORRUPT", PDFS[0])
    assert publish(build) == 1
    assert state()["latest"] == "resumes-old"


def test_an_older_build_does_not_publish(fake):
    build, state = fake
    state(diffs=[1])
    assert publish(build) == 0
    after = state()
    assert after["latest"] == "resumes-old"
    assert TAG not in after["releases"]


def test_main_moving_during_upload_stops_promotion(fake):
    build, state = fake
    state(diffs=[0, 1])
    assert publish(build) == 0
    after = state()
    assert after["latest"] == "resumes-old"
    assert TAG not in after["releases"]


def test_rerunning_a_published_commit_keeps_one_release(fake):
    build, state = fake
    assert publish(build) == 0
    assert publish(build) == 0
    after = state()
    assert after["latest"] == TAG
    assert sorted(after["releases"]) == sorted(["resumes-old", TAG])


def test_a_published_release_is_never_deleted_when_main_moves(fake):
    """A rerun of a published commit must not remove that public release if main moves."""
    build, state = fake
    assert publish(build) == 0
    state(diffs=[0, 1])
    assert publish(build) == 0
    after = state()
    assert after["latest"] == TAG
    assert after["releases"][TAG]["isDraft"] is False
