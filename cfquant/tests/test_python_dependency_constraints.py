"""Keep installable metadata from selecting known broken old-Python packages."""
from pathlib import Path

from packaging.requirements import Requirement
import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('version', ['3.8', '3.9', '3.10', '3.11', '3.12', '3.13', '3.14'])
def test_calendar_and_timezone_requirements_match_both_install_methods(version):
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    requirements = [line.strip() for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()
                    if line.strip() and not line.lstrip().startswith(('#', '--'))]
    selected = []
    for values in (project['project']['dependencies'], requirements):
        active = {}
        for value in values:
            requirement = Requirement(value)
            if not requirement.marker or requirement.marker.evaluate({'python_version': version}):
                active[requirement.name.replace('_', '-')] = requirement.specifier
        calendar = active['pandas-market-calendars']
        assert '5.2.2' in calendar
        assert '5.1.3' not in calendar  # Does not carry the required 2026 SSE data.
        if tuple(map(int, version.split('.'))) < (3, 10):
            assert '5.2.3' not in calendar and '5.2.4' not in calendar
        else:
            assert '5.2.4' in calendar
        assert ('backports.zoneinfo' in active) == (version == '3.8')
        selected.append({name: str(active[name]) for name in ('pandas-market-calendars', 'backports.zoneinfo')
                         if name in active})
    assert selected[0] == selected[1]
