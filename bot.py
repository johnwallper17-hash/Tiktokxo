import os, re, logging, tempfile, asyncio, uuid
import yt_dlp
from telegram import (Update, LinkPreviewOptions,
                      InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup)
from telegram.constants import ParseMode, ChatAction
from telegram.error import TelegramError
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]
FORCE_CHANNEL = os.environ.get("FORCE_CHANNEL", "@Rename_xo")
UPDATES_URL = os.environ.get("UPDATES_URL", "https://t.me/Rename_xo")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/kcvxn")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
MAX_SIZE = 45 * 1024 * 1024  # keep under Telegram bot upload limits

TIKTOK_RE = re.compile(r"(https?://(?:www\.|vt\.|vm\.)?tiktok\.com/\S+)")

JOIN_MSG = (
    "<b>⛔ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ\n\n</b>"
    "<b>ʏᴏᴜ ᴍᴜꜱᴛ ᴊᴏɪɴ ᴛᴏ ᴜꜱᴇ ʙᴏᴛ.\n\n</b>"
    "<b>ᴘʟᴇᴀꜱᴇ ᴊᴏɪɴ ᴜꜱɪɴɢ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ.</b>"
)
JOIN_ALERT = "⛔ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ\n\nʏᴏᴜ ᴍᴜꜱᴛ ᴊᴏɪɴ ᴛᴏ ᴜꜱᴇ ʙᴏᴛ."

WELCOME = (
    "<b>👋 ʜᴇʏ {name}\n\n</b>"
    "<b>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛɪᴋᴛᴏᴋ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ!\n\n</b>"
    "<b> ◈ ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴʏ ᴛɪᴋᴛᴏᴋ ᴠɪᴅᴇᴏ ɪɴ ꜱᴇᴄᴏɴᴅꜱ,\n\n</b>"
    "<b> ◈ ɴᴏ ᴡᴀᴛᴇʀᴍᴀʀᴋ, ꜰᴜʟʟ ǫᴜᴀʟɪᴛʏ.\n\n</b> "
    "<b>☏ ᴅᴇᴘʟᴏʏᴇᴅ ʙʏ <a href=\"https://t.me/kcvxn\">ᗰ𝐞𝐫𝐜𝐲 ♱</a>\n</b>"
    "───────────────────────\n\n"
    "<b>๏ ꜱᴇɴᴅ ᴀ ᴛɪᴋᴛᴏᴋ ʟɪɴᴋ ᴛᴏ ꜱᴛᴀʀᴛ</b>"
)

def main_kb():
    return Markup([
        [Btn("ʜᴏᴡ ᴛᴏ ᴜꜱᴇ", callback_data="how")],
        [
            Btn("ꜱᴜᴘᴘᴏʀᴛ", url=SUPPORT_URL, api_kwargs={"style": "primary"}),
            Btn("ᴜᴘᴅᴀᴛᴇꜱ", url=UPDATES_URL, api_kwargs={"style": "success"}),
        ],
        [Btn("ᴀʙᴏᴜᴛ", callback_data="about", api_kwargs={"style": "danger"})],
    ])

def join_kb():
    return Markup([
        [Btn("♞ ᴊᴏɪɴ", url=f"https://t.me/{FORCE_CHANNEL.lstrip('@')}")],
        [Btn("🟢 ᴊᴏɪɴᴇᴅ", callback_data="check")],
    ])

def result_kb(vid):
    return Markup([
        [Btn("📄 ɢᴇᴛ ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ", callback_data=f"desc:{vid}", api_kwargs={"style": "success"})],
        [
            Btn("🔄 ᴜᴘᴅᴀᴛᴇ", callback_data=f"upd:{vid}"),
            Btn("🎵 ꜰɪɴᴅ ꜱᴏɴɢ", callback_data=f"song:{vid}", api_kwargs={"style": "primary"}),
        ],
    ])

async def is_joined(bot, user_id):
    try:
        m = await bot.get_chat_member(FORCE_CHANNEL, user_id)
        return m.status in ("member", "administrator", "creator")
    except TelegramError:
        return False

async def guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if await is_joined(ctx.bot, update.effective_user.id):
        return True
    await update.message.reply_text(JOIN_MSG, parse_mode=ParseMode.HTML, reply_markup=join_kb())
    return False

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await is_joined(ctx.bot, update.effective_user.id):
        await update.message.reply_text(JOIN_MSG, parse_mode=ParseMode.HTML, reply_markup=join_kb())
        return
    user = update.effective_user
    await update.message.reply_text(
        WELCOME.format(name=user.mention_html()),
        parse_mode=ParseMode.HTML, reply_markup=main_kb(), link_preview_options=NO_PREVIEW)

async def download_video(url, chat_id, ctx, status):
    """Downloads a TikTok video and sends it with the result keyboard. Returns info dict."""
    with tempfile.TemporaryDirectory() as d:
        path_tmpl = os.path.join(d, "%(id)s.%(ext)s")
        ydl_opts = {
            "outtmpl": path_tmpl,
            "format": "mp4/bestvideo+bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "max_filesize": MAX_SIZE,
        }
        loop = asyncio.get_event_loop()
        def run():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info), info
        filepath, info = await loop.run_in_executor(None, run)

        if not os.path.exists(filepath):
            base, _ = os.path.splitext(filepath)
            for ext in (".mp4", ".mkv", ".webm"):
                if os.path.exists(base + ext):
                    filepath = base + ext
                    break

        size = os.path.getsize(filepath)
        if size > MAX_SIZE:
            await status.edit_text(
                "<b>❌ ᴠɪᴅᴇᴏ ɪꜱ ᴛᴏᴏ ʟᴀʀɢᴇ ᴛᴏ ꜱᴇɴᴅ.</b>", parse_mode=ParseMode.HTML)
            return None

        await status.edit_text("<b>⬆️ ꜱᴇɴᴅɪɴɢ...</b>", parse_mode=ParseMode.HTML)
        caption = info.get("title") or "TikTok video"

        vid = uuid.uuid4().hex[:10]
        ctx.bot_data[vid] = {
            "description": info.get("description"),
            "music": info.get("track") or info.get("artist"),
            "title": info.get("title"),
            "webpage_url": info.get("webpage_url") or url,
        }

        with open(filepath, "rb") as fh:
            await ctx.bot.send_video(
                chat_id, fh, caption=f"<b>{caption[:900]}</b>",
                parse_mode=ParseMode.HTML, reply_markup=result_kb(vid),
                read_timeout=600, write_timeout=600, connect_timeout=60)
        return info

async def callbacks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data

    if data != "check" and not await is_joined(ctx.bot, q.from_user.id):
        await q.answer(JOIN_ALERT, show_alert=True)
        return

    if data == "check":
        if await is_joined(ctx.bot, q.from_user.id):
            await q.message.delete()
            user = q.from_user
            await ctx.bot.send_message(
                q.message.chat_id, WELCOME.format(name=user.mention_html()),
                parse_mode=ParseMode.HTML, reply_markup=main_kb(), link_preview_options=NO_PREVIEW)
        else:
            await q.answer("❌ ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ ᴊᴏɪɴᴇᴅ", show_alert=True)
        return

    if data.startswith("desc:"):
        vid = data.split(":", 1)[1]
        info = ctx.bot_data.get(vid)
        if not info:
            await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ, ꜱᴇɴᴅ ᴛʜᴇ ʟɪɴᴋ ᴀɢᴀɪɴ", show_alert=True)
            return
        await q.answer()
        desc = info.get("description") or "ɴᴏ ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ ꜰᴏᴜɴᴅ."
        await ctx.bot.send_message(
            q.message.chat_id, f"<b>📄 ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ:</b>\n\n{desc[:3500]}",
            parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
        return

    if data.startswith("upd:"):
        vid = data.split(":", 1)[1]
        info = ctx.bot_data.get(vid)
        if not info:
            await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ, ꜱᴇɴᴅ ᴛʜᴇ ʟɪɴᴋ ᴀɢᴀɪɴ", show_alert=True)
            return
        await q.answer("🔄 ᴜᴘᴅᴀᴛɪɴɢ...")
        status = await ctx.bot.send_message(
            q.message.chat_id, "<b>⏳ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...</b>", parse_mode=ParseMode.HTML)
        try:
            await download_video(info["webpage_url"], q.message.chat_id, ctx, status)
            await status.delete()
        except Exception as e:
            logging.exception("update failed")
            await status.edit_text(f"<b>❌ ꜰᴀɪʟᴇᴅ: {str(e)[:150]}</b>", parse_mode=ParseMode.HTML)
        return

    if data.startswith("song:"):
        vid = data.split(":", 1)[1]
        info = ctx.bot_data.get(vid)
        if not info:
            await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ, ꜱᴇɴᴅ ᴛʜᴇ ʟɪɴᴋ ᴀɢᴀɪɴ", show_alert=True)
            return
        await q.answer("🎵 ᴇxᴛʀᴀᴄᴛɪɴɢ...")
        status = await ctx.bot.send_message(
            q.message.chat_id, "<b>🎵 ᴇxᴛʀᴀᴄᴛɪɴɢ ꜱᴏɴɢ...</b>", parse_mode=ParseMode.HTML)
        try:
            with tempfile.TemporaryDirectory() as d:
                out_tmpl = os.path.join(d, "%(id)s.%(ext)s")
                opts = {
                    "outtmpl": out_tmpl, "format": "bestaudio/best",
                    "quiet": True, "no_warnings": True, "noplaylist": True,
                    "postprocessors": [{"key": "FFmpegExtractAudio",
                                        "preferredcodec": "mp3", "preferredquality": "192"}],
                }
                loop = asyncio.get_event_loop()
                def run():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([info["webpage_url"]])
                await loop.run_in_executor(None, run)
                mp3 = None
                for fn in os.listdir(d):
                    if fn.endswith(".mp3"):
                        mp3 = os.path.join(d, fn)
                        break
                if not mp3:
                    raise RuntimeError("audio not found")
                title = (info.get("music") or info.get("title") or "TikTok Sound")[:60]
                with open(mp3, "rb") as fh:
                    await ctx.bot.send_audio(
                        q.message.chat_id, fh, title=title, performer="TikTok",
                        read_timeout=300, write_timeout=300, connect_timeout=60)
            await status.delete()
        except Exception as e:
            logging.exception("song extract failed")
            await status.edit_text(f"<b>❌ ꜰᴀɪʟᴇᴅ: {str(e)[:150]}</b>", parse_mode=ParseMode.HTML)
        return

    texts = {
        "how": (
            "<b>ʜᴏᴡ ᴛᴏ ᴜꜱᴇ\n\n"
            "1. ᴏᴘᴇɴ ᴛɪᴋᴛᴏᴋ ᴀɴᴅ ᴄᴏᴘʏ ᴀ ᴠɪᴅᴇᴏ ʟɪɴᴋ\n"
            "2. ᴘᴀꜱᴛᴇ ᴛʜᴇ ʟɪɴᴋ ʜᴇʀᴇ\n"
            "3. ᴡᴀɪᴛ ᴀ ꜰᴇᴡ ꜱᴇᴄᴏɴᴅꜱ ꜰᴏʀ ʏᴏᴜʀ ᴠɪᴅᴇᴏ\n\n"
            "ᴜꜱᴇ 📄 ɢᴇᴛ ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ, 🔄 ᴜᴘᴅᴀᴛᴇ ᴏʀ 🎵 ꜰɪɴᴅ ꜱᴏɴɢ ᴜɴᴅᴇʀ ᴀɴʏ ᴠɪᴅᴇᴏ</b>"
        ),
        "about": (
            "<b>ᴀʙᴏᴜᴛ ᴛɪᴋᴛᴏᴋ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ\n\n"
            "◈ ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴʏ ᴘᴜʙʟɪᴄ ᴛɪᴋᴛᴏᴋ ᴠɪᴅᴇᴏ\n"
            "◈ ɴᴏ ᴡᴀᴛᴇʀᴍᴀʀᴋ\n"
            "◈ ɢᴇᴛ ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ &amp; ꜱᴏɴɢ\n"
            "◈ ꜰᴀꜱᴛ &amp; ꜰʀᴇᴇ\n\n"
            "☏ ᴅᴇᴘʟᴏʏᴇᴅ ʙʏ <a href=\"https://t.me/kcvxn\">ᗰ𝐞𝐫𝐜𝐲 ♱</a></b>"
        ),
    }
    await q.answer()
    back = Markup([[Btn("« ʙᴀᴄᴋ", callback_data="back", api_kwargs={"style": "danger"})]])
    if data in texts:
        await q.message.edit_text(texts[data], parse_mode=ParseMode.HTML,
                                  reply_markup=back, link_preview_options=NO_PREVIEW)
    elif data == "back":
        user = q.from_user
        await q.message.edit_text(WELCOME.format(name=user.mention_html()),
                                  parse_mode=ParseMode.HTML, reply_markup=main_kb(),
                                  link_preview_options=NO_PREVIEW)

async def got_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx):
        return
    text = update.message.text.strip()
    m = TIKTOK_RE.search(text)
    if not m:
        await update.message.reply_text(
            "<b>⚠️ ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ᴛɪᴋᴛᴏᴋ ʟɪɴᴋ.</b>", parse_mode=ParseMode.HTML)
        return
    url = m.group(1)
    status = await update.message.reply_text(
        "<b>⏳ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...</b>", parse_mode=ParseMode.HTML)
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
    try:
        await download_video(url, update.effective_chat.id, ctx, status)
        await status.delete()
    except Exception as e:
        logging.exception("tiktok download failed")
        await status.edit_text(f"<b>❌ ꜰᴀɪʟᴇᴅ: {str(e)[:200]}</b>", parse_mode=ParseMode.HTML)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, got_link))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.run_polling()

if __name__ == "__main__":
    main()
