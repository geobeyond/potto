"""Tests for the coordination of process deployments.

Deploying a process involves the process manager, which records the deployment
status, and the job manager, which does the actual deployment. These tests use the
postgis process manager together with either a fake job manager, or the postgis job
manager talking to a fake container engine.
"""

import asyncio
import datetime as dt
from unittest import mock

import docker
import pytest
from fake_docker import FakeDockerClient

from potto.eventhandlers import processes as process_handlers
from potto.exceptions import (
    DeploymentAlreadyInProgressError,
    ProcessDeploymentStatusConflictError,
    ProcessExecutionUnitRejectedError,
)
from potto.schemas.auth import SystemPrincipal
from potto.schemas.events import (
    InternalProcessDeletionEvent,
    InternalProcessEvent,
    InternalProcessEventType,
)
from potto.schemas.processes import (
    ExecutionUnitOciConfigCreate,
    ExecutionUnitOciConfigUpdate,
    ExecutionUnitOciCreate,
    ExecutionUnitOciUpdate,
    ExecutionUnitOtherUpdate,
    OciBindingsCreate,
    OciBindingsUpdate,
    ProcessCreate,
    ProcessDeploymentStatus,
    ProcessDeploymentStatusValue,
    ProcessDescriptionCreate,
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
        self.undeploy = mock.AsyncMock()

    async def deploy_process(self, process):
        return await self.deploy(process)

    async def undeploy_process(self, process):
        return await self.undeploy(process)


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


def _oci_process_create(identifier, owner, image="docker.io/library/alpine:3.20"):
    return ProcessCreate(
        processDescription=ProcessDescriptionCreate(
            identifier=identifier,
            title="An OCI process",
            owner_id=owner.id,
            is_public=False,
            version="1.0.0",
        ),
        execution_unit=ExecutionUnitOciCreate(
            image=image,
            config=ExecutionUnitOciConfigCreate(),
            bindings=OciBindingsCreate(inputs={}, outputs={}),
        ),
    )


def _use_docker(client):
    return mock.patch.object(docker, "from_env", return_value=client)


def _restrict_registries(settings, allowed):
    return mock.patch.object(
        settings.get_job_manager().config.oci, "allowed_registries", allowed
    )


class TestOciDeployment:
    @pytest.mark.asyncio
    async def test_deploy_through_potto(
        self, postgis_contract_harness, settings, potto
    ):
        client = FakeDockerClient()
        with _capture_events(potto):
            process = await potto.create_process(
                _oci_process_create("oci-process", postgis_contract_harness.owner_user),
                user=postgis_contract_harness.owner_user,
            )
            with _use_docker(client):
                deployed = await potto.deploy_process(process.identifier, user=_SYSTEM)
        status = deployed.deployment_status
        assert status.value == _Value.DEPLOYED
        assert status.deployed_reference.startswith("localhost/potto/process-")
        assert status.deployed_reference in client.image_names()
        assert "docker.io/library/alpine@sha256:" in status.detail

    @pytest.mark.asyncio
    async def test_redeploy_releases_earlier_deployment(
        self, postgis_contract_harness, settings, potto
    ):
        client = FakeDockerClient()
        process_manager = settings.get_process_manager()
        with _capture_events(potto):
            process = await potto.create_process(
                _oci_process_create("oci-process", postgis_contract_harness.owner_user),
                user=postgis_contract_harness.owner_user,
            )
            with _use_docker(client):
                first = await potto.deploy_process(process.identifier, user=_SYSTEM)
                # redeploying needs a definition change, which the reconciler
                # would also react to
                await process_manager.update_process(
                    first,
                    ProcessUpdate(
                        processDescription=ProcessDescriptionUpdate(),
                        execution_unit=ExecutionUnitOciUpdate(
                            image="docker.io/library/alpine:3.21",
                            config=ExecutionUnitOciConfigUpdate(),
                            bindings=OciBindingsUpdate(),
                        ),
                    ),
                    _SYSTEM,
                )
                second = await potto.deploy_process(process.identifier, user=_SYSTEM)
        names = client.image_names()
        assert first.deployment_status.deployed_reference not in names
        assert second.deployment_status.deployed_reference in names
        assert "alpine:3.20" not in names

    @pytest.mark.asyncio
    async def test_registry_disallowed_at_deploy_time_fails(
        self, postgis_contract_harness, settings, potto
    ):
        client = FakeDockerClient()
        with _capture_events(potto):
            process = await potto.create_process(
                _oci_process_create("oci-process", postgis_contract_harness.owner_user),
                user=postgis_contract_harness.owner_user,
            )
            with _use_docker(client), _restrict_registries(settings, ["ghcr.io"]):
                deployed = await potto.deploy_process(process.identifier, user=_SYSTEM)
        assert deployed.deployment_status.value == _Value.FAILED
        assert "docker.io" in deployed.deployment_status.detail
        assert client.images.pulls == []

    @pytest.mark.asyncio
    async def test_disallowed_image_is_rejected_on_creation(
        self, postgis_contract_harness, settings, potto
    ):
        with (
            _capture_events(potto) as publish,
            _restrict_registries(settings, ["ghcr.io"]),
        ):
            with pytest.raises(ProcessExecutionUnitRejectedError):
                await potto.create_process(
                    _oci_process_create(
                        "oci-process", postgis_contract_harness.owner_user
                    ),
                    user=postgis_contract_harness.owner_user,
                )
        assert (
            await settings.get_process_manager().get_process("oci-process", _SYSTEM)
            is None
        )
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disallowed_image_is_rejected_on_update(
        self, postgis_contract_harness, settings, potto
    ):
        with _capture_events(potto):
            process = await potto.create_process(
                _oci_process_create(
                    "oci-process",
                    postgis_contract_harness.owner_user,
                    image="ghcr.io/acme/tool:1",
                ),
                user=postgis_contract_harness.owner_user,
            )
            with _restrict_registries(settings, ["ghcr.io"]):
                with pytest.raises(ProcessExecutionUnitRejectedError):
                    await potto.update_process(
                        process.identifier,
                        ProcessUpdate(
                            processDescription=ProcessDescriptionUpdate(),
                            execution_unit=ExecutionUnitOciUpdate(
                                image="docker.io/library/alpine:3.20",
                                config=ExecutionUnitOciConfigUpdate(),
                                bindings=OciBindingsUpdate(),
                            ),
                        ),
                        user=postgis_contract_harness.owner_user,
                    )
        current = await settings.get_process_manager().get_process(
            process.identifier, _SYSTEM
        )
        assert current.execution_unit.image == "ghcr.io/acme/tool:1"


class TestUndeployment:
    @pytest.mark.asyncio
    async def test_deletion_event_carries_process_snapshot(
        self, postgis_contract_harness, potto
    ):
        process = postgis_contract_harness.private_process
        with _capture_events(potto) as publish:
            await potto.delete_process(
                process.identifier, user=postgis_contract_harness.owner_user
            )
        (event,), _ = publish.await_args
        assert isinstance(event, InternalProcessDeletionEvent)
        assert event.process.identifier == process.identifier
        assert event.process.created_at == process.created_at

    @pytest.mark.asyncio
    async def test_deleting_a_deployed_process_undeploys_it(
        self, postgis_contract_harness, settings, potto
    ):
        client = FakeDockerClient()
        with _capture_events(potto) as publish:
            process = await potto.create_process(
                _oci_process_create("oci-process", postgis_contract_harness.owner_user),
                user=postgis_contract_harness.owner_user,
            )
            with _use_docker(client):
                await potto.deploy_process(process.identifier, user=_SYSTEM)
            await potto.delete_process(
                process.identifier, user=postgis_contract_harness.owner_user
            )
            (deletion_event,), _ = publish.await_args
            publish.reset_mock()
            with _use_docker(client):
                await process_handlers.internal_handle_process_event(
                    deletion_event, settings
                )
        assert client.images.images == {}
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_event_for_a_missing_process_does_nothing(self, db, settings):
        job_manager = _FakeJobManager(_deployed)
        event = InternalProcessEvent(
            event_type=InternalProcessEventType.UPDATED,
            process_identifier="does-not-exist",
            initiated_by=_SYSTEM,
            timestamp=dt.datetime.now(dt.timezone.utc),
            correlation_id="some-correlation-id",
        )
        with _use_job_manager(settings, job_manager):
            await process_handlers.internal_handle_process_event(event, settings)
        job_manager.deploy.assert_not_awaited()
        job_manager.undeploy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_process_deleted_while_deploying_is_undeployed(
        self, postgis_contract_harness, settings, potto
    ):
        process = postgis_contract_harness.private_process
        process_manager = settings.get_process_manager()

        async def deploy_while_deleted(process):
            await process_manager.delete_process(process.identifier, _SYSTEM)
            return ProcessDeploymentStatus(
                value=_Value.DEPLOYED, deployed_reference="localhost/potto/x:y"
            )

        job_manager = _FakeJobManager(deploy_while_deleted)
        with _use_job_manager(settings, job_manager), _capture_events(potto) as publish:
            await potto.deploy_process(process.identifier, user=_SYSTEM)
        job_manager.undeploy.assert_awaited_once()
        (undeployed,), _ = job_manager.undeploy.await_args
        assert undeployed.identifier == process.identifier
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_undeploy_failures_are_not_raised(self, settings, potto):
        job_manager = _FakeJobManager(_deployed)
        job_manager.undeploy.side_effect = RuntimeError("engine is down")
        snapshot = mock.Mock(identifier="some-process")
        with _use_job_manager(settings, job_manager):
            await potto.undeploy_process(snapshot, user=_SYSTEM)
        job_manager.undeploy.assert_awaited_once_with(snapshot)
