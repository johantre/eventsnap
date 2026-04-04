from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgendaItem:
    time: str
    title: str
    speaker: str = ""
    description: str = ""


@dataclass
class Event:
    id: str
    title: str
    date: str
    location: str
    description: str
    agenda: list[AgendaItem] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_url: str = ""


@dataclass
class Ticket:
    id: str
    event_id: str
    event_title: str
    registration_date: str
    event_date: str = ""
    provider: str = ""
    raw: dict = field(default_factory=dict)


class EventProvider(ABC):
    @abstractmethod
    def authenticate(self) -> None:
        """Authenticate with the provider."""

    @abstractmethod
    def fetch_tickets(self) -> list[Ticket]:
        """Return all tickets for the authenticated user."""

    @abstractmethod
    def fetch_event(self, ticket: Ticket) -> Event:
        """Return full event details for a given ticket."""

    @abstractmethod
    def fetch_event_by_id(self, event_id: str) -> Event:
        """Return full event details by provider-specific event ID."""
