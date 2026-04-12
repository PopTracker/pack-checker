#!/usr/bin/python

import argparse
import os.path
import typing as t

from pathlib import Path
from typing import Dict, Mapping, Optional
from urllib.parse import urlparse

from . import __version__
from .checker import (  # noqa F401: see comments below
    schema_names as schema_names,  # re-export for back compat. Remove at 2.0
    schema_default_src as schema_default_src,
    default_checks as default_checks,
    data_checks as data_checks,  # re-export for back compat. Remove at 2.0
    Checker,
)
from .warnings import warn_pack, cli_warnings_formatter_context

warn = warn_pack  # re-export for back compat. Remove at 2.0


def try_configure_https() -> None:
    try:
        # noinspection PyPackageRequirements
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


def check(
    path: Path,
    schema_src: str = schema_default_src,
    strict: bool = False,
    checks: Mapping[str, bool] = default_checks,
    validate_external: bool = False,
) -> int:
    return Checker(schema_src, strict, checks, validate_external).check(path)


def run(args: argparse.Namespace) -> int:
    print(f"PopTracker pack_checker {__version__}")
    checks: Dict[str, bool] = {
        **default_checks,
        "legacy_compat": args.legacy_compat,
    }
    validate_external: bool = getattr(args, "validate_external", False)  # getattr since run is "public" in 1.x
    with cli_warnings_formatter_context():
        res = check(
            args.path, args.schema if args.schema else schema_default_src, args.strict, checks, validate_external
        )
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
    external_group = parser.add_mutually_exclusive_group()
    external_group.add_argument(
        "--validate-external",
        action="store_true",
        dest="validate_external",
        help="allow validation of select known external schemas (will become default in 2.x)",
    )
    external_group.add_argument(
        "--no-validate-external",
        action="store_false",
        dest="validate_external",
        help="do not validate known external schema (default)",
    )
    sys.exit(run(parser.parse_args(args)))


if __name__ == "__main__":
    main()
