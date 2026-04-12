# PopTracker Pack Checker

Tool to check PopTracker packs.


## Features

* Validates json schema
* Warns for some json/jsonc and Lua compatibility issues
* Warns for some hidden/dead files (only for zipped packs)
* Warns for unsupported images and misleading file extensions
* Warns for wrong/missing `min_poptracker_version` if a min is detected
* Errors for some dead references: ref or parent pointing to a missing object

## Installation

`pack_checker.py` can be run from source, it can be run as frozen `pack_checker.exe` from GitHub releases,
or it can be installed as `pack-checker` script into a venv from PyPI with `pip install pack_checker`.

## Recommended Use

* Run pack-checker on your source code folder when looking for bugs.
* Run pack-checker on your source code folder before pushing to a remote server or
  [in CI](https://github.com/PopTracker/pack-checker-action).
* Run pack-checker on your release (ZIP) file before release.

## Usage

```
usage: pack_checker.py [-h] [--strict] [--schema folder/url] [--check-legacy-compat | --no-legacy-compat] [-i | -b] path/to/pack

positional arguments:
  path/to/pack          path to the pack to check

options:
  -h, --help            show this help message and exit
  --strict              use strict json schema
  --schema folder/url   use custom schema source
  --check-legacy-compat
                        check for compatibility issues with old PopTracker versions and alternative implementations (default)
  --no-legacy-compat    skip checking for compatibility issues with very old PopTracker versions and alternative implementations
  -i, --interactive     keep console open when done (default on Windows)
  -b, --batch           exit program when done (default on non-Windows)
```
