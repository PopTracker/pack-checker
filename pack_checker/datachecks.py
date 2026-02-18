import typing as t
from pathlib import Path


class DataCheckError(Exception):
    pass


def _locations_get_section_ids(data: t.Any, start: t.Optional[str] = None) -> t.Generator[str, None, None]:
    assert isinstance(data, list), "locations data not a list"
    for location in data:
        assert isinstance(location, dict), "location not a dict"
        location_name: str = location.get("name", "")
        location_id = location_name if start is None else f"{start}/{location_name}"
        sections = location.get("sections", [])
        for section in sections:
            assert isinstance(section, dict), "section not a dict"
            ref: t.Optional[str] = section.get("ref", None)
            if ref is None:
                section_name: str = section.get("name", "")
                yield f"{location_id}/{section_name}"
        children = location.get("children", [])
        if children:
            yield from _locations_get_section_ids(children, location_id)


def _locations_get_location_ids(data: t.Any, start: t.Optional[str] = None) -> t.Generator[str, None, None]:
    assert isinstance(data, list), "locations data not a list"
    for location in data:
        assert isinstance(location, dict), "location not a dict"
        location_name: str = location.get("name", "")
        location_id = location_name if start is None else f"{start}/{location_name}"
        yield location_id
        children = location.get("children", [])
        if children:
            yield from _locations_get_location_ids(children, location_id)


def _locations_get_refs(data: t.Any) -> t.Generator[str, None, None]:
    assert isinstance(data, list), "locations data not a list"
    for location in data:
        assert isinstance(location, dict), "location not a dict"
        sections = location.get("sections", [])
        for section in sections:
            assert isinstance(section, dict), "section not a dict"
            ref: t.Optional[str] = section.get("ref", None)
            if ref is not None:
                yield ref
        children = location.get("children", [])
        if children:
            yield from _locations_get_refs(children)


def _locations_get_parents(data: t.Any) -> t.Generator[str, None, None]:
    assert isinstance(data, list), "locations data not a list"
    for location in data:
        assert isinstance(location, dict), "location not a dict"
        parent: t.Optional[str] = location.get("parent", None)
        if parent is not None:
            yield parent
        children = location.get("children", [])
        if children:
            yield from _locations_get_parents(children)


def check_refs(data: t.Any, path: Path) -> None:
    from .collect import collect_json

    # TODO: cache all known locations
    section_ids: t.Optional[t.Set[str]] = None
    location_ids: t.Optional[t.Set[str]] = None

    def fill_ids() -> None:
        nonlocal section_ids, location_ids
        section_ids = set()
        location_ids = set()
        for item in collect_json(path, {}):
            if item.type == "locations":
                for id_ in _locations_get_section_ids(item.data):
                    section_ids.add(id_)
                for id_ in _locations_get_location_ids(item.data):
                    location_ids.add(id_)

    for ref in _locations_get_refs(data):
        if section_ids is None:
            fill_ids()
            assert section_ids is not None
        if ref not in section_ids:
            partial_ref = f"/{ref}"
            for section_id in section_ids:
                if section_id.endswith(partial_ref):
                    break
            else:
                raise DataCheckError(f'ref "{ref}" not found')

    for parent in _locations_get_parents(data):
        if location_ids is None:
            fill_ids()
            assert location_ids is not None
        if parent not in location_ids:
            partial_parent = f"/{parent}"
            for location_id in location_ids:
                if location_id.endswith(partial_parent):
                    break
            else:
                raise DataCheckError(f'parent "{parent}" not found')
