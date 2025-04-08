import os
import logging
import asyncio
import pandas as pd
import pyexcel
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# === Настройки ===
TOKEN = "7041529119:AAFNcjZ5g_SVtxMBKjyCaIXeZdm3-tYKc1A"
EXCEL_URL = "https://www.ailita.ru/menu/download/docs/11.xls"
DOWNLOAD_TIME = "20:55"  # по локальному времени
CHAT_ID = 376478334  # твой Telegram chat_id

# === Инициализация ===
os.makedirs("storage", exist_ok=True)
logging.basicConfig(level=logging.INFO)


# === Поиск совпадений ===
async def process_search(app, chat_id, input_path="storage/input_main.txt"):
    try:
        xls_path = "storage/global_excel.xls"

        if not os.path.exists(xls_path):
            await app.bot.send_message(chat_id, "❗ Excel файл не найден.")
            return

        if not os.path.exists(input_path):
            await app.bot.send_message(chat_id, "❗ Файл input_main.txt не найден.")
            return

        xlsx_path = xls_path.replace(".xls", ".xlsx")
        pyexcel.save_book_as(file_name=xls_path, dest_file_name=xlsx_path)

        df_raw = pd.read_excel(xlsx_path, header=None, engine="openpyxl")
        target_columns = ["Код", "Название культуры, сорта"]

        header_row_idx = None
        for i in range(len(df_raw)):
            row_values = df_raw.iloc[i].astype(str).str.lower()
            if all(any(col.lower() in str(cell) for cell in row_values) for col in target_columns):
                header_row_idx = i
                break

        if header_row_idx is None:
            await app.bot.send_message(chat_id, "❌ Не найден заголовок в таблице")
            return

        df = pd.read_excel(xlsx_path, header=header_row_idx, engine="openpyxl")

        with open(input_path, "r", encoding="utf-8") as f:
            search_terms = [s.strip() for s in f.read().strip().lower().split(",") if s.strip()]

        mask = False
        for term in search_terms:
            mask |= df["Код"].astype(str).str.lower().str.contains(term, na=False)
            mask |= df["Название культуры, сорта"].astype(str).str.lower().str.contains(term, na=False)

        results = df[mask]

        if results.empty:
            await app.bot.send_message(chat_id, "❌ Совпадений не найдено.")
        else:
            msg = "📥 Использован автоскачанный Excel\n🔍 Найдены совпадения:\n"
            lines = [f"- {row['Код']} | {row['Название культуры, сорта']}" for _, row in results.iterrows()]
            chunks = ["\n".join(lines[i:i + 80]) for i in range(0, len(lines), 80)]
            for chunk in chunks:
                await app.bot.send_message(chat_id, msg + chunk)

    except Exception as e:
        await app.bot.send_message(chat_id, f"⚠️ Ошибка: {e}")


# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Excel обновляется автоматически в 10:00. "
                                    "Отправь input_main.txt, чтобы бот мог выполнять поиск.")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("❗ Используй: /search <твой запрос>")
        return

    input_path = "storage/input_temp.txt"
    with open(input_path, "w", encoding="utf-8") as f:
        f.write(query)

    await process_search(context, update.message.chat_id, input_path=input_path)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    filename = update.message.document.file_name

    if filename.endswith(".xls"):
        path = "storage/global_excel.xls"
        await file.download_to_drive(path)
        await update.message.reply_text("✅ Excel загружен вручную.")
        await process_search(context, update.message.chat_id)

    elif "input" in filename.lower():
        path = "storage/input_main.txt"
        await file.download_to_drive(path)
        await update.message.reply_text("✅ Input загружен как основной.")
        if os.path.exists("storage/global_excel.xls"):
            await process_search(context, update.message.chat_id)


# === Задача автозагрузки ===
async def scheduled_download(app):
    now = datetime.now().strftime("%H:%M")
    if now == DOWNLOAD_TIME:
        try:
            r = requests.get(EXCEL_URL)
            if r.status_code == 200:
                with open("storage/global_excel.xls", "wb") as f:
                    f.write(r.content)
                print("✅ Excel скачан и обновлён")

                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text="✅ Excel обновлён! Запускаю поиск по input_main.txt..."
                )
                await process_search(app, CHAT_ID)
            else:
                print(f"❌ Ошибка скачивания Excel: статус {r.status_code}")
        except Exception as e:
            print(f"⚠️ Ошибка при скачивании Excel: {e}")


# === Запуск приложения ===
async def post_init(app):
    async def schedule_loop():
        while True:
            await scheduled_download(app)
            await asyncio.sleep(60)
    asyncio.create_task(schedule_loop())


def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("🚀 Бот работает")
    app.run_polling()


if __name__ == "__main__":
    main()
