import os
import sys
import typing as t
from collections import namedtuple
from pathlib import Path

from .imgutil import Format as ImgFormat, formats as img_formats
from .jsonc import parse as parse_jsonc, ParserError as JsonParserError
from .ziputil import ZipPath

PY = sys.version_info

APath = t.TypeVar("APath", Path, ZipPath)

Item = namedtuple("Item", "name type data")


def find_entry_point(path: Path, checks: t.Mapping[str, bool]) -> ZipPath:
    from .cli import warn

    assert path.is_file()
    zippath = ZipPath(path)
    warn_for_hidden_files = checks.get("hidden_files", False)
    # find starting point inside the zip and check for hidden files
    candidates = []
    hidden = []
    manifest_found = False
    for f in zippath.iterdir():
        name = str(f.relative_to(zippath))
        if name.startswith("."):
            hidden.append(name)
        elif f.is_file() and f.name.lower() == "manifest.json":
            manifest_found = True
        if f.is_dir():
            candidates.append(f)
    if not manifest_found and len(candidates) == 1:
        # scan for more hidden files
        for f in candidates[0].iterdir():
            if str(f.relative_to(candidates[0])).startswith("."):
                hidden.append(str(f.relative_to(zippath)))
        # use directory instead of root
        zippath = candidates[0]
    if warn_for_hidden_files and hidden:
        warn(f"Zip contains hidden files: {hidden}.", path)
    return zippath


def read_manifest(path: APath) -> t.Tuple[t.Dict[str, t.Any], t.List[str]]:
    try:
        # py3.8 does not know encoding
        manifest = parse_jsonc(
            t.cast(t.TextIO, (path / "manifest.json").open(encoding="utf-8-sig")).read()
        )  # type: ignore[call-arg, unused-ignore]
    except JsonParserError as ex:
        raise Exception(f"Could not load manifest.json: {ex.__context__}")
    except FileNotFoundError:
        raise Exception(f"Could not find manifest.json in {path}")
    except Exception as ex:
        raise Exception(f"Could not load manifest.json: {ex.__class__.__name__}: {ex}")

    variants = list(manifest["variants"].keys()) if "variants" in manifest else [""]
    if "" not in variants:
        variants.append("")

    return manifest, variants


def identify_json(name: str, stream: t.TextIO, variants: t.List[str]) -> t.Optional[Item]:
    try:
        data = parse_jsonc(stream.read(), name)
    except JsonParserError as ex:
        raise Exception(f"Error parsing {name}: {ex.__context__}")

    if name == "settings.json":
        return Item(name, "settings", data)
    if name == "manifest.json":
        return Item(name, "manifest", data)
    for variant in variants:
        if variant:
            variant = variant + "/"
        if name.startswith(variant + "maps"):
            return Item(name, "maps", data)
        elif name.startswith(variant + "items"):
            return Item(name, "items", data)
        elif name.startswith(variant + "locations"):
            return Item(name, "locations", data)
        elif name.startswith(variant + "layout"):
            return Item(name, "layouts", data)

    return None


if PY < (3, 12):
    from fnmatch import fnmatch, fnmatchcase

    def _rglob_case(
        path: Path, pattern: str, case_sensitive: t.Optional[bool] = None, *args: t.Any, **kwargs: t.Any
    ) -> t.Generator[Path, None, None]:
        if case_sensitive is None:
            yield from _original_rglob(path, pattern, *args, **kwargs)
        elif case_sensitive:
            for candidate in _original_rglob(path, pattern, *args, **kwargs):
                if fnmatchcase(str(candidate), pattern):
                    yield candidate
        else:
            pattern = pattern.lower()
            if "." in pattern:
                candidates = _original_rglob(path, "*.*")
            else:
                candidates = _original_rglob(path, "*")
            for candidate in candidates:
                if fnmatch(str(candidate).lower(), pattern):
                    yield candidate

    _original_rglob = Path.rglob
    Path.rglob = _rglob_case  # type: ignore[method-assign,assignment]


class _CollectJson(t.Generic[APath]):
    path: APath

    def __init__(self, path: APath):
        self.path = path

    def __call__(self, checks: t.Mapping[str, bool]) -> t.Generator[Item, None, None]:
        from .cli import warn

        path = self.path
        manifest, variants = read_manifest(path)
        warn_for_legacy_incompatibility = checks.get("legacy_compat", True)

        for f in path.rglob("*.json*", case_sensitive=False):  # type: ignore[call-arg,unused-ignore]
            name = str(f.relative_to(path)).replace("\\", "/")
            bin_read = "r" if PY < (3, 9) and isinstance(path, ZipPath) else "rb"
            with f.open(mode=bin_read) as bin_stream:
                if bin_stream.read(3) == b"\xef\xbb\xbf":
                    warn("File contains BOM but JSON files should not.", f, 0)
                else:
                    bin_stream.seek(0, os.SEEK_SET)
                pos = 0
                while warn_for_legacy_incompatibility:
                    block = bin_stream.read(4096)
                    assert isinstance(block, bytes)
                    if not block:
                        warn("JSON files appears to be empty.", f, 0)
                        break
                    orig_block_len = len(block)
                    block = block.lstrip()
                    if block:
                        if block[0:1] != b"[" and block[0:1] != b"{":
                            warn(
                                "JSON files should only contain white space before '[' or '{' for best compatibility."
                                f" Byte at {pos + orig_block_len - len(block)} is {block[0:1]!r}.",
                                f,
                            )
                        break
                    pos += orig_block_len

            with f.open(encoding="utf-8-sig") as stream:  # type: ignore[call-arg, unused-ignore]
                try:
                    item = identify_json(name, t.cast(t.TextIO, stream), variants)
                    if item:
                        yield item
                    else:
                        yield Item(name, None, None)
                except Exception as ex:
                    yield Item(name, "error", ex)


class _CollectLua(t.Generic[APath]):
    path: APath

    def __init__(self, path: APath):
        self.path = path

    def __call__(self, checks: t.Mapping[str, bool]) -> t.Generator[Item, None, None]:
        from .cli import warn

        path = self.path

        for f in path.rglob("*.lua", case_sensitive=False):  # type: ignore[call-arg,unused-ignore]
            name = str(f.relative_to(path)).replace("\\", "/")
            bin_read = "r" if PY < (3, 9) and isinstance(path, ZipPath) else "rb"
            with f.open(mode=bin_read) as bin_stream:
                if bin_stream.read(3) == b"\xef\xbb\xbf":
                    warn("File contains BOM but Lua files should not.", f, 0, 0)

            with f.open(encoding="utf-8-sig") as stream:  # type: ignore[call-arg, unused-ignore]
                try:
                    yield Item(name, "lua", stream.read())
                except Exception as ex:
                    yield Item(name, "error", ex)


class _CollectImages(t.Generic[APath]):
    path: APath

    def __init__(self, path: APath):
        self.path = path

    def __call__(self, checks: t.Mapping[str, bool]) -> t.Generator[Item, None, None]:
        from .cli import warn

        path = self.path
        patterns = sorted(set(ext for fmt in img_formats for ext in fmt.extensions))
        max_magic_len = max(len(fmt.magic_number) for fmt in img_formats)

        all_images = (
            f
            for pattern in patterns
            for f in path.rglob(pattern, case_sensitive=False)  # type: ignore[call-arg,unused-ignore]
        )
        for f in all_images:
            name = str(f.relative_to(path)).replace("\\", "/")
            ext_format: t.Optional[ImgFormat] = None
            data_format: t.Optional[ImgFormat] = None
            try:
                bin_read = "r" if PY < (3, 9) and isinstance(path, ZipPath) else "rb"
                with f.open(mode=bin_read) as bin_stream:
                    start = bin_stream.read(max_magic_len)
                    for fmt in img_formats:
                        if fmt.match_filename(str(f)):
                            ext_format = fmt
                        bin_stream.seek(0, os.SEEK_SET)
                        if fmt.match_content(bin_stream, start):  # type: ignore[arg-type,unused-ignore]
                            data_format = fmt
                        if ext_format is not None and ext_format is data_format:
                            yield Item(name, ext_format.name, None)
                            break
                    else:
                        if ext_format is None:
                            raise Exception("Did not match any format. Bad pattern?")
                        ext = "." + str(f).rsplit(".", 1)[-1]
                        if data_format is None:
                            warn(f"Image is named {ext} ({ext_format.name}) " "but content does not match", f)
                        else:
                            warn(
                                f"Image is named {ext} ({ext_format.name}) "
                                f"but content appears to be {data_format.name}",
                                f,
                            )
                        yield Item(name, (data_format or ext_format).name, None)
            except Exception as ex:
                yield Item(name, "error", ex)


def collect_json(path: Path, checks: t.Mapping[str, bool]) -> t.Generator[Item, None, None]:
    if path.is_file():
        return _CollectJson(find_entry_point(path, checks))(checks)
    return _CollectJson(path)(checks)


def collect_lua(path: Path, checks: t.Mapping[str, bool]) -> t.Generator[Item, None, None]:
    if path.is_file():
        return _CollectLua(find_entry_point(path, checks))(checks)
    return _CollectLua(path)(checks)


def collect_images(path: Path, checks: t.Mapping[str, bool]) -> t.Generator[Item, None, None]:
    if path.is_file():
        return _CollectImages(find_entry_point(path, checks))(checks)
    return _CollectImages(path)(checks)
