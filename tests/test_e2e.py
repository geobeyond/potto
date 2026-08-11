from playwright.sync_api import (
    Page,
    expect,
)
import pytest

pytestmark = pytest.mark.e2e


def test_webui_login(authenticated_page: Page):
    authenticated_page.goto("/")
    expect(authenticated_page.get_by_role("link", name="login")).not_to_be_visible()
    expect(authenticated_page.locator("#user-menu-toggle")).to_be_visible()


def test_webui_logout(fresh_authenticated_page: Page):
    fresh_authenticated_page.get_by_role("link", name="Log out").click()
    expect(fresh_authenticated_page.get_by_role("link", name="login")).to_be_visible()


def test_webui_collection_detail_displays_collection(
    authenticated_page: Page, e2e_collection
):
    authenticated_page.goto(f"/collections/{e2e_collection['id']}")
    expect(
        authenticated_page.get_by_role("heading", name=e2e_collection["title"])
    ).to_be_visible()
