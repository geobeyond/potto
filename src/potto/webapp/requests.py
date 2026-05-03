import logging

import babel
import pygeoapi.api
import pygeoapi.l10n
import pygeoapi.util

from ..constants import PYGEOAPI_F_JSON

logger = logging.getLogger(__name__)


class PottoRequest:
    def __init__(
        self,
        locale: babel.Locale,
        output_format: str = PYGEOAPI_F_JSON,
        data_: bytes | None = None,
        **query_param: str,
    ):
        self.format = output_format
        self.locale = locale
        self.params = query_param.copy()
        self.data = data_

    @property
    def raw_locale(self) -> str:
        return self.locale.language

    def get_linkrel(self, format_: str) -> str:
        return "self" if format_.lower() == self.format else "alternate"

    def is_valid(self, additional_formats: list[str] | None = None) -> bool:
        if self.format in pygeoapi.api.FORMAT_TYPES.keys():
            return True
        if self.format in (f.lower() for f in (additional_formats or ())):
            return True
        return False

    def get_response_headers(
        self,
        force_lang: babel.Locale | None = None,
        force_type: str | None = None,
        force_encoding: str | None = None,
        **custom_headers: str,
    ) -> dict[str, str]:
        # note: don't set 'Content-Encoding', GZipMiddleware is already
        # enabled in the starlette app
        return {
            "Content-Type": (force_type or pygeoapi.api.FORMAT_TYPES[self.format]),
            "X-Powered-By": f"pygeoapi {pygeoapi.__version__}",
            "Content-Language": force_lang.language
            if force_lang
            else self.locale.language,
            **custom_headers,
        }
