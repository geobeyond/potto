import typing

CRS_84: typing.Final[str] = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
CRS_84h: typing.Final[str] = "http://www.opengis.net/def/crs/OGC/0/CRS84h"
GREGORIAN: typing.Final[str] = "http://www.opengis.net/def/uom/ISO-8601/0/Gregorian"

FEATURE_COLLECTION_ITEM_TYPE: typing.Final[str] = "feature"

PYGEOAPI_F_JSON: typing.Final[str] = "json"
MEDIA_TYPE_HTML: typing.Final[str] = "text/html"
MEDIA_TYPE_JSON: typing.Final[str] = "application/json"
MEDIA_TYPE_OAS30: typing.Final[str] = "application/vnd.oai.openapi+json;version=3.0"
MEDIA_TYPE_GEO_JSON: typing.Final[str] = "application/geo+json"
MEDIA_TYPE_JSON_SCHEMA: typing.Final[str] = "application/schema+json"

REL_ALTERNATE: typing.Final[str] = "alternate"
REL_LOGIN: typing.Final[str] = "login"
REL_COLLECTION: typing.Final[str] = "collection"
REL_COLLECTIONS: typing.Final[str] = "data"
REL_COLLECTION_ITEMS: typing.Final[str] = "items"
REL_COLLECTION_QUERYABLES: typing.Final[str] = (
    "http://www.opengis.net/def/rel/ogc/1.0/queryables"
)
REL_COLLECTION_SCHEMA: typing.Final[str] = (
    "http://www.opengis.net/def/rel/ogc/1.0/schema"
)
REL_CONFORMANCE: typing.Final[str] = "conformance"
REL_HOME: typing.Final[str] = "home"
REL_SELF: typing.Final[str] = "self"
REL_SERVICE_DESC: typing.Final[str] = "service-desc"
REL_SERVICE_DOC: typing.Final[str] = "service-doc"


CONFORMANCE_CLASS_OGCAPI_FEATURES_CORE = (
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
)
CONFORMANCE_CLASS_OGCAPI_FEATURES_GEOJSON = (
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
)
CONFORMANCE_CLASS_OGCAPI_FEATURES_HTML = (
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/html"
)
CONFORMANCE_CLASS_OGCAPI_FEATURES_OPENAPI3 = (
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30"
)
CONFORMANCE_CLASS_OGCAPI_FEATURES_PART2_CRS = (
    "http://www.opengis.net/spec/ogcapi-features-2/1.0/conf/crs"
)
