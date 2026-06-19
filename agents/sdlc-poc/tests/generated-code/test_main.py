import pytest
from httpx import AsyncClient
from main import app

@pytest.mark.asyncio
async def test_create_todo():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/todos", json={"title": "Test Todo"})
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["title"] == "Test Todo"
        assert data["done"] is False

@pytest.mark.asyncio
async def test_read_todos():
    async with AsyncClient(app=app, base_url="http://test") as client:
        await client.post("/todos", json={"title": "First Todo"})
        await client.post("/todos", json={"title": "Second Todo"})
        response = await client.get("/todos")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

@pytest.mark.asyncio
async def test_read_todo():
    async with AsyncClient(app=app, base_url="http://test") as client:
        await client.post("/todos", json={"title": "Test Todo"})
        response = await client.get("/todos/1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["title"] == "Test Todo"

@pytest.mark.asyncio
async def test_read_todo_not_found():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/todos/999")
        assert response.status_code == 404

@pytest.mark.asyncio
async def test_update_todo():
    async with AsyncClient(app=app, base_url="http://test") as client:
        await client.post("/todos", json={"title": "Test Todo"})
        response = await client.put("/todos/1", json={"done": True})
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["done"] is True

@pytest.mark.asyncio
async def test_delete_todo():
    async with AsyncClient(app=app, base_url="http://test") as client:
        await client.post("/todos", json={"title": "Test Todo"})
        response = await client.delete("/todos/1")
        assert response.status_code == 204

@pytest.mark.asyncio
async def test_delete_todo_not_found():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.delete("/todos/999")
        assert response.status_code == 404