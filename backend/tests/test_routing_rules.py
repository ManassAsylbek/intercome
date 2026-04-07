"""Tests for routing rules API."""

import pytest


@pytest.mark.asyncio
async def test_create_routing_rule(client, auth_headers, sample_door_station):
    payload = {
        "name": "Front door → Living room",
        "call_code": "1001",
        "source_device_id": sample_door_station.id,
        "target_sip_account": "home001",
        "enabled": True,
        "priority": 10,
    }
    resp = await client.post("/api/routing-rules", headers=auth_headers, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["call_code"] == "1001"
    assert data["id"] > 0
    return data["id"]


@pytest.mark.asyncio
async def test_list_routing_rules(client, auth_headers, sample_door_station):
    # Create a rule first
    await client.post(
        "/api/routing-rules",
        headers=auth_headers,
        json={"name": "Rule 1", "call_code": "2001", "enabled": True},
    )
    resp = await client.get("/api/routing-rules", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_update_routing_rule(client, auth_headers):
    # Create
    create_resp = await client.post(
        "/api/routing-rules",
        headers=auth_headers,
        json={"name": "Old Name", "call_code": "3001"},
    )
    rule_id = create_resp.json()["id"]

    # Update
    resp = await client.put(
        f"/api/routing-rules/{rule_id}",
        headers=auth_headers,
        json={"name": "New Name", "call_code": "3002"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["call_code"] == "3002"


@pytest.mark.asyncio
async def test_delete_routing_rule(client, auth_headers):
    create_resp = await client.post(
        "/api/routing-rules",
        headers=auth_headers,
        json={"name": "To Delete", "call_code": "4001"},
    )
    rule_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/routing-rules/{rule_id}", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get(f"/api/routing-rules/{rule_id}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_routing_rules_requires_auth(client):
    resp = await client.get("/api/routing-rules")
    assert resp.status_code == 401
