import logging
from pathlib import Path
from typing import Optional

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette_admin import BaseAdmin, RequestAction
from starlette_admin.views import Link

from ...config import PottoSettings
from ...util import run_sync
from .auth import LocalAdminAuthProvider, OIDCAdminAuthProvider

logger = logging.getLogger(__name__)


class PottoAdmin(BaseAdmin):
    potto_settings: PottoSettings

    def __init__(self, *args, potto_settings: PottoSettings, **kwargs):
        super().__init__(*args, **kwargs)
        self.potto_settings = potto_settings

    def mount_to(self, app: Starlette, redirect_slashes: bool = True) -> None:
        """Reimplemented in order to pass settings to the admin app."""
        admin_app = Starlette(
            routes=self.routes,
            middleware=self.middlewares,
            debug=self.debug,
            exception_handlers={HTTPException: self._render_error},
        )
        admin_app.state.ROUTE_NAME = self.route_name
        admin_app.state.SETTINGS = self.potto_settings
        app.mount(
            self.base_url,
            app=admin_app,
            name=self.route_name,
        )
        admin_app.router.redirect_slashes = redirect_slashes

    async def _render_create(self, request: Request) -> Response:
        identity = request.path_params.get("identity")
        model = self._find_model_from_identity(identity)
        if hasattr(model, "async_can_create"):
            if not await model.async_can_create(request):  # ty: ignore[call-non-callable]
                raise HTTPException(status_code=403)
        return await super()._render_create(request)

    async def _render_edit(self, request: Request) -> Response:
        identity = request.path_params.get("identity")
        model = self._find_model_from_identity(identity)
        if hasattr(model, "async_can_edit"):
            if not await model.async_can_edit(request):  # ty: ignore[call-non-callable]
                raise HTTPException(status_code=403)
        return await super()._render_edit(request)

    async def _render_list(self, request: Request) -> Response:
        """Reimplemented to support async permission checks for the 'Add new' button.

        starlette-admin's `can_create` hook is synchronous, making it impossible to
        delegate to our async authorization backends directly. To work around this, we
        own the full list rendering here so we can pass a `can_create` context variable
        computed asynchronously (via `async_can_create` on the view) to the template,
        rather than having the template call `model.can_create(request)` itself.

        This method also handles the `skip_list` redirect for single-instance views.
        """
        request.state.action = RequestAction.LIST
        identity = request.path_params.get("identity")
        model = self._find_model_from_identity(identity)
        if not model.is_accessible(request):
            raise HTTPException(status_code=403)
        if getattr(model, "skip_list", False):
            items = await model.find_all(request, skip=0, limit=1)
            if items:
                pk = await model.get_pk_value(request, items[0])
                return RedirectResponse(
                    request.url_for(
                        self.route_name + ":detail", identity=identity, pk=pk
                    )
                )
        if hasattr(model, "async_can_create"):
            can_create = await model.async_can_create(request)  # ty: ignore[call-non-callable]
        else:
            can_create = model.can_create(request)
        return self.templates.TemplateResponse(
            request=request,
            name=model.list_template,
            context={
                "model": model,
                "title": model.title(request),
                "_actions": await model.get_all_actions(request),
                "__js_model__": await model._configs(request),
                "can_create": can_create,
            },
        )

    def custom_render_js(self, request: Request) -> Optional[str]:
        return str(request.url_for("static", path="js/admin/listRender.js"))


def create_admin_app_from_settings(settings: PottoSettings) -> BaseAdmin:
    templates_dir = str(
        settings.admin_templates_dir or Path(__file__).parents[1] / "templates/admin"
    )
    auth_provider = (
        OIDCAdminAuthProvider(settings)
        if settings.oidc is not None
        else LocalAdminAuthProvider(settings)
    )
    app = PottoAdmin(
        potto_settings=settings,
        auth_provider=auth_provider,
        templates_dir=templates_dir,
        statics_dir=str(settings.static_dir or Path(__file__).parents[1] / "static"),
        title="Potto admin",
    )
    app.add_view(Link(label="Back to front page", url="/", icon="fa fa-home"))

    async def _get_views():
        return (
            await settings.get_server_metadata_manager().get_server_metadata_admin_view(),
            await settings.get_user_account_manager().get_user_account_admin_view(),
            await settings.get_collection_manager().get_collection_admin_view(),
            await settings.get_process_manager().get_process_admin_view(),
        )

    (
        server_metadata_view,
        user_account_view,
        collection_view,
        process_view,
    ) = run_sync(_get_views())
    if server_metadata_view is not None:
        app.add_view(server_metadata_view)
    if user_account_view is not None:
        app.add_view(user_account_view)
    if collection_view is not None:
        app.add_view(collection_view)
    if process_view is not None:
        app.add_view(process_view)
    return app
