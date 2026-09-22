import uuid

from playwright.sync_api import (
    Page,
    expect,
)
import pytest

pytestmark = pytest.mark.e2e


def test_admin_create_collection(authenticated_page: Page, api_client):
    identifier = f"e2e-admin-coll-{uuid.uuid4().hex[:8]}"
    page = authenticated_page
    page.goto("/admin")
    page.get_by_role("link", name="Collections").click()
    page.get_by_role("link", name="New Collection").click()

    page.get_by_label("Resource identifier").fill(identifier)
    page.get_by_label("Collection type").select_option("feature")
    page.get_by_label("Title", exact=True).fill("E2E admin created collection")
    page.get_by_role("button", name="Save", exact=True).click()

    try:
        expect(page.get_by_text(identifier)).to_be_visible()
    finally:
        api_client.delete(f"/api/collections/{identifier}")


def test_admin_create_process(authenticated_page: Page):
    identifier = f"e2e-admin-proc-{uuid.uuid4().hex[:8]}"
    page = authenticated_page
    page.goto("/admin")
    page.get_by_role("link", name="Processes").click()
    page.get_by_role("link", name="New Process").click()

    page.get_by_label("Resource identifier").fill(identifier)
    page.get_by_label("Title", exact=True).fill("E2E admin created process")
    page.get_by_label("Version").fill("1.0.0")
    page.get_by_role("button", name="Save", exact=True).click()

    expect(page.get_by_text(identifier)).to_be_visible()

    row = page.get_by_role("row").filter(has_text=identifier)
    row.get_by_role("checkbox").check()
    page.get_by_title("Delete").click()
    page.get_by_role("button", name="Yes, delete").click()

    expect(page.get_by_text(identifier)).not_to_be_visible()
