"""Back-compat shim -- :mod:`tribunal.checkers` was renamed to :mod:`tribunal.scan` in v3.0.0a1.

External users importing ``from tribunal.checkers import ...`` keep working;
internal code should import from ``tribunal.scan``.

This shim re-exports the public API and forwards submodule imports so that
``from tribunal.checkers.secrets import ...`` continues to function.
"""

from __future__ import annotations

import importlib
import sys
import warnings

from tribunal.scan import (  # noqa: F401 -- re-export
    CheckResult,
    CheckerFunc,
    Finding,
    collect_files,
    register,
    register_global,
    run_checkers,
)

# Make `tribunal.checkers.<sub>` resolve to `tribunal.scan.<sub>` without
# having to physically duplicate the files. Each submodule is loaded the
# first time it is referenced and aliased in ``sys.modules``.
_SUBMODULES = ("go", "python", "secrets", "tdd", "typescript")

for _sub in _SUBMODULES:
    _full_old = f"{__name__}.{_sub}"
    _full_new = f"tribunal.scan.{_sub}"
    if _full_old not in sys.modules:
        sys.modules[_full_old] = importlib.import_module(_full_new)


def __getattr__(name: str):  # pragma: no cover - simple proxy
    if name in _SUBMODULES:
        return sys.modules[f"{__name__}.{name}"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CheckResult",
    "CheckerFunc",
    "Finding",
    "collect_files",
    "register",
    "register_global",
    "run_checkers",
]

warnings.warn(
    "tribunal.checkers is deprecated; import from tribunal.scan instead. "
    "This shim will be removed in v4.",
    DeprecationWarning,
    stacklevel=2,
)
