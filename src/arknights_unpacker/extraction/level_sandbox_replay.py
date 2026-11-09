"""Read the installed Sandbox V3 substage bindings used for timed playback."""
from math import inf, isfinite, nextafter
from pathlib import Path

from .level_metadata import _entries, _level_path, _root, _text
from .tables import load_local_tables


def sandbox_replay_deadline(root, resource_version, level_id, level, cancel):
    """Return the continuous timeout boundary for an installed Sandbox V3 substage."""
    limit = (level.get('options') or {}).get('maxPlayTime')
    if (not level_id.startswith('gamedata/levels/obt/sandbox/')
            or type(limit) not in (int, float) or not isfinite(limit) or limit <= 0):
        return None
    name = 'sandbox_perm_table'

    def decode(raw, _name):
        detail = _root(raw, name).Detail()
        for topic_entry in _entries(detail, 'SandboxV3', cancel.check, optional=True):
            topic = topic_entry.Value()
            for stage_entry in _entries(topic, 'SubStageData', cancel.check, optional=True):
                if _level_path(_text(stage_entry.Value().LevelId())) == level_id:
                    return True, {'format': 'sandbox_v3_substage_flatbuffers'}
        return False, {'format': 'sandbox_v3_substage_flatbuffers'}

    result = load_local_tables(Path(root), None, cancel=cancel, names={name}, decoders={name: decode},
                               expected_resource_version=resource_version)
    source = result.tables.get(name)
    # OnTick ends the wave when floor(maxPlayTime - userFixedPlayTime) <= 0.
    return nextafter(max(0.0, limit - 1), inf) if source and source.data else None
