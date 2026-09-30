import os, re, logging, tempfile, asyncio, uuid
import yt_dlp
from telegram import (Update, LinkPreviewOptions, LabeledPrice,
                      InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup)
from telegram.constants import ParseMode, ChatAction
from telegram.error import TelegramError
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, PreCheckoutQueryHandler, ContextTypes, filters)

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]
FORCE_CHANNEL = os.environ.get("FORCE_CHANNEL", "@Rename_xo")
UPDATES_URL = os.environ.get("UPDATES_URL", "https://t.me/Rename_xo")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/kcvxn")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
MAX_SIZE = 45 * 1024 * 1024  # keep under Telegram bot upload limits

# any http(s) link — yt-dlp itself decides whether the site is supported
LINK_RE = re.compile(r"(https?://\S+)")

SUPPORTED_HOSTS = (
    "tiktok.com", "youtube.com", "youtu.be",
    "instagram.com", "pinterest.com", "pin.it", "picsart.com",
)

JOIN_MSG = (
    "<b>⛔ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ\n\n</b>"
    "<b>ʏᴏᴜ ᴍᴜꜱᴛ ᴊᴏɪɴ ᴛᴏ ᴜꜱᴇ ʙᴏᴛ.\n\n</b>"
    "<b>ᴘʟᴇᴀꜱᴇ ᴊᴏɪɴ ᴜꜱɪɴɢ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ.</b>"
)
JOIN_ALERT = "⛔ ᴀᴄᴄᴇꜱꜱ ᴅᴇɴɪᴇᴅ\n\nʏᴏᴜ ᴍᴜꜱᴛ ᴊᴏɪɴ ᴛᴏ ᴜꜱᴇ ʙᴏᴛ."

WELCOME = (
    "<b>👋 Hᴇʏ {name}\n\n</b>"
    "<b>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴀʟʟ-ɪɴ-ᴏɴᴇ ᴅᴏᴡɴʟᴏᴀᴅᴇʀ ʙᴏᴛ!\n\n</b>"
    "<b> ◈ ᴛɪᴋᴛᴏᴋ, ʏᴏᴜᴛᴜʙᴇ, ɪɴꜱᴛᴀɢʀᴀᴍ,\n\n</b>"
    "<b> ◈ ᴘɪɴᴛᴇʀᴇꜱᴛ &amp; ᴘɪᴄꜱᴀʀᴛ — ɴᴏ ᴡᴀᴛᴇʀᴍᴀʀᴋ.\n\n</b> "
    "<b>☏ ᴅᴇᴘʟᴏʏᴇᴅ ʙʏ <a href=\"https://t.me/kcvxn\">ᗰ𝐞𝐫𝐜𝐲 ♱</a>\n</b>"
    "───────────────────────\n\n"
    "<b>๏ ꜱᴇɴᴅ ᴀ ʟɪɴᴋ ᴛᴏ ꜱᴛᴀʀᴛ</b>"
)

def main_kb():
    return Markup([
        [Btn("ʜᴏᴡ ᴛᴏ ᴜꜱᴇ", callback_data="how")],
        [
            Btn("ꜱᴜᴘᴘᴏʀᴛ", url=SUPPORT_URL, api_kwargs={"style": "primary"}),
            Btn("ᴜᴘᴅᴀᴛᴇꜱ", url=UPDATES_URL, api_kwargs={"style": "success"}),
        ],
        [
            Btn("ᴀʙᴏᴜᴛ", callback_data="about", api_kwargs={"style": "danger"}),
            Btn("⭐ ᴅᴏɴᴀᴛᴇ", callback_data="donate"),
        ],
    ])

def join_kb():
    return Markup([
        [Btn("♞ ᴊᴏɪɴ", url=f"https://t.me/{FORCE_CHANNEL.lstrip('@')}")],
        [Btn("🟢 ᴊᴏɪɴᴇᴅ", callback_data="check")],
    ])

def result_kb(vid):
    return Markup([
        [Btn("ɢᴇᴛ ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ", callback_data=f"desc:{vid}", api_kwargs={"style": "success"})],
        [Btn("ᴜᴘᴅᴀᴛᴇ", url=UPDATES_URL)],
        [Btn("ᴍᴇɴᴜ", callback_data="back", api_kwargs={"style": "primary"})],
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
    """Downloads a video (any yt-dlp supported site) and sends it with the result keyboard."""
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

        await status.edit_text("<b>📸 ꜱᴇɴᴅɪɴɢ...</b>", parse_mode=ParseMode.HTML)
        caption = info.get("title") or "Downloaded video"

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

async def send_donate_menu(msg):
    kb = Markup([
        [Btn("⭐ 25", callback_data="pay:25"), Btn("⭐ 50", callback_data="pay:50")],
        [Btn("⭐ 100", callback_data="pay:100"), Btn("⭐ 250", callback_data="pay:250")],
        [Btn("⭐ 500", callback_data="pay:500"), Btn("⭐ 1000", callback_data="pay:1000")],
        [Btn("« ʙᴀᴄᴋ", callback_data="back", api_kwargs={"style": "danger"})],
    ])
    await msg.edit_text(
        "<b>⭐ ꜱᴜᴘᴘᴏʀᴛ ᴛʜᴇ ʙᴏᴛ\n\n"
        "ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ꜰʀᴇᴇ ᴛᴏ ᴜꜱᴇ, ᴀɴᴅ ᴀʟᴡᴀʏꜱ ᴡɪʟʟ ʙᴇ.\n"
        "ᴀ ᴅᴏɴᴀᴛɪᴏɴ ʜᴇʟᴘꜱ ᴄᴏᴠᴇʀ ꜱᴇʀᴠᴇʀꜱ ᴀɴᴅ ᴋᴇᴇᴘꜱ ɪᴛ ʀᴜɴɴɪɴɢ.\n\n"
        "ᴄʜᴏᴏꜱᴇ ʜᴏᴡ ᴍᴀɴʏ ꜱᴛᴀʀꜱ ʏᴏᴜ'ᴅ ʟɪᴋᴇ ᴛᴏ ᴅᴏɴᴀᴛᴇ.</b>",
        parse_mode=ParseMode.HTML, reply_markup=kb)

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
            await q.answer("❌ ʏᴏᴜ ʜᴀᴠᴇɴ'ᴛ ᴊᴏɪɴᴇᴅ ᴄʜᴀɴɴʟᴇ", show_alert=True)
        return

    if data == "donate":
        await q.answer()
        await send_donate_menu(q.message)
        return

    if data.startswith("pay:"):
        amount = int(data.split(":", 1)[1])
        await q.answer()
        await ctx.bot.send_invoice(
            chat_id=q.message.chat_id,
            title="Support the bot",
            description=f"A voluntary donation of {amount} Stars. Thank you!",
            payload=f"donate-{amount}",
            currency="XTR",
            prices=[LabeledPrice(f"{amount} Stars", amount)],
        )
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
            q.message.chat_id, f"<b>📄ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ👇:</b>\n\n{desc[:3500]}",
            parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
        return

    texts = {
        "how": (
            "<b>ʜᴏᴡ ᴛᴏ ᴜꜱᴇ\n\n"
            "1. ᴏᴘᴇɴ ᴛɪᴋᴛᴏᴋ / ʏᴏᴜᴛᴜʙᴇ / ɪɴꜱᴛᴀɢʀᴀᴍ / ᴘɪɴᴛᴇʀᴇꜱᴛ / ᴘɪᴄꜱᴀʀᴛ\n"
            "2. ᴄᴏᴘʏ ᴀ ᴠɪᴅᴇᴏ ʟɪɴᴋ ᴀɴᴅ ᴘᴀꜱᴛᴇ ɪᴛ ʜᴇʀᴇ\n"
            "3. ᴡᴀɪᴛ ᴀ ꜰᴇᴡ ꜱᴇᴄᴏɴᴅꜱ ꜰᴏʀ ʏᴏᴜʀ ᴠɪᴅᴇᴏ\n\n"
            "ᴜꜱᴇ ɢᴇᴛ ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ ᴏʀ ᴜᴘᴅᴀᴛᴇ ᴜɴᴅᴇʀ ᴀɴʏ ᴠɪᴅᴇᴏ</b>"
        ),
        "about": (
            "<b>ᴀʙᴏᴜᴛ ᴛʜɪꜱ ʙᴏᴛ\n\n"
            "◈ ᴅᴏᴡɴʟᴏᴀᴅ ꜰʀᴏᴍ ᴛɪᴋᴛᴏᴋ, ʏᴏᴜᴛᴜʙᴇ, ɪɴꜱᴛᴀɢʀᴀᴍ,\n"
            "  ᴘɪɴᴛᴇʀᴇꜱᴛ &amp; ᴘɪᴄꜱᴀʀᴛ\n"
            "◈ ɴᴏ ᴡᴀᴛᴇʀᴍᴀʀᴋ\n"
            "◈ ɢᴇᴛ ᴅᴇꜱᴄʀɪᴘᴛɪᴏɴ\n"
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

async def precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    amount = update.message.successful_payment.total_amount
    await update.message.reply_text(
        f"<b>🎉 ᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ᴅᴏɴᴀᴛɪɴɢ ⭐ {amount} ꜱᴛᴀʀꜱ!</b>",
        parse_mode=ParseMode.HTML)

async def got_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, ctx):
        return
    text = update.message.text.strip()
    m = LINK_RE.search(text)
    if not m:
        await update.message.reply_text(
            "<b>⛔ ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ʟɪɴᴋ.</b>", parse_mode=ParseMode.HTML)
        return
    url = m.group(1)
    if not any(h in url for h in SUPPORTED_HOSTS):
        await update.message.reply_text(
            "<b>⚠️ ᴜɴꜱᴜᴘᴘᴏʀᴛᴇᴅ ʟɪɴᴋ. ꜱᴜᴘᴘᴏʀᴛᴇᴅ: ᴛɪᴋᴛᴏᴋ, ʏᴏᴜᴛᴜʙᴇ, ɪɴꜱᴛᴀɢʀᴀᴍ, "
            "ᴘɪɴᴛᴇʀᴇꜱᴛ, ᴘɪᴄꜱᴀʀᴛ.</b>", parse_mode=ParseMode.HTML)
        return
    status = await update.message.reply_text(
        "<b>⏳ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...</b>", parse_mode=ParseMode.HTML)
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)
    try:
        await download_video(url, update.effective_chat.id, ctx, status)
        await status.delete()
    except Exception as e:
        logging.exception("download failed")
        await status.edit_text("<b>⛔ ꜰᴀɪʟᴇᴅ, ʟɪɴᴋ ɴᴏᴛ ꜱᴜᴘᴘᴏʀᴛᴇᴅ ᴏʀ ᴘʀɪᴠᴀᴛᴇ.</b>",
                               parse_mode=ParseMode.HTML)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, got_link))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.run_polling()

if __name__ == "__main__":
    main()
