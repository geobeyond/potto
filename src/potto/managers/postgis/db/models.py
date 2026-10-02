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
    func,
    Column,
    DateTime,
    Field,
    Relationship,
    SQLModel,
    UniqueConstraint,
)
from starlette.requests import Request

from ....constants import (
    CRS_84,
    CollectionType,
    ProvidedDataType,
)
from ....schemas.auth import PottoUser
from ....schemas import (
    collections as collection_schemas,
    jobs as job_schemas,
    metadata as metadata_schemas,
    processes as process_schemas,
)
from ....schemas.base import (
    OgcApiException,
    PottoProvider,
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
        sa_column=Column(ShapelyGeometryAdapter(srid=4326), nullable=True),
    )
    spatial_extent_crs: str | None = None  # part 1 - CRS of the spatial extent
    crs: list[str] = Field(
        default_factory=lambda: [CRS_84], sa_type=JSONB, nullable=False
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

    def to_potto(self) -> collection_schemas.Collection:
        return collection_schemas.Collection(
            type_=self.collection_type,
            identifier=self.resource_identifier,
            created_at=self.created_at,  # ty: ignore[invalid-argument-type]
            # updated_at's column has no INSERT-time default (only onupdate), so a
            # freshly created row has it as None until the first update.
            updated_at=self.updated_at or self.created_at,  # ty: ignore[invalid-argument-type]
            title=self.title,
            is_public=self.is_public,
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
                ProvidedDataType(name): PottoProvider.model_validate(raw_provider)
                for name, raw_provider in (self.providers or {}).items()
            },
            custom_page_size=self.custom_page_size,
            custom_page_size_max=self.custom_page_size_max,
        )


class Process(SQLModel, table=True):
    __table_args__ = (
        sqlalchemy.Index("idx_process_title_gin", "title", postgresql_using="gin"),
        UniqueConstraint(
            "resource_identifier",
            "version",
            name="unique_constraint_identifier_version",
        ),
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
    version: str
    is_public: bool = Field(default=False)
    title: Title = Field(sa_type=JSONB)
    description: MaybeDescription = Field(default=None, sa_type=JSONB, nullable=True)
    keywords: MaybeKeywords = Field(default=None, sa_type=JSONB, nullable=True)
    additional_links: list[dict[str, str | dict[str, str]]] | None = Field(
        default=None, sa_type=JSONB, nullable=True
    )
    created_at: dt.datetime | None = Field(default_factory=now_)
    updated_at: dt.datetime | None = Field(
        sa_column=Column(DateTime(), onupdate=func.now())
    )
    inputs: list[dict] | None = Field(default=None, sa_type=JSONB, nullable=True)
    outputs: list[dict] | None = Field(default=None, sa_type=JSONB, nullable=True)
    execution_unit: dict | None = Field(default=None, sa_type=JSONB, nullable=True)
    deployment_status: dict | None = Field(default=None, sa_type=JSONB, nullable=True)

    owner: "User" = Relationship(back_populates="owned_processes")
    jobs: list["Job"] = Relationship(back_populates="process", cascade_delete=True)

    def to_potto(self) -> process_schemas.Process:
        match self.execution_unit:
            case {"type_": "oci"}:
                execution_unit = process_schemas.ProcessExecutionUnitOci(
                    **self.execution_unit
                )
            case {"type_": "cwl"}:
                execution_unit = process_schemas.ProcessExecutionUnitCwl(
                    **self.execution_unit
                )
            case {"type_": _}:
                execution_unit = process_schemas.ProcessExecutionUnitOther(
                    **self.execution_unit
                )
            case _:
                execution_unit = None
        return process_schemas.Process(
            identifier=self.resource_identifier,
            created_at=self.created_at,  # ty: ignore[invalid-argument-type]
            updated_at=self.updated_at or self.created_at,  # ty: ignore[invalid-argument-type]
            title=self.title,
            owner=self.owner.to_potto(),
            is_public=self.is_public,
            version=self.version,
            description=self.description,
            keywords=self.keywords,
            additional_links=self.additional_links,
            execution_unit=execution_unit,
            inputs=(
                [process_schemas.ProcessInputDescription(**inp) for inp in self.inputs]
                if self.inputs
                else []
            ),
            outputs=(
                [
                    process_schemas.ProcessOutputDescription(**out)
                    for out in self.outputs
                ]
                if self.outputs
                else []
            ),
            deployment_status=(
                process_schemas.ProcessDeploymentStatus(
                    value=self.deployment_status["value"],
                    detail=self.deployment_status["detail"],
                    definition_hash=self.deployment_status["definition_hash"],
                    changed_at=(
                        dt.datetime.fromisoformat(changed_at)
                        if (changed_at := self.deployment_status["changed_at"])
                        is not None
                        else None
                    ),
                    deployed_reference=self.deployment_status.get("deployed_reference"),
                )
                if self.deployment_status
                else process_schemas.ProcessDeploymentStatus(
                    value=process_schemas.ProcessDeploymentStatusValue.FAILED
                )
            ),
        )


class Job(SQLModel, table=True):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    id: int | None = Field(
        default=None,
        primary_key=True,
    )
    resource_identifier: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        index=True,
        unique=True,
    )
    owner_id: str = Field(foreign_key="user.id", ondelete="CASCADE")
    process_id: int = Field(foreign_key="process.id", ondelete="CASCADE")
    is_public: bool = Field(default=False)
    status: job_schemas.JobStatus
    response_type: str = Field(default="raw")
    additional_links: list[dict[str, str | dict[str, str]]] | None = Field(
        default=None, sa_type=JSONB, nullable=True
    )
    created_at: dt.datetime = Field(default_factory=now_)
    updated_at: dt.datetime | None = Field(
        sa_column=Column(DateTime(), onupdate=func.now())
    )
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    processing_entity_type: str
    message: str | None = Field(default=None, nullable=True)
    exception: dict | None = Field(default=None, sa_type=JSONB, nullable=True)
    progress: int | None = Field(default=None, nullable=True)
    inputs: dict | None = Field(default=None, sa_type=JSONB, nullable=True)
    outputs: dict | None = Field(default=None, sa_type=JSONB, nullable=True)
    callback_uris: dict | None = Field(default=None, sa_type=JSONB, nullable=True)

    owner: "User" = Relationship(back_populates="owned_jobs")
    process: Process = Relationship(back_populates="jobs")

    def to_potto(self) -> job_schemas.Job:
        return job_schemas.Job(
            identifier=self.resource_identifier,
            status=self.status,
            process=self.process.to_potto(),
            created_at=self.created_at,
            updated_at=self.updated_at or self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            owner=self.owner.to_potto(),
            is_public=self.is_public,
            additional_links=self.additional_links,
            inputs=dict(self.inputs) if self.inputs else {},
            outputs=(
                {
                    name: job_schemas.JobOutputDescription(**description)
                    for name, description in self.outputs.items()
                }
                if self.outputs
                else {}
            ),
            response_type=self.response_type,  # ty: ignore[invalid-argument-type]
            callback_uris=(
                job_schemas.JobCallbackUris(**self.callback_uris)
                if self.callback_uris
                else None
            ),
            processingEntityType=self.processing_entity_type,
            message=self.message,
            exception=(OgcApiException(**self.exception) if self.exception else None),
            progress=self.progress,
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

    owned_processes: list[Process] = Relationship(
        back_populates="owner",
        cascade_delete=True,
    )

    owned_jobs: list[Job] = Relationship(
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

    def to_potto(self) -> metadata_schemas.ServerMetadata:
        return metadata_schemas.ServerMetadata(
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
