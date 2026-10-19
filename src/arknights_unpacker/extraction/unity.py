"""UnityPy is imported lazily, and Ark compression is registered only by engine callers."""
from pathlib import Path
import sys

def load_bundle(path, *, data=None):
    import UnityPy
    from UnityPy.enums import CompressionFlags
    from UnityPy.helpers import CompressionHelper
    from arknights_unpacker.paths import resource_root
    vendor=resource_root()/'vendor'
    if str(vendor) not in sys.path: sys.path.insert(0,str(vendor))
    from lz4ak.Block import decompress_lz4ak
    CompressionHelper.DECOMPRESSION_MAP[CompressionFlags.LZHAM]=decompress_lz4ak
    return UnityPy.load(data if data is not None else str(path))

def raw_text(data):
    value=data.m_Script
    return value.encode('utf-8',errors='surrogateescape') if isinstance(value,str) else bytes(value)
