import io
import os
import sys
import zipfile
from typing import Any, Iterator, Union, cast


class ZipPath(zipfile.Path):
    """Emulates pathlib.Path (and py3.12 zipfile.Path) behavior on py3.8"""
    @staticmethod
    def _relative_to(child: str, parent: str) -> str:
        if not parent.endswith("/"):
            parent += "/"
        if not child.startswith(parent):
            raise Exception(f"{parent} is not a parent of {child}")
        return child[len(parent):]

    def open(self, *args: Any, **kwargs: Any) -> Any:
        if "encoding" in kwargs and sys.version_info < (3, 9, 0):
            kwargs.pop("encoding")
            return io.TextIOWrapper(super().open(*args, **kwargs), encoding="utf-8-sig")
        return super().open(*args, **kwargs)

    def __truediv__(self, other: Union[str, "os.PathLike[str]"]) -> "ZipPath":
        res = super().__truediv__(other)
        res.__class__ = self.__class__
        return cast(ZipPath, res)

    def relative_to(self, other: zipfile.Path, *extra: Union[str, "os.PathLike[str]"]) -> str:
        assert not extra, "extra for ZipPath.relative_to not implemented"
        return self._relative_to(str(self), str(other))

    def iterdir(self) -> Iterator["ZipPath"]:
        for f in super().iterdir():
            root = cast(zipfile.ZipFile, getattr(f, "root"))
            yield ZipPath(root, self._relative_to(str(f), str(root.filename)))

    def rglob(self, pattern: str) -> Iterator["ZipPath"]:
        import fnmatch
        root = cast(zipfile.ZipFile, getattr(self, "root"))
        for match in fnmatch.filter((zi.filename for zi in root.filelist), pattern):
            yield ZipPath(root, match)
