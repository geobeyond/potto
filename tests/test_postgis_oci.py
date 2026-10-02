"""Tests for the deployment of processes whose execution unit is an OCI image."""

import datetime as dt
from unittest import mock

import docker
import docker.errors
import pytest
from fake_docker import (
    FakeDockerClient,
    FakeImageCollection,
    api_error,
)

from potto.exceptions import (
    DeploymentFailedException,
    ProcessExecutionUnitRejectedError,
)
from potto.managers.postgis import oci
from potto.managers.postgis.config import (
    OciDeploymentSettings,
    PostgisManagerConfiguration,
)
from potto.managers.postgis import manager as manager_module
from potto.managers.postgis.manager import (
    PostgisManager,
    get_postgis_manager,
)
from potto.schemas.auth import PottoUser
from potto.schemas.processes import (
    ExecutionUnitCwlCreate,
    ExecutionUnitOciConfigCreate,
    ExecutionUnitOciCreate,
    ExecutionUnitOciConfigUpdate,
    ExecutionUnitOciUpdate,
    ExecutionUnitOtherCreate,
    OciBindingsCreate,
    OciBindingsUpdate,
    Process,
    ProcessDeploymentStatus,
    ProcessDeploymentStatusValue,
    ProcessExecutionUnitOci,
)

_OWNER = PottoUser(id="owner", username="owner", is_active=True, scopes=[])


def _process(
    identifier: str = "some-process",
    image: str = "docker.io/library/alpine:3.20",
    created_at: dt.datetime = dt.datetime(2026, 1, 1, 12, 0, 0),
) -> Process:
    return Process(
        identifier=identifier,
        created_at=created_at,
        updated_at=created_at,
        title="Some process",
        owner=_OWNER,
        is_public=False,
        version="1.0.0",
        deployment_status=ProcessDeploymentStatus(
            value=ProcessDeploymentStatusValue.IN_PROGRESS
        ),
        execution_unit=ProcessExecutionUnitOci(
            image=image, bindings_inputs={}, bindings_outputs={}
        ),
    )


class TestParseImageReference:
    @pytest.mark.parametrize(
        ("image", "registry", "repository", "tag", "digest"),
        [
            (
                "docker.io/library/alpine:3.20",
                "docker.io",
                "docker.io/library/alpine",
                "3.20",
                None,
            ),
            ("ghcr.io/acme/tool:1.0", "ghcr.io", "ghcr.io/acme/tool", "1.0", None),
            ("ghcr.io/acme/tool", "ghcr.io", "ghcr.io/acme/tool", None, None),
            (
                "localhost:5000/x/y@sha256:" + "a" * 64,
                "localhost:5000",
                "localhost:5000/x/y",
                None,
                "sha256:" + "a" * 64,
            ),
            (
                "index.docker.io/acme/tool:2",
                "docker.io",
                "index.docker.io/acme/tool",
                "2",
                None,
            ),
        ],
    )
    def test_fully_qualified_references(self, image, registry, repository, tag, digest):
        reference = oci.parse_image_reference(image)
        assert reference.registry == registry
        assert reference.repository == repository
        assert reference.tag == tag
        assert reference.digest == digest

    def test_missing_tag_means_latest(self):
        assert oci.parse_image_reference("ghcr.io/acme/tool").tag_or_digest == "latest"

    @pytest.mark.parametrize("image", ["alpine", "alpine:3.20", "acme/tool:1.0", " "])
    def test_short_names_are_rejected(self, image):
        with pytest.raises(oci.OciImageReferenceError):
            oci.parse_image_reference(image)


class TestRegistrySettings:
    def test_any_registry_allowed_by_default(self):
        reference = oci.parse_image_reference("quay.io/acme/tool:1")
        oci.ensure_registry_allowed(reference, OciDeploymentSettings())

    def test_empty_allowlist_allows_nothing(self):
        reference = oci.parse_image_reference("quay.io/acme/tool:1")
        with pytest.raises(oci.OciImageReferenceError, match="quay.io"):
            oci.ensure_registry_allowed(
                reference, OciDeploymentSettings(allowed_registries=[])
            )

    def test_docker_hub_aliases_are_normalized(self):
        settings = OciDeploymentSettings(allowed_registries=["Index.Docker.IO"])
        assert settings.allowed_registries == ["docker.io"]
        oci.ensure_registry_allowed(
            oci.parse_image_reference("docker.io/library/alpine:3.20"), settings
        )

    def test_settings_accept_json_strings(self):
        # as is the case when they come from environment variables or secret files
        settings = OciDeploymentSettings.model_validate(
            {
                "allowed_registries": '["ghcr.io"]',
                "registry_credentials": (
                    '[{"registry": "ghcr.io", "username": "bot", "password": "s3cret"}]'
                ),
            }
        )
        assert settings.allowed_registries == ["ghcr.io"]
        assert settings.registry_credentials[0].username == "bot"

    def test_credentials_are_looked_up_by_registry(self):
        settings = OciDeploymentSettings.model_validate(
            {
                "registry_credentials": [
                    {"registry": "ghcr.io", "username": "bot", "password": "s3cret"}
                ]
            }
        )
        assert oci.get_auth_config(
            oci.parse_image_reference("ghcr.io/acme/tool:1"), settings
        ) == {"username": "bot", "password": "s3cret"}
        assert (
            oci.get_auth_config(
                oci.parse_image_reference("quay.io/acme/tool:1"), settings
            )
            is None
        )

    def test_passwords_do_not_leak(self):
        settings = OciDeploymentSettings.model_validate(
            {
                "registry_credentials": [
                    {"registry": "ghcr.io", "username": "bot", "password": "s3cret"}
                ]
            }
        )
        assert "s3cret" not in repr(settings)
        assert "s3cret" not in settings.model_dump_json()


class TestProcessRepository:
    def test_same_for_aware_and_naive_timestamps(self):
        naive = _process(created_at=dt.datetime(2026, 1, 1, 12, 0, 0))
        aware = _process(
            created_at=dt.datetime(
                2026, 1, 1, 13, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=1))
            )
        )
        assert oci.process_repository(naive) == oci.process_repository(aware)

    def test_differs_for_recreated_process(self):
        first = _process(created_at=dt.datetime(2026, 1, 1))
        recreated = _process(created_at=dt.datetime(2026, 1, 2))
        assert oci.process_repository(first) != oci.process_repository(recreated)
        assert oci.process_repository(first).startswith(oci.POTTO_REPOSITORY_PREFIX)


class TestPullAndTag:
    @pytest.mark.parametrize("digest_format", ["docker", "podman"])
    def test_pulls_and_tags(self, digest_format):
        client = FakeDockerClient(FakeImageCollection(digest_format=digest_format))
        reference = oci.parse_image_reference("docker.io/library/alpine:3.20")
        deployed = oci.pull_and_tag(
            client, reference, None, "localhost/potto/process-abc", "hash"
        )
        assert deployed.local_reference.startswith("localhost/potto/process-abc:hash-")
        assert deployed.local_reference in client.image_names()
        assert deployed.upstream_digest is not None
        assert deployed.upstream_digest.startswith("docker.io/library/alpine@sha256:")

    def test_passes_credentials(self):
        client = FakeDockerClient()
        oci.pull_and_tag(
            client,
            oci.parse_image_reference("ghcr.io/acme/tool:1"),
            {"username": "bot", "password": "s3cret"},
            "localhost/potto/process-abc",
            None,
        )
        assert client.images.pulls[0]["auth_config"] == {
            "username": "bot",
            "password": "s3cret",
        }

    def test_pulls_again_if_image_vanishes_before_tagging(self):
        vanished = []

        def delete_first_time(image):
            if not vanished:
                vanished.append(image.id)
                del image.collection.images[image.id]

        client = FakeDockerClient(FakeImageCollection(on_pull=delete_first_time))
        deployed = oci.pull_and_tag(
            client,
            oci.parse_image_reference("ghcr.io/acme/tool:1"),
            None,
            "localhost/potto/process-abc",
            None,
        )
        assert len(client.images.pulls) == 2
        assert deployed.local_reference in client.image_names()

    @pytest.mark.parametrize(
        "error",
        [
            api_error(401, "pull access denied"),
            api_error(404, "manifest unknown", docker.errors.ImageNotFound),
            docker.errors.DockerException("connection refused"),
        ],
    )
    def test_engine_errors_fail_the_deployment(self, error):
        client = FakeDockerClient(FakeImageCollection(pull_error=error))
        with pytest.raises(DeploymentFailedException) as excinfo:
            oci.pull_and_tag(
                client,
                oci.parse_image_reference("ghcr.io/acme/tool:1"),
                {"username": "bot", "password": "s3cret"},
                "localhost/potto/process-abc",
                None,
            )
        assert "ghcr.io/acme/tool" in str(excinfo.value)
        assert "s3cret" not in str(excinfo.value)


class TestReleaseTags:
    def _deploy(self, client, repository, image="docker.io/library/alpine:3.20"):
        return oci.pull_and_tag(
            client, oci.parse_image_reference(image), None, repository, None
        )

    def test_image_still_tagged_by_another_process_is_kept(self):
        client = FakeDockerClient()
        first = self._deploy(client, "localhost/potto/process-first")
        second = self._deploy(client, "localhost/potto/process-second")
        released = oci.release_tags(client, "localhost/potto/process-first")
        assert released == [first.local_reference]
        assert client.image_names() == {"alpine:3.20", second.local_reference}

    def test_image_without_potto_tags_is_deleted(self):
        client = FakeDockerClient()
        deployed = self._deploy(client, "localhost/potto/process-first")
        released = oci.release_tags(client, "localhost/potto/process-first")
        assert released == [deployed.local_reference, "alpine:3.20"]
        assert client.images.images == {}

    def test_image_pulled_by_digest_is_deleted(self):
        client = FakeDockerClient()
        self._deploy(
            client,
            "localhost/potto/process-first",
            image="ghcr.io/acme/tool@sha256:" + "b" * 64,
        )
        oci.release_tags(client, "localhost/potto/process-first")
        assert client.images.images == {}

    def test_image_in_use_is_left_in_place(self):
        client = FakeDockerClient()
        self._deploy(client, "localhost/potto/process-first")
        for image in client.images.images.values():
            image.in_use = True
        oci.release_tags(client, "localhost/potto/process-first")
        assert client.image_names() == {"alpine:3.20"}

    def test_keep_is_respected(self):
        client = FakeDockerClient()
        old = self._deploy(client, "localhost/potto/process-first")
        new = self._deploy(client, "localhost/potto/process-first")
        released = oci.release_tags(
            client, "localhost/potto/process-first", keep=new.local_reference
        )
        assert released == [old.local_reference]
        assert new.local_reference in client.image_names()

    def test_releasing_again_is_a_noop(self):
        client = FakeDockerClient()
        self._deploy(client, "localhost/potto/process-first")
        oci.release_tags(client, "localhost/potto/process-first")
        assert oci.release_tags(client, "localhost/potto/process-first") == []


def _manager(**oci_settings) -> PostgisManager:
    return PostgisManager(
        PostgisManagerConfiguration.model_validate({"oci": oci_settings}),
        mock.MagicMock(),
    )


class TestPostgisManager:
    @pytest.mark.asyncio
    async def test_deploy_and_undeploy(self):
        client = FakeDockerClient()
        manager = _manager()
        process = _process()
        with mock.patch.object(docker, "from_env", return_value=client):
            status = await manager.deploy_process(process)
            assert status.value == ProcessDeploymentStatusValue.DEPLOYED
            assert status.deployed_reference in client.image_names()
            assert "docker.io/library/alpine@sha256:" in status.detail
            await manager.undeploy_process(process)
        assert client.images.images == {}
        assert client.closed

    @pytest.mark.asyncio
    async def test_redeploying_releases_earlier_deployment(self):
        client = FakeDockerClient()
        manager = _manager()
        process = _process()
        with mock.patch.object(docker, "from_env", return_value=client):
            first = await manager.deploy_process(process)
            second = await manager.deploy_process(process)
        assert first.deployed_reference not in client.image_names()
        assert second.deployed_reference in client.image_names()

    @pytest.mark.asyncio
    async def test_disallowed_registry_fails_the_deployment(self):
        client = FakeDockerClient()
        manager = _manager(allowed_registries=["ghcr.io"])
        with mock.patch.object(docker, "from_env", return_value=client):
            with pytest.raises(DeploymentFailedException, match="docker.io"):
                await manager.deploy_process(_process())
        assert client.images.pulls == []

    @pytest.mark.asyncio
    async def test_uses_configured_engine_url(self):
        client = FakeDockerClient()
        manager = _manager(docker_base_url="unix:///run/podman.sock")
        with mock.patch.object(docker, "DockerClient", return_value=client) as factory:
            await manager.deploy_process(_process())
        assert factory.call_args.kwargs["base_url"] == "unix:///run/podman.sock"

    @pytest.mark.asyncio
    async def test_undeploying_something_never_deployed_is_a_noop(self):
        client = FakeDockerClient()
        with mock.patch.object(docker, "from_env", return_value=client):
            await _manager().undeploy_process(_process())

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "execution_unit",
        [
            ExecutionUnitOciCreate(
                image="alpine:3.20",
                config=ExecutionUnitOciConfigCreate(),
                bindings=OciBindingsCreate(inputs={}, outputs={}),
            ),
            ExecutionUnitOciCreate(
                image="docker.io/library/alpine:3.20",
                config=ExecutionUnitOciConfigCreate(),
                bindings=OciBindingsCreate(inputs={}, outputs={}),
            ),
            ExecutionUnitOciUpdate(
                image="docker.io/library/alpine:3.20",
                config=ExecutionUnitOciConfigUpdate(),
                bindings=OciBindingsUpdate(),
            ),
        ],
    )
    async def test_rejects_short_or_disallowed_images(self, execution_unit):
        manager = _manager(allowed_registries=["ghcr.io"])
        with pytest.raises(ProcessExecutionUnitRejectedError):
            await manager.validate_execution_unit(execution_unit)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "execution_unit",
        [
            ExecutionUnitOciCreate(
                image="ghcr.io/acme/tool:1",
                config=ExecutionUnitOciConfigCreate(),
                bindings=OciBindingsCreate(inputs={}, outputs={}),
            ),
            ExecutionUnitOciUpdate(
                config=ExecutionUnitOciConfigUpdate(), bindings=OciBindingsUpdate()
            ),
            ExecutionUnitCwlCreate(value={}),
            ExecutionUnitOtherCreate(type_="other", value={}),
        ],
    )
    async def test_accepts_allowed_or_non_oci_execution_units(self, execution_unit):
        manager = _manager(allowed_registries=["ghcr.io"])
        await manager.validate_execution_unit(execution_unit)

    def test_managers_with_different_configurations_are_distinct(self):
        plain_config = PostgisManagerConfiguration().model_dump()
        oci_config = {**plain_config, "oci": {"allowed_registries": ["ghcr.io"]}}
        with mock.patch.dict(manager_module._manager_cache, clear=True):
            plain = get_postgis_manager(plain_config, mock.MagicMock())
            with_oci = get_postgis_manager(oci_config, mock.MagicMock())
            assert plain is not with_oci
            assert with_oci.config.oci.allowed_registries == ["ghcr.io"]
            assert get_postgis_manager(plain_config, mock.MagicMock()) is plain


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_deploy_and_undeploy(settings):
    """Deploy and undeploy against the configured container engine, if there is one.

    Uses the engine configured for the job manager, or docker's defaults. Skipped
    when no engine answers.
    """
    job_manager = settings.get_job_manager()
    engine = job_manager.config.oci
    try:
        client = (
            docker.DockerClient(base_url=engine.docker_base_url, timeout=10)
            if engine.docker_base_url
            else docker.from_env(timeout=10)
        )
        client.ping()
    except docker.errors.DockerException:
        pytest.skip("no container engine available")
    # undeploying deletes the image, including any other name it has in the
    # engine's store, so this uses an image that is unlikely to be there already
    image = "docker.io/traefik/whoami:v1.10"
    first = _process(identifier="live-first", image=image)
    second = _process(identifier="live-second", image=image)
    try:
        first_status = await job_manager.deploy_process(first)
        second_status = await job_manager.deploy_process(second)
        await job_manager.undeploy_process(first)
        names = {tag for i in client.images.list() for tag in i.tags}
        assert first_status.deployed_reference not in names
        assert second_status.deployed_reference in names
        await job_manager.undeploy_process(second)
        names = {tag for i in client.images.list() for tag in i.tags}
        assert second_status.deployed_reference not in names
        assert "traefik/whoami:v1.10" not in {
            n.removeprefix("docker.io/") for n in names
        }
    finally:
        await job_manager.undeploy_process(first)
        await job_manager.undeploy_process(second)
        client.close()
