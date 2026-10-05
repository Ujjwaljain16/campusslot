def slot(room_id, start_hour, end_hour, day="2026-10-06", **overrides):
    """A booking payload for whole-hour UTC times on one day."""
    payload = {
        "room_id": room_id,
        "purpose": "Operating Systems lab",
        "booked_by": "Ujjwal",
        "start_time": f"{day}T{start_hour:02d}:00:00Z",
        "end_time": f"{day}T{end_hour:02d}:00:00Z",
    }
    payload.update(overrides)
    return payload


def book(client, room_id, start_hour, end_hour, **overrides):
    response = client.post("/api/bookings", json=slot(room_id, start_hour, end_hour, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


# ---- create / read ---------------------------------------------------------------------------


def test_create_booking_returns_201_with_confirmed_status(client, room):
    body = book(client, room["id"], 10, 11)
    assert body["status"] == "confirmed"
    assert body["room_id"] == room["id"]
    assert body["start_time"].startswith("2026-10-06T10:00:00")


def test_get_booking_by_id_and_missing_booking_is_404(client, room):
    created = book(client, room["id"], 10, 11)
    assert client.get(f"/api/bookings/{created['id']}").json()["purpose"] == "Operating Systems lab"
    assert client.get("/api/bookings/9999").status_code == 404


def test_list_bookings_filters_by_room_and_day(client, room):
    other = client.post(
        "/api/rooms",
        json={"name": "Lab B", "building": "Block 1", "capacity": 20, "kind": "lab"},
    ).json()
    book(client, room["id"], 9, 10)
    book(client, other["id"], 9, 10)
    book(client, room["id"], 9, 10, day="2026-10-07")

    everything = client.get("/api/bookings").json()
    assert len(everything) == 3

    one_room = client.get(f"/api/bookings?room_id={room['id']}").json()
    assert len(one_room) == 2

    one_day = client.get(f"/api/bookings?room_id={room['id']}&day=2026-10-06").json()
    assert len(one_day) == 1


def test_list_bookings_respects_the_callers_timezone(client, room):
    # 22:00 UTC on the 6th is 03:30 on the 7th in India (UTC+5:30).
    book(client, room["id"], 22, 23)
    in_utc = client.get("/api/bookings?day=2026-10-06").json()
    in_india = client.get("/api/bookings?day=2026-10-06&tz_offset_minutes=330").json()
    assert len(in_utc) == 1
    assert in_india == []


# ---- overlap rules ---------------------------------------------------------------------------


def test_overlapping_booking_is_rejected_with_409_and_names_the_blocker(client, room):
    first = book(client, room["id"], 10, 12)
    response = client.post("/api/bookings", json=slot(room["id"], 11, 13))
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["conflicting_booking"]["id"] == first["id"]


def test_booking_fully_inside_another_is_rejected(client, room):
    book(client, room["id"], 9, 13)
    assert client.post("/api/bookings", json=slot(room["id"], 10, 11)).status_code == 409


def test_booking_that_fully_contains_another_is_rejected(client, room):
    book(client, room["id"], 10, 11)
    assert client.post("/api/bookings", json=slot(room["id"], 9, 13)).status_code == 409


def test_adjacent_slots_are_allowed_on_both_sides(client, room):
    """10:00-11:00 exists, so 11:00-12:00 and 09:00-10:00 must both be accepted."""
    book(client, room["id"], 10, 11)
    book(client, room["id"], 11, 12)
    book(client, room["id"], 9, 10)


def test_same_time_in_a_different_room_is_allowed(client, room):
    other = client.post(
        "/api/rooms",
        json={"name": "Lab B", "building": "Block 1", "capacity": 20, "kind": "lab"},
    ).json()
    book(client, room["id"], 10, 11)
    book(client, other["id"], 10, 11)


def test_cancelled_booking_frees_the_slot(client, room):
    first = book(client, room["id"], 10, 11)
    cancel = {**slot(room["id"], 10, 11), "status": "cancelled"}
    assert client.put(f"/api/bookings/{first['id']}", json=cancel).status_code == 200
    book(client, room["id"], 10, 11, booked_by="Someone else")


# ---- validation and missing resources ------------------------------------------------------


def test_end_before_start_is_rejected_with_422(client, room):
    response = client.post("/api/bookings", json=slot(room["id"], 12, 10))
    assert response.status_code == 422


def test_zero_length_and_overlong_bookings_are_rejected_with_422(client, room):
    assert client.post("/api/bookings", json=slot(room["id"], 10, 10)).status_code == 422
    too_long = {**slot(room["id"], 0, 1), "end_time": "2026-10-06T23:00:00Z"}
    assert client.post("/api/bookings", json=too_long).status_code == 422


def test_booking_an_unknown_room_is_404(client):
    assert client.post("/api/bookings", json=slot(9999, 10, 11)).status_code == 404


def test_booking_a_switched_off_room_is_409(client, room):
    off = {**room, "is_active": False}
    off.pop("id")
    assert client.put(f"/api/rooms/{room['id']}", json=off).status_code == 200
    assert client.post("/api/bookings", json=slot(room["id"], 10, 11)).status_code == 409


# ---- update / delete -------------------------------------------------------------------------


def test_update_booking_changes_its_fields(client, room):
    created = book(client, room["id"], 10, 11)
    changed = {**slot(room["id"], 14, 16), "purpose": "Viva rehearsal"}
    response = client.put(f"/api/bookings/{created['id']}", json=changed)
    assert response.status_code == 200
    assert response.json()["purpose"] == "Viva rehearsal"
    assert response.json()["start_time"].startswith("2026-10-06T14:00:00")


def test_a_booking_can_be_extended_without_conflicting_with_itself(client, room):
    created = book(client, room["id"], 10, 11)
    longer = slot(room["id"], 10, 12)
    assert client.put(f"/api/bookings/{created['id']}", json=longer).status_code == 200


def test_moving_a_booking_into_another_one_is_409(client, room):
    book(client, room["id"], 10, 11)
    second = book(client, room["id"], 13, 14)
    response = client.put(f"/api/bookings/{second['id']}", json=slot(room["id"], 10, 12))
    assert response.status_code == 409


def test_update_missing_booking_is_404(client, room):
    assert client.put("/api/bookings/9999", json=slot(room["id"], 10, 11)).status_code == 404


def test_delete_booking_removes_it_and_a_second_delete_is_404(client, room):
    created = book(client, room["id"], 10, 11)
    assert client.delete(f"/api/bookings/{created['id']}").status_code == 204
    assert client.get(f"/api/bookings/{created['id']}").status_code == 404
    assert client.delete(f"/api/bookings/{created['id']}").status_code == 404


def test_room_with_bookings_cannot_be_deleted(client, room):
    book(client, room["id"], 10, 11)
    assert client.delete(f"/api/rooms/{room['id']}").status_code == 409


# ---- metrics ---------------------------------------------------------------------------------


def test_conflicts_and_creations_are_counted_in_prometheus_metrics(client, room):
    book(client, room["id"], 10, 11)
    client.post("/api/bookings", json=slot(room["id"], 10, 11))
    text = client.get("/metrics").text
    assert 'campusslot_bookings_total{action="created"}' in text
    assert 'campusslot_booking_conflicts_total{layer="application"}' in text
