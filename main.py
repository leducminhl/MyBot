import os
import asyncio
import logging
import tempfile
import httpx

from dotenv import load_dotenv

from fastapi import FastAPI
import uvicorn

from telethon import TelegramClient, events

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load biến môi trường từ file .env
load_dotenv()


app = FastAPI()

# ================= HEALTH CHECK =================
@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}

# (optional) root endpoint
@app.api_route("/", methods=["GET", "HEAD"])
async def home():
    return "OK"

# ================= ENV =================
#API_ID = int(os.environ["API_ID"])
#API_HASH = os.environ["API_HASH"]
#BOT_TOKEN = os.environ["BOT_TOKEN"]
#DEST_CHAT = os.environ["DEST_CHAT"]
#ALLOWED = os.environ.get("ALLOWED_USER")


API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
DEST_CHAT = os.getenv('DEST_CHAT')
ALLOWED = os.environ.get("ALLOWED_USER")
try:
    DEST_CHAT = int(DEST_CHAT)
except:
    pass

pending_albums = {}

# ================= MEDIA =================

async def download_media(msg):
    if msg.photo:
        return await msg.download_media(
            file=tempfile.NamedTemporaryFile(delete=False, suffix=".jpg").name
        )
    elif msg.video:
        return await msg.download_media(
            file=tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        )
    elif msg.document:
        filename = "file.bin"
        if msg.document.attributes:
            for attr in msg.document.attributes:
                if hasattr(attr, 'file_name'):
                    filename = attr.file_name
                    break
        ext = os.path.splitext(filename)[1]
        path = tempfile.NamedTemporaryFile(delete=False, suffix=ext).name
        return await msg.download_media(file=path)
    return None

async def send_to_dest(client, dest_entity, media_paths, caption, is_album=False):
    try:
        if is_album:
            await client.send_file(dest_entity, media_paths, caption=caption, album=True)
        else:
            await client.send_file(dest_entity, media_paths[0], caption=caption)
    finally:
        for path in media_paths:
            try:
                if path and os.path.exists(path):
                    os.unlink(path)
            except:
                pass

# ================= ALBUM =================

async def process_album(chat_id, grouped_id, dest_entity, client):
    await asyncio.sleep(4)

    key = (chat_id, grouped_id)

    if key in pending_albums:
        data = pending_albums.pop(key)
        futures = data["msgs"]

        results = await asyncio.gather(*futures)

        media_paths = []
        captions = []

        for path, msg_text in results:
            if path:
                media_paths.append(path)
            if msg_text and msg_text not in captions:
                captions.append(msg_text)

        if media_paths:
            caption = "\n".join(captions)
            await send_to_dest(client, dest_entity, media_paths, caption, is_album=True)

# ================= BOT =================

async def run_bot():

    while True:
        try:
            client = TelegramClient('bot_session', API_ID, API_HASH)
            await client.start(bot_token=BOT_TOKEN)

            dest_entity = await client.get_entity(DEST_CHAT)
            logger.info("✅ Bot started")

            @client.on(events.NewMessage)
            async def handler(event):

                msg = event.message

                sender = await msg.get_sender()
                sender_name = sender.first_name or sender.username or "User"
                forward_info = f""

                # ===== ALBUM =====
                if msg.grouped_id:
                    key = (msg.chat_id, msg.grouped_id)

                    async def download_task(m):
                        p = await download_media(m)
                        return p, m.text

                    if key not in pending_albums:
                        pending_albums[key] = {
                            "msgs": [asyncio.create_task(download_task(msg))],
                            "task": asyncio.create_task(
                                process_album(msg.chat_id, msg.grouped_id, dest_entity, client)
                            )
                        }
                    else:
                        pending_albums[key]["msgs"].append(
                            asyncio.create_task(download_task(msg))
                        )
                    return

                # ===== MEDIA SINGLE =====
                if msg.media:
                    path = await download_media(msg)
                    if path:
                        caption = f"{forward_info}\n\n{msg.text}" if msg.text else forward_info
                        await send_to_dest(client, dest_entity, [path], caption)
                    return

                # ===== TEXT =====
                if msg.text:
                    await client.send_message(dest_entity, f"{forward_info}\n\n{msg.text}")

            await client.run_until_disconnected()

        except Exception:
            logger.exception("❌ Bot crash → restart sau 10s")
            await asyncio.sleep(10)

# ================= KEEP ALIVE =================

async def self_ping():
    url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000/health")
    while True:
        try:
            await httpx.get(url)
        except:
            pass
        await asyncio.sleep(300)

# ================= START =================

@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())
    asyncio.create_task(self_ping())

# ================= MAIN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
