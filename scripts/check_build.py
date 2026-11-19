"""Check a build directory holds exactly one one-page PDF per preset, then write SHA256SUMS.

Usage: python scripts/check_build.py <build-dir> [--bank bank] [--presets presets]

CI runs this on the final build output before uploading or publishing anything, so a missing,
extra, stale, or overflowing PDF stops the release.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from resume_builder.load import BankError, load_bank
from resume_builder.presets import load_presets
from resume_builder.render import BuildError, page_count, pdf_stem


def check(build_dir: Path, bank_dir: Path, presets_dir: Path) -> list[str]:
    try:
        bank = load_bank(bank_dir)
    except BankError as exc:
        return exc.problems
    presets, problems = load_presets(presets_dir, bank)
    if problems:
        return problems

    expected = {f"{pdf_stem(bank, p)}.pdf" for p in presets}
    found = {p.name for p in build_dir.glob("*.pdf")}
    problems += [f"missing {name}" for name in sorted(expected - found)]
    problems += [f"unexpected {name}" for name in sorted(found - expected)]
    for name in sorted(expected & found):
        try:
            if (pages := page_count(build_dir / name)) != 1:
                problems.append(f"{name} is {pages} pages")
        except BuildError as exc:
            problems.append(str(exc))
    if not problems:
        sums = [
            f"{hashlib.sha256((build_dir / n).read_bytes()).hexdigest()}  {n}"
            for n in sorted(expected)
        ]
        (build_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("build_dir", type=Path)
    parser.add_argument("--bank", type=Path, default=Path("bank"))
    parser.add_argument("--presets", type=Path, default=Path("presets"))
    args = parser.parse_args(argv)
    problems = check(args.build_dir, args.bank, args.presets)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print((args.build_dir / "SHA256SUMS").read_text(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
