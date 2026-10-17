import asyncio
import json
import os
from pathlib import Path

import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_STRING = os.environ["TELEGRAM_SESSION"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]

COURSE_NUMBERS = ["03940805-33", "03940806-20"]
STATE_FILE = Path("state.json")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


async def main():
    state = load_state()

    async with TelegramClient(
        StringSession(SESSION_STRING), API_ID, API_HASH
    ) as client:
        dialogs = await client.get_dialogs()

        for dialog in dialogs:
            if not (dialog.is_group or dialog.is_channel):
                continue

            title = getattr(dialog.entity, "title", "") or ""
            course = next(
                (c for c in COURSE_NUMBERS if c in title), None
            )

            if not course:
                continue

            chat_id = str(dialog.id)
            latest = await client.get_messages(dialog.entity, limit=1)

            if not latest:
                continue

            latest_id = latest[0].id

            # First run: establish a baseline without old notifications.
            if chat_id not in state:
                state[chat_id] = latest_id
                print(f"Initialized: {title}")
                continue

            last_id = int(state[chat_id])

            if latest_id <= last_id:
                continue

            # Process new messages from oldest to newest.
            async for message in client.iter_messages(
                dialog.entity, min_id=last_id, reverse=True
            ):
                text = message.raw_text or "New course message"

                response = requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=text.encode("utf-8"),
                    headers={
                        "Title": f"Course alert: {course}",
                        "Priority": "urgent",
                        "Tags": "bell,loudspeaker",
                    },
                    timeout=10,
                )
                response.raise_for_status()

                print(f"Notified: {title}, message {message.id}")

            state[chat_id] = latest_id

    save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
