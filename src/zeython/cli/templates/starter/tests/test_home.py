from main import app

from zeython.testing import client


async def test_index_returns_welcome_message():
    async with client(app) as http:
        response = await http.get("/")

    assert response.status_code == 200
    assert "message" in response.json()
