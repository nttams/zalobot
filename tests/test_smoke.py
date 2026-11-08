import tomllib
from pathlib import Path

import zalobot


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())
    assert zalobot.__version__ == pyproject["project"]["version"]


def _ultranormalize(name: str) -> str:
    """PyPI's rule for "too similar" names (warehouse ultranormalize_name)."""
    import re

    return re.sub(r"[oO]", "0", re.sub(r"[lLiI]", "1", re.sub(r"[._-]", "", name))).lower()


def test_pypi_name_is_not_too_similar_to_taken_names() -> None:
    """Regression: the plain name "zalobot" is "too similar" to an existing PyPI project and would be refused at
    upload, so the package is published as zalobot-sdk."""
    pyproject = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())
    name = pyproject["project"]["name"]
    assert name == "zalobot-sdk"
    assert _ultranormalize(name) != _ultranormalize("zalobot")
    assert _ultranormalize("zalobot") == "za10b0t"
