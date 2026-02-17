# This file provides backwards compatibility. It should behave like the old pack_checker.py.

from pack_checker import __version__, __version_info__
from pack_checker.cli import run as main, main as cli_main, try_configure_https

__all__ = (
    "__version_info__",
    "__version__",
    "main",
)


try_configure_https()

if __name__ == "__main__":
    cli_main()
