ROOM = {"name": "Lab A", "building": "Block 1", "capacity": 30, "kind": "lab", "is_active": True}


def create_room(client, **overrides):
    response = client.post("/api/rooms", json={**ROOM, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_room_returns_201_and_the_stored_room(client):
    body = create_room(client)
    assert body["id"] >= 1
    assert body["name"] == "Lab A"
    assert body["is_active"] is True


def test_list_rooms_is_ordered_and_can_hide_inactive_rooms(client):
    create_room(client, name="Lab B", building="Block 2")
    create_room(client, name="Lab A", building="Block 1")
    create_room(client, name="Old Lab", building="Block 1", is_active=False)

    names = [room["name"] for room in client.get("/api/rooms").json()]
    assert names == ["Lab A", "Old Lab", "Lab B"]

    active = [room["name"] for room in client.get("/api/rooms?active_only=true").json()]
    assert "Old Lab" not in active


def test_get_room_by_id_and_missing_room_is_404(client):
    room = create_room(client)
    assert client.get(f"/api/rooms/{room['id']}").json()["name"] == "Lab A"
    assert client.get("/api/rooms/9999").status_code == 404


def test_duplicate_room_name_is_rejected_with_409(client):
    create_room(client)
    response = client.post("/api/rooms", json=ROOM)
    assert response.status_code == 409


def test_update_room_replaces_its_fields(client):
    room = create_room(client)
    changed = {**ROOM, "capacity": 45, "kind": "classroom"}
    response = client.put(f"/api/rooms/{room['id']}", json=changed)
    assert response.status_code == 200
    assert response.json()["capacity"] == 45
    assert response.json()["kind"] == "classroom"


def test_update_missing_room_is_404(client):
    assert client.put("/api/rooms/9999", json=ROOM).status_code == 404


def test_delete_room_removes_it(client):
    room = create_room(client)
    assert client.delete(f"/api/rooms/{room['id']}").status_code == 204
    assert client.get(f"/api/rooms/{room['id']}").status_code == 404


def test_invalid_room_payload_is_rejected_with_422(client):
    assert client.post("/api/rooms", json={**ROOM, "capacity": 0}).status_code == 422
    assert client.post("/api/rooms", json={**ROOM, "kind": "ballroom"}).status_code == 422
    assert client.post("/api/rooms", json={"name": "Only a name"}).status_code == 422
