#!/usr/bin/python

import argparse
import json
import os.path
import typing as t
import warnings

from itertools import chain
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Union
from urllib.parse import urlparse
from urllib.request import urlopen

from jsonschema import validate
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

from . import __version__
from .collect import Item, collect_images, collect_json, collect_lua
from .datachecks import check_refs, DataCheckError
from .imgutil import supported_formats as supported_img_formats
from .warnings import warn_pack, cli_warnings_formatter_context

warn = warn_pack  # re-export for back compat. Remove at 2.0


schema_default_src = "https://poptracker.github.io/schema/packs/"
schema_names = {"items", "layouts", "locations", "manifest", "maps", "settings", "classes"}
external_schema = {
    ".luarc": {
        "https://raw.githubusercontent.com/LuaLS/vscode-lua/master/setting/schema.json",
        "https://raw.githubusercontent.com/sumneko/vscode-lua/master/setting/schema.json",
    }
}
allowed_external_schema = set(chain(*external_schema.values()))

default_checks: Mapping[str, bool] = {
    "legacy_compat": True,
}

data_checks: Mapping[str, t.Iterable[t.Callable[[t.Any, Path], None]]] = {
    "locations": (check_refs,),
}


def try_configure_https() -> None:
    try:
        import certifi  # optional dependency
        import ssl
        import urllib.request

        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=certifi.where())
        context.set_alpn_protocols(["http/1.1"])
        https_handler = urllib.request.HTTPSHandler(context=context)
        opener = urllib.request.build_opener(https_handler)
        urllib.request.install_opener(opener)
    except ImportError:
        pass


def pack_path(s: str) -> Path:
    if os.path.isdir(s):
        return Path(s)
    if os.path.isfile(s) and s.lower().endswith(".zip"):
        return Path(s)
    raise argparse.ArgumentTypeError("Given argument is not a pack")


def schema_uri(s: str) -> str:
    uri = urlparse(s)
    if len(uri.scheme) > 1:  # > 1 to ignore windows drive letters
        return s if s.endswith("/") else (s + "/")
    else:
        s = os.path.abspath(s).replace("\\", "/")
        if uri.scheme or len(s) > 1 and s[1] == ":":  # path starts with a drive letter
            s = "/" + s  # convert to absolute path
        return f"file://{s}/"


def _validate_config() -> None:
    # sanity check lists; doing this during runtime in case they get extended
    if not schema_names.isdisjoint(external_schema):
        raise ValueError("schema_names and external_schema overlap")
    for special_name in ("error",):
        if special_name in schema_names or special_name in external_schema:
            raise ValueError(f"'{special_name}' has special meaning and is invalid as schema name")


def check(
    path: Path, schema_src: str = schema_default_src, strict: bool = False, checks: Mapping[str, bool] = default_checks
) -> int:
    _validate_config()

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
        if uri.startswith("file:"):
            raise ValueError("File URI not allowed in schema")
        if "://" in uri or uri.startswith("/"):
            if uri not in allowed_external_schema:
                raise NotImplementedError()  # only relative retrieve and allow-list implemented
            full_uri = uri
        else:
            full_uri = schema_src + uri
        # TODO: deny insecure http in v2
        if not any(full_uri.startswith(schema) for schema in ("file:", "https:", "http:")):
            raise ValueError("Unsupported URI scheme to retrieve resource")
        r = urlopen(full_uri)  # noqa: S310 checked above
        content = r.read().decode(r.headers.get_content_charset() or "utf-8")
        return Resource.from_contents(json.loads(content), default_specification=DRAFT202012)

    registry: Registry[Any] = Registry(retrieve=retrieve)  # type: ignore[call-arg]  # passing retrieve as per docs

    def validate_json_item(item: Item) -> bool:
        try:
            if item.type in external_schema:
                schema_ref = item.data.get("$schema", None)
                if not schema_ref or schema_ref not in external_schema[item.type]:
                    raise ValidationError("Unexpected $schema")
                validate(
                    instance=item.data,
                    schema={"$ref": schema_ref},
                    registry=registry,
                )
            else:
                validate(
                    instance=item.data,
                    schema={"$ref": f"strict/{item.type}.json" if strict else f"{item.type}.json"},
                    registry=registry,
                )
                for data_check in data_checks.get(item.type, []):
                    data_check(item.data, path)
            return True
        except ValidationError as ex:
            print(f"\n{item.name}: {ex}")
        except DataCheckError as ex:
            print(f"\n{item.name}: {ex}")
        except Unresolvable as ex:
            if item.type in external_schema:
                msg = f"Error loading schema {item.data.get('$schema', None)}: {ex}"
            else:
                msg = f"Error loading schema {'strict/' if strict else ''}{item.type}.json: {ex}"
            raise Exception(msg) from ex
        except Exception as ex:
            print(f"{ex} while handling {item.name} {type(ex)}")
            raise
        return False

    ok = True
    count = 0
    is_zipped = path.is_file()
    if is_zipped:
        checks = {**checks, "hidden_files": True}

    # NOTE: PopTracker min version detection is not fully implemented yet
    requires_poptracker = False  # set if we detect an unconditional feature that is only available in PopTracker
    required_min_poptracker_version = (0, 24, 1)  # minimum because of update check
    manifest: Optional[Item] = None

    try:
        for json_item in collect_json(path, checks):
            if json_item.type in schema_names or json_item.type in external_schema:
                if validate_json_item(json_item):
                    count += 1
                    if json_item.type == "manifest":
                        manifest = json_item
                else:
                    ok = False
            elif json_item.type == "error":
                print(f"{json_item.name}: {json_item.data}")
                ok = False
            elif json_item.type is None:
                warn_pack("Unmatched file", filename=json_item.name)
            else:
                warnings.warn(f"No schema {json_item.type} for {json_item.name}", RuntimeWarning)
                ok = False
    except ImportError:
        raise
    except Exception as ex:
        print(f"Error collecting json: {ex}")
        return False
    finally:
        if is_zipped:
            checks = {**checks, "hidden_files": False}  # only check the first time zip is inspected

    try:
        for lua_item in collect_lua(path, checks):  # collecting them checks for encoding errors
            # do we want to bundle a full Lua? py-lua-parser is sadly not good enough
            if lua_item.type == "error":
                warn_pack(str(lua_item.data), lua_item.name)
                # ok = False  # TODO: enable this in v2
    except Exception as ex:
        print(f"Error collecting Lua: {ex}")
        return False
    finally:
        if is_zipped:
            checks = {**checks, "hidden_files": False}  # only check the first time zip is inspected

    try:
        for image_item in collect_images(path, checks):
            # until we verify the image is actually in use, only report compatibility issues for zip
            # since a folder could have source files that then get converted to the format in use
            if image_item.type == "error":
                warn_pack(str(image_item.data), image_item.name)
                # ok = False  # TODO: enable this in v2
            elif is_zipped:
                if image_item.type not in supported_img_formats:
                    warn_pack(f"Image format {image_item.type} is not supported by all versions", image_item.name)
    except Exception as ex:
        print(f"Error collecting images: {ex}")
        return False
    finally:
        if is_zipped:
            checks = {**checks, "hidden_files": False}  # only check the first time zip is inspected

    if manifest and (requires_poptracker or not checks.get("legacy_compat", True)):
        # if either legacy compat is off, or poptracker is required, check min_pop_version is sensible
        manifest_data: Dict[str, Any] = manifest.data
        min_poptracker_version: str = manifest_data.get("min_poptracker_version", "")
        try:
            if tuple(map(int, min_poptracker_version.split("."))) < (0, 24, 1):
                required_min_poptracker_version_string = ".".join(map(str, required_min_poptracker_version))
                warn_pack(
                    f'min_poptracker_version should be at least "{required_min_poptracker_version_string}" '
                    "(this does not detect all features yet).",
                    manifest.name,
                )
        except (ValueError, AttributeError):
            reason = "Pack requires poptracker" if requires_poptracker else "Legacy mode is off"
            warn_pack(f"{reason}, but min_poptracker_version is not set to a valid version.", manifest.name)

    return count if ok else 0


def run(args: argparse.Namespace) -> int:
    print(f"PopTracker pack_checker {__version__}")
    checks: Dict[str, bool] = {
        **default_checks,
        "legacy_compat": args.legacy_compat,
    }
    with cli_warnings_formatter_context():
        res = check(args.path, args.schema if args.schema else schema_default_src, args.strict, checks)
    if res:
        print(f"Validated {res} files")
    if args.interactive:
        try:
            input("\nPress enter to close.")
        except ValueError:
            pass
    return 0 if res else 1


def main(args: Optional[t.Sequence[str]] = None) -> None:
    import platform
    import sys

    try_configure_https()
    is_windows = "windows" in platform.system().lower()
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=pack_path, metavar="path/to/pack", help="path to the pack to check")
    parser.add_argument("--strict", action="store_true", help="use strict json schema")
    parser.add_argument("--schema", type=schema_uri, help="use custom schema source", metavar="folder/url")
    legacy_group = parser.add_mutually_exclusive_group()
    legacy_group.add_argument(
        "--check-legacy-compat",
        action="store_true",
        dest="legacy_compat",
        help="check for compatibility issues with old PopTracker versions and alternative implementations (default)",
        default=True,
    )
    legacy_group.add_argument(
        "--no-legacy-compat",
        action="store_false",
        dest="legacy_compat",
        help="skip checking for compatibility issues with very old PopTracker versions and alternative implementations",
    )
    interactive_group = parser.add_mutually_exclusive_group()
    interactive_group.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        default=is_windows,
        help="keep console open when done (default on Windows)",
    )
    interactive_group.add_argument(
        "-b",
        "--batch",
        action="store_false",
        dest="interactive",
        help="exit program when done (default on non-Windows)",
    )
    sys.exit(run(parser.parse_args(args)))


if __name__ == "__main__":
    main()
