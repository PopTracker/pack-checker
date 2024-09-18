#!/usr/bin/python

import argparse
import json
import os.path
import sys
import warnings

try:
    import certifi
    import ssl
    import urllib.request
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=certifi.where())
    context.set_alpn_protocols(['http/1.1'])
    https_handler = urllib.request.HTTPSHandler(context=context)
    opener = urllib.request.build_opener(https_handler)
    urllib.request.install_opener(opener)
except ImportError:
    pass

from collections import namedtuple
from pathlib import Path
from typing import Any, cast, Callable, Dict, Generator, Generic, List, Optional, TextIO, Tuple, TypeVar, Union
from urllib.parse import urlparse
from urllib.request import urlopen

from jsonschema import validate
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

from imgutil import Format as ImgFormat, formats as img_formats, supported_formats as supported_img_formats
from jsonc import parse as parse_jsonc, ParserError as JsonParserError
from ziputil import ZipPath


__version_info__ = (1, 2, 0)
__version__ = ".".join(map(str, __version_info__))

PY = sys.version_info

APath = TypeVar("APath", Path, ZipPath)

schema_default_src = "https://poptracker.github.io/schema/packs/"
schema_names = ["items", "layouts", "locations", "manifest", "maps", "settings"]

Item = namedtuple("Item", "name type data")


if "CI" not in os.environ or not os.environ["CI"]:
    def warn(message: str, filename: Any = None, row: Optional[int] = None, col: int = 0) -> None:
        if filename is not None and row is not None:
            warnings.warn(f"{filename}[{row}:{col}]: {message}")
        elif filename is not None:
            warnings.warn(f"{filename}: {message}")
        else:
            warnings.warn(message)
else:
    def warn(message: str, filename: Any = None, row: Optional[int] = None, col: int = 0) -> None:
        if filename is not None and row is not None:
            print(f"::warning file={filename},line={row},col={col}::{message}")
        elif filename is not None:
            print(f"::warning file={filename}::{message}")
        else:
            print(f"::warning::{message}")


def pack_path(s: str) -> Path:
    if os.path.isdir(s):
        return Path(s)
    if os.path.isfile(s) and s.lower().endswith(".zip"):
        return Path(s)
    raise argparse.ArgumentTypeError(f"Given argument is not a pack")


def schema_uri(s: str) -> str:
    uri = urlparse(s)
    if len(uri.scheme) > 1:  # > 1 to ignore windows drive letters
        return s if s.endswith("/") else (s + "/")
    else:
        s = os.path.abspath(s).replace('\\', '/')
        if uri.scheme or len(s) > 1 and s[1] == ':':  # path starts with a drive letter
            s = "/" + s  # convert to absolute path
        return f"file://{s}/"


def find_entry_point(path: Path, warn_for_hidden_files: bool = False) -> ZipPath:
    assert path.is_file()
    zippath = ZipPath(path)
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
        warn(f"Zip contains hidden files: {hidden}")
    return zippath


def read_manifest(path: APath) -> Tuple[Dict[str, Any], List[str]]:
    try:
        # py3.8 does not know encoding
        manifest = parse_jsonc(cast(TextIO, (path / "manifest.json")
                                    .open(encoding="utf-8-sig")).read())  # type: ignore[call-arg, unused-ignore]
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


def identify_json(name: str, stream: TextIO, variants: List[str]) -> Optional[Item]:
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


    def _rglob_case(path: Path, pattern: str, case_sensitive: Optional[bool] = None, *args: Any, **kwargs: Any
                    ) -> Generator[Path, None, None]:
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


class _CollectJson(Generic[APath]):
    path: APath

    def __init__(self, path: APath):
        self.path = path

    def __call__(self) -> Generator[Item, None, None]:
        path = self.path
        manifest, variants = read_manifest(path)

        for f in path.rglob("*.json*", case_sensitive=False):  # type: ignore[call-arg,unused-ignore]
            name = str(f.relative_to(path)).replace("\\", "/")
            bin_read = "r" if PY < (3, 9) and isinstance(path, ZipPath) else "rb"
            with f.open(mode=bin_read) as bin_stream:
                if bin_stream.read(3) == b"\xEF\xBB\xBF":
                    warn("File contains BOM but JSON files should not", f, 0)
                else:
                    bin_stream.seek(0, os.SEEK_SET)
                pos = 0
                while True:
                    block = bin_stream.read(4096)
                    assert isinstance(block, bytes)
                    pos += len(block)
                    if not block:
                        warn("JSON files appears to be empty", f, 0)
                        break
                    block = block.lstrip()
                    if block:
                        if block[0:1] != b'[' and block[0:1] != b'{':
                            warn("JSON files should only contain white space before '[' or '{' for best compatibility."
                                 f"Byte at {pos} is {block[0:1]!r}.", f)
                        break

            with f.open(encoding="utf-8-sig") as stream:  # type: ignore[call-arg, unused-ignore]
                try:
                    item = identify_json(name, cast(TextIO, stream), variants)
                    if item:
                        yield item
                    else:
                        yield Item(name, None, None)
                except Exception as ex:
                    yield Item(name, "error", ex)


class _CollectLua(Generic[APath]):
    path: APath

    def __init__(self, path: APath):
        self.path = path

    def __call__(self) -> Generator[Item, None, None]:
        path = self.path

        for f in path.rglob("*.lua", case_sensitive=False):  # type: ignore[call-arg,unused-ignore]
            name = str(f.relative_to(path)).replace("\\", "/")
            bin_read = "r" if PY < (3, 9) and isinstance(path, ZipPath) else "rb"
            with f.open(mode=bin_read) as bin_stream:
                if bin_stream.read(3) == b"\xEF\xBB\xBF":
                    warn("File contains BOM but Lua files should not", f, 0, 0)

            with f.open(encoding="utf-8-sig") as stream:  # type: ignore[call-arg, unused-ignore]
                try:
                    yield Item(name, "lua", stream.read())
                except Exception as ex:
                    yield Item(name, "error", ex)


class _CollectImages(Generic[APath]):
    path: APath

    def __init__(self, path: APath):
        self.path = path

    def __call__(self) -> Generator[Item, None, None]:
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
            ext_format: Optional[ImgFormat] = None
            data_format: Optional[ImgFormat] = None
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
                            warn(f"Image is named {ext} ({ext_format.name}) "
                                 "but content does not match", f)
                        else:
                            warn(f"Image is named {ext} ({ext_format.name}) "
                                 f"but content appears to be {data_format.name}", f)
                        yield Item(name, (data_format or ext_format).name, None)
            except Exception as ex:
                yield Item(name, "error", ex)


def collect_json(path: Path) -> Generator[Item, None, None]:
    if path.is_file():
        return _CollectJson(find_entry_point(path, warn_for_hidden_files=True))()
    return _CollectJson(path)()


def collect_lua(path: Path) -> Generator[Item, None, None]:
    if path.is_file():
        return _CollectLua(find_entry_point(path))()
    return _CollectLua(path)()


def collect_images(path: Path) -> Generator[Item, None, None]:
    if path.is_file():
        return _CollectImages(find_entry_point(path))()
    return _CollectImages(path)()


def check(path: Path, schema_src: str = schema_default_src, strict: bool = False) -> int:
    resource_cache: Dict[str, Union[Exception, Resource[Any]]] = {}

    def cached(f: Callable[[str], Resource[Any]]) -> Callable[[str], Resource[Any]]:
        def wrap(uri: str) -> Resource[Any]:
            cached_res = resource_cache.get(uri)
            if isinstance(cached_res, Exception):
                raise cached_res
            elif cached_res is not None:
                return cached_res
            try:
                res = f(uri)
                resource_cache[uri] = res
                return res
            except Exception as ex:
                resource_cache[uri] = NoSuchResource(ref=uri)  # type: ignore[call-arg]  # passing ref as per docs
                raise NoSuchResource(ref=uri) from ex  # type: ignore[call-arg]
        return wrap

    @cached  # we cache here since registry is immutable
    def retrieve(uri: str) -> Resource[Any]:
        if "://" in uri or uri.startswith("/"):
            raise NotImplementedError()
        full_uri = schema_src + uri
        r = urlopen(full_uri)
        content = r.read().decode(r.headers.get_content_charset() or "utf-8")
        return Resource.from_contents(json.loads(content),
                                      default_specification=DRAFT202012)

    registry: Registry[Any] = Registry(retrieve=retrieve)  # type: ignore[call-arg]  # passing retrieve as per docs

    def validate_json_item(item: Item) -> bool:
        try:
            validate(
                instance=item.data,
                schema={"$ref": f"strict/{item.type}.json" if strict else f"{item.type}.json"},
                registry=registry,
            )
            return True
        except ValidationError as ex:
            print(f"\n{item.name}: {ex}")
        except Unresolvable as ex:
            msg = f"Error loading schema {'strict/' if strict else ''}{item.type}.json: {ex}"
            raise Exception(msg) from ex
        except Exception as ex:
            print(f"{ex} while handling {item.name} {type(ex)}")
            raise
        return False

    ok = True
    count = 0
    is_zipped = path.is_file()

    try:
        for json_item in collect_json(path):
            if json_item.type in schema_names:
                if validate_json_item(json_item):
                    count += 1
                else:
                    ok = False
            elif json_item.type == "error":
                print(json_item.data)
                ok = False
            elif json_item.type is None:
                print(f"Unmatched file: {json_item.name}")
            else:
                print("No schema {item.type} for {item.name}")
                ok = False
    except Exception as ex:
        print(f"Error collecting json: {ex}")
        return False

    try:
        for lua_item in collect_lua(path):  # collecting them checks for encoding errors
            # do we want to bundle a full Lua? py-lua-parser is sadly not good enough
            if lua_item.type == "error":
                print(lua_item.data)
                # ok = False  # TODO: enable this in v2
    except Exception as ex:
        print(f"Error collecting Lua: {ex}")
        return False

    try:
        for image_item in collect_images(path):
            # until we verify the image is actually in use, only report compatibility issues for zip
            # since a folder could have source files that then get converted to the format in use
            if image_item.type == "error":
                print("Error")
                print(image_item.data)
                # ok = False  # TODO: enable this in v2
            elif is_zipped:
                if image_item.type not in supported_img_formats:
                    warn(f"Image format {image_item.type} is not supported by all versions", image_item.name)
    except Exception as ex:
        print(f"Error collecting images: {ex}")
        return False

    return count if ok else 0


def main(args: argparse.Namespace) -> int:
    print(f"PopTracker pack_checker {__version__}")
    res = check(args.path, args.schema if args.schema else schema_default_src, args.strict)
    if res:
        print(f"Validated {res} files")
    if args.interactive:
        try:
            input("\nPress enter to close.")
        except ValueError:
            pass
    return 0 if res else 1


if __name__ == "__main__":
    import platform
    import sys
    is_windows = "windows" in platform.system().lower()
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=pack_path, metavar="path/to/pack", help="path to the pack to check")
    parser.add_argument("--strict", action="store_true", help="use strict json schema")
    parser.add_argument("--schema", type=schema_uri, help="use custom schema source", metavar="folder/url")
    interactive_group = parser.add_mutually_exclusive_group()
    interactive_group.add_argument("-i", "--interactive", action="store_true", default=is_windows,
                                   help="keep console open when done (default on Windows)")
    interactive_group.add_argument("-b", "--batch", action="store_false", dest="interactive",
                                   help="exit program when done (default on non-Windows)")
    sys.exit(main(parser.parse_args()))
