import json
import typing as t
import warnings
from itertools import chain
from pathlib import Path
from urllib.request import urlopen

from jsonschema import validate
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

from .collect import Item, collect_images, collect_json, collect_lua
from .datachecks import check_refs, DataCheckError
from .imgutil import supported_formats as supported_img_formats
from .warnings import warn_pack

schema_default_src = "https://poptracker.github.io/schema/packs/"
default_checks: t.Mapping[str, bool] = {
    "legacy_compat": True,
}

data_checks: t.Mapping[str, t.Iterable[t.Callable[[t.Any, Path], None]]] = {
    "locations": (check_refs,),
}

schema_names = {"items", "layouts", "locations", "manifest", "maps", "settings", "classes"}
external_schema = {
    ".luarc": {
        "https://raw.githubusercontent.com/LuaLS/vscode-lua/master/setting/schema.json",
        "https://raw.githubusercontent.com/sumneko/vscode-lua/master/setting/schema.json",
    },
    "versions": {
        "https://raw.githubusercontent.com/black-sliver/PopTracker/refs/heads/packlist/schema/versions.schema.json"
    },
}
allowed_external_schema = set(chain(*external_schema.values()))

T = t.TypeVar("T")


class CollectError(Exception):
    pass


def _validate_config() -> None:
    # sanity check lists; doing this during runtime in case they get extended
    if not schema_names.isdisjoint(external_schema):
        raise ValueError("schema_names and external_schema overlap")
    for special_name in ("error", "ignore"):
        if special_name in schema_names or special_name in external_schema:
            raise ValueError(f"'{special_name}' has special meaning and is invalid as schema name")


def _cached(f: t.Callable[[T, str], Resource[t.Any]]) -> t.Callable[[T, str], Resource[t.Any]]:
    resource_cache: t.Dict[str, t.Union[Exception, Resource[t.Any]]] = {}

    def wrap(self: T, uri: str) -> Resource[t.Any]:
        cached_res = resource_cache.get(uri)
        if isinstance(cached_res, Exception):
            raise cached_res
        elif cached_res is not None:
            return cached_res
        try:
            res = f(self, uri)
            resource_cache[uri] = res
            return res
        except Exception as ex:
            resource_cache[uri] = NoSuchResource(ref=uri)  # type: ignore[call-arg]  # passing ref as per docs
            raise NoSuchResource(ref=uri) from ex  # type: ignore[call-arg]

    return wrap


class Checker:
    schema_source: str
    strict: bool
    checks: t.Mapping[str, bool]
    validate_external: bool

    # noinspection PyTypeHints
    registry: Registry[t.Any]  # PyCharm does not understand this

    def __init__(
        self,
        schema_src: str = schema_default_src,
        strict: bool = False,
        checks: t.Mapping[str, bool] = default_checks,
        validate_external: bool = False,
    ) -> None:
        _validate_config()
        self.schema_src = schema_src
        self.strict = strict
        self.checks = checks
        self.validate_external = validate_external
        self.registry = Registry(retrieve=self._retrieve)  # type: ignore[call-arg]  # passing retrieve as per docs

    def check(self, path: Path) -> int:
        ok = True
        count = 0

        # NOTE: PopTracker min version detection is not fully implemented yet
        requires_poptracker = False  # set if we detect an unconditional feature that is only available in PopTracker
        required_min_poptracker_version = (0, 24, 1)  # minimum because of update check
        manifest: t.Optional[Item]

        is_zipped = path.is_file()
        if is_zipped:
            # TODO: split collect and check to avoid mutating Checker
            self.checks = {**self.checks, "hidden_files": True, "unused_files": True}

        try:
            json_ok, json_count, manifest = self.check_json(path)
            ok &= json_ok
            count += json_count
        except CollectError:
            return 0
        finally:
            self.checks = {**self.checks, "hidden_files": False, "unused_files": False}  # only check hidden/unused once

        try:
            lua_ok, lua_count = self.check_lua(path)
            ok &= lua_ok
            count += lua_count
        except CollectError:
            return 0

        try:
            images_ok, images_count = self.check_images(path)
            ok &= images_ok
            count += images_count
        except CollectError:
            return 0

        ok &= self.check_poptracker_version(manifest, requires_poptracker, required_min_poptracker_version)

        return count if ok else 0

    # Item group validators

    def check_json(self, path: Path) -> t.Tuple[bool, int, t.Optional[Item]]:
        ok = True
        count = 0
        manifest: t.Optional[Item] = None
        try:
            for json_item in collect_json(path, self.checks):
                is_external = json_item.type in external_schema
                if json_item.type in schema_names or (self.validate_external and is_external):
                    if self.validate_json_item(json_item, path):
                        count += 1
                        if json_item.type == "manifest":
                            manifest = json_item
                    else:
                        ok = False
                elif json_item.type == "ignore" or is_external:
                    pass
                elif json_item.type == "error":
                    print(f"{json_item.name}: {json_item.data}")
                    ok = False
                elif json_item.type is None:
                    warn_pack("Unmatched file", filename=json_item.name)
                else:
                    warnings.warn(f"No schema {json_item.type} for {json_item.name}", RuntimeWarning)
                    ok = False
        except ImportError:
            raise
        except Exception as ex:
            print(f"Error collecting json: {ex}")
            raise CollectError from ex

        return ok, count, manifest

    def check_lua(self, path: Path) -> t.Tuple[bool, int]:
        ok = True
        count = 0
        try:
            for lua_item in collect_lua(path, self.checks):  # collecting them checks for encoding errors
                # do we want to bundle a full Lua? py-lua-parser is sadly not good enough
                if lua_item.type == "error":
                    warn_pack(str(lua_item.data), lua_item.name)
                    # ok = False  # TODO: enable this in v2
        except Exception as ex:
            print(f"Error collecting Lua: {ex}")
            raise CollectError from ex

        return ok, count

    def check_images(self, path: Path) -> t.Tuple[bool, int]:
        ok = True
        count = 0
        is_zipped = path.is_file()
        try:
            for image_item in collect_images(path, self.checks):
                # until we verify the image is actually in use, only report compatibility issues for zip
                # since a folder could have source files that then get converted to the format in use
                if image_item.type == "error":
                    warn_pack(str(image_item.data), image_item.name)
                    # ok = False  # TODO: enable this in v2
                elif is_zipped:
                    if image_item.type not in supported_img_formats:
                        warn_pack(f"Image format {image_item.type} is not supported by all versions", image_item.name)
        except Exception as ex:
            print(f"Error collecting images: {ex}")
            raise CollectError from ex

        return ok, count

    def check_poptracker_version(
        self,
        manifest: t.Optional[Item],
        requires_poptracker: bool,
        required_min_poptracker_version: t.Tuple[int, int, int],
    ) -> bool:
        ok = True
        if manifest and (requires_poptracker or not self.checks.get("legacy_compat", True)):
            # if either legacy compat is off, or poptracker is required, check min_pop_version is sensible
            manifest_data: t.Dict[str, t.Any] = manifest.data
            min_poptracker_version: str = manifest_data.get("min_poptracker_version", "")
            try:
                if tuple(map(int, min_poptracker_version.split("."))) < (0, 24, 1):
                    required_min_poptracker_version_string = ".".join(map(str, required_min_poptracker_version))
                    warn_pack(
                        f'min_poptracker_version should be at least "{required_min_poptracker_version_string}" '
                        "(this does not detect all features yet).",
                        manifest.name,
                    )
            except (ValueError, AttributeError):
                reason = "Pack requires poptracker" if requires_poptracker else "Legacy mode is off"
                warn_pack(f"{reason}, but min_poptracker_version is not set to a valid version.", manifest.name)

        return ok

    # Single item validators

    def validate_json_item(self, item: Item, pack_path: Path) -> bool:
        try:
            if not isinstance(item.type, str):
                raise ValueError("Invalid item.type")
            if item.type in external_schema:
                # check $schema, allow undefined/missing $schema if the expected schema is unambiguous
                possible_schemas = external_schema[item.type]
                first_schema = next(iter(possible_schemas))
                schema_ref = (
                    first_schema
                    if not isinstance(item.data, dict) and len(possible_schemas) == 1
                    else item.data.get("$schema", first_schema if len(external_schema[item.type]) == 1 else None)
                )
                if not schema_ref or schema_ref not in external_schema[item.type]:
                    raise ValidationError("Unexpected $schema")
                validate(
                    instance=item.data,
                    schema={"$ref": schema_ref},
                    registry=self.registry,
                )
            else:
                # validate against pack schema
                validate(
                    instance=item.data,
                    schema={"$ref": f"strict/{item.type}.json" if self.strict else f"{item.type}.json"},
                    registry=self.registry,
                )
                for data_check in data_checks.get(item.type, []):
                    data_check(item.data, pack_path)
            return True
        except ValidationError as ex:
            print(f"\n{item.name}: {ex}")
        except DataCheckError as ex:
            print(f"\n{item.name}: {ex}")
        except Unresolvable as ex:
            if item.type in external_schema:
                msg = f"Error loading schema {item.data.get('$schema', None)}: {ex}"
            else:
                msg = f"Error loading schema {'strict/' if self.strict else ''}{item.type}.json: {ex}"
            raise Exception(msg) from ex
        except Exception as ex:
            print(f"{ex} while handling {item.name} {type(ex)}")
            raise
        return False

    # Helper functions

    @_cached  # we cache here since registry is immutable
    def _retrieve(self, uri: str) -> Resource[t.Any]:
        """Function to retrieve a schema resource from uri"""
        if uri.startswith("file:"):
            raise ValueError("File URI not allowed in schema")
        if "://" in uri or uri.startswith("/"):
            if uri not in allowed_external_schema:
                raise NotImplementedError()  # only relative retrieve and allow-list implemented
            full_uri = uri
        else:
            full_uri = self.schema_src + uri
        # TODO: deny insecure http in v2
        if not any(full_uri.startswith(schema) for schema in ("file:", "https:", "http:")):
            raise ValueError("Unsupported URI scheme to retrieve resource")
        r = urlopen(full_uri)  # noqa: S310 checked above
        content = r.read().decode(r.headers.get_content_charset() or "utf-8")
        return Resource.from_contents(json.loads(content), default_specification=DRAFT202012)
