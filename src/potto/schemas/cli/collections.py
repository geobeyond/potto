import datetime as dt

import pydantic

from ...constants import CollectionType
from ...db.models import (
    Collection,
    User,
)
from .. import base


class SimplifiedFeatureCollectionCreate(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    resource_identifier: base.CollectionIdentifier
    english_title: str
    provider: base.PottoProvider
    spatial_extent: base.MaybeShapelyGeometry = None
    is_public: bool = False


class CollectionListItem(pydantic.BaseModel):
    resource_identifier: str
    collection_type: CollectionType
    owner: str
    is_public: bool

    @classmethod
    def from_db_item(cls, item: Collection) -> "CollectionListItem":
        return cls(
            **item.model_dump(),
            owner=item.owner.username,
        )


class CollectionDetail(CollectionListItem):
    title: str | dict[str, str]
    editors: list[str] = []
    viewers: list[str] = []
    created_at: dt.datetime
    updated_at: dt.datetime | None
    spatial_extent: str | None

    @classmethod
    def from_db_item(
        cls,
        item: Collection,
        editors: list[User] | None = None,
        viewers: list[User] | None = None,
    ) -> "CollectionDetail":
        return cls(
            **item.model_dump(exclude={"spatial_extent"}),
            owner=item.owner.username,
            editors=[u.username for u in (editors or [])],
            viewers=[v.username for v in (viewers or [])],
            spatial_extent=str(item.spatial_extent) if item.spatial_extent else None,
        )
