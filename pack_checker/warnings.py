import contextlib
import os
import typing as t
import warnings
from pathlib import Path

from .ziputil import ZipPath


class PackWarning(UserWarning):
    pass


@contextlib.contextmanager
def cli_warnings_formatter_context() -> t.Generator[None, None, None]:
    original_formatter = warnings.formatwarning

    def custom_formatter(
        message: t.Union[Warning, str],
        category: t.Type[Warning],
        filename: str,
        lineno: int,
        line: t.Optional[str] = None,
    ) -> str:
        if category == PackWarning:
            return f"{message}\n"
        if category == RuntimeWarning:
            return f"Runtime Warning: {message}\n"
        return original_formatter(message, category, filename, lineno, line)

    warnings.formatwarning = custom_formatter
    yield
    warnings.formatwarning = original_formatter


if "CI" not in os.environ or not os.environ["CI"]:

    def warn_pack(message: str, filename: t.Any = None, row: t.Optional[int] = None, col: int = 0) -> None:
        if filename is not None and row is not None:
            warnings.warn(f"{filename}[{row}:{col}]: {message}", PackWarning, stacklevel=2)
        elif filename is not None:
            warnings.warn(f"{filename}: {message}", PackWarning, stacklevel=2)
        else:
            warnings.warn(message, PackWarning, stacklevel=2)

else:

    def warn_pack(message: str, filename: t.Any = None, row: t.Optional[int] = None, col: int = 0) -> None:
        physical_filename: t.Optional[str]
        message_file_marker: str
        if filename is not None:
            message_file_marker = f"%0Ain {filename}"
            if row is not None:
                message_file_marker += f" at {col}:{row}"
            if isinstance(filename, (str, Path)) and os.path.exists(filename):
                physical_filename = str(filename)
            elif isinstance(filename, ZipPath) and os.path.exists(str(getattr(filename, "root"))):
                physical_filename = str(getattr(filename, "root"))
                row = None
            else:
                physical_filename = None
        else:
            physical_filename = None
            message_file_marker = ""
        if physical_filename and row is not None:
            print(f"::warning file={filename},line={row},col={col}::{message}{message_file_marker}")
        elif physical_filename:
            print(f"::warning file={filename}::{message}{message_file_marker}")
        else:
            print(f"::warning::{message}{message_file_marker}")
