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
DOWNLOAD_TIME = "11:00"  # по локальному времени
CHAT_ID = 376478334  # твой Telegram chat_id


# === Инструкция ===
RULES_TEXT = """📌 Инструкция по использованию Telegram-бота:
/start — приветствие и краткая справка.
/rules или /r — полная инструкция по использованию бота.
/search [запрос] или /s [запрос] — поиск по Excel по одному запросу (не влияет на основной файл).
Пример: /s редис
/input [слова] или /i [слова] — добавить позиции в конец основного файла input_main.txt.
Пример: /i укроп, базилик
/print или /p — показать текущее содержимое input_main.txt.
/edit_input [слова] или /e [слова] — полностью заменить input_main.txt на новый список.
Пример: /e томат, морковь, кабачок

Важно:

Бот каждый день в 11:00 (по серверу) скачивает Excel и запускает автоматический поиск по input_main.txt.

Можно загружать Excel вручную — тогда он будет использоваться с приоритетом и перезапишет авто-скачанный файл.
Название файла с запросами должно быть строго input_main.txt, загрузка файла в чат-бот перезапишет внутренний файл input_main.txt аналогично команде /e .
"""

# === Инициализация ===
os.makedirs("storage", exist_ok=True)
logging.basicConfig(level=logging.INFO)


manual_excel_uploaded = False
# === Скачивание Excel ===

# === Поиск совпадений ===
async def process_search(app, chat_id, input_path="storage/input_main.txt", manual=False):
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

        MAX_MESSAGE_LENGTH = 4000  # немного меньше лимита, чтобы избежать ошибок

# ...
        if results.empty:
            await app.bot.send_message(chat_id, "❌ Совпадений не найдено.")
        else:
            note = "ℹ️ Использован вручную загруженный Excel\n" if manual else "📥 Использован автоскачанный Excel\n"
            lines = [f"- {row['Код']} | {row['Название культуры, сорта']}" for _, row in results.iterrows()]
            
            msg = note
            for line in lines:
                if len(msg) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                    await app.bot.send_message(chat_id, msg.strip())
                    msg = ""  # начинаем новое сообщение
                msg += line + "\n"

            if msg.strip():  # не забываем отправить остаток
                await app.bot.send_message(chat_id, msg.strip())
        await app.bot.send_message(chat_id, "✅ Поиск завершён.")
    except Exception as e:
        await app.bot.send_message(chat_id, f"⚠️ Ошибка: {e}")




# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Excel обновляется автоматически в 11:00.\n"
        "Загружай Excel вручную, если нужно.\n"
        "Команды: /search или /s для поиска, /rules или /r для инструкции."
    )


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RULES_TEXT)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("❗ Используй: /search <твой запрос>")
        return

    input_path = "storage/input_temp.txt"
    with open(input_path, "w", encoding="utf-8") as f:
        f.write(query)

    await process_search(context, update.message.chat_id, input_path=input_path, manual=manual_excel_uploaded)


manual_excel_uploaded = False  # глобальный флаг, должен быть в начале файла

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global manual_excel_uploaded
    file = await update.message.document.get_file()
    filename = update.message.document.file_name

    if filename.endswith(".xls"):
        path = "storage/global_excel.xls"
        await file.download_to_drive(path)
        manual_excel_uploaded = True
        await update.message.reply_text("✅ Excel загружен вручную.")
        if os.path.exists("storage/input_main.txt"):
            await process_search(context, update.message.chat_id, manual=True)

    elif "input" in filename.lower():
        path = "storage/input_main.txt"
        await file.download_to_drive(path)
        await update.message.reply_text("✅ Input загружен как основной.")
        if os.path.exists("storage/global_excel.xls"):
            await process_search(context, update.message.chat_id, manual=manual_excel_uploaded)





# === Задача автозагрузки ===
async def scheduled_download(app):
    global manual_excel_uploaded
    now = datetime.now().strftime("%H:%M")

    if now == DOWNLOAD_TIME:
        try:
            r = requests.get(EXCEL_URL)
            if r.status_code == 200:
                with open("storage/global_excel.xls", "wb") as f:
                    f.write(r.content)
                manual_excel_uploaded = False
                print("✅ Excel скачан и обновлён")

                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text="✅ Excel обновлён! Запускаю поиск по input_main.txt..."
                )
                await process_search(app, CHAT_ID, manual=False)
            else:
                print(f"❌ Ошибка скачивания Excel: статус {r.status_code}")
        except Exception as e:
            print(f"⚠️ Ошибка при скачивании Excel: {e}")

async def append_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("❗ Используй: /i <позиции через запятую>")
        return

    path = "storage/input_main.txt"
    # Создаём файл, если его нет
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(query)
    else:
        with open(path, "a", encoding="utf-8") as f:
            f.write("," + query)

    await update.message.reply_text("✅ Добавлено в input_main.txt:\n" + query)
    # Запускаем поиск
    await process_search(context, update.message.chat_id, manual=manual_excel_uploaded)

async def show_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    path = "storage/input_main.txt"
    if not os.path.exists(path):
        await update.message.reply_text("❗ Файл input_main.txt не найден.")
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        await update.message.reply_text("⚠️ Файл input_main.txt пуст.")
        return

    await update.message.reply_text(f"📄 Содержимое input_main.txt:\n{content}")

async def edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_text = " ".join(context.args).strip().lower()
    if not new_text:
        await update.message.reply_text("❗ Используй: /edit_input <новый список>")
        return

    path = "storage/input_main.txt"
    os.makedirs("storage", exist_ok=True)

    # Перезаписываем файл
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)

    await update.message.reply_text(f"✏️ input_main.txt обновлён: {new_text}")

    # Запускаем поиск
    await process_search(context, update.message.chat_id, manual=manual_excel_uploaded)


# === Инициализация задачи ===
async def post_init(app):
    async def schedule_loop():
        while True:
            await scheduled_download(app)
            await asyncio.sleep(60)
    asyncio.create_task(schedule_loop())


# === Запуск приложения ===
def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("r", rules))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("s", search_command))
    app.add_handler(CommandHandler("i", append_input))
    app.add_handler(CommandHandler("input", append_input))
    app.add_handler(CommandHandler("p", show_input))
    app.add_handler(CommandHandler("print", show_input))
    app.add_handler(CommandHandler("edit_input", edit_input))
    app.add_handler(CommandHandler("e", edit_input))



    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("🚀 Бот работает")
    app.run_polling()


if __name__ == "__main__":
    main()
