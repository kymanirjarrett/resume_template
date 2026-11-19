# Resume as Code

Build tailored, one-page PDF resumes from a shared YAML bank. Keep your experience,
projects, and skills in one place, then use a preset to choose what each resume
shows. The sample bank carries my name and public links, but the work history,
school, and projects behind the five starter presets are fictional. Replace them
with your own before you build.

## Quick start

1. Choose **Use this template → Create a new repository** on GitHub, or download
   the source and start a repository from it. Choose **Private** if your copy will
   contain contact details or other information you want to keep private.
2. Install Python 3.12 or later, pdfLaTeX, and Poppler. On Ubuntu or Debian, install
   the system packages below. On macOS, install the TeX Live distribution with
   `brew install --cask mactex-no-gui` and Poppler with `brew install poppler`.

   ```sh
   sudo apt-get update
   sudo apt-get install texlive-latex-base texlive-latex-recommended \
     texlive-latex-extra texlive-fonts-recommended poppler-utils
   ```

3. From the root of your checkout, install and build the examples.

   ```sh
   python3.12 -m venv .venv
   source .venv/bin/activate
   python -m pip install -e ".[dev]"
   resume validate
   resume build --all --engine pdflatex
   ```

Open `build/Kymani_Jarrett_ResumeSWE.pdf` to see the software engineering example.
`resume build` selects `swe` by default, and `resume build --preset data-eng` builds
just the data engineering resume. Use `--out <directory>` for a separate output
directory. Builds also leave the generated LaTeX next to the PDFs.

## Customize your copy

| Path | What to edit |
| --- | --- |
| `bank/profile.yaml` | Name, links, and optional `phone` and `email` in the PDF header. The sample leaves phone and email out, which suits a public copy. Use `links: []` for no profile links and `about: []` for no background notes. |
| `bank/education.yaml`, `bank/experience.yaml`, `bank/projects.yaml`, `bank/skills.yaml` | Content available for presets to select. |
| `bank/secondary.yaml`, `bank/leadership.yaml`, `bank/awards.yaml` | Optional reference records. The supplied LaTeX layout renders education, work experience, projects, and technical skills. |
| `presets/` | One YAML file per resume. The `name` matches the filename without `.yaml`, and the unique `label` controls the PDF suffix. |
| `templates/resume.tex.j2` | Typography, spacing, and section layout. |
| `tests/fixtures/` | Standalone sample data for tests. You can customize your bank and presets without editing these fixtures. |

Keep the expected bank files in place. If a list file has no records, set its
contents to `[]`. Update preset references if you rename any record IDs. The
starter preset names are `swe`, `data-eng`, `ml`, `quant`, and `cyber`.
You can add or delete presets. Keep `swe.yaml` if you want bare `resume build` to
work, or specify a preset name explicitly.

For example, save this as `presets/backend.yaml` while the sample bank is in place.

```yaml
name: backend
label: Backend
education: [kessler-state]
experience:
  - id: halden-freight
    bullets: [halden-freight-retry]
  - meridian-health
projects: [ledger-lens]
skills:
  - id: languages
    skills: [Python, SQL]
  - data
```

A bare ID selects the active bullets or skills in bank order. An explicit list
selects the listed items in that order, including items marked `off`. Use
`bullets: []` for a heading alone. Presets reject archived items. In bullet text,
use `**bold**` for emphasis and quote YAML strings that contain `: `.

Run `resume validate` to catch unknown IDs, malformed YAML, and schema errors.
Build to a fresh directory after renaming presets if you want an exact set of
outputs. If a resume exceeds one page, trim its selections and rebuild.

## GitHub Actions

The workflow validates the YAML, runs Ruff and pytest, builds all presets with
pdfLaTeX, and checks the PDF filenames and page counts. Download the PDFs from the
**resumes** artifact on the workflow run. Artifacts follow the repository's
visibility, so on a public repository, treat committed data and built PDFs as public.

To publish PDFs as releases, set the repository Actions variable `PUBLISH_RESUMES`
to `true` under **Settings → Secrets and variables → Actions → Variables**, then
run **Build resumes** on `main`. Publication is opt-in. The workflow verifies the
assets in a draft release before promoting it. You can inspect the workflow
under [Actions](.github/workflows/build.yml).

For local development, run `ruff check .`, `ruff format --check .`, and `pytest`.
Use `REQUIRE_TEX=1 pytest` to require the PDF integration tests.

## License

[MIT](LICENSE) © 2026 Kymani Jarrett
