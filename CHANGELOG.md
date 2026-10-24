# pack-checker Changelog

## v1.7.0 Changes

### New Checks

* Schema validation for classes
* Optional schema validation of .luarc.json and versions.json
  * Default off, enable with `--validate-external`
  * This will become default on in the future, disable with `--no-validate-external`

## New features

* Switch some print statements to proper warnings
* Ignore JSON files in .vs and .vscode folders

### Other Changes

* EXE: Update dependencies and certificates


## v1.6.0 Changes

### New Checks

* Check that `ref` and `parent` fields point to an existing section/location.
  This does not guarantee the ref/parent will work, but is likely to find typos.

### New Features

* Error when an unsupported URI scheme is supplied for `--schema`

### Other Changes

* EXE: Update dependencies


## Older Versions

See [GitHub Releases](https://github.com/PopTracker/pack-checker/releases).
