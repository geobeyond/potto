"""An in-memory stand-in for the parts of the docker SDK's client that potto uses.

It models the image store semantics that potto's OCI deployment relies on, as
implemented by both Docker and podman:

- removing a name only untags the image, unless it is the image's last name, in
  which case the image is deleted;
- an image that a container uses cannot be deleted without forcing it;
- an image that has more than one name cannot be removed by id without forcing it.
"""

import dataclasses
import hashlib
from typing import Any

import docker.errors
import requests


def api_error(
    status_code: int, explanation: str, error_class=docker.errors.APIError
) -> docker.errors.APIError:
    response = requests.Response()
    response.status_code = status_code
    return error_class(explanation, response=response, explanation=explanation)


@dataclasses.dataclass
class FakeImage:
    collection: "FakeImageCollection"
    id: str
    repo_tags: list[str] = dataclasses.field(default_factory=list)
    repo_digests: list[str] = dataclasses.field(default_factory=list)
    in_use: bool = False

    @property
    def tags(self) -> list[str]:
        return list(self.repo_tags)

    @property
    def attrs(self) -> dict[str, Any]:
        return {"Id": self.id, "RepoTags": self.tags, "RepoDigests": self.repo_digests}

    def tag(self, repository: str, tag: str | None = None, **kwargs) -> bool:
        if self.id not in self.collection.images:
            raise api_error(
                404, f"no such image: {self.id}", docker.errors.ImageNotFound
            )
        self.repo_tags.append(f"{repository}:{tag or 'latest'}")
        return True


class FakeImageCollection:
    def __init__(
        self,
        *,
        digest_format: str = "docker",
        pull_error: Exception | None = None,
        on_pull=None,
    ) -> None:
        self.images: dict[str, FakeImage] = {}
        self.digest_format = digest_format
        self.pull_error = pull_error
        self.on_pull = on_pull
        self.pulls: list[dict[str, Any]] = []

    def pull(self, repository: str, tag: str | None = None, auth_config=None, **kwargs):
        self.pulls.append(
            {"repository": repository, "tag": tag, "auth_config": auth_config}
        )
        if self.pull_error is not None:
            raise self.pull_error
        is_digest = tag is not None and tag.startswith("sha256:")
        digest = (
            tag
            if is_digest
            else "sha256:" + hashlib.sha256(f"{repository}:{tag}".encode()).hexdigest()
        )
        image_id = "sha256:" + hashlib.sha256(digest.encode()).hexdigest()
        image = self.images.get(image_id)
        if image is None:
            image = FakeImage(collection=self, id=image_id)
            self.images[image_id] = image
        name = repository
        if self.digest_format == "docker" and name.startswith("docker.io/library/"):
            name = name.removeprefix("docker.io/library/")
        if f"{name}@{digest}" not in image.repo_digests:
            image.repo_digests.append(f"{name}@{digest}")
        if not is_digest and f"{name}:{tag}" not in image.repo_tags:
            image.repo_tags.append(f"{name}:{tag}")
        if self.on_pull is not None:
            self.on_pull(image)
        return image

    def list(self, name: str | None = None, **kwargs) -> list[FakeImage]:
        if name is None:
            return list(self.images.values())
        return [
            image
            for image in self.images.values()
            if any(tag.rsplit(":", 1)[0] == name for tag in image.repo_tags)
        ]

    def get(self, name: str) -> FakeImage:
        if name in self.images:
            return self.images[name]
        for image in self.images.values():
            if name in image.repo_tags:
                return image
        raise api_error(404, f"no such image: {name}", docker.errors.ImageNotFound)

    def remove(self, image: str, force: bool = False, noprune: bool = False) -> None:
        if image in self.images:
            found = self.images[image]
            if len(found.repo_tags) > 1 and not force:
                raise api_error(409, "image is referenced in multiple repositories")
            if found.in_use and not force:
                raise api_error(409, "image is being used by a container")
            del self.images[image]
            return
        found = self.get(image)
        if len(found.repo_tags) == 1 and found.in_use and not force:
            raise api_error(409, "image is being used by a container")
        found.repo_tags.remove(image)
        if not found.repo_tags:
            del self.images[found.id]


class FakeDockerClient:
    def __init__(self, images: FakeImageCollection | None = None) -> None:
        self.images = images or FakeImageCollection()
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def image_names(self) -> set[str]:
        return {tag for image in self.images.images.values() for tag in image.repo_tags}
