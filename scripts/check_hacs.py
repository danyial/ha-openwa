"""Offline check of the HACS repository layout.

hacs/action needs a GitHub repository and token, so it cannot run on
GitLab. This covers the structural rules it enforces for integrations.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_MANIFEST_KEYS = (
    "domain",
    "name",
    "documentation",
    "issue_tracker",
    "codeowners",
    "version",
)


def main() -> int:
    errors: list[str] = []
    hacs = json.loads((ROOT / "hacs.json").read_text())
    if not hacs.get("name"):
        errors.append("hacs.json: 'name' missing")

    integrations = [
        p
        for p in (ROOT / "custom_components").iterdir()
        if p.is_dir() and not p.name.startswith("__")
    ]
    if len(integrations) != 1:
        errors.append(f"expected exactly one integration, found {len(integrations)}")
    for integration in integrations:
        manifest = json.loads((integration / "manifest.json").read_text())
        errors.extend(
            f"{integration.name}/manifest.json: '{key}' missing"
            for key in REQUIRED_MANIFEST_KEYS
            if not manifest.get(key)
        )
        if manifest.get("domain") != integration.name:
            errors.append(
                f"domain {manifest.get('domain')!r} != dir {integration.name!r}"
            )
    if not (ROOT / "README.md").is_file():
        errors.append("README.md missing")

    for error in errors:
        print(f"ERROR: {error}")
    print("hacs structure ok" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
