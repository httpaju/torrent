import os
import time
import shutil
import threading
import json
import requests
import libtorrent as lt

from telegram import Update, Document
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
from io import BytesIO
import qrcode

# Load bot token from .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

TEMP_DIR = './temp'
USAGE_FILE = 'usage.json'
MAX_FREE_DOWNLOADS = 5

# Load/download count per user
def load_usage():
    return json.load(open(USAGE_FILE)) if os.path.exists(USAGE_FILE) else {}

def save_usage(data):
    with open(USAGE_FILE, 'w') as f:
        json.dump(data, f)

user_download_count = load_usage()

# Cleanup after a delay
def clean_temp_folder(path, delay=300):
    def delayed_delete():
        time.sleep(delay)
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"[Auto Clean] Deleted {path}")
    threading.Thread(target=delayed_delete).start()

# Upload large files to transfer.sh
def upload_to_transfersh(file_path):
    with open(file_path, 'rb') as f:
        response = requests.put(f"https://transfer.sh/{os.path.basename(file_path)}", data=f)
    return response.text.strip()

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Send me a .torrent file to download.\n"
        "🆓 Free users get 5 downloads.\n"
        "💎 Use /premium to upgrade for unlimited downloads."
    )

# Premium command with auto QR generation
async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or f"user_{update.effective_user.id}"
    upi_url = f"upi://pay/?pa=aj-mod@sbi&pn=AJ%20APPLICATIONS&cu=INR&am=149&tn=Payment%20by%20{username}"

    qr = qrcode.make(upi_url)
    bio = BytesIO()
    bio.name = "premium_qr.png"
    qr.save(bio, "PNG")
    bio.seek(0)

    await update.message.reply_photo(
        photo=bio,
        caption=(
            "💎 *Upgrade to Premium* for ₹149 only!\n\n"
            "🧾 Scan this UPI QR or use the link below:\n"
            f"`{upi_url}`\n\n"
            f"📌 *Note*: Mention your Telegram username (`{username}`) in the payment note.\n"
            "📨 After payment, send proof to @YourUsername"
        ),
        parse_mode="Markdown"
    )

# Handle torrent file
async def handle_torrent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    doc: Document = update.message.document

    if not doc.file_name.endswith('.torrent'):
        await update.message.reply_text("❌ Please send a valid .torrent file.")
        return

    count = user_download_count.get(user_id, 0)
    if count >= MAX_FREE_DOWNLOADS:
        await update.message.reply_text(
            "🛑 You've reached your 5 free torrent downloads.\n"
            "💎 Use /premium to upgrade and continue using the bot."
        )
        return

    folder = os.path.join(TEMP_DIR, f"{user_id}_{int(time.time())}")
    os.makedirs(folder, exist_ok=True)
    torrent_path = os.path.join(folder, doc.file_name)

    await doc.get_file().download_to_drive(torrent_path)
    await update.message.reply_text("📥 Torrent received. Starting download...")

    # Start session
    ses = lt.session()
    info = lt.torrent_info(torrent_path)
    h = ses.add_torrent({'ti': info, 'save_path': folder})

    while not h.is_seed():
        s = h.status()
        progress = s.progress * 100
        await update.message.reply_text(f"🔄 Downloading... {progress:.2f}%")
        time.sleep(5)

    await update.message.reply_text("✅ Torrent download complete!")

    # Send files or upload
    for f in info.files():
        file_path = os.path.join(folder, f.path)
        if os.path.exists(file_path):
            try:
                if os.path.getsize(file_path) <= 49 * 1024 * 1024:
                    await update.message.reply_document(open(file_path, 'rb'))
                else:
                    link = upload_to_transfersh(file_path)
                    await update.message.reply_text(f"📤 {f.path} is too large, link:\n{link}")
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error with {f.path}: {e}")

    # Track usage
    user_download_count[user_id] = count + 1
    save_usage(user_download_count)

    await update.message.reply_text("🧹 Files will auto-delete in 5 minutes.")
    clean_temp_folder(folder)

# Launch bot
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_torrent))
    print("🤖 Bot running...")
    await app.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
