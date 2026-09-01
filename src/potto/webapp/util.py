import logging

import pygeoapi.api
import pygeoapi.l10n
from starlette.requests import Request

from ..constants import (
    LinkRelation,
    MediaType,
)
from ..schemas.base import Link
from .protocols import UrlResolver

logger = logging.getLogger(__name__)


def get_base_links(url_resolver: UrlResolver) -> list[Link]:
    return [
        Link(
            type=MediaType.JSON,
            rel=LinkRelation.HOME,
            href=str(
                url_resolver(
                    "api:landing-page",
                )
            ),
            title="API landing page",
        ),
    ]


def set_html_link_self_relation(original_links: list[dict]) -> list[dict]:
    """Modify input list of links so that the HTML link has `rel=self`.

    As HTML is always rendered outside pygeoapi core, this means links generated
    by pygeoapi will never have an HTML-related link with a relation of 'self'.

    This function can be used to ensure the list of links has the `self`
    relation set on the link that points to an HTML resource.
    """
    result = []
    for link in original_links:
        new_link = link.copy()
        if link["rel"] == "self":
            new_link["rel"] = "alternate"
            result.append(new_link)
        elif link["type"] == pygeoapi.api.FORMAT_TYPES[pygeoapi.api.F_HTML]:
            new_link["rel"] = "self"
            result.append(new_link)
        else:
            result.append(new_link)
    return result


def get_accepted_info(request: Request) -> tuple[str, str | None]:
    accepted_media_type = _get_requested_media_type(request)
    return accepted_media_type, _get_requested_format(accepted_media_type)


def _get_requested_media_type(request: Request) -> str:
    if f_param := request.query_params.get("f"):
        return pygeoapi.api.FORMAT_TYPES.get(f_param, "*/*")
    else:
        if raw_accept_header := request.headers.get("Accept"):
            items = []
            for index, i in enumerate(raw_accept_header.split(",")):
                raw_param, raw_quality = i.partition(";")[::2]
                try:
                    quality = float(raw_quality.replace("q=", ""))
                except ValueError:
                    quality = 1.0
                items.append((quality, index, raw_param))
            return sorted(items, key=lambda x: (x[0], -x[1])).pop()[-1]

        return "*/*"


def _get_requested_format(media_type: str) -> str | None:
    type_, subtype = media_type.partition("/")[::2]
    for format_, recognized_media_type in pygeoapi.api.FORMAT_TYPES.items():
        recognized_type, recognized_subtype = recognized_media_type.partition("/")[::2]
        if type_ == recognized_type:
            if subtype == recognized_subtype or subtype == "*":
                return format_
    else:
        return None
