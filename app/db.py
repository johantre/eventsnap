import os
import sqlite3
import bcrypt
from pathlib import Path
from cryptography.fernet import Fernet

DB_PATH = Path(__file__).parent.parent / "drafts.db"

# Keys die gevoelig zijn en versleuteld worden opgeslagen
SENSITIVE_KEYS = {
    "claude_api_key", "groq_api_key", "openai_api_key", "gemini_api_key",
    "eventbrite_token", "collective_password",
}

def _fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY niet gevonden in omgeving")
    return Fernet(key.encode())


def encrypt_value(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def get_user_by_email(conn, email: str):
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(conn, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_user(conn, email: str, password: str):
    hashed = hash_password(password)
    conn.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (email, hashed),
    )
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_admin_kpis(conn) -> dict:
    import json
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_posts = conn.execute(
        "SELECT COUNT(*) FROM analytics_events WHERE event_type = 'generate_ok'"
    ).fetchone()[0]
    avg_ms = conn.execute(
        "SELECT AVG(json_extract(properties, '$.duration_ms')) "
        "FROM analytics_events WHERE event_type IN ('generate_ok', 'regenerate_ok')"
    ).fetchone()[0]
    top_llm = conn.execute(
        "SELECT json_extract(properties, '$.llm') AS llm, COUNT(*) AS cnt "
        "FROM analytics_events WHERE event_type IN ('generate_ok', 'regenerate_ok') "
        "GROUP BY llm ORDER BY cnt DESC LIMIT 1"
    ).fetchone()
    return {
        "total_users": total_users,
        "total_posts": total_posts,
        "avg_ms": round(avg_ms) if avg_ms else None,
        "top_llm": top_llm["llm"] if top_llm else None,
    }


def get_posts_per_day(conn, days: int = 14) -> list:
    return conn.execute("""
        SELECT DATE(created_at) AS day, COUNT(*) AS cnt
        FROM analytics_events
        WHERE event_type = 'generate_ok'
          AND created_at >= DATE('now', ?)
        GROUP BY day ORDER BY day
    """, (f"-{days} days",)).fetchall()


def get_llm_stats(conn) -> list:
    return conn.execute("""
        SELECT
            json_extract(properties, '$.llm') AS llm,
            COUNT(*) AS total,
            ROUND(AVG(json_extract(properties, '$.duration_ms'))) AS avg_ms,
            MIN(json_extract(properties, '$.duration_ms')) AS min_ms,
            MAX(json_extract(properties, '$.duration_ms')) AS max_ms
        FROM analytics_events
        WHERE event_type IN ('generate_ok', 'regenerate_ok')
        GROUP BY llm ORDER BY total DESC
    """).fetchall()


def get_llm_cost_per_user(conn, user_id: int) -> dict:
    """Returns {llm_id: total_cost_usd} for a given user."""
    rows = conn.execute("""
        SELECT
            json_extract(properties, '$.llm') AS llm,
            SUM(CAST(json_extract(properties, '$.cost_usd') AS REAL)) AS total_usd
        FROM analytics_events
        WHERE user_id = ?
          AND event_type IN ('generate_ok', 'regenerate_ok')
          AND json_extract(properties, '$.cost_usd') IS NOT NULL
        GROUP BY llm
    """, (user_id,)).fetchall()
    return {row["llm"]: row["total_usd"] or 0.0 for row in rows}


def get_fail_stats(conn) -> list:
    return conn.execute("""
        SELECT
            json_extract(properties, '$.llm') AS llm,
            COUNT(*) AS fails
        FROM analytics_events
        WHERE event_type IN ('generate_fail', 'regenerate_fail')
        GROUP BY llm ORDER BY fails DESC
    """).fetchall()


def get_user_activity_stats(conn) -> list:
    return conn.execute("""
        SELECT
            u.email,
            u.created_at,
            u.email_verified,
            COUNT(DISTINCT d.id) AS draft_count,
            MAX(ae.created_at) AS last_activity
        FROM users u
        LEFT JOIN drafts d ON d.user_id = u.id
        LEFT JOIN analytics_events ae ON ae.user_id = u.id
            AND ae.event_type IN ('generate_ok', 'regenerate_ok')
        GROUP BY u.id
        ORDER BY draft_count DESC
    """).fetchall()


def log_event(conn, user_id: int, event_type: str, properties: dict) -> None:
    import json
    conn.execute(
        "INSERT INTO analytics_events (user_id, event_type, properties) VALUES (?, ?, ?)",
        (user_id, event_type, json.dumps(properties)),
    )
    conn.commit()


def get_all_users_with_stats(conn):
    return conn.execute("""
        SELECT
            u.id, u.email, u.created_at, u.email_verified, u.is_admin,
            CASE WHEN u.totp_secret IS NOT NULL THEN 1 ELSE 0 END AS totp_enabled,
            COUNT(d.id) AS draft_count
        FROM users u
        LEFT JOIN drafts d ON d.user_id = u.id
        GROUP BY u.id
        ORDER BY u.created_at DESC
    """).fetchall()


def set_user_verified(conn, user_id: int, verified: int) -> None:
    conn.execute("UPDATE users SET email_verified = ? WHERE id = ?", (verified, user_id))
    conn.commit()


def create_email_verification_token(conn, user_id: int, token: str, expires_at: str) -> None:
    conn.execute(
        "INSERT INTO email_verification_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at),
    )
    conn.commit()


def get_email_verification_token(conn, token: str):
    return conn.execute(
        "SELECT * FROM email_verification_tokens WHERE token = ? AND used = 0",
        (token,),
    ).fetchone()


def consume_email_verification_token(conn, token: str) -> None:
    conn.execute(
        "UPDATE email_verification_tokens SET used = 1 WHERE token = ?",
        (token,),
    )
    conn.commit()


def mark_email_verified(conn, user_id: int) -> None:
    conn.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
    conn.commit()


def create_password_reset_token(conn, user_id: int, token: str, expires_at: str) -> None:
    conn.execute(
        "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at),
    )
    conn.commit()


def get_password_reset_token(conn, token: str):
    return conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token = ? AND used = 0",
        (token,),
    ).fetchone()


def consume_password_reset_token(conn, token: str) -> None:
    conn.execute(
        "UPDATE password_reset_tokens SET used = 1 WHERE token = ?",
        (token,),
    )
    conn.commit()


def update_user_password(conn, user_id: int, new_password: str) -> None:
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new_password), user_id),
    )
    conn.commit()


def update_user_email(conn, user_id: int, new_email: str) -> None:
    conn.execute(
        "UPDATE users SET email = ? WHERE id = ?",
        (new_email, user_id),
    )
    conn.commit()


def delete_user(conn, user_id: int) -> None:
    conn.execute("DELETE FROM settings WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM drafts WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM prompts WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


def get_setting(key: str, user_id: int, default: str = "") -> str:
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM settings WHERE user_id = ? AND key = ?",
        (user_id, key),
    ).fetchone()
    conn.close()
    if not row:
        return default
    value = row["value"]
    if key in SENSITIVE_KEYS and value:
        try:
            value = decrypt_value(value)
        except Exception:
            pass  # waarde was nog niet versleuteld (legacy)
    return value


def set_setting(key: str, value: str, user_id: int) -> None:
    conn = get_db()
    stored = encrypt_value(value) if key in SENSITIVE_KEYS and value else value
    conn.execute(
        "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
        (user_id, key, stored),
    )
    conn.commit()
    conn.close()


SEED_PROMPTS = [
    (
        "Klassieke Collective post",
        """Schrijf exact in deze structuur:
1. Opener: "Live vanuit [locatie] 🔥" of gelijkaardig (1 zin + emoji)
2. Korte subtitel die het thema neerzet (1 zin, geen punt)
3. Eén enthousiaste zin over de sfeer of line-up, eindigend met een passende emoji en dubbele punt
4. Bullet lijst van de sprekers met hun functie/rol (emoji per spreker mag)
5. 5-8 relevante hashtags

Toon: persoonlijk, enthousiast, authentiek. Eerste persoon. Nederlands."""
    ),
]


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            totp_secret TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
    except Exception:
        pass

    # Migreer settings naar per-user schema als dat nog niet gedaan is
    has_user_id = conn.execute(
        "SELECT COUNT(*) FROM pragma_table_info('settings') WHERE name='user_id'"
    ).fetchone()[0]

    if not has_user_id:
        # Sla bestaande settings op voor migratie
        old_settings = []
        try:
            old_settings = conn.execute("SELECT key, value FROM settings").fetchall()
        except Exception:
            pass

        conn.execute("DROP TABLE IF EXISTS settings")
        conn.execute("""
            CREATE TABLE settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, key)
            )
        """)

        # Wijs bestaande settings toe aan de eerste user (als die bestaat)
        first_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if first_user and old_settings:
            conn.executemany(
                "INSERT OR IGNORE INTO settings (user_id, key, value) VALUES (?, ?, ?)",
                [(first_user["id"], row["key"], row["value"]) for row in old_settings if row["value"]],
            )
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, key)
            )
        """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            event_title TEXT NOT NULL,
            event_date TEXT,
            post_text TEXT NOT NULL,
            llm TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'draft',
            provider TEXT DEFAULT '',
            prompt_text TEXT DEFAULT ''
        )
    """)
    # Migreer bestaande drafts: voeg user_id toe en wijs toe aan eerste user
    for col_def in ["ALTER TABLE drafts ADD COLUMN llm TEXT DEFAULT ''",
                    "ALTER TABLE drafts ADD COLUMN provider TEXT DEFAULT ''",
                    "ALTER TABLE drafts ADD COLUMN prompt_text TEXT DEFAULT ''"]:
        try:
            conn.execute(col_def)
        except Exception:
            pass
    has_draft_user_id = conn.execute(
        "SELECT COUNT(*) FROM pragma_table_info('drafts') WHERE name='user_id'"
    ).fetchone()[0]
    if not has_draft_user_id:
        try:
            conn.execute("ALTER TABLE drafts ADD COLUMN user_id INTEGER")
            first_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            if first_user:
                conn.execute("UPDATE drafts SET user_id = ? WHERE user_id IS NULL", (first_user["id"],))
        except Exception:
            pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migreer bestaande prompts
    has_prompt_user_id = conn.execute(
        "SELECT COUNT(*) FROM pragma_table_info('prompts') WHERE name='user_id'"
    ).fetchone()[0]
    if not has_prompt_user_id:
        try:
            conn.execute("ALTER TABLE prompts ADD COLUMN user_id INTEGER")
            first_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            if first_user:
                conn.execute("UPDATE prompts SET user_id = ? WHERE user_id IS NULL", (first_user["id"],))
        except Exception:
            pass
    # email_verified kolom op users
    try:
        conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
        # Bestaande gebruikers zijn al geverifieerd
        conn.execute("UPDATE users SET email_verified = 1 WHERE email_verified = 0")
    except Exception:
        pass

    # is_admin kolom op users
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass

    # generation_ms kolom op drafts
    try:
        conn.execute("ALTER TABLE drafts ADD COLUMN generation_ms INTEGER")
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT NOT NULL,
            properties TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    count = conn.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
    if count == 0:
        first_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if first_user:
            conn.executemany(
                "INSERT INTO prompts (user_id, title, prompt_text) VALUES (?, ?, ?)",
                [(first_user["id"], title, text) for title, text in SEED_PROMPTS],
            )
    conn.commit()
    conn.close()
