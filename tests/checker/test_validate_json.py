import typing as t
from pathlib import Path
from unittest import TestCase

from pack_checker.checker import Checker
from pack_checker.collect import Item


class TestValidateJson(TestCase):
    checker: t.ClassVar[Checker]
    strict: t.ClassVar[bool] = False

    @classmethod
    def setUpClass(cls) -> None:
        # NOTE: since we don't cache HTTP requests (yet), create a Checker per class rather than per instance
        super().setUpClass()
        cls.checker = Checker(strict=cls.strict)

    def assert_validation_result(self, expected: bool, schema_name: str, data: t.Any) -> None:
        res = self.checker.validate_json_item(Item(self._testMethodName, schema_name, data), Path())
        texts = ["failure", "success"]
        self.assertEqual(res, expected, f"Unexpected schema validation result! Expected {texts[expected]}.")

    def test_unknown_schema(self) -> None:
        with self.assertRaises(Exception):
            self.checker.validate_json_item(Item(self._testMethodName, "unknown", {}), Path())

    def test_maps_object(self) -> None:
        self.assert_validation_result(False, "maps", {})

    def test_maps_empty_array(self) -> None:
        self.assert_validation_result(True, "maps", [])

    def test_maps_unknown_key(self) -> None:
        self.assert_validation_result(not self.strict, "maps", [{"something": "something"}])


class TestValidateStringJson(TestValidateJson):
    strict: t.ClassVar[bool] = True
