"""Shared contracts. Paths are source paths, never instructions to mutate the game."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any, Callable

PROTOCOL_VERSION = 1
ProgressSink = Callable[[dict[str, Any]], None]


class CancelledError(Exception):
    pass


class CancelToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise CancelledError("任务已取消")


def null_progress(event: dict[str, Any]) -> None:
    pass


@dataclass
class GameInstallation:
    root: Path
    profile_id: str
    base_root: Path | None = None
    hot_root: Path | None = None
    locale: str = "unknown"
    diagnostics: list[str] = field(default_factory=list)

    @property
    def source_roots(self) -> dict[str, Path]:
        return {k: v for k, v in {"base": self.base_root, "hot": self.hot_root}.items() if v is not None}


@dataclass
class SourceRef:
    path: str = ""
    layer: str = ""
    logical_name: str = ""
    object_name: str = ""
    path_id: str = ""
    table: str = ""
    pointer: str = ""
    sha256: str = ""
    decoder_version: str = ""


@dataclass
class FileRecord:
    path: str
    size: int
    mtime_ns: int
    extension: str = ""
    layer: str = "other"
    category: str = "未知用途"
    sha256: str | None = None
    hash_status: str = "metadata_only"
    error: str | None = None
    first_seen_at: float | None = None


@dataclass
class ScanOptions:
    window_hours: float = 24.0
    strict: bool = False
    resource_only: bool = False


@dataclass
class ScanSnapshot:
    snapshot_id: str
    profile_id: str
    root: str
    started_at: float
    finished_at: float
    files: list[FileRecord] = field(default_factory=list)
    complete: bool = True
    errors: list[str] = field(default_factory=list)
    manifest_versions: dict[str, Any] = field(default_factory=dict)
    baseline_id: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class FileChange:
    kind: str
    path: str
    before: FileRecord | None = None
    after: FileRecord | None = None


@dataclass
class FileChangeSet:
    baseline_id: str | None
    current_id: str
    changes: list[FileChange] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class ResolvedResource:
    logical_key: str
    path: str | None
    layer: str = ""
    status: str = "unknown"
    category: str = "未知用途"
    size: int = 0
    expected_hash: str = ""
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceCatalog:
    installation: GameInstallation
    resources: dict[str, ResolvedResource] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class ExtractionRequest:
    paths: list[str]
    output_root: str
    mode: str = "auto"
    kinds: list[str] = field(default_factory=lambda: ["image", "text", "audio", "spine", "video"])
    source_root: str = ""
    object_ids: dict[str, list[str]] = field(default_factory=dict)
    request_id: str = ""


@dataclass
class ExtractionResult:
    request_id: str = ""
    status: str = "succeeded"
    outputs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    output_root: str = ""


@dataclass
class DecodedTable:
    name: str
    data: Any
    source: SourceRef = field(default_factory=SourceRef)
    field_evidence: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class TableSourceSet:
    tables: dict[str, DecodedTable] = field(default_factory=dict)
    version: str = "unknown"
    resource_version: str = "unknown"
    diagnostics: list[str] = field(default_factory=list)
    complete: bool = True
    locale: str = "unknown"


@dataclass
class GameDataSnapshot:
    snapshot_id: str
    version: str
    resource_version: str
    tables: dict[str, Any]
    sources: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    complete: bool = True
    created_at: float = 0.0
    locale: str = "unknown"


@dataclass
class BuildSpec:
    phase: int | None = None
    level: int | None = None
    potential: int | None = None
    trust: int = 200
    module_id: str | None = None
    module_level: int = 3


@dataclass
class OperatorProfile:
    char_id: str
    name: str
    summary: dict[str, Any] = field(default_factory=dict)
    attributes: list[dict[str, Any]] = field(default_factory=list)
    trait: str = ""
    talents: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    building_skills: list[dict[str, Any]] = field(default_factory=list)
    potentials: list[str] = field(default_factory=list)
    modules: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class ModuleProfile:
    equip_id: str
    char_id: str
    char_name: str
    name: str
    type_name: str = ""
    phases: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class EntityChangeSet:
    baseline_id: str | None
    current_id: str
    operators: list[dict[str, Any]] = field(default_factory=list)
    modules: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    comparison_version: int = 0


class ExportFormat(str, Enum):
    PNG = "png"
    HTML = "html"
    JSON = "json"
    TXT = "txt"


@dataclass
class ReportOptions:
    width: int = 1200
    font_size: int = 28
    theme: str = "dark"
    max_page_height: int = 16000
    title: str = ""
    module_image_layout: str = "single"


@dataclass
class ReportSelection:
    operators: list[OperatorProfile] = field(default_factory=list)
    modules: list[ModuleProfile] = field(default_factory=list)
    changes: EntityChangeSet | None = None


@dataclass
class ReportDocument:
    title: str
    operators: list[OperatorProfile] = field(default_factory=list)
    modules: list[ModuleProfile] = field(default_factory=list)
    options: ReportOptions = field(default_factory=ReportOptions)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportArtifact:
    path: str
    format: str
    title: str = ""
    pages: int = 1
    status: str = "succeeded"


def as_jsonable(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return as_jsonable(asdict(obj))
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): as_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [as_jsonable(v) for v in obj]
    return obj
