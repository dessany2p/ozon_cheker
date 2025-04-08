import os
import logging
import pandas as pd
import pyexcel
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import tempfile
import requests

# Вставьте свой токен ниже
TOKEN = "7041529119:AAFNcjZ5g_SVtxMBKjyCaIXeZdm3-tYKc1A"

# Словарь для хранения загруженных файлов по пользователю
uploaded_files = {}

# Создаем папку для хранения загруженных файлов
os.makedirs("storage", exist_ok=True)

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Отправь мне Excel (.xls) и input.txt, чтобы найти совпадения.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    document = update.message.document
    file_name = document.file_name

    # Определяем путь для сохранения файла по пользователю
    if file_name.endswith(".xls"):
        excel_path = os.path.join("storage", f"{user_id}_excel.xls")
        file_obj = await document.get_file()
        await file_obj.download_to_drive(excel_path)
        uploaded_files.setdefault(user_id, {})["excel"] = excel_path
        await update.message.reply_text(f"✅ Файл {file_name} загружен")
    elif file_name.endswith(".txt"):
        input_path = os.path.join("storage", f"{user_id}_input.txt")
        file_obj = await document.get_file()
        await file_obj.download_to_drive(input_path)
        uploaded_files.setdefault(user_id, {})["input"] = input_path
        await update.message.reply_text(f"✅ Файл {file_name} загружен")

    # Если оба файла загружены, запускаем обработку
    if "excel" in uploaded_files.get(user_id, {}) and "input" in uploaded_files.get(user_id, {}):
        await process_search(update, context, uploaded_files[user_id])

async def process_search(update: Update, context: ContextTypes.DEFAULT_TYPE, paths: dict):
    chat_id = update.message.chat_id
    xls_file = paths["excel"]
    txt_file = paths["input"]
    xlsx_path = xls_file.replace(".xls", ".xlsx")

    try:
        # Конвертация .xls → .xlsx
        pyexcel.save_book_as(file_name=xls_file, dest_file_name=xlsx_path)
        df_raw = pd.read_excel(xlsx_path, header=None, engine="openpyxl")

        # Поиск строки с заголовками
        target_columns = ["Код", "Название культуры, сорта"]
        header_row_idx = None
        for i in range(len(df_raw)):
            row_values = df_raw.iloc[i].astype(str).str.lower()
            if all(any(col.lower() in str(cell) for cell in row_values) for col in target_columns):
                header_row_idx = i
                break
        if header_row_idx is None:
            await update.message.reply_text("❌ Не удалось найти строку с заголовками")
            return

        df = pd.read_excel(xlsx_path, header=header_row_idx, engine="openpyxl")

        with open(txt_file, "r", encoding="utf-8") as f:
            content = f.read().strip().lower()
            search_terms = [term.strip() for term in content.split(",") if term.strip()]

        mask = False
        for term in search_terms:
            mask |= df["Код"].astype(str).str.lower().str.contains(term, na=False)
            mask |= df["Название культуры, сорта"].astype(str).str.lower().str.contains(term, na=False)

        results = df[mask]

        if results.empty:
            await update.message.reply_text("❌ Совпадений не найдено.")
        else:
            # Собираем сообщение и разбиваем на куски (ограничение Telegram — 4096 символов)
            msg = "🔍 Найдены совпадения:\n"
            lines = []
            for _, row in results.iterrows():
                line = f"- {row['Код']} | {row['Название культуры, сорта']}"
                lines.append(line)
            full_msg = msg + "\n".join(lines)
            for i in range(0, len(full_msg), 4000):
                await context.bot.send_message(chat_id=chat_id, text=full_msg[i:i+4000])
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка обработки: {e}")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Обработка команды /search
    query = " ".join(context.args).strip().lower()
    user_id = update.message.from_user.id
    if not query:
        await update.message.reply_text("❗ Используй: /search <твой запрос>")
        return
    if user_id not in uploaded_files or "excel" not in uploaded_files[user_id]:
        await update.message.reply_text("❗ Сначала загрузи Excel файл.")
        return

    # Сохраняем запрос во временный input-файл
    input_path = os.path.join("storage", f"{user_id}_input.txt")
    with open(input_path, "w", encoding="utf-8") as f:
        f.write(query)
    uploaded_files[user_id]["input"] = input_path

    await process_search(update, context, uploaded_files[user_id])

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("🚀 Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
