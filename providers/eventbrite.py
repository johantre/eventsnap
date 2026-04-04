import requests
from .base import Event, EventProvider, Ticket

BASE = "https://www.eventbriteapi.com/v3"


class EventbriteProvider(EventProvider):
    """Event provider for Eventbrite (REST API, personal OAuth token)."""

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def authenticate(self) -> None:
        pass  # Token-based, no separate auth step needed

    def fetch_tickets(self) -> list[Ticket]:
        resp = self.session.get(
            f"{BASE}/users/me/orders/",
            params={"expand": "event"},
            timeout=10,
        )
        resp.raise_for_status()
        orders = resp.json().get("orders", [])
        tickets = []
        for order in orders:
            event = order.get("event") or {}
            if not event:
                continue
            tickets.append(Ticket(
                id=order["id"],
                event_id=event["id"],
                event_title=event.get("name", {}).get("text", ""),
                registration_date=order.get("created", "")[:10],
                event_date=(event.get("start") or {}).get("local", "")[:10],
                provider="eventbrite",
                raw={"event": event},
            ))
        return tickets

    def fetch_event(self, ticket: Ticket) -> Event:
        return self.fetch_event_by_id(ticket.event_id)

    def fetch_event_by_id(self, event_id: str) -> Event:
        resp = self.session.get(
            f"{BASE}/events/{event_id}/",
            params={"expand": "description,venue"},
        )
        resp.raise_for_status()
        e = resp.json()
        venue = e.get("venue") or {}
        address = venue.get("address") or {}
        location = address.get("localized_address_display") or venue.get("name", "")
        description = (e.get("description") or {}).get("text") or (e.get("description") or {}).get("html", "")

        return Event(
            id=event_id,
            title=(e.get("name") or {}).get("text", ""),
            date=(e.get("start") or {}).get("local", ""),
            location=location,
            description=description,
            source_url=e.get("url", ""),
        )
