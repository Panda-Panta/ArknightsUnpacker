"""Lightweight file-type inventory shared by source extraction and preview entry points.

The suffix identifies a preview candidate, not a promise that a decoder supports
its contents. Playback and image readers report unsupported/corrupt data later.
"""
from pathlib import Path


DIRECT_SOURCE_TYPES = {
    **{suffix: ('Image', 'image') for suffix in (
        '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff', '.tga', '.ico')},
    **{suffix: ('AudioClip', 'audio') for suffix in (
        '.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac', '.wma', '.opus', '.aif', '.aiff', '.adx', '.sfa')},
    **{suffix: ('VideoClip', 'video') for suffix in (
        '.mp4', '.m4v', '.mov', '.mkv', '.webm', '.avi', '.wmv', '.mpeg', '.mpg', '.ogv', '.ivf', '.usm')},
    **{suffix: ('TextAsset', 'text') for suffix in (
        '.txt', '.json', '.xml', '.csv', '.tsv', '.ini', '.yaml', '.yml', '.shader', '.log', '.md', '.bytes', '.idx')},
    '.atlas': ('TextAsset', 'spine'),
    '.skel': ('TextAsset', 'spine'),
}


def source_preview_type(path):
    """Return (object type, extraction kind) for a standalone candidate, if any."""
    return DIRECT_SOURCE_TYPES.get(Path(path).suffix.lower())
