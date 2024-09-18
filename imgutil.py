import fnmatch
import io
import os
from dataclasses import dataclass
from typing import Callable, List, Optional

__all__ = ["Format", "formats", "supported_formats"]


@dataclass
class Format:
    name: str
    extensions: List[str]
    magic_number: bytes
    _identify: Callable[[io.BytesIO], bool] = lambda _: True
    """Extended identification on top of magic_number"""

    def match_filename(self, filename: str) -> bool:
        return any(fnmatch.fnmatchcase(filename.lower(), pattern) for pattern in self.extensions)

    def match_content(self, stream: io.BytesIO, start: Optional[bytes] = None) -> bool:
        if start is None:
            start = stream.read(len(self.magic_number))
            stream.seek(0, os.SEEK_SET)
        if not start.startswith(self.magic_number):
            return False
        return self._identify(stream)


formats = [
    Format("BMP", ["*.bmp", "*.dib"], b"BM"),
    Format("GIF", ["*.gif"], b"GIF8"),  # GIF87a or GIF89a
    Format("JPEG", ["*.jpg", "*.jpe", "*.jpeg", "*.jif", "*jfi", "*.jfif"], b"\xff\xd8\xff"),
    Format("PNG", ["*.png"], b"\x89PNG"),
    Format("TIFF (BE)", ["*.tif", "*.tiff"], b"MM\x00*"),
    Format("TIFF (LE)", ["*.tif", "*.tiff"], b"II*\x00"),
    Format("WEBP", ["*.webp"], b"RIFF", lambda f: f.read(12)[8:] == b"WEBP"),
    Format("AV1 IF", ["*.avif", "*.avifs"], b"\x00", lambda f: f.read(12)[4:] == b"ftypavif"),
]

supported_formats = ("BMP", "GIF", "JPEG", "PNG")
