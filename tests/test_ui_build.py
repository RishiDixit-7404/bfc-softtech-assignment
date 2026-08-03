"""The committed frontend build, checked from the Python side.

``ui/`` is build output that is committed on purpose (``DECISIONS.md`` D27), so
it is the one directory in this repository whose contents nobody writes by
hand. That makes it exactly the place where an accidental CDN reference would
survive review: a reviewer reads ``frontend/src``, and a font link pulled in by
a dependency appears only in the bundle.

So the assertion lives here, in the suite that always runs, rather than in the
frontend suite that needs a Node toolchain to run at all.

Nothing here imports ``chat`` or ``calculators``. It reads files.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
INDEX = UI / "index.html"

# src="..." / href="..." on any element, single or double quoted.
_REFERENCE = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

# @import "..." and @import url(...), in a stylesheet or an inline <style>.
_IMPORT = re.compile(r"""@import\s+(?:url\()?["']?([^"')\s;]+)""", re.IGNORECASE)

# url(...) inside CSS - how a webfont or background image would be pulled in.
_CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)""", re.IGNORECASE)

# Anything that leaves this origin. Protocol-relative "//host/x" counts, and is
# the form most likely to be missed by eye.
_OFF_ORIGIN = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.IGNORECASE)


def _references(text: str) -> list[str]:
    return [
        *(match.group(1).strip() for match in _REFERENCE.finditer(text)),
        *(match.group(1).strip() for match in _IMPORT.finditer(text)),
    ]


def _off_origin(candidates: list[str]) -> list[str]:
    """The subset that would make the browser talk to another host.

    ``data:`` and ``blob:`` are inlined by the bundler and fetch nothing;
    everything else with a scheme or a leading ``//`` does.
    """
    return [
        candidate
        for candidate in candidates
        if _OFF_ORIGIN.match(candidate) and not candidate.startswith(("data:", "blob:"))
    ]


def test_the_frontend_build_is_committed():
    """Python alone must be enough to serve the page. D27."""
    assert INDEX.is_file(), "ui/index.html is missing - run: cd frontend && npm run build"
    assert list(UI.rglob("*.js")), "ui/ has no bundle - the build did not run"


def test_the_built_index_references_no_external_url():
    """No CDN, no font host, no analytics - in src, href, or @import.

    This is the whole of the no-external-request rule, asserted on the artifact
    that ships rather than on the source that produces it.
    """
    offenders = _off_origin(_references(INDEX.read_text(encoding="utf-8")))

    assert offenders == [], f"ui/index.html reaches off-origin: {offenders}"


def test_every_reference_in_the_built_index_resolves_inside_ui():
    """A relative path is only safe if the file is actually there.

    Catches the other half of the same mistake: an asset referenced but not
    committed loads nothing, which looks like a styling bug rather than a
    missing file.
    """
    missing = []
    for reference in _references(INDEX.read_text(encoding="utf-8")):
        if _OFF_ORIGIN.match(reference) or reference.startswith(("data:", "#", "mailto:")):
            continue
        target = UI / reference.split("?")[0].split("#")[0].lstrip("./")
        if not target.is_file():
            missing.append(reference)

    assert missing == [], f"ui/index.html references files that are not there: {missing}"


@pytest.mark.parametrize(
    "stylesheet", sorted(UI.rglob("*.css")), ids=lambda path: path.name
)
def test_no_stylesheet_pulls_in_a_font_or_image_from_another_host(stylesheet):
    """The realistic way a CDN sneaks back in.

    An ``@import`` at the top of a stylesheet, or a ``url()`` behind a
    ``font-face``, is invisible in ``frontend/src`` if a dependency added it.
    """
    text = stylesheet.read_text(encoding="utf-8")
    candidates = [
        *(match.group(1).strip() for match in _IMPORT.finditer(text)),
        *(match.group(1).strip() for match in _CSS_URL.finditer(text)),
    ]

    assert _off_origin(candidates) == [], (
        f"{stylesheet.name} reaches off-origin: {_off_origin(candidates)}"
    )
