import os
import re
import requests
from bs4 import BeautifulSoup
from .base import Event, EventProvider, Ticket

PUBLIC_BASE = "https://www.wintercircus.be"


def event_id_from_url(url: str) -> int:
    """Extract event ID from a Collective event URL slug.

    e.g. /event/wintercircus-x-techwolf-present-ai-day-2026-535/ → 535
    """
    match = re.search(r"-(\d+)/?(?:register)?/?$", url.rstrip("/"))
    if not match:
        raise ValueError(f"Cannot extract event ID from URL: {url}")
    return int(match.group(1))


class CollectiveProvider(EventProvider):
    """Event provider for Collective / Wintercircus (Odoo backend)."""

    def __init__(self, url: str = None, email: str = None, password: str = None):
        self.base_url = url or os.environ["COLLECTIVE_URL"]
        self.email = email or os.environ["COLLECTIVE_EMAIL"]
        self.password = password or os.environ["COLLECTIVE_PASSWORD"]
        self.session = requests.Session()

    def authenticate(self) -> None:
        resp = self.session.post(
            f"{self.base_url}/web/session/authenticate",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "db": self._db_name(),
                    "login": self.email,
                    "password": self.password,
                },
            },
        )
        result = resp.json()
        if "error" in result or not result.get("result", {}).get("uid"):
            raise RuntimeError(f"Authentication failed: {result}")
        self.partner_id = result["result"].get("partner_id")

    def _db_name(self) -> str:
        resp = self.session.post(
            f"{self.base_url}/web/database/list",
            json={"jsonrpc": "2.0", "method": "call", "params": {}},
        )
        databases = resp.json().get("result", [])
        if not databases:
            raise RuntimeError("No databases found on this Odoo instance.")
        return databases[0]

    def _call(self, model: str, method: str, args: list, kwargs: dict = None, _retry: bool = True) -> dict:
        resp = self.session.post(
            f"{self.base_url}/web/dataset/call_kw",
            timeout=10,
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": model,
                    "method": method,
                    "args": args,
                    "kwargs": kwargs or {},
                },
            },
        )
        result = resp.json()
        if "error" in result:
            error = result["error"]
            if _retry and isinstance(error, dict) and error.get("code") == 100:
                self.authenticate()
                return self._call(model, method, args, kwargs, _retry=False)
            raise RuntimeError(f"API error: {error}")
        return result["result"]

    def fetch_tickets(self) -> list[Ticket]:
        domain = [["partner_id", "=", self.partner_id]] if self.partner_id else []
        records = self._call(
            model="event.registration",
            method="search_read",
            args=[domain],
            kwargs={
                "fields": ["id", "event_id", "name", "create_date"],
                "order": "id desc",
                "limit": 100,
            },
        )
        # Deduplicate by event_id, keep most recent registration per event
        seen = {}
        for r in records:
            if not r["event_id"]:
                continue
            eid = r["event_id"][0]
            if eid not in seen:
                seen[eid] = r

        # Try to fetch event dates in bulk (may fail for members without access)
        event_dates = {}
        try:
            event_ids = [r["event_id"][0] for r in seen.values()]
            date_records = self._call(
                model="event.event",
                method="read",
                args=[event_ids],
                kwargs={"fields": ["id", "date_begin"]},
            )
            event_dates = {str(r["id"]): str(r.get("date_begin", ""))[:10] for r in date_records}
        except RuntimeError:
            pass

        return [
            Ticket(
                id=str(r["id"]),
                event_id=str(r["event_id"][0]),
                event_title=r["event_id"][1],
                registration_date=str(r.get("create_date", ""))[:10],
                event_date=event_dates.get(str(r["event_id"][0]), ""),
                provider="collective",
                raw=r,
            )
            for r in seen.values()
        ]

    def fetch_event_by_id(self, event_id: str) -> Event:
        return self._fetch_event_record(int(event_id))

    def fetch_event(self, ticket: Ticket) -> Event:
        return self._fetch_event_record(int(ticket.event_id))

    def _fetch_event_record(self, event_id: int) -> Event:
        try:
            return self._fetch_via_odoo(event_id)
        except RuntimeError:
            return self._fetch_via_public_website(event_id)

    def _fetch_via_odoo(self, event_id: int) -> Event:
        records = self._call(
            model="event.event",
            method="read",
            args=[[event_id]],
            kwargs={
                "fields": [
                    "id", "name", "date_begin", "date_end",
                    "address_id", "description", "tag_ids", "website_url",
                ],
            },
        )
        r = records[0]
        location = r["address_id"][1] if r.get("address_id") else ""

        tags = []
        if r.get("tag_ids"):
            tag_records = self._call(
                model="event.tag",
                method="read",
                args=[r["tag_ids"]],
                kwargs={"fields": ["name"]},
            )
            tags = [t["name"] for t in tag_records]

        return Event(
            id=str(r["id"]),
            title=r["name"],
            date=f"{r.get('date_begin', '')} → {r.get('date_end', '')}",
            location=location,
            description=r.get("description") or "",
            tags=tags,
            source_url=r.get("website_url") or f"{PUBLIC_BASE}/en/events/id/{event_id}",
        )

    def _fetch_via_public_website(self, event_id: int) -> Event:
        url = f"{PUBLIC_BASE}/en/events/id/{event_id}"
        resp = requests.get(url)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Strip nav/footer noise, grab main content text
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        # Best-effort title from <title> or <h1>
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else f"Event {event_id}"

        return Event(
            id=str(event_id),
            title=title,
            date="",
            location="Wintercircus, Gent",
            description=text,
            source_url=url,
        )
