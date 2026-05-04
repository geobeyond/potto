import datetime as dt
import logging
import uuid
from functools import partial
from typing import Any

import pydantic
import shapely
import sqlalchemy
import geoalchemy2
from jinja2 import Template
from geoalchemy2.shape import to_shape
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import (
    Column,
    DateTime,
    Field,
    Relationship,
    SQLModel,
    func,
)
from starlette.requests import Request

from ..schemas.auth import PottoUser
from ..schemas import potto as potto_schemas
from ..schemas import metadata as metadata_schemas
from ..schemas.base import (
    CollectionProvider,
    CollectionType,
    Title,
    MaybeDescription,
    MaybeKeywords,
    MaybeShapelyGeometry,
)

logger = logging.getLogger(__name__)
now_ = partial(dt.datetime.now, tz=dt.timezone.utc)


class ShapelyGeometryAdapter(geoalchemy2.Geometry):
    """Geometry column type that converts to/from shapely objects transparently.

    geoalchemy2's bind_processor passes unrecognised types through as-is,
    causing psycopg3 to fail on raw shapely objects. This subclass intercepts
    both directions: shapely → EWKT string on writes, WKBElement → shapely on reads.
    """

    def bind_processor(self, dialect):
        parent = super().bind_processor(dialect)

        def process(value):
            if isinstance(value, shapely.Geometry):
                return f"SRID={self.srid};{shapely.to_wkt(value)}"
            return parent(value)

        return process

    def result_processor(self, dialect, coltype):
        parent = super().result_processor(dialect, coltype)

        def process(value):
            if parent is not None:
                value = parent(value)
            return to_shape(value) if value is not None else None

        return process


class Collection(SQLModel, table=True):
    __table_args__ = (
        sqlalchemy.Index("idx_collection_title_gin", "title", postgresql_using="gin"),
    )

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    id: int | None = Field(
        default=None,
        primary_key=True,
    )
    resource_identifier: str = Field(
        min_length=3,
        max_length=100,
        index=True,
        unique=True,
    )
    owner_id: str = Field(foreign_key="user.id", ondelete="CASCADE")
    is_public: bool = Field(default=False)
    collection_type: CollectionType
    title: Title = Field(sa_type=JSONB)
    description: MaybeDescription = Field(default=None, sa_type=JSONB, nullable=True)
    keywords: MaybeKeywords = Field(default=None, sa_type=JSONB, nullable=True)
    spatial_extent: MaybeShapelyGeometry = Field(
        default=None,
        sa_type=ShapelyGeometryAdapter,
        nullable=True,
    )
    spatial_extent_crs: str | None = None  # part 1 - CRS of the spatial extent
    crs: list[str] | None = Field(
        sa_type=JSONB, nullable=True
    )  # part 2 - list of supported CRS
    storage_crs: str | None = Field(
        default=None, nullable=True
    )  # part 2 - CRS of the dataset
    storage_crs_coordinate_epoch: float | None = Field(
        default=None, nullable=True
    )  # part 3 - epoch of the dataset CRS
    temporal_extent_begin: dt.datetime | None = None
    temporal_extent_end: dt.datetime | None = None
    # this can be used for configuring additional extents, as mentioned in
    # OAPIF - Part 1
    additional_extents: dict[str, dict[str, str | int | float | None]] | None = Field(
        default=None, sa_type=JSONB, nullable=True
    )
    custom_page_size: int | None = Field(default=None, ge=1)
    custom_page_size_max: int | None = Field(default=None, ge=1)
    additional_links: list[dict[str, str | dict[str, str]]] | None = Field(
        default=None, sa_type=JSONB, nullable=True
    )
    providers: dict[str, dict[str, Any]] | None = Field(
        default=None, sa_type=JSONB, nullable=True
    )
    created_at: dt.datetime | None = Field(default_factory=now_)
    updated_at: dt.datetime | None = Field(
        sa_column=Column(DateTime(), onupdate=func.now())
    )

    owner: "User" = Relationship(back_populates="owned_collections")

    def to_potto(self) -> potto_schemas.Collection:
        return potto_schemas.Collection(
            type_=self.collection_type,
            identifier=self.resource_identifier,
            title=self.title,
            description=self.description,
            owner=self.owner.to_potto(),
            keywords=self.keywords,
            spatial_extent=self.spatial_extent,
            crs=self.crs,
            storage_crs=self.storage_crs,
            storage_crs_coordinate_epoch=self.storage_crs_coordinate_epoch,
            temporal_extent_begin=self.temporal_extent_begin,
            temporal_extent_end=self.temporal_extent_end,
            additional_links=self.additional_links,
            providers={
                name: CollectionProvider.model_validate(raw_provider)
                for name, raw_provider in (self.providers or {}).items()
            },
            custom_page_size=self.custom_page_size,
            custom_page_size_max=self.custom_page_size_max,
        )


class User(SQLModel, table=True):
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    username: str = Field(
        min_length=5,
        max_length=20,
        index=True,
        unique=True,
    )
    email: str | None = Field(
        default=None,
        max_length=254,
        unique=True,
        nullable=True,
    )
    hashed_password: str | None = Field(default=None, nullable=True)
    is_active: bool = Field(default=True)
    scopes: list[str] = Field(default_factory=list, sa_type=JSONB)

    owned_collections: list[Collection] = Relationship(
        back_populates="owner",
        cascade_delete=True,
    )

    def __admin_repr__(self, request: Request) -> str:
        return self.username

    def __admin_select2_repr__(self, request: Request) -> str:
        return Template("<span>{{ name }}</span>", autoescape=True).render(
            name=self.username,
        )

    def to_potto(self) -> PottoUser:
        return PottoUser(
            **self.model_dump(exclude={"hashed_password"}),
        )


class ServerMetadata(SQLModel, table=True):
    id: int | None = Field(
        default=None,
        primary_key=True,
    )
    title: Title = Field(sa_type=JSONB)
    description: MaybeDescription = Field(default=None, sa_type=JSONB, nullable=True)
    keywords: MaybeKeywords = Field(default=None, sa_type=JSONB, nullable=True)
    keywords_type: str | None = Field(
        default=None, min_length=3, max_length=50, nullable=True
    )
    terms_of_service: MaybeDescription = Field(
        default=None, sa_type=JSONB, nullable=True
    )
    url: str | None = Field(default=None, min_length=3, max_length=100, nullable=True)
    license: dict[str, Any] = Field(default=None, sa_type=JSONB, nullable=True)
    data_provider: dict[str, Any] = Field(default=None, sa_type=JSONB, nullable=True)
    point_of_contact: dict[str, Any] = Field(default=None, sa_type=JSONB, nullable=True)

    def to_potto(self) -> potto_schemas.ServerMetadata:
        return potto_schemas.ServerMetadata(
            title=self.title,
            description=self.description,
            keywords=self.keywords,
            keywords_type=self.keywords_type,
            terms_of_service=self.terms_of_service,
            url=self.url,
            license=(
                metadata_schemas.LicenseInformation.model_validate(self.license)
                if self.license is not None
                else None
            ),
            data_provider=(
                metadata_schemas.DataProviderInformation.model_validate(
                    self.data_provider
                )
                if self.data_provider is not None
                else None
            ),
            point_of_contact=(
                metadata_schemas.PointOfContact(
                    name=self.point_of_contact.get("name"),
                    position=self.point_of_contact.get("position"),
                    address=self.point_of_contact.get("address"),
                    city=self.point_of_contact.get("city"),
                    state_or_province=self.point_of_contact.get("state_or_province"),
                    postal_code=self.point_of_contact.get("postal_code"),
                    country=self.point_of_contact.get("country"),
                    phone=self.point_of_contact.get("phone"),
                    fax=self.point_of_contact.get("fax"),
                    email=self.point_of_contact.get("email"),
                    url=self.point_of_contact.get("url"),
                    contact_hours=self.point_of_contact.get("contact_hours"),
                    contact_instructions=self.point_of_contact.get(
                        "contact_instructions"
                    ),
                )
                if self.point_of_contact is not None
                else None
            ),
        )
