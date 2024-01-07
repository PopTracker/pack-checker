#!/usr/bin/python

import argparse
import json
import os.path
import re
import warnings
import zipfile

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
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from pathlib import Path
from typing import Any, cast, Callable, Dict, Generator, Generic, Iterator, List, Optional, TextIO, TypeVar, Union
from urllib.parse import urlparse
from urllib.request import urlopen


__version_info__ = (1, 0, 1)
__version__ = ".".join(map(str, __version_info__))


schema_default_src = "https://poptracker.github.io/schema/packs/"
schema_names = ["items", "layouts", "locations", "manifest", "maps", "settings"]

Item = namedtuple("Item", "name type data")

trailing_regex = re.compile(r"(\".*?\"|\'.*?\')|,(\s*[\]\}])", re.MULTILINE | re.DOTALL)
comment_regex = re.compile(r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)", re.MULTILINE | re.DOTALL)
# comment_regex from jsonc-parser: https://github.com/NickolaiBeloguzov/jsonc-parser


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
        if uri.scheme:  # path starts with a drive letter
            s = "/" + s  # convert to absolute path
        return f"file://{s}/"


class ParserError(Exception):
    pass


def parse_jsonc(s: str, name: Optional[str] = None) -> Any:
    def __re_sub_comment(match: re.Match[str]) -> str:
        if match.group(2) is not None:
            return ""
        else:
            return match.group(1)

    def __re_sub_comma(match: re.Match[str]) -> str:
        if match.group(2) is not None:
            return match.group(2)
        else:
            return match.group(1)

    # remove comments
    s = comment_regex.sub(__re_sub_comment, s)
    # remove trailing comma as JsoncParser does not do that
    s = trailing_regex.sub(__re_sub_comma, s)
    # parse as json
    try:
        return json.loads(s)
    except Exception as e:
        raise ParserError("{} file cannot be parsed (message: {})".format(name or s, str(e)))


def identify_json(name: str, stream: TextIO, variants: List[str]) -> Optional[Item]:
    try:
        data = parse_jsonc(stream.read(), name)
    except ParserError as ex:
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


class ZipPath(zipfile.Path):
    """Emulates pathlib.Path (and py3.12 zipfile.Path) behavior on py3.8"""
    @staticmethod
    def _relative_to(child: str, parent: str) -> str:
        if not parent.endswith("/"):
            parent += "/"
        if not child.startswith(parent):
            raise Exception(f"{parent} is not a parent of {child}")
        return child[len(parent):]

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


APath = TypeVar("APath", Path, ZipPath)


class _CollectJson(Generic[APath]):
    path: APath

    def __init__(self, path: APath):
        self.path = path

    def __call__(self) -> Generator[Item, None, None]:
        path = self.path
        try:
            # py3.8 mypy does not know encoding
            manifest = parse_jsonc(cast(TextIO, (path / "manifest.json")
                                        .open(encoding="utf-8-sig")).read())  # type: ignore[call-arg, unused-ignore]
        except ParserError as ex:
            raise Exception(f"Could not load manifest.json: {ex.__context__}")
        except FileNotFoundError:
            raise Exception(f"Could not find manifest.json in {path}")
        except Exception as ex:
            raise Exception(f"Could not load manifest.json: {ex.__class__.__name__}: {ex}")

        variants = list(manifest["variants"].keys()) if "variants" in manifest else [""]
        if "" not in variants:
            variants.append("")

        for f in path.rglob("*.json"):
            name = str(f.relative_to(path)).replace("\\", "/")
            with f.open(encoding="utf-8-sig") as stream:  # type: ignore[call-arg, unused-ignore]
                try:
                    item = identify_json(name, cast(TextIO, stream), variants)
                    if item:
                        yield item
                    else:
                        yield Item(name, None, None)
                except Exception as ex:
                    yield Item(name, "error", ex)


def collect_json(path: Path) -> Generator[Item, None, None]:
    if isinstance(path, Path) and path.is_file():
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
        if hidden:
            warnings.warn(f"Zip contains hidden files: {hidden}")
        return _CollectJson(zippath)()

    return _CollectJson(path)()


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
