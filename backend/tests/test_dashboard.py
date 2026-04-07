"""Tests for health, system, and dashboard endpoints."""

import pytest


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_system_info_requires_auth(client):
    resp = await client.get("/api/system/info")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_system_info_authenticated(client, auth_headers):
    resp = await client.get("/api/system/info", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "server_ip" in data
    assert "app_env" in data


@pytest.mark.asyncio
async def test_dashboard_summary(client, auth_headers, sample_door_station):
    resp = await client.get("/api/dashboard/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_devices" in data
    assert data["total_devices"] >= 1
    assert data["door_stations"] >= 1
    assert "recent_activity" in data


@pytest.mark.asyncio
async def test_dashboard_summary_requires_auth(client):
    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 401
