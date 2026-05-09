import asyncio
import json
import logging
from http import HTTPStatus
from typing import (
    cast,
    Literal,
    Sequence,
    TypeAlias,
)

import babel
from pygeoapi.api import (
    API as _API,
    describe_collections as _describe_collections,
    get_collection_schema as _get_collection_schema,
)
from pygeoapi.api.itemtypes import (
    get_collection_items as _get_collection_items,
    get_collection_item as _get_collection_item,
    get_collection_queryables as _get_collection_queryables,
)
from pygeoapi.openapi import get_oas_30
from pygeoapi.l10n import translate_struct

from . import (
    constants,
    exceptions as potto_exceptions,
)
from .config import PottoSettings
from .operations.config import get_pygeoapi_config
from .operations import (
    collections as collection_ops,
    metadata as metadata_ops,
)
from .schemas import (
    base,
    auth,
    potto as potto_schemas,
)
from .schemas.base import FeatureFilter
from .webapp.requests import PottoRequest
from .util import get_collection_pagination_limit

logger = logging.getLogger(__name__)

ResourceTypes: TypeAlias = Sequence[Literal["collection", "stac-collection", "process"]]


class Potto:
    """A wrapper around pygeoapi core.

    This wrapper presents a simpler interface than pygeoapi core and also
    implements some additional operations.

    The major difference from pygeoapi core is that this wrapper's methods
    accept direct arguments rather than receiving a generic `Request` class
    and then parsing the contents of the request. This means that this class
    demands that parsing of an HTTP request be done before calling it, or in
    other words, that the framework that is wrapping pygeoapi core deals with
    the complexity of retrieving parameters from the HTTP request.

    Note that internally this class' methods still need to construct a
    `Request` instance in order to send to pygeoapi core, which expects it.
    But the interface they present to the world is request-free. This is done
    with two intentions:

    - Allow non HTTP clients to use pygeoapi core. For example, a CLI
      application
    - Demonstrate what pygeoapi core's public API would look like if it did
      not focus on parsing HTTP Requests but rather whatever input parameters
      were needed for each particular method
    """

    _settings: PottoSettings

    def __init__(
        self,
        settings: PottoSettings,
    ) -> None:
        self._settings = settings

    async def _get_pygeoapi(
        self,
        user: auth.PottoUser | None,
        *,
        collection_identifier: str | None = None,
        collection_page: int = 1,
        collection_page_size: int = 20,
    ) -> _API:
        async with self._settings.get_db_session_maker()() as session:
            pygeoapi_config = await get_pygeoapi_config(
                session,
                self._settings,
                user,
                collection_identifier=collection_identifier,
                collection_page=collection_page,
                collection_page_size=collection_page_size,
            )
        openapi_document = get_oas_30(pygeoapi_config, fail_on_invalid_collection=True)
        return _API(config=pygeoapi_config, openapi=openapi_document)

    async def _get_collection(
        self,
        collection_id: str,
        user: auth.PottoUser | None,
    ) -> potto_schemas.Collection:
        async with self._settings.get_db_session_maker()() as session:
            if (
                db_collection
                := await collection_ops.get_collection_by_resource_identifier(
                    session,
                    user,
                    self._settings.get_authorization_backend(),
                    collection_id,
                )
            ) is None:
                raise potto_exceptions.PottoCollectionNotFoundException(
                    f"Collection {collection_id} not found"
                )
        return db_collection.to_potto()

    async def get_localized_config(
        self, user: auth.PottoUser | None, locale: babel.Locale
    ) -> dict:
        pygeoapi_api = await self._get_pygeoapi(user)
        return translate_struct(pygeoapi_api.config, locale_=locale, is_config=True)

    async def api_get_landing_page(
        self,
        *,
        user: auth.PottoUser | None,
    ) -> potto_schemas.LandingPage:
        """Return overview information.

        The response contains useful info for generating a landing page for the API.
        """
        page = 1
        async with self._settings.get_db_session_maker()() as session:
            db_collections, total = await collection_ops.paginated_list_collections(
                session,
                user,
                self._settings.get_authorization_backend(),
                page=page,
                include_total=True,
            )
            server_metadata = await metadata_ops.get_server_metadata(session)
        assert total is not None
        return potto_schemas.LandingPage(
            metadata=server_metadata.to_potto(),
            collections=potto_schemas.CollectionList(
                collections=[db_col.to_potto() for db_col in db_collections],
                pagination=potto_schemas.Pagination(
                    page=page,
                    page_size=len(db_collections),
                    total=total,
                ),
            ),
        )

    async def api_get_conformance_details(self) -> potto_schemas.ConformanceDetail:
        return potto_schemas.ConformanceDetail(
            conforms_to=[
                constants.CONFORMANCE_CLASS_OGCAPI_FEATURES_CORE,
                constants.CONFORMANCE_CLASS_OGCAPI_FEATURES_GEOJSON,
                constants.CONFORMANCE_CLASS_OGCAPI_FEATURES_OPENAPI3,
                constants.CONFORMANCE_CLASS_OGCAPI_FEATURES_PART2_CRS,
            ]
        )

    async def api_list_collections(
        self,
        *,
        user: auth.PottoUser | None,
        locale: babel.Locale,
        page: int = 1,
        page_size: int = 20,
    ) -> potto_schemas.CollectionList:
        pygeoapi_api = await self._get_pygeoapi(
            user, collection_page=page, collection_page_size=page_size
        )
        pygeoapi_response = await asyncio.to_thread(
            _describe_collections,
            pygeoapi_api,
            PottoRequest(locale=locale, output_format="json"),
        )
        pygeoapi_headers, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
        parsed_pygeoapi_content = json.loads(pygeoapi_content)
        found_collections = []
        for pygeoapi_collection in parsed_pygeoapi_content.get("collections", []):
            found_collections.append(
                potto_schemas.Collection.from_pygeoapi(
                    pygeoapi_collection, pygeoapi_api
                )
            )
        return potto_schemas.CollectionList(
            collections=found_collections,
            pagination=potto_schemas.Pagination(
                page=page,
                page_size=len(found_collections),
                total=0,  # FIXME
            ),
        )

    async def api_get_collection(
        self,
        collection_id: str,
        *,
        user: auth.PottoUser | None,
        locale: babel.Locale,
        include_queryables: bool = False,
        include_schema: bool = False,
    ) -> potto_schemas.Collection | None:
        pygeoapi_api = await self._get_pygeoapi(
            user, collection_identifier=collection_id
        )
        pygeoapi_response = await asyncio.to_thread(
            _describe_collections,
            pygeoapi_api,
            PottoRequest(locale=locale, output_format="json"),
            collection_id,
        )
        pygeoapi_headers, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
        parsed_pygeoapi_content = json.loads(pygeoapi_content)
        if pygeoapi_status_code == HTTPStatus.NOT_FOUND:
            return None
        collection_queryables = None
        if include_queryables:
            queryables_response = await asyncio.to_thread(
                _get_collection_queryables,
                pygeoapi_api,
                PottoRequest(locale=locale, output_format="json"),
                collection_id,
            )
            pygeoapi_queryables_content = queryables_response[-1]
            collection_queryables = json.loads(pygeoapi_queryables_content)
        collection_schema = None
        if include_schema:
            schema_response = await asyncio.to_thread(
                _get_collection_schema,
                pygeoapi_api,
                PottoRequest(locale=locale, output_format="json"),
                collection_id,
            )
            pygeoapi_schema_content = schema_response[-1]
            collection_schema = json.loads(pygeoapi_schema_content)
        return potto_schemas.Collection.from_pygeoapi(
            parsed_pygeoapi_content,
            pygeoapi_api,
            pygeoapi_collection_queryables=collection_queryables,
            pygeoapi_collection_schema=collection_schema,
        )

    async def api_list_collection_items(
        self,
        collection_id: str,
        *,
        locale: babel.Locale,
        user: auth.PottoUser | None = None,
        filter_: FeatureFilter | None = None,
    ) -> potto_schemas.FeatureListResponse:
        collection = await self._get_collection(collection_id, user)
        pygeoapi_api = await self._get_pygeoapi(
            user, collection_identifier=collection_id, collection_page_size=1
        )
        pygeoapi_response = await asyncio.to_thread(
            _get_collection_items,
            pygeoapi_api,
            PottoRequest(
                locale=locale,
                output_format="json",
                **(
                    filter_.model_dump(by_alias=True, exclude_none=True)
                    if filter_
                    else {}
                ),
            ),
            dataset=collection_id,
        )
        pygeoapi_headers, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
        status_value = cast(HTTPStatus, pygeoapi_status_code).value
        if status_value != 200:
            detail = json.loads(pygeoapi_content).get("description", pygeoapi_content)
            if status_value == 400:
                raise potto_exceptions.PottoBadRequestException(detail)
            raise potto_exceptions.PottoException(str(pygeoapi_response))
        parsed_pygeoapi_content = json.loads(pygeoapi_content)
        logger.debug(f"{parsed_pygeoapi_content=}")
        features = [
            potto_schemas.Feature.from_pygeoapi_feature(feat)
            for feat in parsed_pygeoapi_content["features"]
        ]
        effective_pagination_limit = get_collection_pagination_limit(
            filter_.limit if filter_ else None, collection, self._settings
        )
        return potto_schemas.FeatureListResponse(
            collection=collection,
            features=features,
            pagination=base.PaginationContext(
                limit=effective_pagination_limit,
                number_matched=parsed_pygeoapi_content.get("numberMatched", 0),
                number_returned=parsed_pygeoapi_content.get(
                    "numberReturned", len(features)
                ),
                offset=parsed_pygeoapi_content.get("offset", 0),
            ),
            filter_=filter_,
            metadata={
                **pygeoapi_headers,
                "timestamp": parsed_pygeoapi_content.get("timeStamp"),
            },
        )

    async def api_get_collection_item(
        self,
        user: auth.PottoUser | None,
        *,
        item_id: str,
        collection_id: str,
        locale: babel.Locale,
        crs: str | None = None,
        output_format: Literal["json", "jsonld"] = "json",
    ) -> potto_schemas.FeatureResponse:
        collection = await self._get_collection(collection_id, user)
        pygeoapi_api = await self._get_pygeoapi(
            user, collection_identifier=collection_id
        )
        extra_params = {"crs": crs} if crs is not None else {}
        pygeoapi_response = await asyncio.to_thread(
            _get_collection_item,
            pygeoapi_api,
            PottoRequest(  # ty: ignore[invalid-argument-type]
                locale=locale,
                output_format=output_format,
                **extra_params,  # ty: ignore[invalid-argument-type]
            ),
            dataset=collection_id,
            identifier=item_id,
        )
        pygeoapi_headers, pygeoapi_status_code, pygeoapi_content = pygeoapi_response
        status_value = cast(HTTPStatus, pygeoapi_status_code).value
        if status_value != 200:
            if status_value == 400:
                detail = json.loads(pygeoapi_content).get(
                    "description", pygeoapi_content
                )
                raise potto_exceptions.PottoBadRequestException(detail)
            raise potto_exceptions.PottoCollectionItemNotFoundException(
                f"Item {item_id} not found"
            )
        parsed_pygeoapi_content = json.loads(pygeoapi_content)
        return potto_schemas.FeatureResponse(
            collection=collection,
            feature=potto_schemas.Feature.from_pygeoapi_feature(
                parsed_pygeoapi_content
            ),
            metadata=pygeoapi_headers,
        )
