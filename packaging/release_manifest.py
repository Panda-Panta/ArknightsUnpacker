"""Record the complete bundle, dependency versions, and explicit source inputs."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess


_GODOT_EXE = "scripts/level_preview/native_player/Godot.exe"
_GODOT_ASSETS = (
    _GODOT_EXE,
    "scripts/level_preview/native_player/project.godot", "scripts/level_preview/native_player/replay.tscn",
    "scripts/level_preview/native_player/replay.gd", "scripts/level_preview/native_player/battle_static.gdshader",
    "scripts/level_preview/native_bake/bake.html", "scripts/level_preview/native_bake/bake.js",
    "licenses/Godot/LICENSE.txt", "licenses/Godot/COPYRIGHT.txt", "licenses/Godot/source.json",
)


def _forbidden_asset(path: Path, preview_only: bool) -> bool:
    names = [part.casefold() for part in path.parts]
    if any(part in {".work", ".venv", ".tools", "tests", "fixtures"} for part in names):
        return True
    if any("webengine" in part or "webchannel" in part for part in names):
        return True
    return not preview_only and (
        "level_preview" in names or "godot" in names or "godot.exe" in names
    )


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files_under(root: Path):
    return sorted(path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)


def source_records(root: Path):
    source_inputs = [root / name for name in ("pyproject.toml", "uv.lock")]
    for name in ("src", "resources", "vendor", "packaging", "scripts"):
        source_inputs.extend(files_under(root / name))
    source_inputs.extend(root / "docs" / name for name in
                         ("USER_GUIDE.md", "LEVEL_PREVIEW_GUIDE.md", "THIRD_PARTY_NOTICES.md"))
    return [{"path": p.relative_to(root).as_posix(), "size": p.stat().st_size, "sha256": sha256(p)} for p in sorted(set(source_inputs))]


def source_provenance(root: Path):
    """Record the actual checkout; input hashes remain authoritative for bytes."""
    try:
        def git(*args):
            return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL,
                                           encoding="utf-8").strip()
        return {"source_kind": "git-workspace-file-manifest", "git_commit": git("rev-parse", "HEAD"),
                "git_tree": git("rev-parse", "HEAD^{tree}"),
                "git_dirty": bool(git("status", "--porcelain", "--untracked-files=normal"))}
    except (OSError, subprocess.CalledProcessError):
        return {"source_kind": "workspace-file-manifest", "git_commit": None, "git_tree": None,
                "git_dirty": None}


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
    preview_only = os.environ.get("ARKNIGHTS_LEVEL_PREVIEW_ONLY") == "1"
    bundle_name = "ArknightsMapViewer" if preview_only else "ArknightsUnpacker"
    guide = "LEVEL_PREVIEW_GUIDE.md" if preview_only else "USER_GUIDE.md"
    if not (bundle / (bundle_name + ".exe")).is_file():
        raise SystemExit("Missing executable")
    required_assets = (
        "resources/folder_rules.json", "resources/report_styles.json", "resources/html/operator.html", "resources/html/report.css",
        "resources/ui/app-icon.png", "resources/ui/app-icon.ico",
        "vendor/ark_fbs/__init__.py", "vendor/ark_fbs/CN/__init__.py", "vendor/ark_fbs/CN/character_table.py",
        "vendor/lz4ak/Block.py", "fmod_toolkit/libfmod/Windows/x64/fmod.dll",
        "PySide6/plugins/platforms/qwindows.dll", f"docs/{guide}", "docs/THIRD_PARTY_NOTICES.md",
        "licenses/Ark-Unpacker/Ark-Unpacker-LICENSE", "licenses/LGPL-3.0-only.txt",
    )
    godot = bundle / "_internal" / _GODOT_EXE
    if preview_only and not os.environ.get("ARKNIGHTS_GODOT_RUNTIME"):
        raise SystemExit("The level preview bundle requires ARKNIGHTS_GODOT_RUNTIME")
    if preview_only:
        if not re.search(r"(?:^|[-._])test(?:$|[-._])", args.version, re.IGNORECASE):
            raise SystemExit("ARKNIGHTS_GODOT_RUNTIME is only supported for a test build")
        required_assets += _GODOT_ASSETS
    elif godot.exists():
        raise SystemExit("Unexpected Godot runtime in the unpacker bundle")
    missing = [name for name in required_assets if not (bundle / "_internal" / name).is_file()]
    if missing:
        raise SystemExit("Missing required bundle assets: " + ", ".join(missing))
    relative_paths = (path.relative_to(bundle) for path in files_under(bundle))
    forbidden = [path.as_posix() for path in relative_paths if _forbidden_asset(path, preview_only)]
    if forbidden:
        raise SystemExit("Unexpected files for the selected bundle: " + ", ".join(forbidden[:20]))
    provenance = {
        "version": args.version, "task_id": args.task_id,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        **source_provenance(root), "python": platform.python_version(),
        "source_consistency_checked": bool(args.source_snapshot),
        "platform": platform.platform(),
        "application": bundle_name,
        "preflight": os.environ.get("ARKNIGHTS_BUILD_PREFLIGHT") == "1",
        "acceptance": "Build succeeded; consult docs/ACCEPTANCE.md for runtime acceptance boundaries.",
        "upstreams": {
            "Ark-Unpacker": "4a4b9efc6be4690b68b70b4a16578950baa066d3",
            "Ark-FBS-Py": "161d5e229916d7193364983396076556fbeaa549",
        },
        "dependencies": {d.metadata["Name"]: d.version for d in metadata.distributions() if d.metadata.get("Name")},
        "source_files": current_sources,
    }
    if preview_only:
        source = json.loads((root / "packaging/godot/source.json").read_text(encoding="utf-8"))
        if sha256(godot) != source["executable_sha256"]:
            raise SystemExit("Godot executable in the bundle does not match the pinned source")
        for name, notice in source["notices"].items():
            if sha256(bundle / "_internal" / "licenses" / "Godot" / name) != notice["sha256"]:
                raise SystemExit(f"Godot notice in the bundle does not match the pinned source: {name}")
        provenance["godot_runtime"] = {**source, "path": f"_internal/{_GODOT_EXE}"}
    (bundle / "build-info.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entries = [{"path": p.relative_to(bundle).as_posix(), "size": p.stat().st_size, "sha256": sha256(p)} for p in files_under(bundle) if p.name not in ("file-manifest.json", "SHA256SUMS.txt")]
    (bundle / "file-manifest.json").write_text(json.dumps({"version": args.version, "files": entries, "excludes": ["file-manifest.json", "SHA256SUMS.txt"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (bundle / "SHA256SUMS.txt").write_text("".join(f'{entry["sha256"]}  {entry["path"]}\n' for entry in entries) + f'{sha256(bundle / "file-manifest.json")}  file-manifest.json\n', encoding="utf-8")
    print(f"Manifest written: {len(entries)} bundle files; {len(provenance['source_files'])} source files")


if __name__ == "__main__":
    main()
