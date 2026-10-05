from datetime import UTC, datetime, timedelta

from tests.test_bookings import book, slot

DAY = "2026-10-06"


def make_room(client, name):
    response = client.post(
        "/api/rooms",
        json={"name": name, "building": "Block 1", "capacity": 30, "kind": "lab"},
    )
    assert response.status_code == 201
    return response.json()


def test_stats_calculates_utilisation_inside_the_opening_window(client):
    lab_a = make_room(client, "Lab A")
    lab_b = make_room(client, "Lab B")
    # The default opening window is 08:00-20:00, which is 720 minutes.
    book(client, lab_a["id"], 8, 14)  # 6 hours = 360 min = 50.0%
    book(client, lab_b["id"], 9, 12)  # 3 hours = 180 min = 25.0%

    body = client.get(f"/api/bookings/stats?day={DAY}").json()

    by_name = {room["name"]: room for room in body["rooms"]}
    assert by_name["Lab A"]["booked_minutes"] == 360
    assert by_name["Lab A"]["utilisation_pct"] == 50.0
    assert by_name["Lab B"]["utilisation_pct"] == 25.0
    assert body["average_utilisation_pct"] == 37.5
    assert body["busiest_room"]["name"] == "Lab A"
    assert body["day_confirmed"] == 2
    assert body["day"] == DAY


def test_stats_only_counts_the_part_of_a_booking_inside_opening_hours(client):
    lab = make_room(client, "Lab A")
    book(client, lab["id"], 7, 9)  # only 08:00-09:00 is inside the window

    body = client.get(f"/api/bookings/stats?day={DAY}").json()
    assert body["rooms"][0]["booked_minutes"] == 60


def test_stats_ignore_cancelled_bookings_and_switched_off_rooms(client):
    lab = make_room(client, "Lab A")
    off = make_room(client, "Old Lab")
    kept = book(client, lab["id"], 9, 10)
    book(client, off["id"], 9, 10)
    cancel = {**slot(lab["id"], 9, 10), "status": "cancelled"}
    client.put(f"/api/bookings/{kept['id']}", json=cancel)
    client.put(
        f"/api/rooms/{off['id']}",
        json={
            "name": "Old Lab",
            "building": "Block 1",
            "capacity": 30,
            "kind": "lab",
            "is_active": False,
        },
    )

    body = client.get(f"/api/bookings/stats?day={DAY}").json()
    assert [room["name"] for room in body["rooms"]] == ["Lab A"]
    assert body["rooms"][0]["booked_minutes"] == 0
    assert body["busiest_room"] is None


def test_stats_use_the_callers_timezone_for_the_day(client):
    lab = make_room(client, "Lab A")
    # 22:00 UTC on the 6th is 03:30 on the 7th in India, so it belongs to the 7th there.
    book(client, lab["id"], 22, 23)
    sixth = client.get(f"/api/bookings/stats?day={DAY}&tz_offset_minutes=330").json()
    seventh = client.get("/api/bookings/stats?day=2026-10-07&tz_offset_minutes=330").json()
    assert sixth["day_confirmed"] == 0
    assert seventh["day_confirmed"] == 1


def test_stats_report_rooms_in_use_right_now(client):
    lab = make_room(client, "Lab A")
    now = datetime.now(UTC)
    payload = {
        "room_id": lab["id"],
        "purpose": "Running now",
        "booked_by": "Ujjwal",
        "start_time": (now - timedelta(minutes=30)).isoformat(),
        "end_time": (now + timedelta(minutes=30)).isoformat(),
    }
    assert client.post("/api/bookings", json=payload).status_code == 201

    body = client.get("/api/bookings/stats").json()
    assert body["rooms_in_use_now"] == 1
    assert body["total_confirmed"] == 1


def test_stats_with_no_data_returns_zeros_not_errors(client):
    body = client.get(f"/api/bookings/stats?day={DAY}").json()
    assert body["rooms"] == []
    assert body["average_utilisation_pct"] == 0.0
    assert body["busiest_room"] is None
    assert body["total_confirmed"] == 0
