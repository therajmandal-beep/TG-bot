import logging
import sqlite3
import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ─────────────────────────────────────────────
BOT_TOKEN          = "8598800608:AAHllMFYXsfyv5rTPaFtA7JcIJHv6P8dPVA"
ADMIN_CHAT_ID      = 1256115118
PRIVATE_GROUP_LINK = "https://t.me/+FgsZ3xFFKyxlNDhl"

REFERRAL_LINKS = {
    "CoinDCX": "https://invite.coindcx.com/27157291",
    "Mudrex":  "https://mudrex.go.link/2u3hZ",
    "Vantage": "https://vigco.co/la-com-inv/HQ5hNvyG",
}
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

CHOOSING_APP, SUBMITTING_PROOF = range(2)

# ── Health Server ─────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    httpd = HTTPServer(("0.0.0.0", port), HealthHandler)
    httpd.serve_forever()

# ── Database ──────────────────────────────────

def init_db():
    conn = sqlite3.connect("bot.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            full_name  TEXT,
            chosen_app TEXT,
            proof      TEXT,
            status     TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row

def save_user(user_id, username, full_name, chosen_app, proof):
    conn = sqlite3.connect("bot.db")
    conn.execute("""
        INSERT OR REPLACE INTO users (user_id, username, full_name, chosen_app, proof, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, (user_id, username, full_name, chosen_app, proof))
    conn.commit()
    conn.close()

def update_status(user_id, status):
    conn = sqlite3.connect("bot.db")
    conn.execute("UPDATE users SET status = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()

# ── Handlers ──────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user     = update.effective_user
    existing = get_user(user.id)

    if existing:
        status = existing[5]
        if status == "approved":
            await update.message.reply_text(
                f"✅ You're already a member!\n\n"
                f"👉 Join here: {PRIVATE_GROUP_LINK}"
            )
            return ConversationHandler.END
        if status == "pending":
            await update.message.reply_text(
                "⏳ Your request is still under review.\n"
                "Please wait — the admin will get back to you soon!"
            )
            return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📈 CoinDCX",  callback_data="app_CoinDCX")],
        [InlineKeyboardButton("💰 Mudrex",   callback_data="app_Mudrex")],
        [InlineKeyboardButton("🏦 Vantage",  callback_data="app_Vantage")],
    ]
    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\n"
        "To join our *exclusive private group*, complete one simple task:\n\n"
        "📌 Register on any crypto platform below using *my referral link*.\n\n"
        "👇 Choose a platform to get started:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_APP


async def app_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    app_name = query.data.replace("app_", "")
    context.user_data["chosen_app"] = app_name
    link     = REFERRAL_LINKS[app_name]
    await query.edit_message_text(
        f"Great choice! 🎉\n\n"
        f"*Step 1 —* Register on *{app_name}* using my referral link:\n"
        f"👉 {link}\n\n"
        f"*Step 2 —* After registering, send me your *UID or Email* from {app_name} as proof.\n"
        f"_(UID can be found in your profile/account section of the app)_\n\n"
        f"_⚡ Approvals are done within 24 hours._",
        parse_mode="Markdown"
    )
    return SUBMITTING_PROOF


async def proof_submitted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user       = update.effective_user
    proof      = update.message.text
    chosen_app = context.user_data.get("chosen_app", "Unknown")
    save_user(user.id, user.username, user.full_name, chosen_app, proof)

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{user.id}"),
    ]]
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=(
            f"🔔 *New Access Request*\n\n"
            f"👤 Name: {user.full_name}\n"
            f"🔗 Username: @{user.username or 'N/A'}\n"
            f"🆔 Telegram ID: `{user.id}`\n"
            f"📱 App: {chosen_app}\n"
            f"🪪 UID/Email: `{proof}`\n\n"
            f"Tap a button to respond:"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text(
        "✅ *Proof submitted successfully!*\n\n"
        "The admin will review and approve you within 24 hours.\n"
        "You'll receive a message here once you're in! 🚀",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("⛔ Not authorized!", show_alert=True)
        return
    await query.answer()
    action, uid = query.data.split("_", 1)
    user_id = int(uid)

    if action == "approve":
        update_status(user_id, "approved")
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 *Congratulations! You've been approved!*\n\n"
                "Welcome to the community! Here's your exclusive group link:\n"
                f"👉 {PRIVATE_GROUP_LINK}\n\n"
                "_See you inside! 🚀_"
            ),
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"✅ User `{user_id}` approved!", parse_mode="Markdown")

    elif action == "reject":
        update_status(user_id, "rejected")
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ *Your request was not approved.*\n\n"
                "We couldn't verify your registration.\n"
                "Please make sure you signed up using the referral link and type /start to try again."
            ),
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"❌ User `{user_id}` rejected.", parse_mode="Markdown")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Type /start to begin again.")
    return ConversationHandler.END


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    conn = sqlite3.connect("bot.db")
    rows = conn.execute(
        "SELECT user_id, full_name, chosen_app, proof FROM users WHERE status='pending'"
    ).fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("✅ No pending requests.")
        return
    text = "*⏳ Pending Requests:*\n\n"
    for r in rows:
        text += f"🆔 `{r[0]}` | {r[1]} | {r[2]} | `{r[3]}`\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Main (async) ──────────────────────────────

async def main():
    init_db()

    # Start health server in background thread
    threading.Thread(target=run_health_server, daemon=True).start()
    print("✅ Health server started...")

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_APP:     [CallbackQueryHandler(app_chosen, pattern="^app_")],
            SUBMITTING_PROOF: [MessageHandler(filters.TEXT & ~filters.COMMAND, proof_submitted)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(admin_action, pattern="^(approve|reject)_"))
    app.add_handler(CommandHandler("pending", pending))

    print("✅ @Livedatacryptobot is running...")

    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await asyncio.Event().wait()  # Run forever
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
    
