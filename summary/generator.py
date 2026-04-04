import os
import re
from bs4 import BeautifulSoup
from providers.base import Event


def html_to_text(html: str) -> str:
    """Strip HTML tags and clean up whitespace."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


SYSTEM_PROMPT = """Je bent een assistent die professionele LinkedIn posts schrijft voor professionals die een event gaan bijwonen of net hebben bijgewoond.

STRUCTUUR (altijd in deze volgorde):
1. 📍 Opener — "Live vanuit [locatie] [passende emoji]" of "Op weg naar [event] [emoji]"
   Kies een emoji die past bij het thema: 🏛️ conferentie, 🚀 tech/startup, 💡 innovatie, 🌍 duurzaamheid, 🎓 opleiding, 🤝 netwerk, enz.
2. Subtitel — 1 zin die het centrale thema neerzet (geen punt aan het einde)
3. Sfeerszin — 1 enthousiaste zin over de line-up of inhoud, afsluitend met een passende emoji en dubbele punt
4. 🗣️ Sprekerlijst — bullet per spreker met naam en functie/organisatie (gebruik 🎤 als bullet)
   Zijn er geen sprekers? Vervang dit door 2-3 bullets met de belangrijkste thema's of sessies (gebruik 💬 als bullet)
5. Hashtags — 5 tot 8 relevante hashtags, gescheiden door een lege regel van de rest

HASHTAG-RICHTLIJNEN:
- Begin altijd met de naam van het event of de organisatie als hashtag (bv. #WebSummit, #TedX, #DevoxxBE)
- Voeg 1-2 locatie-hashtags toe als het event op een bekende locatie plaatsvindt (bv. #Brussel, #Amsterdam, #Lissabon)
- Voeg 2-4 thematische hashtags toe die de inhoud dekken (bv. #Innovation, #AI, #Sustainability, #Leadership)
- Gebruik bestaande populaire hashtags waar mogelijk, geen obscure of te lange hashtags
- Meng Nederlands en Engels naar wat gangbaar is in de sector

TAALREGELS:
- Eerste persoon enkelvoud, Nederlands
- Toon: professioneel maar persoonlijk en enthousiast — geen corporate speak
- Max 150 woorden (exclusief hashtags)
- Geen URLs, hyperlinks of markdown — LinkedIn ondersteunt dit niet
- Schrijf namen gewoon uit, geen @ notaties

VOORBEELD OUTPUT:
Live vanuit de Beurs van Berlage Amsterdam 🏛️
De toekomst van duurzame stadslogistiek staat centraal vandaag.

Een inspirerende dag met experts die laten zien hoe slimme mobiliteit onze steden verandert 🚲:

🗣️ Anna Vermeer – Directeur Stedelijke Mobiliteit, Gemeente Amsterdam
🗣️ Luca Martini – Head of Last-Mile, DHL Supply Chain
🗣️ Sophie Janssen – Oprichter GreenRoute

#CityLogistics #DuurzameMobiliteit #Amsterdam #Innovation #Sustainability #SmartCity"""


def test_llm(llm: str) -> tuple[bool, str]:
    """Try a minimal API call. Returns (success, message)."""
    try:
        msg = "Zeg enkel 'ok'."
        if llm == "groq":
            from groq import Groq
            client = Groq(api_key=os.environ["GROQ_API_KEY"])
            client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": msg}],
                max_tokens=5,
            )
        elif llm == "claude":
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                messages=[{"role": "user", "content": msg}],
            )
        elif llm == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": msg}],
                max_tokens=5,
            )
        elif llm == "gemini":
            from google import genai
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            client.models.generate_content(
                model="gemini-2.5-flash",
                contents=msg,
            )
        else:
            return False, f"Onbekende LLM: {llm}"
        return True, "Verbinding OK"
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "invalid api key" in msg or "invalid_api_key" in msg or "authentication" in msg or "unauthorized" in msg:
            return False, "Ongeldige API key — controleer of je de juiste key hebt geplakt"
        if "429" in msg or "quota" in msg or "rate limit" in msg:
            return False, "Limiet bereikt — je hebt geen credits meer of je zit aan de gratis limiet"
        if "403" in msg or "billing" in msg or "payment" in msg:
            return False, "Betalingsgegevens vereist — voeg een betaalmethode toe in de console"
        if "no api key" in msg or "api key not" in msg:
            return False, "Geen API key ingevuld"
        return False, f"Verbinding mislukt — {str(e)}"


def detect_llm() -> str:
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    raise RuntimeError("Geen LLM API key gevonden in .env")


def generate_linkedin_post(
    event: Event, user_prompt: str, llm: str = None, system_prompt: str = None
) -> tuple[str, int, int]:
    """Returns (post_text, input_tokens, output_tokens)."""
    if llm is None:
        llm = detect_llm()
    effective_system = system_prompt or SYSTEM_PROMPT
    event_text = f"""
Titel: {event.title}
Datum: {event.date}
Locatie: {event.location}
Tags: {', '.join(event.tags)}

{html_to_text(event.description)}
""".strip()

    user_message = f"""Schrijf een LinkedIn post voor dit event dat ik ga bijwonen:

{event_text}

Aanvullende instructies:
{user_prompt}"""

    if llm == "groq":
        return _generate_groq(user_message, effective_system)
    elif llm == "gemini":
        return _generate_gemini(user_message, effective_system)
    elif llm == "claude":
        return _generate_claude(user_message, effective_system)
    elif llm == "openai":
        return _generate_openai(user_message, effective_system)
    else:
        raise ValueError(f"Onbekende LLM: {llm}")


def _generate_groq(user_message: str, system_prompt: str) -> tuple[str, int, int]:
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    usage = response.usage
    return response.choices[0].message.content, usage.prompt_tokens, usage.completion_tokens


def _generate_gemini(user_message: str, system_prompt: str) -> tuple[str, int, int]:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{system_prompt}\n\n{user_message}",
    )
    usage = response.usage_metadata
    return response.text, usage.prompt_token_count or 0, usage.candidates_token_count or 0


def _generate_claude(user_message: str, system_prompt: str) -> tuple[str, int, int]:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=60.0)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    usage = message.usage
    return message.content[0].text, usage.input_tokens, usage.output_tokens


def _generate_openai(user_message: str, system_prompt: str) -> tuple[str, int, int]:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    usage = response.usage
    return response.choices[0].message.content, usage.prompt_tokens, usage.completion_tokens
