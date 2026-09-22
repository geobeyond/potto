from typing import Any

from ...constants import (
    CollectionType,
    ProvidedDataType,
)
from ...schemas.auth import PottoUser
from ...schemas.base import (
    PottoProvider,
    to_shapely,
)
from ...schemas.collections import Collection
from ...schemas.metadata import (
    DataProviderInformation,
    LicenseInformation,
    PointOfContact,
    ServerMetadata,
)
from ...schemas.processes import (
    OciInputBinding,
    OciOutputBinding,
    Process,
    ProcessDeploymentStatus,
    ProcessExecutionUnitCwl,
    ProcessExecutionUnitOci,
    ProcessExecutionUnitOther,
    ProcessInputDescription,
    ProcessOutputDescription,
)


def parse_user_accounts(
    raw_entries: list[dict[str, Any]],
) -> tuple[dict[str, PottoUser], dict[str, str]]:
    """Parse ``[[user_account]]`` entries into users, keyed by id.

    Returns the users alongside a separate ``{user_id: hashed_password}`` mapping for
    entries that set ``hashed_password`` - kept out of ``PottoUser`` itself, which has
    no password field.
    """
    users: dict[str, PottoUser] = {}
    hashed_passwords: dict[str, str] = {}
    for raw in raw_entries:
        raw = dict(raw)
        hashed_password = raw.pop("hashed_password", None)
        user = PottoUser(**raw)
        users[user.id] = user
        if hashed_password:
            hashed_passwords[user.id] = hashed_password
    return users, hashed_passwords


def parse_collections(
    raw_entries: list[dict[str, Any]],
    users_by_id: dict[str, PottoUser],
) -> dict[str, Collection]:
    """Parse ``[[collection]]`` entries into ``Collection`` instances, keyed by identifier.

    ``Collection`` is a plain frozen dataclass, so unlike ``PottoUser`` (a pydantic
    model) its fields are not coerced/validated on construction - this function does
    that coercion by hand for the fields that need it: ``owner`` (resolved from
    ``owner_id`` against ``users_by_id``), ``type_`` (a ``CollectionType``),
    ``spatial_extent`` (a ``shapely.Geometry``, parsed from WKT), and ``providers``
    (``dict[ProvidedDataType, PottoProvider]``).
    """
    collections: dict[str, Collection] = {}
    for raw in raw_entries:
        raw = dict(raw)
        owner_id = raw.pop("owner_id")
        try:
            owner = users_by_id[owner_id]
        except KeyError:
            raise ValueError(
                f"Collection {raw.get('identifier')!r} references unknown "
                f"owner_id {owner_id!r}"
            ) from None
        raw["owner"] = owner
        raw["type_"] = CollectionType(raw["type_"])
        if (raw_extent := raw.get("spatial_extent")) is not None:
            raw["spatial_extent"] = to_shapely(raw_extent)
        if (raw_providers := raw.get("providers")) is not None:
            raw["providers"] = {
                ProvidedDataType(key): PottoProvider(**value)
                for key, value in raw_providers.items()
            }
        collection = Collection(**raw)
        collections[collection.identifier] = collection
    return collections


def _parse_execution_unit(
    raw: dict[str, Any],
) -> ProcessExecutionUnitOci | ProcessExecutionUnitCwl | ProcessExecutionUnitOther:
    raw = dict(raw)
    type_ = raw.get("type_")
    if type_ == "oci":
        raw["bindings_inputs"] = {
            key: OciInputBinding(**value)
            for key, value in raw.get("bindings_inputs", {}).items()
        }
        raw["bindings_outputs"] = {
            key: OciOutputBinding(**value)
            for key, value in raw.get("bindings_outputs", {}).items()
        }
        return ProcessExecutionUnitOci(**raw)
    elif type_ == "cwl":
        return ProcessExecutionUnitCwl(**raw)
    else:
        return ProcessExecutionUnitOther(**raw)


def parse_processes(
    raw_entries: list[dict[str, Any]],
    users_by_id: dict[str, PottoUser],
) -> dict[str, Process]:
    """Parse ``[[process]]`` entries into ``Process`` instances, keyed by identifier.

    Like ``parse_collections``, this hand-builds the fields that ``Process`` (a plain
    frozen dataclass) can't coerce on its own: ``owner`` (resolved from ``owner_id``
    against ``users_by_id``), ``inputs``/``outputs`` (lists of
    ``ProcessInputDescription``/``ProcessOutputDescription``), ``execution_unit`` (one
    of the OCI/CWL/other variants, picked by its ``type_`` field), and
    ``deployment_status`` (defaulting to ``failed`` when absent, mirroring
    ``managers/postgis/db/models.py``'s ``Process.to_potto()``).
    """
    processes: dict[str, Process] = {}
    for raw in raw_entries:
        raw = dict(raw)
        owner_id = raw.pop("owner_id")
        try:
            owner = users_by_id[owner_id]
        except KeyError:
            raise ValueError(
                f"Process {raw.get('identifier')!r} references unknown "
                f"owner_id {owner_id!r}"
            ) from None
        raw["owner"] = owner
        raw["inputs"] = [
            ProcessInputDescription(**value) for value in raw.get("inputs", [])
        ]
        raw["outputs"] = [
            ProcessOutputDescription(**value) for value in raw.get("outputs", [])
        ]
        if (raw_execution_unit := raw.get("execution_unit")) is not None:
            raw["execution_unit"] = _parse_execution_unit(raw_execution_unit)
        if (raw_deployment_status := raw.get("deployment_status")) is not None:
            raw["deployment_status"] = ProcessDeploymentStatus(**raw_deployment_status)
        else:
            raw["deployment_status"] = ProcessDeploymentStatus(value="failed")
        process = Process(**raw)
        processes[process.identifier] = process
    return processes


def parse_server_metadata(raw: dict[str, Any]) -> ServerMetadata:
    """Parse the ``[server_metadata]`` table into a ``ServerMetadata`` instance.

    Like ``Collection``, ``ServerMetadata`` is a plain frozen dataclass, so its
    ``license``/``data_provider``/``point_of_contact`` sub-tables need to be
    explicitly built into their pydantic model instances rather than left as raw
    dicts.
    """
    raw = dict(raw)
    if (raw_license := raw.get("license")) is not None:
        raw["license"] = LicenseInformation(**raw_license)
    if (raw_data_provider := raw.get("data_provider")) is not None:
        raw["data_provider"] = DataProviderInformation(**raw_data_provider)
    if (raw_point_of_contact := raw.get("point_of_contact")) is not None:
        raw["point_of_contact"] = PointOfContact(**raw_point_of_contact)
    return ServerMetadata(**raw)
