import csv
import os
from datetime import datetime, timedelta, timezone, date
from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from zoneinfo import ZoneInfo

from db import (
    init_db,
    add_event_db,
    add_notification_db,
    get_event_by_id,
    get_notification_by_id,
    update_notification_by_id,
    delete_event_by_id,
    get_notifications_by_event_id,
    delete_notification_by_job,
    delete_all_notifications,
    get_notifation_by_job,
    bulk_insert_events,
    get_unschedule_events,
    update_event_status_by_id,
    delete_all_events
)


load_dotenv()  # читает .env в текущей директории

DION_URL = "https://dion.vc/event/"
ENV = os.getenv("ENV", "PROD")
BOT_TOKEN = os.getenv("PROD_BOT_TOKEN") if ENV == "PROD" else os.getenv("TEST_BOT_TOKEN")
FILE_SCHEDULE = os.getenv("FILE_SCHEDULE")
ASK_DATE, ASK_TIME, ASK_TITLE, ASK_LOCATION, ASK_EVENT_ID = range(5)

BASE_COMMANDS = [
    BotCommand("add_event", "добавить событие"),
    BotCommand("delete_event", "удалить событие"),
    BotCommand("clear_schedule", "очистить расписание"),
    BotCommand("schedule", "запланировать"),
    BotCommand("get_schedule", "получить расписание"), 
]

CONV_COMMANDS = [
    BotCommand("cancel", "отменить добавление"),
]


async def set_base_commands(bot):
    # устанавливаем дефолтные команды бота
    scope = BotCommandScopeDefault()
    await bot.set_my_commands(BASE_COMMANDS, scope=scope)


async def set_conv_commands(chat_id: int, bot):
    # устанавливаем персональные команды чата в диалоге ConversationHandler
    scope = BotCommandScopeChat(chat_id=chat_id)
    await bot.set_my_commands(CONV_COMMANDS, scope=scope)


async def reset_chat_commands(chat_id: int, bot):
    # удаляем персональные команды чата, чтобы снова действовал default
    scope = BotCommandScopeChat(chat_id=chat_id)
    await bot.delete_my_commands(scope=scope)


def read_schedule_csv(filename: str) -> list:
    meetings = []
    with open(filename, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tz = ZoneInfo(row.get("timezone", "Europe/Moscow"))
            dt = datetime.strptime(row["start_at"], "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=tz)
            dt = dt.astimezone(timezone.utc)
            
            if dt > datetime.now(timezone.utc):
                meetings.append({
                    "title": row["title"],
                    "start_at": dt,
                    "location": row["location"]
                })

    return meetings


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    bot = context.bot
    
    await reset_chat_commands(chat_id, bot)
    await set_base_commands(bot)

    await update.message.reply_text("Привет! Я бот-напоминалка.")


async def reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    notification = get_notifation_by_job(job.name)
    cnt = len(get_notifications_by_event_id(notification["event_id"]))

    start_at = job.data['start_at'].astimezone(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d %H:%M")
    message = f"{job.data['reminder']}\n\n" + f"Start at: {start_at}\n" + f"Location: {job.data['location']}"

    await context.bot.send_message(job.chat_id, message)
    if cnt == 1:
        delete_event_by_id(notification["event_id"])
    else:
        delete_notification_by_job(job.name)


def add_notifications_for_event(event_id, job_queue):
    event_row = get_event_by_id(event_id)
    
    start_at_utc = datetime.strptime(event_row["start_at"][:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)

    # три момента напоминаний
    times = [
        (start_at_utc - timedelta(minutes=15), f"Через 15 минут встреча: \"{event_row['title']}\""),
        (start_at_utc - timedelta(minutes=5),  f"Через 5 минут встреча: \"{event_row['title']}\""),
        (start_at_utc,                         f"Встреча началась: \"{event_row['title']}\""),
    ]
    
    now = datetime.now(timezone.utc)

    for notify_at, reminder in times:
        # не ставим задачи в прошлое
        if notify_at <= now:
            continue
        
        job = job_queue.run_once(
        reminder_callback,
        when=notify_at,
        chat_id=event_row["chat_id"],
        data={
            "event_id": event_id,
            "title": event_row["title"],
            "start_at": start_at_utc,
            "reminder": reminder,
            "location": event_row["location"]
        },
        name=f"{event_row['chat_id']}_{notify_at}_{reminder}",
        )

        notification_id = add_notification_db(event_id, reminder, notify_at, job.name)
        update_event_status_by_id(event_id, 1)

    
    return notification_id


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    meetings = read_schedule_csv(FILE_SCHEDULE)
    bulk_insert_events(chat_id, meetings)

    schedule_notifications(context.job_queue)

    await update.message.reply_text(
        "Расписание загружено, напоминания будут за 15 минут, 5 минут и в момент начала."
    )


def schedule_notifications(job_queue):
    unscheduled_events = get_unschedule_events()
    
    for unschedule_event in unscheduled_events:
        add_notifications_for_event(unschedule_event["id"], job_queue)


async def get_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    schedule = []
    message = ""
    event_keys = ["event_id", "title", "location", "start_at"]

    for job in context.job_queue.jobs():
        event = {k: job.data[k] for k in event_keys if k in job.data}
        # event = job.data
        if event not in schedule:
            schedule.append(event)

    for event in schedule:
        start_at = event["start_at"].astimezone(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d %H:%M")
        message += " ".join([f"[{event['event_id']}]", start_at, f"\"{event['title']}\"", event["location"], "\n\n"])

    await update.message.reply_text(message or "Расписание пусто!")


async def clear_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get a list of all currently scheduled jobs
    all_jobs = context.job_queue.jobs()

    # Remove each job
    for job in all_jobs:
        job.remove()
    
    delete_all_events()

    await update.message.reply_text("Расписание очищено!")


async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Готовим callback_data: по ним date_from_button поймёт, что выбрано
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"Сегодня ({today.isoformat()})",
                callback_data=f"date:{today.isoformat()}",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Завтра ({tomorrow.isoformat()})",
                callback_data=f"date:{tomorrow.isoformat()}",
            )
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    chat_id = update.effective_chat.id

    await set_conv_commands(chat_id, context.bot)
    await update.message.reply_text("Введите дату события в формате ГГГГ-ММ-ДД (например, 2026-01-21)", reply_markup=reply_markup)

    return ASK_DATE


async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    
    try:
        start_at_date = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text("Неверный формат даты. Попробуйте ещё раз: ГГГГ-ММ-ДД")
        return ASK_DATE

    context.user_data["new_event"] = {"start_at": start_at_date}
    await update.message.reply_text("Введите время события в формате ЧЧ:ММ (например, 14:30)")
    return ASK_TIME


async def ask_date_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора даты через кнопку."""
    query = update.callback_query
    await query.answer()

    data = query.data  # например, "date:2026-02-05"
    _, value = data.split(":", 1)
    chosen_date = datetime.strptime(value, "%Y-%m-%d").date()  # строка "2026-02-05"

    # Здесь можно сохранить дату в context.user_data или в БД
    context.user_data["new_event"] = {"start_at": chosen_date}

    await query.message.reply_text("Введите время события в формате ЧЧ:ММ (например, 14:30)")
    return ASK_TIME


async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        start_at_time = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text("Неверный формат времени. Попробуйте ещё раз: ЧЧ:ММ")
        return ASK_TIME

    start_at = datetime.combine(context.user_data["new_event"]["start_at"], start_at_time)

    context.user_data["new_event"]["start_at"] = start_at
    await update.message.reply_text("Введите название события")
    return ASK_TITLE


async def ask_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    context.user_data["new_event"]["title"] = text
    await update.message.reply_text("Введите место события")
    return ASK_LOCATION


async def ask_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    bot = context.bot
    text = update.message.text.strip()

    location = text.split(" ")
    location = DION_URL + location[1] if len(location) == 2 and location[0] == "dion" else text

    context.user_data["new_event"]["location"] = location
    event = context.user_data["new_event"]

    event_id = add_event_db(chat_id, event["title"], event["location"], event["start_at"])

    event["event_id"] = event_id

    add_notifications_for_event(event_id, context.job_queue)
    await reset_chat_commands(chat_id, bot)

    message = (
        "Событие добавлено:\n\n"
        f"Дата: {event['start_at'].date().isoformat()}\n"
        f"Время: {event['start_at'].time().strftime('%H:%M')}\n"
        f"Название: {event['title']}\n"
        f"Место: {event['location']}"
    )

    await update.message.reply_text(message)
    context.user_data.pop("new_event", None)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    bot = context.bot

    await reset_chat_commands(chat_id, bot)

    await update.message.reply_text("Добавление события отменено.")
    context.user_data.pop("new_event", None)

    return ConversationHandler.END


async def delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    await set_conv_commands(chat_id, context.bot)
    await update.message.reply_text("Введите ID события для удаления")

    return ASK_EVENT_ID


async def ask_event_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    bot = context.bot
    job_queue = context.job_queue

    text = update.message.text.strip()
    try:
        event_id = int(text)
    except ValueError:
        await update.message.reply_text("Введено некорректное значение идентифкатора события.")
        return ASK_EVENT_ID
    
    notifications = get_notifications_by_event_id(event_id)
    
    for notification in notifications:
        for job in job_queue.get_jobs_by_name(notification['job_name']):
            print(job)
            job.schedule_removal()
    
    delete_event_by_id(event_id)
    
    await reset_chat_commands(chat_id, bot)
    await update.message.reply_text(f"Событие [{event_id}] удалено.")

    return ConversationHandler.END


def main():
    init_db(True if ENV == "TEST" else False)  # создаём таблицы, если их нет
    # init_db(False)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CommandHandler("get_schedule", get_schedule))
    app.add_handler(CommandHandler("clear_schedule", clear_schedule))

    add_event_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add_event", add_event)],
        states={
            ASK_DATE: [
                CallbackQueryHandler(ask_date_from_button, pattern=r"^date:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date),
            ],
            ASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            ASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_title)],
            ASK_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_location)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    delete_event_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("delete_event", delete_event)],
        states={
            ASK_EVENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_event_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(add_event_conv_handler)
    app.add_handler(delete_event_conv_handler)

    app.run_polling()  # запускает long polling и слушает апдейты


if __name__ == "__main__":
    main()
