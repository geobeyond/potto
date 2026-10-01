"""Tests for the coordination of process deployments.

Deploying a process involves the process manager, which records the deployment
status, and the job manager, which does the actual deployment. These tests use the
postgis process manager together with a fake job manager.
"""

import asyncio
from unittest import mock

import pytest

from potto.eventhandlers import processes as process_handlers
from potto.exceptions import (
    DeploymentAlreadyInProgressError,
    ProcessDeploymentStatusConflictError,
)
from potto.schemas.auth import SystemPrincipal
from potto.schemas.events import InternalProcessEventType
from potto.schemas.processes import (
    ExecutionUnitOtherUpdate,
    ProcessDeploymentStatus,
    ProcessDeploymentStatusValue,
    ProcessDescriptionUpdate,
    ProcessUpdate,
)
from potto.wrapper import Potto

pytestmark = pytest.mark.integration

_SYSTEM = SystemPrincipal("test-system")
_Value = ProcessDeploymentStatusValue


class _FakeJobManager:
    def __init__(self, deploy):
        self.deploy = mock.AsyncMock(side_effect=deploy)

    async def deploy_process(self, process):
        return await self.deploy(process)


async def _deployed(process):
    return ProcessDeploymentStatus(value=_Value.DEPLOYED, detail="all good")


@pytest.fixture
def potto(settings):
    return Potto(settings)


def _use_job_manager(settings, job_manager):
    return mock.patch.object(
        type(settings), "get_job_manager", return_value=job_manager
    )


def _capture_events(potto):
    return mock.patch.object(potto, "publish_internal_process_event")


class TestConditionalDeploymentStatus:
    @pytest.mark.asyncio
    async def test_process_without_status_counts_as_failed(
        self, postgis_contract_harness, settings
    ):
        process_manager = settings.get_process_manager()
        process = postgis_contract_harness.private_process
        claimed = await process_manager.set_process_deployment_status(
            process, _Value.IN_PROGRESS, _SYSTEM, from_values={_Value.FAILED}
        )
        assert claimed.deployment_status.value == _Value.IN_PROGRESS
        assert claimed.deployment_status.definition_hash == (
            process.get_deployment_hash()
        )

    @pytest.mark.asyncio
    async def test_unmatched_value_is_a_conflict(
        self, postgis_contract_harness, settings
    ):
        process_manager = settings.get_process_manager()
        process = postgis_contract_harness.private_process
        await process_manager.set_process_deployment_status(
            process, _Value.IN_PROGRESS, _SYSTEM
        )
        with pytest.raises(ProcessDeploymentStatusConflictError):
            await process_manager.set_process_deployment_status(
                process,
                _Value.IN_PROGRESS,
                _SYSTEM,
                from_values={_Value.DEPLOYED, _Value.FAILED},
            )
        current = await process_manager.get_process(process.identifier, _SYSTEM)
        assert current.deployment_status.value == _Value.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_unmatched_definition_hash_is_a_conflict(
        self, postgis_contract_harness, settings
    ):
        process_manager = settings.get_process_manager()
        process = postgis_contract_harness.private_process
        await process_manager.set_process_deployment_status(
            process, _Value.IN_PROGRESS, _SYSTEM
        )
        with pytest.raises(ProcessDeploymentStatusConflictError):
            await process_manager.set_process_deployment_status(
                process,
                _Value.DEPLOYED,
                _SYSTEM,
                from_values={_Value.IN_PROGRESS},
                expected_definition_hash="some-other-hash",
            )
        deployed = await process_manager.set_process_deployment_status(
            process,
            _Value.DEPLOYED,
            _SYSTEM,
            from_values={_Value.IN_PROGRESS},
            expected_definition_hash=process.get_deployment_hash(),
        )
        assert deployed.deployment_status.value == _Value.DEPLOYED


class TestDeployProcess:
    @pytest.mark.asyncio
    async def test_successful_deployment(
        self, postgis_contract_harness, settings, potto
    ):
        process = postgis_contract_harness.private_process
        job_manager = _FakeJobManager(_deployed)
        with _use_job_manager(settings, job_manager), _capture_events(potto) as publish:
            deployed = await potto.deploy_process(process.identifier, user=_SYSTEM)
        job_manager.deploy.assert_awaited_once()
        assert deployed.deployment_status.value == _Value.DEPLOYED
        assert deployed.deployment_status.detail == "all good"
        (event,), _ = publish.await_args
        assert event.event_type == InternalProcessEventType.DEPLOYED

    @pytest.mark.asyncio
    async def test_failing_deployment_is_recorded_as_failed(
        self, postgis_contract_harness, settings, potto
    ):
        process = postgis_contract_harness.private_process
        job_manager = _FakeJobManager(RuntimeError("no luck"))
        with _use_job_manager(settings, job_manager), _capture_events(potto) as publish:
            deployed = await potto.deploy_process(process.identifier, user=_SYSTEM)
        assert deployed.deployment_status.value == _Value.FAILED
        assert deployed.deployment_status.detail == "no luck"
        (event,), _ = publish.await_args
        assert event.event_type == InternalProcessEventType.DEPLOYMENT_FAILED

    @pytest.mark.asyncio
    async def test_concurrent_deployments_deploy_only_once(
        self, postgis_contract_harness, settings, potto
    ):
        process = postgis_contract_harness.private_process

        async def slow_deploy(process):
            await asyncio.sleep(0.2)
            return await _deployed(process)

        job_manager = _FakeJobManager(slow_deploy)
        with _use_job_manager(settings, job_manager), _capture_events(potto):
            results = await asyncio.gather(
                *(
                    potto.deploy_process(process.identifier, user=_SYSTEM)
                    for _ in range(5)
                ),
                return_exceptions=True,
            )
        assert job_manager.deploy.await_count == 1
        already_in_progress = [
            r for r in results if isinstance(r, DeploymentAlreadyInProgressError)
        ]
        assert len(already_in_progress) == 4

    @pytest.mark.asyncio
    async def test_definition_changed_while_deploying_is_detectable(
        self, postgis_contract_harness, settings, potto
    ):
        process = postgis_contract_harness.private_process
        process_manager = settings.get_process_manager()

        async def deploy_while_definition_changes(process):
            await process_manager.update_process(
                process,
                ProcessUpdate(
                    processDescription=ProcessDescriptionUpdate(),
                    execution_unit=ExecutionUnitOtherUpdate(
                        type_="other", value={"changed": True}
                    ),
                ),
                _SYSTEM,
            )
            return await _deployed(process)

        job_manager = _FakeJobManager(deploy_while_definition_changes)
        with _use_job_manager(settings, job_manager), _capture_events(potto) as publish:
            await potto.deploy_process(process.identifier, user=_SYSTEM)
        current = await process_manager.get_process(process.identifier, _SYSTEM)
        # the recorded hash is that of the definition that got deployed, so the
        # reconciler, triggered by the published event, sees it is outdated
        assert current.deployment_status.value == _Value.DEPLOYED
        assert current.deployment_status.definition_hash == (
            process.get_deployment_hash()
        )
        assert current.get_deployment_hash() != process.get_deployment_hash()
        publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_outcome_is_not_recorded_when_status_changed_meanwhile(
        self, postgis_contract_harness, settings, potto
    ):
        process = postgis_contract_harness.private_process
        process_manager = settings.get_process_manager()

        async def deploy_while_status_changes(process):
            await process_manager.set_process_deployment_status(
                process, _Value.FAILED, _SYSTEM, detail="reset by someone else"
            )
            return await _deployed(process)

        job_manager = _FakeJobManager(deploy_while_status_changes)
        with _use_job_manager(settings, job_manager), _capture_events(potto) as publish:
            await potto.deploy_process(process.identifier, user=_SYSTEM)
        current = await process_manager.get_process(process.identifier, _SYSTEM)
        assert current.deployment_status.value == _Value.FAILED
        assert current.deployment_status.detail == "reset by someone else"
        publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconciler_ignores_deployments_already_in_progress(settings):
    process = mock.Mock()
    process.get_deployment_hash.return_value = "new-hash"
    process.deployment_status = ProcessDeploymentStatus(
        value=_Value.IN_PROGRESS, definition_hash="old-hash"
    )
    with mock.patch.object(process_handlers, "Potto") as potto_class:
        potto_class.return_value.get_process = mock.AsyncMock(return_value=process)
        potto_class.return_value.deploy_process = mock.AsyncMock(
            side_effect=DeploymentAlreadyInProgressError
        )
        await process_handlers._reconcile_process(
            "some-process", "some-correlation-id", settings=settings
        )
    potto_class.return_value.deploy_process.assert_awaited_once()
