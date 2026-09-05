"""Initialize writable configuration without replacing user changes."""
import json
from pathlib import Path


def initialize_data(data_dir, bundle_dir, defaults):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    marker = data_dir / ".defaults-initialized"
    first_initialization = not marker.exists()
    for name, fallback in defaults.items():
        target = data_dir / name
        repair_empty = False
        if target.exists():
            if first_initialization and name in ("sources.json", "profiles.json"):
                with target.open(encoding="utf-8") as stream:
                    repair_empty = json.load(stream) == []
            if not repair_empty:
                continue
        template = Path(bundle_dir) / "data" / name
        value = fallback
        if template.is_file():
            with template.open(encoding="utf-8") as stream:
                value = json.load(stream)
            if not isinstance(value, type(fallback)):
                raise ValueError(f"Invalid bundled data structure: {name}")
        try:
            if repair_empty:
                backup = target.with_suffix(".before-defaults.json")
                if not backup.exists():
                    with backup.open("x", encoding="utf-8") as stream:
                        json.dump([], stream)
            with target.open("w" if repair_empty else "x", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2)
        except FileExistsError:
            pass
    marker.touch(exist_ok=True)
