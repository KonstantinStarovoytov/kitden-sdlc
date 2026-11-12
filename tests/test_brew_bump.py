from pathlib import Path

from brew_bump import bump_formula, deps_changed

FORMULA = (Path(__file__).parent / "fixtures" / "release" / "kitden.rb").read_text()
URL = "https://files.pythonhosted.org/packages/aa/bb/cc/kitden-0.8.1.tar.gz"
SHA = "f" * 64
DESC = "A new description"

OLD = (
    '[project]\nname = "kitden"\nversion = "0.8.0"\n'
    'dependencies = ["mcp>=2.3", "Starlette>=1.8"]\n'
)


def test_deps_changed_ignores_version():
    new = OLD.replace("0.8.0", "0.8.1")
    assert deps_changed(OLD, new) is False


def test_deps_changed_ignores_order_and_spacing():
    new = OLD.replace('"mcp>=2.3", "Starlette>=1.8"', '"starlette >= 1.8", "mcp>=2.3"')
    assert deps_changed(OLD, new) is False


def test_deps_changed_sees_a_change():
    assert deps_changed(OLD, OLD.replace("mcp>=2.3", "mcp>=2.4")) is True
    assert deps_changed(OLD, OLD.replace(', "Starlette>=1.8"', "")) is True


def test_bump_formula_touches_top_only():
    new = bump_formula(FORMULA, URL, SHA, DESC)
    old_lines, new_lines = FORMULA.splitlines(), new.splitlines()
    assert len(old_lines) == len(new_lines)
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines, strict=True)) if a != b]
    assert len(changed) == 3
    assert f'desc "{DESC}"' in new_lines[changed[0]]
    assert new_lines[changed[1]] == f'  url "{URL}"'
    assert new_lines[changed[2]] == f'  sha256 "{SHA}"'
    assert max(changed) < new.index("bottle do") and "bottle do" in new
    assert new.count(SHA) == 1


def test_bump_skips_when_formula_current():
    once = bump_formula(FORMULA, URL, SHA, DESC)
    assert bump_formula(once, URL, SHA, DESC) == once
