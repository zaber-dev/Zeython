from main import app

from zeython.testing import client


async def test_index_renders_welcome_page():
    async with client(app) as http:
        response = await http.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "{{ project_name }}" in response.text
