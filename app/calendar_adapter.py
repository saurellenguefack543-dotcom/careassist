"""Adaptateurs d'agenda.

- SQLiteCalendar : la base SQLite est la seule source de vérité (défaut).
- MockGoogleCalendar : simule l'API Google Calendar (events.insert / events.delete)
  en journalisant les événements dans data/mock_google_calendar.jsonl.
- GoogleCalendarAdapter : squelette pour brancher la vraie API (google-api-python-client).
"""
from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod

from . import config, db


class CalendarAdapter(ABC):
    name = "abstract"

    @abstractmethod
    def create_event(self, summary: str, start_iso: str, duration_min: int, description: str = "") -> str | None:
        """Crée un événement et renvoie son identifiant externe."""

    @abstractmethod
    def delete_event(self, event_id: str) -> None:
        """Supprime un événement."""


class SQLiteCalendar(CalendarAdapter):
    name = "sqlite"

    def create_event(self, summary, start_iso, duration_min, description=""):
        return None

    def delete_event(self, event_id):
        return None


class MockGoogleCalendar(CalendarAdapter):
    """Reproduit la forme des payloads Google Calendar v3, sans réseau."""

    name = "mock_google"

    def _path(self) -> str:
        return os.path.join(os.path.dirname(config.db_path()), "mock_google_calendar.jsonl")

    def _write(self, record: dict) -> None:
        with open(self._path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def create_event(self, summary, start_iso, duration_min, description=""):
        event_id = "mock-gcal-" + uuid.uuid4().hex[:12]
        self._write({
            "op": "events.insert",
            "calendarId": "primary",
            "id": event_id,
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": config.timezone()},
            "durationMinutes": duration_min,
            "at": db.now_iso(),
        })
        return event_id

    def delete_event(self, event_id):
        self._write({"op": "events.delete", "calendarId": "primary", "id": event_id, "at": db.now_iso()})


class GoogleCalendarAdapter(CalendarAdapter):  # pragma: no cover - squelette
    """À implémenter avec google-api-python-client + compte de service :

        service = build("calendar", "v3", credentials=creds)
        service.events().insert(calendarId=CAL_ID, body=event).execute()
    """

    name = "google"

    def create_event(self, summary, start_iso, duration_min, description=""):
        raise NotImplementedError("Brancher google-api-python-client ici")

    def delete_event(self, event_id):
        raise NotImplementedError


def get_calendar() -> CalendarAdapter:
    backend = config.env("CALENDAR_BACKEND", "mock_google")
    if backend == "google":
        return GoogleCalendarAdapter()
    if backend == "sqlite":
        return SQLiteCalendar()
    return MockGoogleCalendar()
