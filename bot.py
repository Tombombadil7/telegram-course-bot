import asyncio
import base64
import json
import os
import re
from pathlib import Path

import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_STRING = os.environ["TELEGRAM_SESSION"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]

COURSES_FILE = Path("courses.txt")
STATE_FILE = Path("state.json")


def load_courses():
    if not COURSES_FILE.exists():
        return []
    lines = [
        line.strip()
        for line in COURSES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return sorted(lines, key=len, reverse=True)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def encode_hebrew_header(text):
    """
    מקודד עברית לפורמט RFC-2047 כדי ש-ntfy ו-requests יוכלו לקרוא 
    את הכותרת ללא שגיאות קידוד.
    """
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"=?UTF-8?B?{encoded}?="


async def main():
    course_numbers = load_courses()
    if not course_numbers:
        print("No courses configured in courses.txt")
        return

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
                (c for c in course_numbers if c in title), None
            )

            if not course:
                continue

            chat_id = str(dialog.id)
            latest = await client.get_messages(dialog.entity, limit=1)

            if not latest:
                continue

            latest_id = latest[0].id

            if chat_id not in state:
                state[chat_id] = latest_id
                print(f"Initialized: {title}")
                continue

            last_id = int(state[chat_id])

            if latest_id <= last_id:
                continue

            async for message in client.iter_messages(
                dialog.entity, min_id=last_id, reverse=True
            ):
                text = message.raw_text or ""
                
                # ערכי ברירת מחדל
                course_name = f"עדכון קורס: {course}"
                course_number = course
                spots = "לא ידוע"
                priority = "high"
                tags = "bell"

                # זיהוי הפורמטים
                match1 = re.search(r"נפתחו\s+(\d+)\s+מקומות\s+בקורס\s+([\d\-]+)\s+-\s+([^\r\n]+)", text)
                match2 = re.search(r"התפנה\s+מקום\s+אחד.*בקורס\s+([\d\-]+)\s+-\s+([^\r\n]+)", text)

                if match1:
                    spots = match1.group(1)
                    course_number = match1.group(2)
                    course_name = match1.group(3).strip()
                elif match2:
                    spots = "1"
                    course_number = match2.group(1)
                    course_name = match2.group(2).strip()

                # יצירת תוכן ההתראה והגדרת דחיפות
                if match1 or match2:
                    body_text = f"מספר קורס: {course_number}\nמקומות פנויים: {spots}"
                    
                    # הקפצת דחיפות אם מדובר במקום אחד בלבד
                    if spots == "1":
                        body_text += "\n\n🚨 לרוץ!! נשאר רק מקום אחד!"
                        priority = "max"
                        tags = "rotating_light,fire"
                    else:
                        priority = "high"
                        tags = "bell,green_circle"
                else:
                    # Fallback
                    body_text = text

                headers = {
                    "Title": encode_hebrew_header(course_name),
                    "Priority": priority,
                    "Tags": tags,
                }
                
                response = requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=body_text.encode("utf-8"),
                    headers=headers,
                    timeout=10,
                )
                response.raise_for_status()

                print(f"Notified: {title} (Spots: {spots}), message {message.id}")

            state[chat_id] = latest_id

    save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
