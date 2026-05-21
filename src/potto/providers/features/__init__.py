import logging
from .protocol import FeatureProviderProtocol
from .registry import (
    FeatureProviderFactory,
    register_feature_provider,
    get_feature_provider,
)

logger = logging.getLogger(__name__)

try:
    from . import _pyogrio
except ImportError:
    logger.info("pyogrio is not installed; PyogrioFeatureProvider will not work")
    pass

register_feature_provider("pyogrio", _pyogrio.pyogrio_provider_factory)

__all__ = [
    "FeatureProviderFactory",
    "FeatureProviderProtocol",
    "get_feature_provider",
    "register_feature_provider",
]
