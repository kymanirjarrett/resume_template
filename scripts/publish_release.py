"""Publish checked PDFs as a new GitHub release, then make it the latest one.

Usage: python scripts/publish_release.py <commit-sha> <build-dir>

Each commit gets its own release, tagged resumes-<short sha>. The PDFs are uploaded to a draft,
checked against SHA256SUMS, and only then published and marked latest. A failed upload leaves an
unpublished draft and the previous latest release untouched; running again replaces the draft.
A build whose resume inputs no longer match main (an older rerun) publishes nothing.

Needs the gh and git command-line tools, with GH_TOKEN set for gh.
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Files that change the PDFs. A main commit that touches none of these builds identical PDFs.
INPUTS = ["bank", "presets", "templates", "src", "pyproject.toml"]


class PublishError(Exception):
    pass


def run(*cmd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise PublishError(f"{' '.join(cmd[:3])} failed: {result.stderr.strip()}")
    return result


def matches_main(sha: str) -> bool:
    """True when main's resume inputs are the same as this commit's."""
    run("git", "fetch", "--quiet", "origin", "main")
    return (
        run("git", "diff", "--quiet", sha, "origin/main", "--", *INPUTS, check=False).returncode
        == 0
    )


def view(tag: str) -> dict | None:
    result = run("gh", "release", "view", tag, "--json", "isDraft,assets", check=False)
    return json.loads(result.stdout) if result.returncode == 0 else None


def read_sums(build_dir: Path) -> dict[str, str]:
    sums = {}
    for line in (build_dir / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        sums[name] = digest
    return sums


def verify(tag: str, build_dir: Path, sums: dict[str, str]) -> None:
    release = view(tag)
    if release is None:
        raise PublishError(f"release {tag} does not exist")
    assets = {a["name"]: a for a in release["assets"]}
    if set(assets) != set(sums):
        raise PublishError(f"release {tag} has {sorted(assets)}, expected {sorted(sums)}")
    for name, digest in sums.items():
        asset = assets[name]
        if asset.get("size") != (build_dir / name).stat().st_size:
            raise PublishError(f"{name} on {tag} does not match the built file's size")
        if asset.get("digest") and asset["digest"] != f"sha256:{digest}":
            raise PublishError(f"{name} on {tag} does not match the built file's digest")


def publish(sha: str, build_dir: Path) -> str:
    sums = read_sums(build_dir)
    pdfs = [str(build_dir / name) for name in sorted(sums)]
    tag = f"resumes-{sha[:7]}"

    if not matches_main(sha):
        return f"{sha[:7]} is behind main's resume inputs; not publishing."

    existing = view(tag)
    if existing is not None and existing["isDraft"]:
        run("gh", "release", "delete", tag, "--yes")
        existing = None
    if existing is None:
        today = datetime.now(UTC).strftime("%B %-d, %Y")
        run(
            "gh", "release", "create", tag, *pdfs,
            "--draft", "--target", sha, "--title", "Latest Resumes",
            "--notes", f"Built from {sha[:7]} on {today}.",
        )  # fmt: skip
    verify(tag, build_dir, sums)

    # Main may have moved while uploading; check again right before promoting. Only a draft
    # is ever removed: a release that is already public stays as it is.
    if not matches_main(sha):
        if existing is None:
            run("gh", "release", "delete", tag, "--yes", check=False)
        return f"main moved past {sha[:7]} during upload; not publishing."
    run("gh", "release", "edit", tag, "--draft=false", "--latest")
    return f"Published {tag} as the latest release."


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(publish(argv[0], Path(argv[1])))
    except PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
