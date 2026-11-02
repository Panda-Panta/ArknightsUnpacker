"""Read installed font names without installing fonts or scanning other folders."""
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path


@dataclass(frozen=True)
class FontFace:
    path: str
    index: int
    family: str
    style: str


def system_font_directories():
    directories = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts']
    local = os.environ.get('LOCALAPPDATA')
    if local:
        directories.append(Path(local) / 'Microsoft' / 'Windows' / 'Fonts')
    # Desktop sandbox helpers can redirect LOCALAPPDATA while the user's
    # installed fonts remain in the ordinary profile font directory.
    directories.append(Path.home() / 'AppData' / 'Local' / 'Microsoft' / 'Windows' / 'Fonts')
    return tuple(dict.fromkeys(directories))


def _name(table, ids, fallback):
    for name_id in ids:
        records = [record for record in table.names if record.nameID == name_id]
        # Prefer the font's own Chinese name, then its English name.
        records.sort(key=lambda record: (0 if record.langID in (0x804, 0x404) else
                                        1 if record.langID == 0x409 else 2))
        for record in records:
            try:
                value = record.toUnicode().strip()
            except (UnicodeError, ValueError):
                continue
            if value:
                return value
    return fallback


def font_faces(path):
    """Return each face's stable file/index identity, reading only its name table."""
    from fontTools.ttLib import TTCollection, TTFont

    path = Path(path).resolve()

    def face(font, index):
        names = font['name']
        return FontFace(str(path), index, _name(names, (16, 1), path.stem),
                        _name(names, (17, 2), 'Regular'))

    if path.suffix.lower() == '.ttc':
        # TTCollection opens its TTFont readers lazily with their fontNumber.
        with TTCollection(str(path), lazy=True) as collection:
            return tuple(face(font, index) for index, font in enumerate(collection.fonts))
    with TTFont(str(path), lazy=True) as font:
        return (face(font, 0),)


@lru_cache(maxsize=1)
def system_font_faces():
    """Cache the two font-directory inventories for this application process."""
    faces = {}
    for directory in system_font_directories():
        try:
            if directory.is_symlink():
                continue
            paths = sorted(directory.iterdir())
        except OSError:
            continue
        for path in paths:
            try:
                if path.suffix.lower() not in {'.ttf', '.otf', '.ttc'} or path.is_symlink() or not path.is_file():
                    continue
                for item in font_faces(path):
                    faces[(item.path.casefold(), item.index)] = item
            except Exception:
                # A single malformed or unreadable installed font must not
                # prevent the remaining installed fonts from being selected.
                continue
    return tuple(sorted(faces.values(), key=lambda item:
                        (item.family.casefold(), item.style.casefold(), item.path.casefold(), item.index)))
