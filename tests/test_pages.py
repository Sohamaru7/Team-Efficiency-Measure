import pytest

PAGE_PATHS = [
    "/login",
    "/",
    "/tasks",
    "/tasks/new",
    "/tasks/1",
    "/tasks/1/edit",
    "/daily-update",
    "/performance",
    "/manager",
    "/manager/assistant",
    "/manager/import-export",
    "/manager/daily-report",
]


@pytest.mark.parametrize("path", PAGE_PATHS)
def test_page_renders(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
