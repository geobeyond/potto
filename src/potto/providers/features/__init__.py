import logging
from .protocol import FeatureProviderProtocol
from .registry import (
    FeatureProviderFactory,
    register_feature_provider,
    get_feature_provider,
)
from ._collectionconfig import collection_config_provider_factory
from ._duckdb import duckdb_provider_factory
from ._postgis import postgis_provider_factory
from ._pygeoapi import pygeoapi_feature_provider_factory

logger = logging.getLogger(__name__)

try:
    from . import _pyogrio
except ImportError:
    logger.info("pyogrio is not installed; PyogrioFeatureProvider will not work")
    pass

register_feature_provider("duckdb", duckdb_provider_factory)
register_feature_provider("pyogrio", _pyogrio.pyogrio_provider_factory)
register_feature_provider("pygeoapi", pygeoapi_feature_provider_factory)
register_feature_provider("postgis", postgis_provider_factory)
register_feature_provider("collection-config", collection_config_provider_factory)

__all__ = [
    "FeatureProviderFactory",
    "FeatureProviderProtocol",
    "get_feature_provider",
    "register_feature_provider",
]
