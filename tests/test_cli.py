from typer.testing import CliRunner

from resume_builder import __version__
from resume_builder.cli import app


def test_version_command_prints_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
