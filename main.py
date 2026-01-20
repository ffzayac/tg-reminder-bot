import csv, os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from zoneinfo import ZoneInfo


load_dotenv()  # читает .env в текущей директории

BOT_TOKEN = os.getenv("BOT_TOKEN")
FILE_SCHEDULE = os.getenv("FILE_SCHEDULE")
# print(BOT_TOKEN)


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
    
    print(job_queue.jobs())


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
    print("*****************************")
    print(context.job_queue.jobs())


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    # app.add_handler(CommandHandler("remind10", remind_in_10))
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CommandHandler("get_schedule", get_schedule))

    app.run_polling()  # запускает long polling и слушает апдейты


if __name__ == "__main__":
    main()
