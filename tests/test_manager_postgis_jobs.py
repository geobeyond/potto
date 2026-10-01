"""Tests for the postgis manager's implementation of ``JobManagerProtocol``.

These are not part of the manager contract suite (``tests/test_manager_contract.py``)
because the configuration file manager is not a job manager.
"""

import asyncio
import dataclasses
import datetime as dt
from unittest import mock

import pydantic
import pytest
import pytest_asyncio

from potto.eventhandlers import jobs as job_handlers
from potto.exceptions import (
    CannotCreateResourceError,
    CannotDeleteResourceError,
    CannotUpdateResourceError,
)
from potto.pubsub.audience import resolve_job_audience
from potto.schemas.auth import (
    PottoScope,
    SystemPrincipal,
    UserUpdate,
)
from potto.schemas.events import (
    AnyInternalJobEvent,
    InternalJobDeletionEvent,
    InternalJobEvent,
    InternalJobEventType,
    ResourceAudience,
)
from potto.schemas.jobs import (
    JobCreate,
    JobFilter,
    JobStatus,
)
from potto.schemas.processes import ProcessDeploymentStatusValue
from potto.wrapper import Potto

pytestmark = pytest.mark.integration

_SYSTEM = SystemPrincipal("test-system")


@dataclasses.dataclass
class JobsHarness:
    harness: object
    manager: object

    def __getattr__(self, name):
        return getattr(self.harness, name)


@pytest_asyncio.fixture
async def jobs_harness(postgis_contract_harness, settings) -> JobsHarness:
    process_manager = settings.get_process_manager()
    for process in (
        postgis_contract_harness.public_process,
        postgis_contract_harness.private_process,
    ):
        await process_manager.set_process_deployment_status(
            process, ProcessDeploymentStatusValue.DEPLOYED, _SYSTEM
        )
    return JobsHarness(
        harness=postgis_contract_harness, manager=settings.get_job_manager()
    )


async def _create_private_job(h: JobsHarness, user=None):
    return await h.manager.create_job(
        h.private_process.identifier, JobCreate(), user or h.viewer_user
    )


class TestJobCreation:
    @pytest.mark.asyncio
    async def test_anonymous_job_on_public_process_is_public_and_owned_by_process_owner(
        self, jobs_harness
    ):
        job = await jobs_harness.manager.create_job(
            jobs_harness.public_process.identifier,
            JobCreate(inputs={"a": 1}),
            None,
        )
        assert job.status == JobStatus.ACCEPTED
        assert job.is_public
        assert job.owner.id == jobs_harness.owner_user.id
        assert job.inputs == {"a": 1}

    @pytest.mark.asyncio
    async def test_anonymous_cannot_create_job_on_private_process(self, jobs_harness):
        with pytest.raises(CannotCreateResourceError):
            await jobs_harness.manager.create_job(
                jobs_harness.private_process.identifier, JobCreate(), None
            )

    @pytest.mark.asyncio
    async def test_unrelated_user_cannot_create_job_on_private_process(
        self, jobs_harness
    ):
        with pytest.raises(CannotCreateResourceError):
            await _create_private_job(jobs_harness, jobs_harness.other_user)

    @pytest.mark.asyncio
    async def test_process_viewer_creates_private_job_and_owns_it(self, jobs_harness):
        job = await _create_private_job(jobs_harness)
        assert not job.is_public
        assert job.owner.id == jobs_harness.viewer_user.id

    @pytest.mark.asyncio
    async def test_cannot_create_job_on_undeployed_process(
        self, jobs_harness, settings
    ):
        await settings.get_process_manager().set_process_deployment_status(
            jobs_harness.private_process, ProcessDeploymentStatusValue.FAILED, _SYSTEM
        )
        with pytest.raises(CannotCreateResourceError):
            await _create_private_job(jobs_harness)

    @pytest.mark.asyncio
    async def test_execute_request_is_persisted(self, jobs_harness):
        job = await jobs_harness.manager.create_job(
            jobs_harness.private_process.identifier,
            JobCreate.model_validate(
                {
                    "outputs": {"result": {"transmissionMode": "reference"}},
                    "response": "document",
                    "subscriber": {"successUri": "http://example.com/done"},
                }
            ),
            jobs_harness.owner_user,
        )
        assert job.outputs["result"].transmission_mode == "reference"
        assert job.response_type == "document"
        assert job.callback_uris.success_uri == "http://example.com/done"


class TestJobVisibility:
    @pytest.mark.asyncio
    async def test_private_job_visible_through_inherited_and_own_grants(
        self, jobs_harness
    ):
        job = await _create_private_job(jobs_harness)
        for user in (
            jobs_harness.viewer_user,
            jobs_harness.editor_user,
            jobs_harness.owner_user,
            jobs_harness.admin_user,
        ):
            assert await jobs_harness.manager.get_job(job.identifier, user) is not None
        for user in (None, jobs_harness.other_user):
            assert await jobs_harness.manager.get_job(job.identifier, user) is None

    @pytest.mark.asyncio
    async def test_listing_includes_inherited_jobs(self, jobs_harness):
        private_job = await _create_private_job(jobs_harness)
        public_job = await jobs_harness.manager.create_job(
            jobs_harness.public_process.identifier, JobCreate(), None
        )

        async def listed_ids(user):
            jobs, total = await jobs_harness.manager.paginated_list_jobs(
                user, include_total=True
            )
            assert total == len(jobs)
            return {j.identifier for j in jobs}

        both = {private_job.identifier, public_job.identifier}
        assert await listed_ids(jobs_harness.editor_user) == both
        assert await listed_ids(jobs_harness.owner_user) == both
        assert await listed_ids(jobs_harness.admin_user) == both
        assert await listed_ids(_SYSTEM) == both
        assert await listed_ids(jobs_harness.other_user) == {public_job.identifier}
        assert await listed_ids(None) == {public_job.identifier}

    @pytest.mark.asyncio
    async def test_listing_filters_by_identifier(self, jobs_harness):
        first = await _create_private_job(jobs_harness)
        await _create_private_job(jobs_harness)
        jobs, _ = await jobs_harness.manager.paginated_list_jobs(
            jobs_harness.viewer_user,
            filter_=JobFilter(identifiers=[first.identifier]),
        )
        assert [j.identifier for j in jobs] == [first.identifier]


class TestJobDeletion:
    @pytest.mark.asyncio
    async def test_process_viewer_cannot_delete_job_they_do_not_own(self, jobs_harness):
        job = await _create_private_job(jobs_harness, jobs_harness.editor_user)
        with pytest.raises(CannotDeleteResourceError):
            await jobs_harness.manager.delete_job(
                job.identifier, jobs_harness.viewer_user
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("deleter", ["viewer_user", "editor_user", "owner_user"])
    async def test_job_owner_and_process_editors_can_delete(
        self, jobs_harness, deleter
    ):
        job = await _create_private_job(jobs_harness)
        await jobs_harness.manager.delete_job(
            job.identifier, getattr(jobs_harness, deleter)
        )
        assert await jobs_harness.manager.get_job(job.identifier, _SYSTEM) is None


class TestJobStatus:
    @pytest.mark.asyncio
    async def test_users_cannot_set_job_status(self, jobs_harness):
        job = await _create_private_job(jobs_harness)
        with pytest.raises(CannotUpdateResourceError):
            await jobs_harness.manager.set_job_status(
                job.identifier, JobStatus.SUCCESSFUL, jobs_harness.viewer_user
            )

    @pytest.mark.asyncio
    async def test_status_transitions_set_timestamps(self, jobs_harness):
        job = await _create_private_job(jobs_harness)
        running = await jobs_harness.manager.set_job_status(
            job.identifier, JobStatus.RUNNING, _SYSTEM, progress=150
        )
        assert running.status == JobStatus.RUNNING
        assert running.started_at is not None
        assert running.finished_at is None
        assert running.progress == 100
        finished = await jobs_harness.manager.set_job_status(
            job.identifier, JobStatus.SUCCESSFUL, _SYSTEM, message="done"
        )
        assert finished.status == JobStatus.SUCCESSFUL
        assert finished.finished_at is not None
        assert finished.message == "done"


class TestJobExecution:
    @pytest.mark.asyncio
    async def test_execution_failure_marks_job_as_failed(self, jobs_harness):
        job = await _create_private_job(jobs_harness)
        executed = await jobs_harness.manager.execute_job(job.identifier, _SYSTEM)
        # the harness processes have an execution unit which is not supported
        assert executed.status == JobStatus.FAILED
        assert executed.started_at is not None
        assert executed.finished_at is not None
        assert executed.message
        assert executed.exception is not None

    @pytest.mark.asyncio
    async def test_successful_execution(self, jobs_harness):
        job = await _create_private_job(jobs_harness)
        with mock.patch.object(type(jobs_harness.manager), "_run_job") as run_job:
            executed = await jobs_harness.manager.execute_job(job.identifier, _SYSTEM)
        run_job.assert_awaited_once()
        assert executed.status == JobStatus.SUCCESSFUL

    @pytest.mark.asyncio
    async def test_repeated_execution_is_a_noop(self, jobs_harness):
        job = await _create_private_job(jobs_harness)
        first = await jobs_harness.manager.execute_job(job.identifier, _SYSTEM)
        with mock.patch.object(type(jobs_harness.manager), "_run_job") as run_job:
            second = await jobs_harness.manager.execute_job(job.identifier, _SYSTEM)
        run_job.assert_not_awaited()
        assert second.status == first.status
        assert second.finished_at == first.finished_at

    @pytest.mark.asyncio
    async def test_concurrent_executions_run_the_job_only_once(self, jobs_harness):
        job = await _create_private_job(jobs_harness)

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(0.2)

        with mock.patch.object(
            type(jobs_harness.manager), "_run_job", side_effect=slow_run
        ) as run_job:
            results = await asyncio.gather(
                *(
                    jobs_harness.manager.execute_job(job.identifier, _SYSTEM)
                    for _ in range(5)
                )
            )
        assert run_job.await_count == 1
        final = await jobs_harness.manager.get_job(job.identifier, _SYSTEM)
        assert final.status == JobStatus.SUCCESSFUL
        assert {r.status for r in results} <= {JobStatus.RUNNING, JobStatus.SUCCESSFUL}

    @pytest.mark.asyncio
    async def test_job_dismissed_while_running_keeps_its_status(self, jobs_harness):
        job = await _create_private_job(jobs_harness)

        async def dismiss_during_run(*args, **kwargs):
            await jobs_harness.manager.set_job_status(
                job.identifier, JobStatus.DISMISSED, _SYSTEM, message="dismissed"
            )

        with mock.patch.object(
            type(jobs_harness.manager), "_run_job", side_effect=dismiss_during_run
        ):
            executed = await jobs_harness.manager.execute_job(job.identifier, _SYSTEM)
        assert executed.status == JobStatus.DISMISSED
        assert executed.message == "dismissed"
        assert executed.progress is None

    @pytest.mark.asyncio
    async def test_users_cannot_execute_jobs(self, jobs_harness):
        job = await _create_private_job(jobs_harness)
        with pytest.raises(CannotUpdateResourceError):
            await jobs_harness.manager.execute_job(
                job.identifier, jobs_harness.owner_user
            )


@pytest.mark.asyncio
async def test_job_created_handler_executes_job(settings):
    event = InternalJobEvent(
        job_identifier="some-job",
        event_type=InternalJobEventType.CREATED,
        initiated_by=None,
        timestamp=dt.datetime.now(dt.timezone.utc),
        correlation_id="some-correlation-id",
    )
    with mock.patch.object(job_handlers, "Potto") as potto_class:
        potto_class.return_value.execute_job = mock.AsyncMock()
        await job_handlers.internal_handle_job_created(event, settings)
    potto_class.return_value.execute_job.assert_awaited_once_with(
        "some-job",
        user=job_handlers._EXECUTOR_PRINCIPAL,
        correlation_id="some-correlation-id",
    )


class TestJobAudience:
    @pytest.mark.asyncio
    async def test_public_job_has_no_audience(self, jobs_harness, settings):
        job = await jobs_harness.manager.create_job(
            jobs_harness.public_process.identifier, JobCreate(), None
        )
        assert await resolve_job_audience(job, settings) == ResourceAudience(
            is_public=False, user_ids=[]
        )

    @pytest.mark.asyncio
    async def test_private_job_audience_includes_own_and_inherited_grants(
        self, jobs_harness, settings
    ):
        job = await _create_private_job(jobs_harness)
        await settings.get_user_account_manager().update_user(
            jobs_harness.other_user.id,
            UserUpdate(scopes=[PottoScope.job_viewer(job.identifier)]),
            jobs_harness.admin_user,
        )
        audience = await resolve_job_audience(job, settings)
        assert not audience.is_public
        assert set(audience.user_ids) == {
            jobs_harness.viewer_user.id,  # job owner, and process viewer
            jobs_harness.owner_user.id,  # process owner
            jobs_harness.editor_user.id,  # process editor
            jobs_harness.other_user.id,  # job viewer
        }

    @pytest.mark.asyncio
    async def test_deleting_a_job_publishes_its_audience(self, jobs_harness, settings):
        job = await _create_private_job(jobs_harness)
        expected_audience = await resolve_job_audience(job, settings)
        potto = Potto(settings)
        with mock.patch.object(potto, "publish_internal_job_event") as publish:
            await potto.delete_job(
                job.identifier,
                user=jobs_harness.viewer_user,
                correlation_id="some-correlation-id",
            )
        assert await jobs_harness.manager.get_job(job.identifier, _SYSTEM) is None
        (event,), _ = publish.await_args
        assert isinstance(event, InternalJobDeletionEvent)
        assert event.job_identifier == job.identifier
        assert event.audience == expected_audience
        assert event.correlation_id == "some-correlation-id"


def test_job_deletion_event_requires_an_audience():
    adapter = pydantic.TypeAdapter(AnyInternalJobEvent)
    raw = {
        "job_identifier": "some-job",
        "event_type": "deleted",
        "initiated_by": None,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "correlation_id": "some-correlation-id",
    }
    with pytest.raises(pydantic.ValidationError):
        adapter.validate_python(raw)
    parsed = adapter.validate_python({**raw, "audience": {"is_public": False}})
    assert isinstance(parsed, InternalJobDeletionEvent)
    created = adapter.validate_python({**raw, "event_type": "created"})
    assert isinstance(created, InternalJobEvent)
