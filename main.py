import csv, os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from zoneinfo import ZoneInfo


load_dotenv()  # читает .env в текущей директории
ENV = os.getenv("ENV", "PROD")
BOT_TOKEN = os.getenv("PROD_BOT_TOKEN") if ENV == "PROD" else os.getenv("TEST_BOT_TOKEN")
FILE_SCHEDULE = os.getenv("FILE_SCHEDULE")
ASK_DATE, ASK_TIME, ASK_TITLE, ASK_LOCATION = range(4)


def read_schedule_csv(filename: str) -> list:
    meetings = []
    with open(filename, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tz = ZoneInfo(row.get("timezone", "Europe/Moscow"))
            dt = datetime.strptime(row["start_at"], "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=tz)

            meetings.append({
                "title": row["title"],
                "start_at": dt,
                "dion": row["dion"]
            })

    return meetings


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот-напоминалка.")


async def reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    reminder = job.data["reminder"]
    meeting = job.data["meeting"]

    message = f"{reminder}\n\n" + f"Start at: {meeting['start_at'].strftime('%Y-%m-%d %H:%M')}\n" + f"Dion: {meeting['dion']}"
    await context.bot.send_message(job.chat_id, message)


# async def remind_in_10(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     chat_id = update.effective_chat.id
#     run_at = datetime.now(timezone.utc) + timedelta(seconds=15)
#     print("Run at: {run_at}")

#     context.job_queue.run_once(
#         reminder_callback,
#         when=run_at,
#         chat_id=chat_id,
#         # data={"text": "Напоминание через 10 минут нахуй!"},
#         data={"meeting": meetings[0]},
#         name=f"reminder_{chat_id}",
#     )
#     await update.message.reply_text("Ок, напомню через 10 минут!")


def schedule_meeting_jobs(meetings, chat_id, job_queue):
    now = datetime.now(timezone.utc)

    for meeting in meetings:
        start_at = meeting["start_at"]  # datetime с tzinfo
        start_at_utc = start_at.astimezone(timezone.utc)
        title = meeting["title"]

        # три момента напоминаний
        times = [
            (start_at_utc - timedelta(minutes=15), f"Через 15 минут встреча: \"{title}\""),
            (start_at_utc - timedelta(minutes=5),  f"Через 5 минут встреча: \"{title}\""),
            (start_at_utc,                         f"Встреча началась: \"{title}\""),
        ]

        for run_at, reminder in times:
            # не ставим задачи в прошлое
            if run_at <= now:
                continue

            job_queue.run_once(
                reminder_callback,
                when=run_at,
                chat_id=chat_id,
                data={"reminder": reminder, "meeting": meeting},
                name=f"{chat_id}_{start_at.isoformat()}_{reminder}",
            )


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    meetings = read_schedule_csv(FILE_SCHEDULE)
    # meetings = [
    #     {
    #         "title": "Созвон с командой",
    #         "start_at": datetime(2026, 1, 20, 18, 18, tzinfo=ZoneInfo("Europe/Moscow")),
    #         "dion": "https://dion.vc/event/ilin-au-vtb"
    #     },
    # ]
    
    schedule_meeting_jobs(meetings, chat_id, context.job_queue)

    await update.message.reply_text(
        "Расписание загружено, напоминания будут за 15 минут, 5 минут и в момент начала."
    )


async def get_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    schedule = []
    message = ""

    for job in context.job_queue.jobs():
        if job.data['meeting'] not in schedule:
            schedule.append(job.data['meeting'])

    for meeting in schedule:
        message += " ".join((meeting['start_at'].strftime('%Y-%m-%d %H:%M'), meeting['title'], meeting['dion'], "\n\n"))

    await update.message.reply_text(message or "Расписание пусто!")


async def clear_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get a list of all currently scheduled jobs
    all_jobs = context.job_queue.jobs()

    # Remove each job
    for job in all_jobs:
        job.remove()

    await update.message.reply_text("Расписание очищено!")


async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите дату события в формате ГГГГ-ММ-ДД (например, 2026-01-21)")
    return ASK_DATE


async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        date = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text("Неверный формат даты. Попробуйте ещё раз: ГГГГ-ММ-ДД")
        return ASK_DATE

    context.user_data["new_event"] = {"date": date}
    await update.message.reply_text("Введите время события в формате ЧЧ:ММ (например, 14:30)")
    return ASK_TIME


async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        time = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text("Неверный формат времени. Попробуйте ещё раз: ЧЧ:ММ")
        return ASK_TIME

    context.user_data["new_event"]["time"] = time
    await update.message.reply_text("Введите название события")
    return ASK_TITLE


async def ask_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    context.user_data["new_event"]["title"] = text
    await update.message.reply_text("Введите место события")
    return ASK_LOCATION


async def ask_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    context.user_data["new_event"]["location"] = text
    event = context.user_data["new_event"]
    
    start_at = datetime.combine(event['date'], event['time'])

    meetings = [{
        "title": event['title'],
        "start_at": start_at,
        "dion": event['location']
        },
    ]
    
    chat_id = update.effective_chat.id

    schedule_meeting_jobs(meetings, chat_id, context.job_queue)

    message = (
        "Событие добавлено:\n\n"
        f"Дата: {event['date'].isoformat()}\n"
        f"Время: {event['time'].strftime('%H:%M')}\n"
        f"Название: {event['title']}\n"
        f"Место: {event['location']}"
    )

    await update.message.reply_text(message)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_event", None)
    await update.message.reply_text("Добавление события отменено.")
    return ConversationHandler.END


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CommandHandler("get_schedule", get_schedule))
    app.add_handler(CommandHandler("clear_schedule", clear_schedule))
    
    add_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add_event", add_event)],
        states={
            ASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date)],
            ASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            ASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_title)],
            ASK_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_location)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(add_conv_handler)

    app.run_polling()  # запускает long polling и слушает апдейты


if __name__ == "__main__":
    main()
