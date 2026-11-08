import asyncio
import os
import tempfile
import re
import logging
import subprocess

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiohttp import web

import yt_dlp
from ffmpeg_downloader import get_ffmpeg_path

# Получаем токен из переменных окружения Render
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sc-bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CAPTION = "🎵 <b>Tipoke Music</b> — https://t.me/tipokeee"
URL_RE = re.compile(r"https?://(?:www\.|m\.|on\.)?soundcloud\.com/\S+")

# Скачиваем ffmpeg при старте (если его еще нет на сервере)
log.info("Проверка наличия ffmpeg...")
subprocess.run(["ffdl", "install"], check=False)
log.info("ffmpeg готов к работе.")


def download_track(url: str, out_dir: str) -> str:
    # Получаем путь к скачанному ffmpeg
    ffmpeg_path = get_ffmpeg_path()
    
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, "%(title).80s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ffmpeg_location": ffmpeg_path, # Указываем yt-dlp, где лежит ffmpeg
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        base = ydl.prepare_filename(info)
        mp3_path = os.path.splitext(base)[0] + ".mp3"
        return mp3_path


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Привет! Пришли ссылку на трек с SoundCloud — я скачаю и пришлю MP3.\n\n"
        "Пример: <code>https://soundcloud.com/artist/track</code>",
        parse_mode=ParseMode.HTML,
    )


@dp.message(F.text)
async def link_handler(message: Message):
    # Ищем ссылку в тексте сообщения
    match = URL_RE.search(message.text or "")
    
    if not match:
        # Если в тексте ссылки нет, проверяем скрытые ссылки (превью Telegram)
        url = None
        if message.entities:
            for entity in message.entities:
                if entity.type == "text_link" and "soundcloud.com" in entity.url:
                    url = entity.url
                    break
        
        if not url:
            await message.answer("Пришли ссылку на трек SoundCloud.")
            return
    else:
        url = match.group(0)

    # Очищаем ссылку от лишних символов по краям
    url = url.strip("()[]{}<> \"'")

    status = await message.answer("⏳ Скачиваю трек...")

    with tempfile.TemporaryDirectory() as tmp:
        try:
            loop = asyncio.get_running_loop()
            # Запускаем скачивание в отдельном потоке
            file_path = await loop.run_in_executor(None, download_track, url, tmp)
        except Exception as e:
            log.exception("download failed")
            await status.edit_text(f"❌ Не удалось скачать: {e}")
            return

        if not os.path.exists(file_path):
            await status.edit_text("❌ Файл не найден после скачивания.")
            return

        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > 49:
            await status.edit_text(
                f"⚠️ Файл слишком большой ({size_mb:.1f} МБ). "
                "Telegram-боты могут отправлять до 50 МБ."
            )
            return

        await status.edit_text("📤 Отправляю...")
        try:
            await message.answer_audio(
                FSInputFile(file_path),
                caption=CAPTION,
                parse_mode=ParseMode.HTML,
                title=os.path.splitext(os.path.basename(file_path))[0],
            )
            await status.delete()
        except Exception as e:
            log.exception("send failed")
            await status.edit_text(f"❌ Ошибка отправки: {e}")


# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def health(request):
    return web.Response(text="ok")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_health_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
