__version_info__ = (1, 6, 0)
__version__ = ".".join(map(str, __version_info__))

# public API for use as lib
from .checker import Checker

__all__ = ["__version__", "__version_info__", "Checker"]
