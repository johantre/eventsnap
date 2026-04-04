import requests
from .base import Event, EventProvider, Ticket

GQL_URL = "https://api.meetup.com/gql"


class MeetupProvider(EventProvider):
    """Event provider for Meetup (GraphQL API, OAuth2 bearer token)."""

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def authenticate(self) -> None:
        pass  # Token-based

    def _gql(self, query: str, variables: dict = None) -> dict:
        resp = self.session.post(GQL_URL, json={"query": query, "variables": variables or {}})
        resp.raise_for_status()
        return resp.json()

    def fetch_tickets(self) -> list[Ticket]:
        result = self._gql("""
            query {
                self {
                    upcomingEvents(input: {}) {
                        edges {
                            node {
                                id
                                title
                                dateTime
                            }
                        }
                    }
                }
            }
        """)
        edges = (
            result.get("data", {})
            .get("self", {})
            .get("upcomingEvents", {})
            .get("edges", [])
        )
        tickets = []
        for edge in edges:
            node = edge.get("node") or {}
            tickets.append(Ticket(
                id=node["id"],
                event_id=node["id"],
                event_title=node.get("title", ""),
                registration_date=(node.get("dateTime") or "")[:10],
                event_date=(node.get("dateTime") or "")[:10],
                provider="meetup",
                raw=node,
            ))
        return tickets

    def fetch_event(self, ticket: Ticket) -> Event:
        return self.fetch_event_by_id(ticket.event_id)

    def fetch_event_by_id(self, event_id: str) -> Event:
        result = self._gql("""
            query GetEvent($id: ID!) {
                event(id: $id) {
                    id
                    title
                    dateTime
                    description
                    venue {
                        name
                        address
                        city
                    }
                    eventUrl
                    topics {
                        edges {
                            node { name }
                        }
                    }
                }
            }
        """, {"id": event_id})
        e = result.get("data", {}).get("event") or {}
        venue = e.get("venue") or {}
        location = ", ".join(filter(None, [
            venue.get("name"), venue.get("address"), venue.get("city")
        ]))
        topics = [
            edge["node"]["name"]
            for edge in (e.get("topics") or {}).get("edges", [])
        ]

        return Event(
            id=event_id,
            title=e.get("title", ""),
            date=e.get("dateTime", ""),
            location=location,
            description=e.get("description", ""),
            tags=topics,
            source_url=e.get("eventUrl", ""),
        )
