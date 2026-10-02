import logging

from starlette_admin.exceptions import FormValidationError
from starlette_admin.views import BaseModelView

from ...exceptions import (
    PottoCannotChangeCollectionOwnerException,
    PottoCannotCreateCollectionException,
    PottoCannotCreateUserException,
    PottoCannotEditCollectionException,
    PottoCannotEditServerMetadataException,
    PottoCannotEditUserException,
    PottoCannotSetAdminScopeException,
    PottoCannotSetScopesException,
    ProcessExecutionUnitRejectedError,
)

logger = logging.getLogger(__name__)


class _PottoAdminModelView(BaseModelView):
    def handle_exception(self, exc: Exception) -> None:
        if isinstance(
            exc, (PottoCannotSetAdminScopeException, PottoCannotSetScopesException)
        ):
            raise FormValidationError({"scopes": str(exc)})
        if isinstance(exc, PottoCannotChangeCollectionOwnerException):
            raise FormValidationError({"owner": str(exc)})
        if isinstance(exc, PottoCannotEditCollectionException):
            raise FormValidationError({"resource_identifier": str(exc)})
        if isinstance(exc, PottoCannotCreateCollectionException):
            raise FormValidationError({"resource_identifier": str(exc)})
        if isinstance(exc, PottoCannotEditServerMetadataException):
            raise FormValidationError({"title": str(exc)})
        if isinstance(exc, PottoCannotCreateUserException):
            raise FormValidationError({"username": str(exc)})
        if isinstance(exc, PottoCannotEditUserException):
            raise FormValidationError({"username": str(exc)})
        if isinstance(exc, ProcessExecutionUnitRejectedError):
            raise FormValidationError({"execution_unit": str(exc)})
        logger.exception(f"An error occurred: {exc}")
        raise exc
