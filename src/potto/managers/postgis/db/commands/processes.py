import dataclasses
import logging
from typing import cast

from sqlmodel.ext.asyncio.session import AsyncSession

from .....exceptions import (
    CannotCreateResourceException,
    CannotUpdateResourceException,
    ResourceNotFoundException,
)
from .....schemas.processes import (
    ExecutionUnitCwlCreate,
    ExecutionUnitCwlUpdate,
    ExecutionUnitOciCreate,
    ExecutionUnitOciUpdate,
    ExecutionUnitOtherCreate,
    ExecutionUnitOtherUpdate,
    ProcessCreate,
    ProcessUpdate,
)
from ..models import Process
from ..queries.processes import get_process

logger = logging.getLogger(__name__)


def _execution_unit_create_to_dict(
    execution_unit: ExecutionUnitOciCreate
    | ExecutionUnitCwlCreate
    | ExecutionUnitOtherCreate,
) -> dict:
    match execution_unit:
        case ExecutionUnitOciCreate():
            cfg = execution_unit.config
            return {
                "type_": "oci",
                "image": execution_unit.image,
                "bindings_inputs": {
                    name: {
                        "prefix": b.prefix,
                        "position": b.position,
                        "value_from": b.value_from,
                        "item_separator": b.item_separator,
                        "shell_quote": b.shell_quote,
                    }
                    for name, b in execution_unit.bindings.inputs.items()
                },
                "bindings_outputs": {
                    name: {"glob_pattern": b.glob_pattern}
                    for name, b in execution_unit.bindings.outputs.items()
                },
                "config_cpu_min_num": cfg.cpu_min_num,
                "config_cpu_max_num": cfg.cpu_max_num,
                "config_memory_min_gb": cfg.memory_min_gb,
                "config_memory_max_gb": cfg.memory_max_gb,
                "config_storage_temp_min_gb": cfg.storage_temp_min_gb,
                "config_storage_outputs_min_gb": cfg.storage_outputs_min_gb,
                "config_job_timeout_seconds": cfg.job_timeout_seconds,
            }
        case ExecutionUnitCwlCreate():
            return {"type_": "cwl", "definition": execution_unit.value}
        case ExecutionUnitOtherCreate():
            return {"type_": execution_unit.type_, "definition": execution_unit.value}


def _execution_unit_update_to_dict(
    execution_unit: ExecutionUnitOciUpdate
    | ExecutionUnitCwlUpdate
    | ExecutionUnitOtherUpdate,
) -> dict:
    match execution_unit:
        case ExecutionUnitOciUpdate():
            result: dict = {"type_": "oci"}
            if execution_unit.image is not None:
                result["image"] = execution_unit.image
            for key, value in execution_unit.config.model_dump(
                exclude_unset=True
            ).items():
                result[f"config_{key}"] = value
            if execution_unit.bindings.inputs is not None:
                result["bindings_inputs"] = {
                    name: {
                        "prefix": b.prefix,
                        "position": b.position,
                        "value_from": b.value_from,
                        "item_separator": b.item_separator,
                        "shell_quote": b.shell_quote,
                    }
                    for name, b in execution_unit.bindings.inputs.items()
                }
            if execution_unit.bindings.outputs is not None:
                result["bindings_outputs"] = {
                    name: {"glob_pattern": b.glob_pattern}
                    for name, b in execution_unit.bindings.outputs.items()
                }
            return result
        case ExecutionUnitCwlUpdate():
            cwl_result: dict = {"type_": "cwl"}
            if execution_unit.value is not None:
                cwl_result["definition"] = execution_unit.value
            return cwl_result
        case ExecutionUnitOtherUpdate():
            other_result: dict = {"type_": execution_unit.type_}
            if execution_unit.value is not None:
                other_result["definition"] = execution_unit.value
            return other_result


def _process_create_to_orm_kwargs(to_create: ProcessCreate) -> dict:
    desc = to_create.description
    return {
        "resource_identifier": desc.identifier,
        "owner_id": desc.owner_id,
        "version": desc.version,
        "is_public": desc.is_public,
        "title": desc.title,
        "description": desc.description,
        "keywords": desc.keywords,
        "additional_links": desc.additional_links,
        "inputs": [dataclasses.asdict(i) for i in desc.inputs],
        "outputs": [dataclasses.asdict(o) for o in desc.outputs],
        "execution_unit": _execution_unit_create_to_dict(to_create.execution_unit),
    }


async def create_process(session: AsyncSession, to_create: ProcessCreate) -> Process:
    logger.debug(f"{to_create=}")
    instance = Process(**_process_create_to_orm_kwargs(to_create))
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    if (created := await get_process(session, cast(int, instance.id))) is None:
        raise CannotCreateResourceException("error creating process")
    return created


async def update_process(
    session: AsyncSession,
    db_process: Process,
    to_update: ProcessUpdate,
) -> Process:
    desc_updates = to_update.description.model_dump(exclude_unset=True)
    if "inputs" in desc_updates:
        desc_updates["inputs"] = (
            [dataclasses.asdict(i) for i in to_update.description.inputs]
            if to_update.description.inputs is not None
            else None
        )
    if "outputs" in desc_updates:
        desc_updates["outputs"] = (
            [dataclasses.asdict(o) for o in to_update.description.outputs]
            if to_update.description.outputs is not None
            else None
        )
    for key, value in desc_updates.items():
        setattr(db_process, key, value)

    if exec_updates := _execution_unit_update_to_dict(to_update.execution_unit):
        db_process.execution_unit = {
            **(db_process.execution_unit or {}),
            **exec_updates,
        }

    session.add(db_process)
    await session.commit()
    await session.refresh(db_process)
    if (updated := await get_process(session, cast(int, db_process.id))) is None:
        raise CannotUpdateResourceException(f"error updating process {db_process.id}")
    return updated


async def delete_process(
    session: AsyncSession,
    process_id: int,
) -> None:
    if instance := (await get_process(session, process_id)):
        await session.delete(instance)
        await session.commit()
    else:
        raise ResourceNotFoundException(f"Process with id {process_id} does not exist.")
