import typing as t
from io import StringIO
from unittest import TestCase

from pack_checker.collect import Item, identify_json


class TestIdentifyJson(TestCase):
    def test_identify_nothing(self) -> None:
        self.assertIsNone(identify_json("unknown.json", StringIO("{}"), [""]))

    def assert_is_type(self, expected: str, item: t.Optional[Item]) -> None:
        self.assertIsNotNone(item)
        assert item is not None  # noqa: S101 just for type checking
        self.assertEqual(expected, item.type)

    def test_identify_class_json(self) -> None:
        self.assert_is_type("classes", identify_json("class.json", StringIO("{}"), [""]))

    def test_identify_var_classes_json(self) -> None:
        self.assert_is_type("classes", identify_json("var1/classes.json", StringIO("{}"), ["var1"]))

    def test_identify_class_file_json(self) -> None:
        self.assert_is_type("classes", identify_json("class/some.json", StringIO("{}"), [""]))

    def test_identify_var_classes_file_json(self) -> None:
        self.assert_is_type("classes", identify_json("var1/classes/some.json", StringIO("{}"), ["var1"]))

    def test_identify_luarc_json(self) -> None:
        self.assert_is_type(".luarc", identify_json(".luarc.json", StringIO("{}"), [""]))

    def test_not_identify_luarc_json_subfolder(self) -> None:
        # we don't care about it outside of pack root
        self.assertIsNone(identify_json("var1/.luarc.json", StringIO("{}"), ["var1"]))

    def test_ignore_vs_json(self) -> None:
        self.assert_is_type("ignore", identify_json(".vs/test.json", StringIO("{}"), [""]))

    def test_ignore_vscode_json(self) -> None:
        self.assert_is_type("ignore", identify_json(".vscode/test.json", StringIO("{}"), [""]))

    def test_identify_versions_json(self) -> None:
        self.assert_is_type("versions", identify_json("versions.json", StringIO("{}"), [""]))

    def test_not_identify_versions_json_subfolder(self) -> None:
        # we don't care about it outside of pack root (for now)
        self.assertIsNone(identify_json("var1/versions.json", StringIO("{}"), ["var1"]))
