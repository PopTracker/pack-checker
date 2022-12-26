# PopTracker Pack Checker

Tool to check PopTracker packs.


## Features

Currently only json schema is validated.


## Usage

```
usage: pack_checker.py [-h] [--strict] [--schema folder/url] [-i | -b] path/to/pack

positional arguments:
  path/to/pack         path to the pack to check

options:
  -h, --help           show this help message and exit
  --strict             use strict json schema
  --schema folder/url  use custom schema source
  -i, --interactive    keep console open when done (default on Windows)
  -b, --batch          exit program when done (default on non-Windows)
```