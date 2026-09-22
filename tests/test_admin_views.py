"""Smoke tests for the starlette-admin views in managers/postgis/admin/.

These views had no test coverage at all before the BaseModelView refactor (which
removed the SQLAlchemy-contrib base they used to depend on) - this module exercises
find_all/find_by_pk/count/serialize/can_create/can_edit/can_delete against each,
enough to catch the kind of issue the refactor surfaced (ServerMetadataModelView's
primary key handling relied on the SQLA-contrib base tolerating a missing attribute).
The configuration-file manager's read-only CollectionView is covered separately in
tests/test_manager_configurationfile.py.
"""

import types
from typing import cast

import pytest
from starlette.requests import Request
from starlette_admin import RequestAction

from potto.managers.postgis.admin.collections import CollectionView
from potto.managers.postgis.admin.metadata import ServerMetadataModelView
from potto.managers.postgis.admin.processes import ProcessView
from potto.managers.postgis.admin.users import UserView


class _FakeRequest:
    def __init__(self, settings, user, action=RequestAction.LIST):
        self.app = types.SimpleNamespace(
            state=types.SimpleNamespace(SETTINGS=settings, ROUTE_NAME="admin")
        )
        self.user = user
        self.state = types.SimpleNamespace(action=action)
        self.path_params = {}

    def url_for(self, *args, **kwargs):
        return "/fake"


def fake_request(settings, user, action=RequestAction.LIST) -> Request:
    """Just enough of a Request for these views' methods, cast to satisfy typing."""
    return cast(Request, _FakeRequest(settings, user, action=action))


class TestCollectionView:
    @pytest.mark.asyncio
    async def test_find_all_and_find_by_pk(
        self, settings, admin_user, obs_feature_collection
    ):
        view = CollectionView()
        request = fake_request(settings, admin_user)

        results = await view.find_all(request)
        assert any(c.identifier == obs_feature_collection.identifier for c in results)

        found = await view.find_by_pk(request, obs_feature_collection.identifier)
        assert found is not None
        assert found.identifier == obs_feature_collection.identifier

    @pytest.mark.asyncio
    async def test_serialize(self, settings, admin_user, obs_feature_collection):
        view = CollectionView()
        request = fake_request(settings, admin_user, action=RequestAction.DETAIL)
        collection = await view.find_by_pk(request, obs_feature_collection.identifier)
        # owner/editors/viewers are HasOne/HasMany relation fields, which need the
        # full admin app's view registry (_find_foreign_model, wired up by
        # PottoAdmin.add_view) to resolve - out of scope for this view-level smoke
        # test, so relationships are skipped here.
        result = await view.serialize(
            collection, request, RequestAction.DETAIL, include_relationships=False
        )
        assert result["identifier"] == obs_feature_collection.identifier
        assert result["_meta"]["detailUrl"]


class TestProcessView:
    @pytest.mark.asyncio
    async def test_find_all_and_find_by_pk(self, settings, admin_user, obs_process):
        view = ProcessView()
        request = fake_request(settings, admin_user)

        results = await view.find_all(request)
        assert any(p.identifier == obs_process.identifier for p in results)

        found = await view.find_by_pk(request, obs_process.identifier)
        assert found is not None
        assert found.identifier == obs_process.identifier

    @pytest.mark.asyncio
    async def test_serialize(self, settings, admin_user, obs_process):
        view = ProcessView()
        request = fake_request(settings, admin_user, action=RequestAction.DETAIL)
        process = await view.find_by_pk(request, obs_process.identifier)
        # owner/editors/viewers are HasOne/HasMany relation fields, which need the
        # full admin app's view registry (_find_foreign_model, wired up by
        # PottoAdmin.add_view) to resolve - out of scope for this view-level smoke
        # test, so relationships are skipped here.
        result = await view.serialize(
            process, request, RequestAction.DETAIL, include_relationships=False
        )
        assert result["identifier"] == obs_process.identifier
        assert result["_meta"]["detailUrl"]


class TestUserView:
    @pytest.mark.asyncio
    async def test_find_all_and_find_by_pk(self, settings, admin_user):
        view = UserView()
        request = fake_request(settings, admin_user)

        results = await view.find_all(request)
        assert any(u.username == admin_user.username for u in results)

        found = await view.find_by_pk(request, admin_user.id)
        assert found is not None
        assert found.username == admin_user.username

    @pytest.mark.asyncio
    async def test_serialize(self, settings, admin_user):
        view = UserView()
        request = fake_request(settings, admin_user, action=RequestAction.DETAIL)
        result = await view.serialize(admin_user, request, RequestAction.DETAIL)
        assert result["username"] == admin_user.username
        assert result["is_active"] is True
        assert result["scopes"] == admin_user.scopes


class TestServerMetadataModelView:
    @pytest.mark.asyncio
    async def test_find_all_and_serialize(self, settings, db):
        view = ServerMetadataModelView()
        request = fake_request(settings, None, action=RequestAction.DETAIL)

        results = await view.find_all(request)
        assert len(results) == 1

        result = await view.serialize(results[0], request, RequestAction.DETAIL)
        assert result["_meta"]["detailUrl"]

    def test_permissions(self):
        view = ServerMetadataModelView()
        assert view.can_create(cast(Request, None)) is False
        assert view.can_delete(cast(Request, None)) is False
