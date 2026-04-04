"""MVP: haal event op via Collective, genereer LinkedIn post draft."""
import sys
import os
from dotenv import load_dotenv
from providers.collective import CollectiveProvider, event_id_from_url
from summary.generator import generate_linkedin_post

load_dotenv()


def main():
    provider = CollectiveProvider()

    print("Authenticeren met Collective...")
    provider.authenticate()
    print("OK\n")

    # Optie 1: event URL als argument
    #   python3 main.py <url>
    if len(sys.argv) > 1:
        url = sys.argv[1]
        event_id = event_id_from_url(url)
        print(f"Event ID uit URL: {event_id}")
        event = provider.fetch_event_by_id(event_id)

    # Optie 2: kies uit jouw tickets
    else:
        print("Tickets ophalen...")
        tickets = provider.fetch_tickets()
        if not tickets:
            print("Geen tickets gevonden.")
            return

        print(f"{len(tickets)} ticket(s) gevonden:\n")
        for i, t in enumerate(tickets):
            print(f"  [{i}] {t.event_title}  ({t.registration_date[:10]})")

        print()
        choice = int(input("Kies een ticket nummer: "))
        event = provider.fetch_event(tickets[choice])

    print(f"\nEvent: {event.title}")
    print(f"Datum: {event.date}\n")

    # Gebruiker geeft prompt mee
    print("Hoe wil je de post? (druk Enter voor standaard)")
    print("  bv. 'schrijf in het Nederlands, focus op wat ik ga leren, voeg hashtags toe'")
    user_prompt = input("> ").strip() or "Schrijf een professionele maar persoonlijke post in het Nederlands."

    from summary.generator import detect_llm
    llm = detect_llm()
    print(f"\nLinkedIn post genereren via {llm}...\n")
    post = generate_linkedin_post(event, user_prompt)

    print("=" * 60)
    print(post)
    print("=" * 60)


if __name__ == "__main__":
    main()
