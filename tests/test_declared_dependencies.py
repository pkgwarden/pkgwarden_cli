import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

CLI_ROOT = Path(__file__).resolve().parents[1]
FIRST_PARTY_MODULES = {"pkgwarden_cli", "pkgwarden_cli_enterprise"}

# Both wheels are installed into the one embedded interpreter that becomes the pw binary
# (scripts/prepare_pyapp_enterprise_distribution.py), so an undeclared import in either
# package breaks the same binary. The enterprise project is a sibling of this one in the
# monorepo and absent from the public standalone mirror of pkgwarden-cli.
PACKAGED_PROJECTS = [
    CLI_ROOT,
    CLI_ROOT.parent / "pkgwarden-cli-enterprise",
]

# Distributions whose import name differs from the package name; declared-vs-imported
# comparison is by import name, so anything added here must be mapped explicitly.
IMPORT_NAME_BY_DISTRIBUTION = {"pyyaml": "yaml"}


def _declared_import_names(project_root: Path) -> set[str]:
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text())
    requirements: list[str] = pyproject["project"]["dependencies"]
    distributions = {
        re.split(r"[<>=!~\[;\s]", requirement, maxsplit=1)[0].strip().lower().replace("-", "_")
        for requirement in requirements
    }
    return {IMPORT_NAME_BY_DISTRIBUTION.get(name, name) for name in distributions}


def _imported_top_level_modules(source_root: Path) -> set[str]:
    modules: set[str] = set()
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                modules.add(node.module.split(".")[0])
    return modules


@pytest.mark.parametrize("project_root", PACKAGED_PROJECTS, ids=lambda path: path.name)
def test_every_third_party_import_is_a_declared_dependency(project_root: Path) -> None:
    """The packaged pw binary installs only declared dependencies, so a module imported
    directly but inherited transitively (click, via typer) is missing at runtime there while
    every local venv still resolves it -- a break no unit test or local run can see. Only
    static imports are checked; a dynamic importlib.import_module would slip past this."""
    if not project_root.is_dir():
        pytest.skip(f"{project_root.name} is not checked out beside this project")
    source_root = next((project_root / "src").iterdir())
    third_party = {
        module
        for module in _imported_top_level_modules(source_root)
        if module not in sys.stdlib_module_names and module not in FIRST_PARTY_MODULES
    }
    undeclared = third_party - _declared_import_names(project_root)
    assert undeclared == set(), (
        f"{project_root.name} imports but does not declare: {sorted(undeclared)}"
    )
