import logging
from typing import Annotated

import pydantic

from ...constants import (
    LinkRelation,
    MediaType,
)
from ...webapp.protocols import UrlResolver
from ..base import Link
from ..system import SystemOverview

logger = logging.getLogger(__name__)


class JsonLanding(pydantic.BaseModel):
    links: list[Link]
    title: str | None = None
    description: str | None = None
    attribution: str | None = None

    @classmethod
    def from_potto(
        cls,
        potto_response: SystemOverview,
        url_resolver: UrlResolver,
        oidc_configured: bool = False,
    ) -> "JsonLanding":
        links = [
            Link(
                type=MediaType.JSON,
                rel=LinkRelation.SELF,
                href=str(url_resolver("api:landing-page")),
                title="This resource",
            ),
            Link(
                type=MediaType.HTML,
                rel=LinkRelation.ALTERNATE,
                href=str(url_resolver("landing-page")),
                title="HTML landing page",
            ),
            Link(
                type=MediaType.OAS30,
                rel=LinkRelation.SERVICE_DESC,
                href=str(url_resolver("api:openapi")),
                title="OpenAPI document",
            ),
            Link(
                type=MediaType.HTML,
                rel=LinkRelation.SERVICE_DOC,
                href=str(url_resolver("api:swagger_ui_html")),
                title="API documentation",
            ),
            Link(
                type=MediaType.JSON,
                rel=LinkRelation.CONFORMANCE,
                href=str(url_resolver("api:conformance-page")),
                title="API conformance declaration",
            ),
            Link(
                type=MediaType.JSON,
                rel=LinkRelation.COLLECTIONS,
                href=str(url_resolver("api:collection-list")),
                title="Collections exposed by this server",
            ),
            Link(
                type=MediaType.HTML if oidc_configured else MediaType.JSON,
                rel=LinkRelation.LOGIN,
                href=str(
                    url_resolver("oidc-login")
                    if oidc_configured
                    else url_resolver("api:login")
                ),
                title=(
                    "Authenticate via OIDC provider"
                    if oidc_configured
                    else "Obtain a bearer token"
                ),
            ),
        ]
        return cls(
            title=(
                potto_response.metadata.title.get("en")
                if isinstance(potto_response.metadata.title, dict)
                else potto_response.metadata.title
            ),
            description=(
                potto_response.metadata.description.get("en")
                if isinstance(potto_response.metadata.description, dict)
                else potto_response.metadata.description
            ),
            attribution=potto_response.attribution,
            links=links,
        )


class JsonConformance(pydantic.BaseModel):
    conforms_to: Annotated[list[str], pydantic.Field(serialization_alias="conformsTo")]
