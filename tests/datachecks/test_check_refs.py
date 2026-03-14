from pathlib import Path
from unittest import TestCase

from pack_checker.datachecks import check_refs, DataCheckError

pack_data_dir = Path(__file__).parent / "pack-data"


class TestCheckRefs(TestCase):
    def test_missing_parent_raises(self) -> None:
        data = [
            {
                "name": "test",
                "parent": "does-not-exist",
            }
        ]
        with self.assertRaisesRegex(DataCheckError, "parent"):
            check_refs(data, pack_data_dir)

    def test_section_parent_raises(self) -> None:
        data = [
            {
                "name": "test",
                "parent": "example-location/example-section",  # a section, not a location
            }
        ]
        with self.assertRaisesRegex(DataCheckError, "parent"):
            check_refs(data, pack_data_dir)

    def test_existing_full_parent_ok(self) -> None:
        data = [
            {
                "name": "test",
                "parent": "example-location/inner-location",
            }
        ]
        check_refs(data, pack_data_dir)

    def test_existing_partial_parent_ok(self) -> None:
        data = [
            {
                "name": "test",
                "parent": "inner-location",
            }
        ]
        check_refs(data, pack_data_dir)

    def test_missing_ref_raises(self) -> None:
        data = [
            {
                "name": "test",
                "sections": [
                    {
                        "name": "test",
                        "ref": "does-not-exist",
                    },
                ],
            }
        ]
        with self.assertRaisesRegex(DataCheckError, "ref"):
            check_refs(data, pack_data_dir)

    def test_location_ref_raises(self) -> None:
        data = [
            {
                "name": "test",
                "sections": [
                    {
                        "name": "test",
                        "ref": "example-location",  # a location, not a section
                    },
                ],
            }
        ]
        with self.assertRaisesRegex(DataCheckError, "ref"):
            check_refs(data, pack_data_dir)

    def test_existing_full_ref_ok(self) -> None:
        data = [
            {
                "name": "test",
                "sections": [
                    {
                        "name": "test",
                        "ref": "example-location/example-section",
                    },
                ],
            }
        ]
        check_refs(data, pack_data_dir)

    def test_existing_partial_ref_ok(self) -> None:
        data = [
            {
                "name": "test",
                "sections": [
                    {
                        "name": "test",
                        "ref": "example-section",
                    },
                ],
            }
        ]
        check_refs(data, pack_data_dir)
