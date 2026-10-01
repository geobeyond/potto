"""Deployment of processes whose execution unit is an OCI image.

Deploying a process pulls its image and gives it a tag of its own, under a
repository that is specific to the process. Undeploying releases those tags, and
deletes the image once no potto process uses it anymore. This lets the engine keep
track of which images are still needed, even when several processes use the same
one.

The functions in this module are synchronous, since the docker SDK is - callers
are expected to run them in a thread.

This works with any engine that offers a Docker-compatible API, e.g. Docker
itself or podman.
"""

import dataclasses
import datetime as dt
import hashlib
import logging
import uuid
from typing import (
    TYPE_CHECKING,
    Any,
)

import docker.errors
from docker.auth import resolve_repository_name
from docker.utils import parse_repository_tag

from ...exceptions import DeploymentFailedException

if TYPE_CHECKING:
    from docker import DockerClient
    from docker.models.images import Image

    from ...schemas.processes import Process
    from .config import OciDeploymentSettings

logger = logging.getLogger(__name__)

DOCKER_HUB_REGISTRY = "docker.io"
POTTO_REPOSITORY_PREFIX = "localhost/potto/process-"
_DOCKER_HUB_ALIASES = {"index.docker.io", "registry-1.docker.io", DOCKER_HUB_REGISTRY}


class OciImageReferenceError(ValueError):
    """An image reference is malformed or not allowed."""


@dataclasses.dataclass(frozen=True)
class OciImageReference:
    registry: str
    repository: str  # as given, including the registry, e.g. "ghcr.io/acme/tool"
    tag: str | None = None
    digest: str | None = None

    @property
    def tag_or_digest(self) -> str:
        return self.digest or self.tag or "latest"


@dataclasses.dataclass(frozen=True)
class DeployedImage:
    local_reference: str
    upstream_digest: str | None


def normalize_registry(registry: str) -> str:
    normalized = registry.strip().lower()
    return DOCKER_HUB_REGISTRY if normalized in _DOCKER_HUB_ALIASES else normalized


def parse_image_reference(image: str) -> OciImageReference:
    """Parse a fully qualified image reference.

    References must name their registry explicitly (e.g.
    ``docker.io/library/alpine:3.20`` rather than ``alpine:3.20``), since engines
    differ in how they resolve short names.
    """
    reference = image.strip()
    if not reference:
        raise OciImageReferenceError("image reference is empty")
    repository, tag_or_digest = parse_repository_tag(reference)
    first_component = repository.split("/", 1)[0]
    is_qualified = "/" in repository and (
        "." in first_component
        or ":" in first_component
        or first_component == "localhost"
    )
    if not is_qualified:
        raise OciImageReferenceError(
            f"image reference {image!r} must be fully qualified, including its "
            f"registry (e.g. docker.io/library/alpine:3.20)"
        )
    registry, _ = resolve_repository_name(repository)
    is_digest = tag_or_digest is not None and tag_or_digest.startswith("sha256:")
    return OciImageReference(
        registry=normalize_registry(registry),
        repository=repository,
        tag=None if is_digest else tag_or_digest,
        digest=tag_or_digest if is_digest else None,
    )


def ensure_registry_allowed(
    reference: OciImageReference, settings: "OciDeploymentSettings"
) -> None:
    allowed = settings.allowed_registries
    if allowed is not None and reference.registry not in allowed:
        raise OciImageReferenceError(
            f"images from registry {reference.registry!r} are not allowed"
        )


def get_auth_config(
    reference: OciImageReference, settings: "OciDeploymentSettings"
) -> dict[str, str] | None:
    for credential in settings.registry_credentials:
        if credential.registry == reference.registry:
            return {
                "username": credential.username,
                "password": credential.password.get_secret_value(),
            }
    return None


def process_repository(process: "Process") -> str:
    """Return the local repository that holds the tags of a process.

    The repository depends on both the identifier and the creation date of the
    process, so that a process which gets deleted and then created again with the
    same identifier does not share tags with its predecessor.
    """
    created_at = process.created_at
    if created_at.tzinfo is not None:
        created_at = created_at.astimezone(dt.timezone.utc).replace(tzinfo=None)
    key = hashlib.sha256(
        f"{process.identifier}\n{created_at.isoformat()}".encode()
    ).hexdigest()[:16]
    return f"{POTTO_REPOSITORY_PREFIX}{key}"


def pull_and_tag(
    client: "DockerClient",
    reference: OciImageReference,
    auth_config: dict[str, str] | None,
    repository: str,
    definition_hash: str | None,
) -> DeployedImage:
    """Pull an image and tag it in the process's local repository."""
    tag = f"{(definition_hash or 'nohash')[:12]}-{uuid.uuid4().hex[:8]}"
    for attempt in range(2):
        image = _pull(client, reference, auth_config)
        try:
            image.tag(repository, tag=tag)
        except docker.errors.ImageNotFound:
            # the image was deleted between pulling and tagging it - e.g. by the
            # concurrent undeployment of the last other process that used it
            if attempt == 0:
                logger.info(f"image {reference.repository!r} vanished, pulling again")
                continue
            raise DeploymentFailedException(
                f"image {reference.repository!r} vanished right after being pulled"
            )
        except docker.errors.APIError as err:
            raise _engine_error(f"could not tag image {reference.repository!r}", err)
        return DeployedImage(
            local_reference=f"{repository}:{tag}",
            upstream_digest=_find_repo_digest(image, reference),
        )
    raise AssertionError("unreachable")


def release_tags(
    client: "DockerClient", repository: str, keep: str | None = None
) -> list[str]:
    """Remove the tags of a process's local repository, except for ``keep``.

    Images that are no longer tagged by any potto process are then deleted
    altogether, including their upstream names. Images that are still in use by a
    container are left in place.

    Returns the references that were removed. Releasing is idempotent.
    """
    released: list[str] = []
    try:
        images = client.images.list(name=repository)
    except docker.errors.APIError as err:
        raise _engine_error(f"could not list images of {repository!r}", err)
    for image in images:
        own_tags = [
            tag
            for tag in image.tags
            if parse_repository_tag(tag)[0] == repository and tag != keep
        ]
        if not own_tags:
            continue
        for tag in own_tags:
            if _remove(client, tag):
                released.append(tag)
        released.extend(_remove_if_unused(client, image.id))
    return released


def _pull(
    client: "DockerClient",
    reference: OciImageReference,
    auth_config: dict[str, str] | None,
) -> "Image":
    try:
        return client.images.pull(
            reference.repository,
            tag=reference.tag_or_digest,
            auth_config=auth_config,
        )
    except docker.errors.ImageNotFound as err:
        raise _engine_error(f"image {reference.repository!r} not found", err)
    except docker.errors.APIError as err:
        raise _engine_error(f"could not pull image {reference.repository!r}", err)
    except docker.errors.DockerException as err:
        raise DeploymentFailedException(
            f"could not pull image {reference.repository!r}: {err}"
        ) from err


def _remove_if_unused(client: "DockerClient", image_id: str) -> list[str]:
    """Delete an image if no potto process tags it anymore."""
    try:
        image = client.images.get(image_id)
    except docker.errors.ImageNotFound:
        return []
    except docker.errors.APIError as err:
        raise _engine_error(f"could not inspect image {image_id!r}", err)
    if any(tag.startswith(POTTO_REPOSITORY_PREFIX) for tag in image.tags):
        return []
    # removing the remaining names one by one, rather than the image by id, since
    # an image that has more than one name cannot be removed by id without forcing
    # it, and forcing would also remove images used by (stopped) containers
    removed: list[str] = []
    for tag in image.tags:
        if not _remove(client, tag):
            return removed
        removed.append(tag)
    try:
        client.images.get(image_id)
    except docker.errors.ImageNotFound:
        return removed
    except docker.errors.APIError as err:
        raise _engine_error(f"could not inspect image {image_id!r}", err)
    # an image that was pulled by digest has no names left, only its id
    if _remove(client, image_id):
        removed.append(image_id)
    return removed


def _remove(client: "DockerClient", reference: str) -> bool:
    """Remove an image reference, without forcing it.

    Returns whether the reference was removed.
    """
    try:
        client.images.remove(reference)
    except docker.errors.ImageNotFound:
        return False
    except docker.errors.APIError as err:
        if err.status_code == 409:
            logger.warning(
                f"not removing {reference!r}, as it is still in use: {err.explanation}"
            )
            return False
        raise _engine_error(f"could not remove {reference!r}", err)
    return True


def _find_repo_digest(image: "Image", reference: OciImageReference) -> str | None:
    if reference.digest is not None:
        return f"{reference.repository}@{reference.digest}"
    wanted = _canonical_repository(reference.repository)
    for repo_digest in (image.attrs or {}).get("RepoDigests") or []:
        name, _, digest = repo_digest.partition("@")
        if _canonical_repository(name) == wanted:
            return f"{reference.repository}@{digest}"
    return None


def _canonical_repository(repository: str) -> tuple[str, str]:
    """Normalize a repository name, so that the forms used by engines compare equal.

    For example, Docker reports ``alpine`` where podman reports
    ``docker.io/library/alpine``.
    """
    registry, name = resolve_repository_name(repository)
    registry = normalize_registry(registry)
    if registry == DOCKER_HUB_REGISTRY and "/" not in name:
        name = f"library/{name}"
    return registry, name


def _engine_error(message: str, err: Any) -> DeploymentFailedException:
    explanation = getattr(err, "explanation", None) or str(err)
    return DeploymentFailedException(f"{message}: {explanation}")
