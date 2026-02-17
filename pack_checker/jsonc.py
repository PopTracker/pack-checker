import json
import re
from typing import Any, Optional

__all__ = ["ParserError", "parse"]

trailing_regex = re.compile(r"(\".*?\"|\'.*?\')|,(\s*[\]\}])", re.MULTILINE | re.DOTALL)
comment_regex = re.compile(r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)", re.MULTILINE | re.DOTALL)


# comment_regex from jsonc-parser: https://github.com/NickolaiBeloguzov/jsonc-parser


class ParserError(Exception):
    pass


def parse(s: str, name: Optional[str] = None) -> Any:
    def __re_sub_comment(match: "re.Match[str]") -> str:
        if match.group(2) is not None:
            return ""
        else:
            return match.group(1)

    def __re_sub_comma(match: "re.Match[str]") -> str:
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
