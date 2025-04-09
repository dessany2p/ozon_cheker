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
import pytz
import json


# === Настройки ===
TOKEN = "7041529119:AAFNcjZ5g_SVtxMBKjyCaIXeZdm3-tYKc1A"
EXCEL_URL = "https://www.ailita.ru/menu/download/docs/11.xls"

CHAT_ID = 376478334  # твой Telegram chat_id
SETTINGS_FILE = "settings.json"
# === Загрузка настроек ===



def load_settings():
    if os.path.exists("settings.json"):
        with open("settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_settings(data):
    with open("settings.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

settings = load_settings()

DOWNLOAD_TIME = settings.get("download_time", "11:30")

# === инструкция ===
def get_rules_text():
    return f"""📌 Инструкция по использованию Telegram-бота:

/start — краткая справка.
/rules или /r — показать эту инструкцию.
/search или /s [запрос] — разовый поиск по Excel, без сохранения.
/input или /i [позиции] — добавить позиции в конец файла input_main.txt.
/print или /p — показать текущее содержимое input_main.txt.
/edit_input или /e [позиции] — полностью заменить содержимое input_main.txt.
/logs или /l — показать дату последнего обновления Excel и input_main.txt.
/settime [время] — установить время автозагрузки Excel (формат HH:MM).
Пример: /settime 14:00
/time или /t — показать текущее установленное время автозагрузки.
/download или /d - вручную скачать Excel с сайта и запустить поиск.

⏰ Автозагрузка Excel каждый день в {DOWNLOAD_TIME} по МСК. После загрузки запускается поиск по input_main.txt.

📥 Можно загружать Excel вручную — он перезапишет автоскачанный файл и будет использован в приоритете.
📄 Название файла с запросами должно быть строго input_main.txt — загрузка такого файла заменит его содержимое.
"""



# === Инициализация ===
os.makedirs("storage", exist_ok=True)


# === Логирование ===
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "bot.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)


manual_excel_uploaded = False
last_excel_update = None
last_input_update = None
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
        f"👋 Привет! Excel обновляется автоматически в {DOWNLOAD_TIME}.\n"
        "Загружай Excel вручную, если нужно.\n"
        "Команды: /search или /s для поиска, /rules или /r для инструкции."
    )


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_rules_text())
    # Отправляем инструкцию


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
    global manual_excel_uploaded, last_excel_update, last_input_update
    file = await update.message.document.get_file()
    filename = update.message.document.file_name

    if filename.endswith(".xls"):
        path = "storage/global_excel.xls"
        await file.download_to_drive(path)
        manual_excel_uploaded = True
        await update.message.reply_text("✅ Excel загружен вручную.")
        last_excel_update = datetime.now(pytz.timezone("Europe/Moscow"))

        if os.path.exists("storage/input_main.txt"):
            await process_search(context, update.message.chat_id, manual=True)

    elif filename.lower() == "input_main.txt":

        path = "storage/input_main.txt"
        await file.download_to_drive(path)
        await update.message.reply_text("✅ Input загружен как основной.")
        last_input_update = datetime.now(pytz.timezone("Europe/Moscow"))
        if os.path.exists("storage/global_excel.xls"):
            await process_search(context, update.message.chat_id, manual=manual_excel_uploaded)


async def show_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = pytz.timezone("Europe/Moscow")
    msg = "🧾 Логи обновлений:\n"

    if last_excel_update:
        msg += f"📥 Excel: {last_excel_update.strftime('%d.%m %H:%M')} (МСК)\n"
    else:
        msg += "📥 Excel: ещё не обновлялся\n"

    if last_input_update:
        msg += f"📝 input_main.txt: {last_input_update.strftime('%d.%m %H:%M')} (МСК)\n"
    else:
        msg += "📝 input_main.txt: ещё не обновлялся\n"

    settings = load_settings()
    if "excel_last_status" in settings:
        msg += f"📊 Статус последней попытки скачивания Excel: {settings['excel_last_status']}\n"

    await update.message.reply_text(msg)
    logging.info("Показаны логи обновлений.")


# === Задача автозагрузки Excel ===
async def scheduled_download(app):
    global manual_excel_uploaded, last_excel_update, last_input_update
    tz = pytz.timezone("Europe/Moscow")
    now_dt = datetime.now(tz)
    now = now_dt.strftime("%H:%M")

    print(f"[{now}] ⏰ Проверка времени для автозагрузки...")
    logging.info(f"Проверка времени: сейчас {now}, целевое время — {DOWNLOAD_TIME}")

    if now == DOWNLOAD_TIME:
        print(f"[{now}] ⏬ Время совпало, начинаем загрузку Excel...")
        logging.info(f"⏰ Время совпало: {now} — запускаю попытку скачивания Excel.")

        try:
            r = requests.get(EXCEL_URL)
            if r.status_code == 200:
                with open("storage/global_excel.xls", "wb") as f:
                    f.write(r.content)

                manual_excel_uploaded = False
                last_excel_update = now_dt
                logging.info(f"✅ Excel успешно скачан и сохранён в {now} (МСК)")
                print(f"[{now}] ✅ Excel успешно скачан и сохранён.")

                # ✅ Обновляем статус
                settings = load_settings()
                settings["excel_last_status"] = f"успешно ({now})"
                save_settings(settings)

                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"✅ Excel обновлён в {now} (МСК)! Запускаю поиск по input_main.txt..."
                )

                await process_search(app, CHAT_ID, manual=False)
                logging.info("Поиск по input_main.txt завершён.")
            else:
                msg = f"❌ Ошибка скачивания Excel: статус {r.status_code}"
                logging.warning(msg)
                print(f"[{now}] ❌ {msg}")

                # ❌ Обновляем статус
                settings = load_settings()
                settings["excel_last_status"] = f"ошибка {r.status_code} ({now})"
                save_settings(settings)

                await app.bot.send_message(chat_id=CHAT_ID, text=msg)

        except Exception as e:
            msg = f"⚠️ Ошибка при скачивании Excel: {e}"
            logging.exception(msg)
            print(f"[{now}] ⚠️ {msg}")

            # ❌ Обновляем статус
            settings = load_settings()
            settings["excel_last_status"] = f"ошибка: {str(e)} ({now})"
            save_settings(settings)

            await app.bot.send_message(chat_id=CHAT_ID, text=msg)




# === Инициализация периодической задачи ===
async def post_init(app):
    print("🟢 post_init запущен — бот инициализируется")
    logging.info("post_init запущен — бот инициализируется")

    # Отправляем сообщение в Telegram о запуске
    try:
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text="🔄 Бот перезапущен и работает.\nАвтопоиск каждый день в " + DOWNLOAD_TIME
        )
        print("📤 Отправлено сообщение в Telegram о перезапуске")
        logging.info("Отправлено сообщение о перезапуске бота")

    except Exception as e:
        print(f"⚠️ Ошибка при отправке уведомления о запуске: {e}")
        logging.exception("Ошибка при отправке уведомления о запуске")

    # Цикл автообновления
    async def schedule_loop():
        print("🔁 schedule_loop стартовал")
        while True:
            await scheduled_download(app)
            await asyncio.sleep(60)

    asyncio.create_task(schedule_loop())


async def append_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_input_update
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
    last_input_update = datetime.now(pytz.timezone("Europe/Moscow"))

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
    global last_input_update  # ← добавляем, чтобы обновить
    new_text = " ".join(context.args).strip().lower()
    if not new_text:
        await update.message.reply_text("❗ Используй: /edit_input <новый список>")
        return

    path = "storage/input_main.txt"
    os.makedirs("storage", exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)

    last_input_update = datetime.now(pytz.timezone("Europe/Moscow"))  # ← фикс
    await update.message.reply_text(f"✏️ input_main.txt обновлён: {new_text}")

    # Запускаем поиск
    await process_search(context, update.message.chat_id, manual=manual_excel_uploaded)


async def set_download_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Укажи новое время в формате HH:MM\nПример: `/settime 10:45`", parse_mode="Markdown")
        return

    new_time = context.args[0]
    try:
        # Проверка формата времени
        datetime.strptime(new_time, "%H:%M")

        # Обновляем в settings.json
        settings = load_settings()
        settings["download_time"] = new_time
        save_settings(settings)

        global DOWNLOAD_TIME
        DOWNLOAD_TIME = new_time

        await update.message.reply_text(f"⏰ Время автозагрузки Excel обновлено на {new_time} (МСК)")
    except ValueError:
        await update.message.reply_text("⚠️ Неверный формат времени. Используй HH:MM (например, 09:30)")

async def get_download_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"⏰ Текущее время автозагрузки Excel — {DOWNLOAD_TIME} (МСК)")

async def manual_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global manual_excel_uploaded, last_excel_update
    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)

    try:
        r = requests.get(EXCEL_URL)
        if r.status_code == 200:
            with open("storage/global_excel.xls", "wb") as f:
                f.write(r.content)

            manual_excel_uploaded = False
            last_excel_update = now
            logging.info(f"📥 Excel вручную загружен по ссылке в {now.strftime('%H:%M')} (МСК)")

            await update.message.reply_text(f"✅ Excel вручную загружен по ссылке в {now.strftime('%H:%M')} (МСК)")
            await process_search(context, update.message.chat_id, manual=False)

        else:
            msg = f"❌ Не удалось скачать Excel: статус {r.status_code}"
            logging.warning(msg)
            await update.message.reply_text(msg)

    except Exception as e:
        msg = f"⚠️ Ошибка при загрузке Excel вручную: {e}"
        logging.exception(msg)
        await update.message.reply_text(msg)


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
    app.add_handler(CommandHandler("l", show_log))
    app.add_handler(CommandHandler("logs", show_log))
    app.add_handler(CommandHandler("settime", set_download_time))   
    app.add_handler(CommandHandler("time", get_download_time))
    app.add_handler(CommandHandler("t", get_download_time))
    app.add_handler(CommandHandler("download", manual_download))
    app.add_handler(CommandHandler("d", manual_download))


    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("🚀 Бот работает")
    app.run_polling()


if __name__ == "__main__":
    try:
        start_time = datetime.now(pytz.timezone("Europe/Moscow"))
        logging.info("🔄 Бот запущен.")
        main()
    except Exception as e:
        crash_time = datetime.now(pytz.timezone("Europe/Moscow"))
        duration = crash_time - start_time
        logging.exception("💥 Бот упал с ошибкой:")

        # Уведомим в Telegram
        import telegram
        bot = telegram.Bot(token=TOKEN)
        try:
            bot.send_message(
                chat_id=CHAT_ID,
                text=(
                    f"❌ Бот упал в {crash_time.strftime('%H:%M:%S %d.%m')} (МСК)\n"
                    f"⏱ Был в онлайне: {duration}\n"
                    f"Ошибка записана в лог."
                )
            )
        except Exception as notify_err:
            logging.error(f"⚠️ Не удалось отправить сообщение об ошибке: {notify_err}")
            logging.error(f"🛑 Ошибка: {e}")
