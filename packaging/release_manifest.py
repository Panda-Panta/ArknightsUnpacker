"""Record the complete bundle, dependency versions, and explicit source inputs."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files_under(root: Path):
    return sorted(path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)


def source_records(root: Path):
    source_inputs = [root / name for name in ("pyproject.toml", "uv.lock")]
    for name in ("src", "resources", "vendor", "packaging", "scripts"):
        source_inputs.extend(files_under(root / name))
    source_inputs.extend(root / "docs" / name for name in ("USER_GUIDE.md", "THIRD_PARTY_NOTICES.md"))
    return [{"path": p.relative_to(root).as_posix(), "size": p.stat().st_size, "sha256": sha256(p)} for p in sorted(set(source_inputs))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--task-id")
    parser.add_argument("--capture-source", type=Path)
    parser.add_argument("--source-snapshot", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    current_sources = source_records(root)
    if args.capture_source:
        args.capture_source.write_text(json.dumps(current_sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Source snapshot: {len(current_sources)} files")
        return
    if not args.bundle or not args.version or not args.task_id:
        parser.error("--bundle, --version and --task-id are required for a release manifest")
    if args.source_snapshot:
        previous_sources = json.loads(args.source_snapshot.read_text(encoding="utf-8"))
        if current_sources != previous_sources:
            old = {item["path"]: item for item in previous_sources}
            new = {item["path"]: item for item in current_sources}
            changed = [path for path in sorted(old.keys() | new.keys()) if old.get(path) != new.get(path)]
            raise SystemExit("Source changed during build; retain intermediate files and rebuild a fixed candidate: " + ", ".join(changed))
    bundle = args.bundle.resolve()
    if not (bundle / "ArknightsUnpacker.exe").is_file():
        raise SystemExit("Missing executable")
    required_assets = (
        "resources/folder_rules.json", "resources/html/operator.html", "resources/html/report.css",
        "vendor/ark_fbs/__init__.py", "vendor/ark_fbs/CN/__init__.py", "vendor/ark_fbs/CN/character_table.py",
        "vendor/lz4ak/Block.py", "fmod_toolkit/libfmod/Windows/x64/fmod.dll",
        "PySide6/plugins/platforms/qwindows.dll", "docs/USER_GUIDE.md", "docs/THIRD_PARTY_NOTICES.md",
        "licenses/Ark-Unpacker/Ark-Unpacker-LICENSE", "licenses/LGPL-3.0-only.txt",
    )
    missing = [name for name in required_assets if not (bundle / "_internal" / name).is_file()]
    if missing:
        raise SystemExit("Missing required bundle assets: " + ", ".join(missing))
    forbidden = [p.relative_to(bundle).as_posix() for p in files_under(bundle)
                 if any(part in {".work", ".venv", ".tools", "tests", "fixtures"} for part in p.relative_to(bundle).parts)
                 or "webengine" in p.name.lower()]
    if forbidden:
        raise SystemExit("Unexpected development or QtWebEngine files in bundle: " + ", ".join(forbidden[:20]))
    provenance = {
        "version": args.version, "task_id": args.task_id,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_kind": "workspace-file-manifest-no-git", "python": platform.python_version(),
        "source_consistency_checked": bool(args.source_snapshot),
        "platform": platform.platform(),
        "preflight": __import__("os").environ.get("ARKNIGHTS_BUILD_PREFLIGHT") == "1",
        "acceptance": "Build succeeded; consult artifacts/M9 for final runtime acceptance.",
        "upstreams": {
            "Ark-Unpacker": "4a4b9efc6be4690b68b70b4a16578950baa066d3",
            "Ark-FBS-Py": "161d5e229916d7193364983396076556fbeaa549",
        },
        "dependencies": {d.metadata["Name"]: d.version for d in metadata.distributions() if d.metadata.get("Name")},
        "source_files": current_sources,
    }
    (bundle / "build-info.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entries = [{"path": p.relative_to(bundle).as_posix(), "size": p.stat().st_size, "sha256": sha256(p)} for p in files_under(bundle) if p.name not in ("file-manifest.json", "SHA256SUMS.txt")]
    (bundle / "file-manifest.json").write_text(json.dumps({"version": args.version, "files": entries, "excludes": ["file-manifest.json", "SHA256SUMS.txt"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (bundle / "SHA256SUMS.txt").write_text("".join(f'{entry["sha256"]}  {entry["path"]}\n' for entry in entries) + f'{sha256(bundle / "file-manifest.json")}  file-manifest.json\n', encoding="utf-8")
    print(f"Manifest written: {len(entries)} bundle files; {len(provenance['source_files'])} source files")


if __name__ == "__main__":
    main()
