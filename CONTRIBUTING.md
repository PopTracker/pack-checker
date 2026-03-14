# Contributing to pack-checker

If you have found a bug or want to suggest a new feature, please check if it was already reported/suggested
[on GitHub](https://github.com/PopTracker/pack-checker/issues). If not, open a new issue.
If the problem is in the JSON schema, instead check for and open issues in the PopTracker repository.

If you want to add a new feature or fix a bug, please consider first talking to us on Discord or on GitHub via issue.
The community Discord is linked on [https://poptracker.github.io](https://poptracker.github.io).

Once a fix or feature is ready, [create a pull request on GitHub](https://github.com/PopTracker/pack-checker/pulls).

## Python Version Compatibility

The minimum python version we support is listed in [pyproject.toml](./pyproject.toml).
This may be older than the oldest version supported by the official/upstream Python distribution.

You may be able to configure your IDE to check your code for compatibility, but it will also be checked in CI
(GitHub Actions).

Only drop support for a Python version if there is a good reason to, such as:
- need/want to update a **runtime** dependency that is not available on older versions
- a feature became incompatible/replaced and there is no back-port available
- it became impossible to test it in CI (GitHub Actions)
- need a typing feature that is not available in `typing-extensions`

Syntax sugar is not reason enough.

## Linting and Type Checking

Tools, versions and settings used are listed in [pyproject.toml](./pyproject.toml).
You can install them via `pip install '.[lint]'`, then run
```sh
mypy --strict pack_checker/ tests/
flake8 pack_checker/ pack_checker.py tests/
```
(A single "unable to find qualified name" warning is expected.)

Notes about checks:
* S101 complains about **any** use of `assert`, however we may want to use `assert isinstance` for type checking.
  If the condition that is asserted does not depend on user-provided data or would simply fail with a less clear error,
  add a `# noqa: S101` with explanation.
* always add an explanation to a `# noqa` and `# type: ignore` and make them as narrow as possible.

## Code Style

Please format your code with [black](https://pypi.org/project/black/) before committing your changes.
The exact version used is listed in pyproject.toml.
The tool should be correctly configured via pyproject.toml, but if you work outside the project use `-l120`.

The formatting will be checked in CI and will fail if you forgot to format the code.

All functions, methods and class members should be typed. Local variables should be typed if the type can't be inferred.
As long as we support py3.8 (see above), use Dict, Tuple, etc. Once we drop py3.8, prefer to use dict, tuple, etc.
Put type annotations in quotes if they would be invalid during runtime (don't `__future__` import).

## Testing

If possible, create unit tests for newly added features or fixed behavior in [tests/](./tests/).
Tests should be compatible to any test runner (only depend on builtin unittest), so they work in IDEs out of the box.
In CI, we use pytest to run the tests. See [requirements_ci.txt](./requirements_ci.txt).

For manual (end-to-end) testing, create an example pack that triggers the behavior and demonstrates the feature/fix.
