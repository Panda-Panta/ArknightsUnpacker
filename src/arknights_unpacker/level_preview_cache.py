"""Local rendered clips keyed by game installation, resource version and level."""
from hashlib import sha256
from pathlib import Path


def preview_directory(data_root, game_root, resource_version):
    identity = f'{Path(game_root).resolve().as_posix().casefold()}\0{resource_version}'
    return Path(data_root) / 'level-previews' / sha256(identity.encode('utf-8')).hexdigest()


def preview_filename(level_id):
    return sha256(level_id.encode('utf-8')).hexdigest() + '.mp4'


def cached_previews(data_root, catalog):
    directory = preview_directory(data_root, catalog['root'], catalog['resource_version'])
    try:
        names = {entry.name for entry in directory.glob('*.mp4') if entry.is_file()}
    except OSError:
        return {}
    return {
        row['id']: directory / name
        for row in catalog['levels'] if row['available']
        if (name := preview_filename(row['id'])) in names
    }
