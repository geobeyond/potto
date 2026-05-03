import logging
from typing import Any

from jinja2 import pass_context
from pygeoapi.util import (
    DATETIME_FORMAT,
    to_json as _to_json,
    format_datetime as _format_datetime,
    format_duration as _format_duration,
    human_size as _human_size,
    get_path_basename as _get_path_basename,
    get_breadcrumbs as _get_breadcrumbs,
    filter_dict_by_key_value as _filter_dict_by_key_value,
)

logger = logging.getLogger(__name__)

COLORS: dict[str, str] = {
    # collection type badge colors (Bootstrap text-bg-* classes)
    "collection_type_feature": "text-bg-primary",
    "collection_type_record": "text-bg-success",
    "collection_type_coverage": "text-bg-info",
}

ICONS: dict[str, str] = {
    # collection types
    "collection_type_feature": "bi bi-layers",
    "collection_type_record": "bi bi-archive",
    "collection_type_coverage": "bi bi-grid-3x3-gap",
    # user / auth
    "user": "bi bi-person",
    "login": "bi bi-box-arrow-in-right",
    "logout": "bi bi-box-arrow-right",
    # navigation / actions
    "settings": "bi bi-gear",
    "search": "bi bi-search",
    "chevron_left": "bi bi-chevron-left",
    "chevron_right": "bi bi-chevron-right",
    # content
    "collections": "bi bi-collection",
    "warning": "bi bi-exclamation-triangle-fill",
}


@pass_context
def get_translatable_string(
    context: dict[str, Any], value: str | dict[str, str] | None
) -> str | None:
    logger.debug(f"{value=}")
    request = context["request"]
    logger.debug(f"{request.state.language=}")
    if value is None:
        return None
    if isinstance(value, dict):
        try:
            default_value = list(value.values())[0]
        except IndexError:
            return None
        else:
            result = value.get(request.state.language, default_value)
            logger.debug(f"{result=}")
            return result
    else:
        return str(value)


def to_json(data_: dict, pretty: bool = False) -> str:
    return _to_json(data_, pretty)


def format_datetime(value: str, format_: str = DATETIME_FORMAT) -> str:
    return _format_datetime(value, format_)


def format_duration(start: str, end: str | None = None) -> str:
    return _format_duration(start, end)  # ty: ignore


def human_size(nbytes: int) -> str:
    return _human_size(nbytes)


def get_path_basename(urlpath: str) -> str:
    return _get_path_basename(urlpath)


def get_breadcrumbs(urlpath: str) -> list:
    return _get_breadcrumbs(urlpath)


def filter_dict_by_key_value(data_: dict, key: str, value: str) -> dict:
    return _filter_dict_by_key_value(data_, key, value)
