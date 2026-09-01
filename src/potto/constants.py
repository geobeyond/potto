import enum
import typing


class CollectionType(str, enum.Enum):
    COVERAGE = "coverage"
    FEATURE_COLLECTION = "feature"
    RECORD_COLLECTION = "record"


class ProvidedDataType(str, enum.Enum):
    COVERAGE = "coverage"
    EDR = "edr"
    FEATURE = "feature"
    MAP = "map"
    RECORD = "record"
    STAC = "stac"
    TILE = "tile"


class MediaType(str, enum.Enum):
    HTML = "text/html"
    JSON = "application/json"
    OAS30 = "application/vnd.oai.openapi+json;version=3.0"
    GEO_JSON = "application/geo+json"
    JSON_SCHEMA = "application/schema+json"


class LinkRelation(str, enum.Enum):
    ALTERNATE = "alternate"
    CONFORMANCE = "conformance"
    COLLECTION = "collection"
    COLLECTIONS = "data"
    COLLECTION_ITEMS = "items"
    COLLECTION_QUERYABLES = "http://www.opengis.net/def/rel/ogc/1.0/queryables"
    COLLECTION_SCHEMA = "http://www.opengis.net/def/rel/ogc/1.0/schema"
    HOME = "home"
    LOGIN = "login"
    SELF = "self"
    SERVICE_DESC = "service-desc"
    SERVICE_DOC = "service-doc"


class ConformanceClass(str, enum.Enum):
    OGCAPI_FEATURES_CORE = "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
    OGCAPI_FEATURES_GEOJSON = (
        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
    )
    OGCAPI_FEATURES_HTML = "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/html"
    OGCAPI_FEATURES_OPENAPI3 = (
        "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30"
    )
    OGCAPI_FEATURES_PART2_CRS = (
        "http://www.opengis.net/spec/ogcapi-features-2/1.0/conf/crs"
    )
    OGCAPI_PROCESSES_CORE = (
        "http://www.opengis.net/spec/ogcapi-processes-1/1.0/req/core"
    )
    OGCAPI_PROCESSES_JSON = (
        "http://www.opengis.net/spec/ogcapi-processes-1/1.0/req/json"
    )
    OGCAPI_PROCESSES_OPENAPI3 = (
        "http://www.opengis.net/spec/ogcapi-processes-1/1.0/req/oas30"
    )
    OGCAPI_PROCESSES_OGC_PROCESS_DESCRIPTION = (
        "http://www.opengis.net/spec/ogcapi-processes-1/1.0/req/ogc-process-description"
    )
    OGC_API_PROCESSES_JOB_LIST = (
        "http://www.opengis.net/spec/ogcapi-processes-1/1.0/req/job-list"
    )
    OGC_API_PROCESSES_CALLBACK = (
        "http://www.opengis.net/spec/ogcapi-processes-1/1.0/req/callback"
    )
    OGC_API_PROCESSES_DISMISS = (
        "http://www.opengis.net/spec/ogcapi-processes-1/1.0/req/dismiss"
    )


CRS_84: typing.Final[str] = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
CRS_84h: typing.Final[str] = "http://www.opengis.net/def/crs/OGC/0/CRS84h"
GREGORIAN: typing.Final[str] = "http://www.opengis.net/def/uom/ISO-8601/0/Gregorian"

FEATURE_COLLECTION_ITEM_TYPE: typing.Final[str] = "feature"

PYGEOAPI_F_JSON: typing.Final[str] = "json"
