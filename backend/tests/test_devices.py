"""Tests for device management API."""

import pytest


@pytest.mark.asyncio
async def test_list_devices_empty(client, auth_headers):
    resp = await client.get("/api/devices", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_create_device(client, auth_headers):
    payload = {
        "name": "Front Door",
        "device_type": "door_station",
        "ip_address": "192.168.31.31",
        "web_port": 8000,
        "enabled": True,
        "unlock_enabled": True,
        "unlock_method": "http_get",
        "unlock_url": "http://192.168.31.31:8000/unlock",
        "unlock_username": "admin",
        "unlock_password": "123456",
        "rtsp_enabled": True,
        "rtsp_url": "rtsp://admin:123456@192.168.31.31:554/h264",
    }
    resp = await client.post("/api/devices", headers=auth_headers, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Front Door"
    assert data["device_type"] == "door_station"
    assert data["id"] > 0
    return data["id"]


@pytest.mark.asyncio
async def test_get_device(client, auth_headers, sample_door_station):
    resp = await client.get(f"/api/devices/{sample_door_station.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == sample_door_station.id
    assert data["name"] == sample_door_station.name


@pytest.mark.asyncio
async def test_get_device_not_found(client, auth_headers):
    resp = await client.get("/api/devices/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_device(client, auth_headers, sample_door_station):
    resp = await client.put(
        f"/api/devices/{sample_door_station.id}",
        headers=auth_headers,
        json={"name": "Updated Door"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Door"


@pytest.mark.asyncio
async def test_delete_device(client, auth_headers, sample_door_station):
    resp = await client.delete(f"/api/devices/{sample_door_station.id}", headers=auth_headers)
    assert resp.status_code == 204

    # Verify gone
    resp = await client.get(f"/api/devices/{sample_door_station.id}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_devices_with_filter(client, auth_headers, sample_door_station):
    # Create a home station too
    await client.post(
        "/api/devices",
        headers=auth_headers,
        json={"name": "Home Station", "device_type": "home_station"},
    )
    resp = await client.get("/api/devices?device_type=door_station", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["device_type"] == "door_station"


@pytest.mark.asyncio
async def test_list_devices_requires_auth(client):
    resp = await client.get("/api/devices")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_test_connection_no_ip(client, auth_headers, db_session):
    from app.models import Device, DeviceType

    device = Device(name="NoIP", device_type=DeviceType.HOME_STATION, ip_address=None)
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(device)

    resp = await client.post(f"/api/devices/{device.id}/test-connection", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_test_unlock_not_configured(client, auth_headers, db_session):
    from app.models import Device, DeviceType

    device = Device(
        name="NoUnlock",
        device_type=DeviceType.DOOR_STATION,
        ip_address="192.168.31.31",
        unlock_enabled=False,
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(device)

    resp = await client.post(f"/api/devices/{device.id}/test-unlock", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is False
