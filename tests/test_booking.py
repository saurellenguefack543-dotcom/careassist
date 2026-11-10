import pytest

from app import booking, db


def test_seed_creates_one_practice_per_specialty(client):
    practices = db.list_practices()
    assert {p["specialty"] for p in practices} == {"dentiste", "psychologue", "ophtalmologue", "generaliste", "kinesitherapeute"}


def test_find_slots_scoped_to_practice(client):
    psy = db.get_practice("psychologue")
    slots = booking.find_slots(practice_id=psy["id"], limit=5)
    assert slots and all(s["duration_min"] == 60 for s in slots)
    assert all(s["is_emergency"] == 0 for s in slots)


def test_book_and_double_booking_and_cancel(client):
    p = db.get_practice("dentiste")
    slot = booking.find_slots(practice_id=p["id"], limit=1)[0]
    appt = booking.book(slot["id"], "Jean Test", "06 11 22 33 44", "Contrôle")
    assert appt["status"] == "confirmed" and appt["calendar_event_id"].startswith("mock-gcal-")
    with pytest.raises(booking.BookingError):
        booking.book(slot["id"], "Autre Patient", "06 00 00 00 00")
    assert booking.upcoming_for_phone("+33 6 11 22 33 44")[0]["id"] == appt["id"]
    booking.cancel(appt["id"])
    assert booking.get_slot(slot["id"])["booked"] == 0
    with pytest.raises(booking.BookingError):
        booking.cancel(appt["id"])


def test_rest_endpoints(client):
    slots = client.get("/api/slots", params={"practice": "ophtalmologue", "limit": 2}).json()["slots"]
    assert len(slots) == 2
    r = client.post("/api/appointments", json={"slot_id": slots[0]["id"], "patient_name": "Ana Lopes", "phone": "0611223344"})
    assert r.status_code == 201
    assert client.post("/api/appointments", json={"slot_id": slots[0]["id"], "patient_name": "Ana Lopes", "phone": "0611223344"}).status_code == 409
    assert client.delete(f"/api/appointments/{r.json()['id']}").json()["status"] == "cancelled"
