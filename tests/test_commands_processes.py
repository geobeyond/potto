import pytest
from sqlalchemy.exc import IntegrityError

from potto import exceptions
from potto.managers.postgis.db.commands import processes as process_commands
from potto.managers.postgis.operations import processes as process_operations
from potto.schemas import processes as process_schemas

pytestmark = pytest.mark.integration


def _description(admin_user, **overrides) -> process_schemas.ProcessDescriptionCreate:
    kwargs = {
        "identifier": "proc1",
        "title": "Fake process title",
        "owner_id": admin_user.id,
        "is_public": False,
        "version": "1.0.0",
    }
    kwargs.update(overrides)
    return process_schemas.ProcessDescriptionCreate(**kwargs)


def _oci_execution_unit_create() -> process_schemas.ExecutionUnitOciCreate:
    return process_schemas.ExecutionUnitOciCreate(
        image="fake-image:latest",
        config=process_schemas.ExecutionUnitOciConfigCreate(cpuMin=2, cpuMax=4),
        bindings=process_schemas.OciBindingsCreate(
            inputs={
                "an-input": process_schemas.OciInputBindingCreate(
                    prefix="--input", valueFrom="an-input"
                )
            },
            outputs={"an-output": process_schemas.OciOutputBindingCreate(glob="*.tif")},
        ),
    )


@pytest.mark.asyncio
async def test_process_create_with_oci_execution_unit_round_trips(
    db_session_maker, admin_user
):
    to_create = process_schemas.ProcessCreate(
        processDescription=_description(admin_user),
        execution_unit=_oci_execution_unit_create(),
    )
    async with db_session_maker() as session:
        db_process = await process_commands.create_process(session, to_create)
        assert db_process.id is not None
        process = db_process.to_potto()
        execution_unit = process.execution_unit
        assert isinstance(execution_unit, process_schemas.ProcessExecutionUnitOci)
        assert execution_unit.image == "fake-image:latest"
        assert execution_unit.config_cpu_min_num == 2
        assert execution_unit.config_cpu_max_num == 4
        assert execution_unit.bindings_inputs == {
            "an-input": {
                "prefix": "--input",
                "position": None,
                "value_from": "an-input",
                "item_separator": None,
                "shell_quote": True,
            }
        }
        assert execution_unit.bindings_outputs == {
            "an-output": {"glob_pattern": "*.tif"}
        }


@pytest.mark.asyncio
async def test_process_create_with_cwl_execution_unit_round_trips(
    db_session_maker, admin_user
):
    to_create = process_schemas.ProcessCreate(
        processDescription=_description(admin_user),
        execution_unit=process_schemas.ExecutionUnitCwlCreate(
            value={"cwlVersion": "v1.2", "class": "CommandLineTool"}
        ),
    )
    async with db_session_maker() as session:
        db_process = await process_commands.create_process(session, to_create)
        execution_unit = db_process.to_potto().execution_unit
        assert isinstance(execution_unit, process_schemas.ProcessExecutionUnitCwl)
        assert execution_unit.definition == {
            "cwlVersion": "v1.2",
            "class": "CommandLineTool",
        }


@pytest.mark.asyncio
async def test_process_create_with_other_execution_unit_round_trips(
    db_session_maker, admin_user
):
    to_create = process_schemas.ProcessCreate(
        processDescription=_description(admin_user),
        execution_unit=process_schemas.ExecutionUnitOtherCreate(
            type_="custom-type", value={"foo": "bar"}
        ),
    )
    async with db_session_maker() as session:
        db_process = await process_commands.create_process(session, to_create)
        execution_unit = db_process.to_potto().execution_unit
        assert isinstance(execution_unit, process_schemas.ProcessExecutionUnitOther)
        assert execution_unit.type_ == "custom-type"
        assert execution_unit.definition == {"foo": "bar"}


@pytest.mark.asyncio
async def test_process_create_fails_on_duplicate_identifier_and_version(
    db_session_maker, admin_user
):
    first_to_create = process_schemas.ProcessCreate(
        processDescription=_description(admin_user),
        execution_unit=process_schemas.ExecutionUnitCwlCreate(value={}),
    )
    second_to_create = process_schemas.ProcessCreate(
        processDescription=_description(admin_user, title="Another fake title"),
        execution_unit=process_schemas.ExecutionUnitCwlCreate(value={}),
    )
    async with db_session_maker() as session:
        await process_commands.create_process(session, first_to_create)
        with pytest.raises(IntegrityError):
            await process_commands.create_process(session, second_to_create)


@pytest.mark.asyncio
async def test_process_update_partial_leaf_field_preserves_rest(
    db_session_maker, admin_user
):
    to_create = process_schemas.ProcessCreate(
        processDescription=_description(admin_user, keywords=["fake", "keywords"]),
        execution_unit=_oci_execution_unit_create(),
    )
    async with db_session_maker() as session:
        db_process = await process_commands.create_process(session, to_create)

        to_update = process_schemas.ProcessUpdate(
            processDescription=process_schemas.ProcessDescriptionUpdate(
                title="Updated title"
            ),
            execution_unit=process_schemas.ExecutionUnitOciUpdate(
                image="another-image:latest",
                config=process_schemas.ExecutionUnitOciConfigUpdate(),
                bindings=process_schemas.OciBindingsUpdate(),
            ),
        )
        updated = await process_commands.update_process(session, db_process, to_update)

        assert updated.title == "Updated title"
        assert updated.keywords == ["fake", "keywords"]
        execution_unit = updated.to_potto().execution_unit
        assert isinstance(execution_unit, process_schemas.ProcessExecutionUnitOci)
        assert execution_unit.image == "another-image:latest"
        # unset leaf fields on the update must not clobber previously stored values
        assert execution_unit.config_cpu_min_num == 2
        assert execution_unit.config_cpu_max_num == 4
        assert execution_unit.bindings_inputs == {
            "an-input": {
                "prefix": "--input",
                "position": None,
                "value_from": "an-input",
                "item_separator": None,
                "shell_quote": True,
            }
        }


@pytest.mark.asyncio
async def test_operations_update_process_owner_change_requires_permission(
    db_session_maker, admin_user
):
    to_create = process_schemas.ProcessCreate(
        processDescription=_description(admin_user),
        execution_unit=process_schemas.ExecutionUnitCwlCreate(value={}),
    )

    class _DenyOwnerChangeBackend:
        async def can_edit_process(self, user, process) -> bool:
            return True

        async def can_change_process_owner(self, user, process) -> bool:
            return False

    async with db_session_maker() as session:
        db_process = await process_commands.create_process(session, to_create)
        process = db_process.to_potto()

        to_update = process_schemas.ProcessUpdate(
            processDescription=process_schemas.ProcessDescriptionUpdate(
                owner_id="someone-else"
            ),
            execution_unit=process_schemas.ExecutionUnitCwlUpdate(),
        )
        with pytest.raises(exceptions.CannotChangeResourceOwnerException):
            await process_operations.update_process(
                session,
                admin_user,
                _DenyOwnerChangeBackend(),
                process,
                to_update,
            )
