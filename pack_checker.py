#!/usr/bin/python

import argparse
import json
import os.path
import re
import requests
import threading
from collections import namedtuple
from functools import wraps
from jsonschema import validate
from jsonschema.exceptions import ValidationError
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, ParamSpec, TextIO, Tuple, TypeVar
from urllib.parse import urlparse


schema_lax_src = "https://poptracker.github.io/schema/packs"
schema_strict_src = "https://poptracker.github.io/schema/packs/strict"
schema_names = ["items", "layouts", "locations", "manifest", "maps"]

Item = namedtuple("Item", "name type data")

trailing_regex = re.compile(r"(\".*?\"|\'.*?\')|,(\s*[\]\}])", re.MULTILINE | re.DOTALL)
comment_regex = re.compile(r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)", re.MULTILINE | re.DOTALL)
# comment_regex from jsonc-parser: https://github.com/NickolaiBeloguzov/jsonc-parser

P = ParamSpec("P")
R = TypeVar("R")


class ParserError(Exception):
    pass


def cache_threaded(func: Callable[P, R]) -> Callable[P, R]:
    lock = threading.Lock()
    cache: Dict[P.args, R] = {}
    busy: Dict[P.args, threading.Event] = {}

    @wraps(func)
    def wrap(*k: P.args, **kwargs: P.kwargs) -> R:
        if kwargs:
            raise Exception("Can't cache with kwargs")
        lock.acquire()
        try:
            if k in busy:
                event = busy[k]
                lock.release()
                event.wait()
                lock.acquire()
            elif k not in cache:
                busy[k] = threading.Event()
                lock.release()
                try:
                    res = func(*k, **kwargs)
                    lock.acquire()
                    cache[k] = res
                except Exception as ex:
                    lock.acquire()
                    raise ex
                finally:
                    busy[k].set()
                    del busy[k]
            return cache[k]
        finally:
            lock.release()

    return wrap


@cache_threaded
def fetch_json(uri: str) -> Dict[str, Any]:
    if uri.startswith("file://"):
        return json.loads(open(uri[7:], encoding="utf-8-sig").read())
    else:
        return json.loads(requests.get(uri, allow_redirects=True).content)


def pack_path(s: str):
    if os.path.isdir(s):
        return Path(s)
    if os.path.isfile(s) and s.lower().endswith(".zip"):
        return Path(s)
    raise argparse.ArgumentTypeError(f"Given argument is not a pack")


def schema_uri(s: str):
    uri = urlparse(s)
    if uri.scheme:
        return s
    else:
        return f"file://{s}"


def parse_jsonc(s: str, name: Optional[str] = None) -> dict:
    def __re_sub_comment(match):
        if match.group(2) is not None:
            return ""
        else:
            return match.group(1)

    def __re_sub_comma(match):
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
        data = parse_jsonc(stream.read())
    except ParserError as ex:
        raise Exception(f"Error parsing {name}: {ex.__context__}")

    if name == "settings.json":
        return None
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
    print(f"Unmatched file: {name}")
    return None


def collect_json(path: Path) -> Tuple[bool, List[Item]]:
    ok = True
    res = []

    try:
        manifest = parse_jsonc((path / "manifest.json").open(encoding="utf-8-sig").read())
    except ParserError as ex:
        print(f"Could not load manifest.json: {ex.__context__}")
        return False, []

    variants = list(manifest["variants"].keys()) if "variants" in manifest else [""]
    if "" not in variants:
        variants.append("")

    for f in path.rglob("*.json"):
        name = str(f.relative_to(path)).replace("\\", "/")
        stream = f.open(encoding="utf-8-sig")
        try:
            item = identify_json(name, stream, variants)
            if item:
                res.append(item)
        except Exception as ex:
            print(ex)
            ok = False

    return ok, res


def check(path: Path, schema_src: str = schema_lax_src) -> bool:
    json_ok, json_items = collect_json(path)

    ok = json_ok
    schema = {name: f"{schema_src}/{name}.json" for name in schema_names}
    for item in json_items:
        if item.type in schema:
            try:
                validate(
                    instance=item.data,
                    schema=fetch_json(schema[item.type])
                )
            except ValidationError as ex:
                print(f"{item.name}: {ex}")
                ok = False
        else:
            print("No schema {item.type} for {item.name}")
            ok = False
    return ok


def main(args):
    if not args.path.is_dir():
        raise NotImplementedError("Zip not supported yet :-(")
    if not check(args.path, args.schema if args.schema else schema_strict_src if args.strict else schema_lax_src):
        exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=pack_path, metavar="path/to/pack", help="path to the pack to check")
    schema_src_group = parser.add_mutually_exclusive_group()
    schema_src_group.add_argument("--strict", action='store_true', help="use strict json schema")
    schema_src_group.add_argument("--schema", type=schema_uri, help="use custom schema source", metavar="folder/url")
    main(parser.parse_args())
