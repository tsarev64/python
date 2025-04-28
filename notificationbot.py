import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import calendar
import json
from typing import List, Dict
import os

# Настройки
API_TOKEN = 'Ins_Token'
TEAM_CHAT_ID = chat_id # Командный чат для отправки уведомлений. Example -32737213
SERVICE_CHAT_ID = service_chat_id  # Чат для служебных сообщений. Если хочешь получать сообщения о старт\стоп и других служебных сообщениях в другой чат
TIMEZONE = pytz.timezone('Europe/Moscow')

# Инициализация бота
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

# Дата начала первого спринта
SPRINT_START_DATE = datetime(2025, 4, 23, tzinfo=TIMEZONE)
SPRINT_DURATION_DAYS = 14

# Файл для хранения событий
EVENTS_FILE = "events.json"

# База данных событий
events_db: List[Dict] = []

# Загрузка событий из файла
def load_events():
    global events_db
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r", encoding="utf-8") as file:
            events_db = json.load(file)
    else:
        events_db = []

# Сохранение событий в файл
def save_events():
    with open(EVENTS_FILE, "w", encoding="utf-8") as file:
        json.dump(events_db, file, ensure_ascii=False, indent=4)

# Клавиатура с основными командами
def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('Добавить событие'))
    keyboard.add(KeyboardButton('Список событий'))
    keyboard.add(KeyboardButton('Удалить событие'))
    return keyboard

# Состояния для добавления события
class EventStates(StatesGroup):
    waiting_for_event_name = State()
    waiting_for_event_date = State()
    waiting_for_event_time = State()
    waiting_for_event_repeat = State()

# Функция для расчета текущего дня спринта
def calculate_sprint_day(current_date: datetime) -> int:
    if current_date < SPRINT_START_DATE:
        raise ValueError("Текущая дата не может быть раньше даты начала спринта.")
    
    workday_count = 0
    current_day = SPRINT_START_DATE
    
    while current_day <= current_date:
        if current_day.weekday() < 5:
            workday_count += 1
        current_day += timedelta(days=1)
    
    current_sprint_day = (workday_count - 1) % SPRINT_DURATION_DAYS + 1
    return current_sprint_day

# Проверка на выходной
def is_holiday(date: datetime) -> bool:
    holidays = ["2025-01-01", "2025-01-02", "2025-01-07", "2025-02-23", 
                "2025-03-08", "2025-05-01", "2025-05-09", "2025-06-12", 
                "2025-11-04"]
    return date.strftime("%Y-%m-%d") in holidays or date.weekday() >= 5

# Генератор клавиатуры с календарем
def generate_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=7)
    # Заголовок с месяцем и годом
    month_name = calendar.month_name[month]
    keyboard.row(InlineKeyboardButton(f"{month_name} {year}", callback_data="ignore"))
    # Дни недели
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.row(*[InlineKeyboardButton(day, callback_data="ignore") for day in week_days])
    # Дни месяца
    month_calendar = calendar.monthcalendar(year, month)
    for week in month_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                row.append(InlineKeyboardButton(str(day), callback_data=f"date_{date_str}"))
        keyboard.row(*row)
    # Кнопки навигации
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    keyboard.row(
        InlineKeyboardButton("←", callback_data=f"nav_{prev_year}_{prev_month}"),
        InlineKeyboardButton("→", callback_data=f"nav_{next_year}_{next_month}")
    )
    return keyboard

# Уведомление о дейлике
async def send_daily_notification():
    now = datetime.now(TIMEZONE)
    if is_holiday(now):
        return
    current_sprint_day = calculate_sprint_day(now)
    message = (
        f"Сегодня {current_sprint_day}-й день спринта.⏰ Коллеги, скоро начнётся daily!\n"
        f"Приглашаю всех в DION "
    )
    await bot.send_message(TEAM_CHAT_ID, message)

# Планировщик уведомлений о событиях
async def send_event_notifications():
    now = datetime.now(TIMEZONE)
    if is_holiday(now):
        return
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    for event in events_db:
        if event['time'] == current_time:
            if event.get('repeat', False) or event.get('date', '') == current_date:
                await bot.send_message(TEAM_CHAT_ID, f"⏰ Событие: {event['name']} начинается сейчас!")

# Автоматическая очистка одноразовых событий
async def cleanup_old_events():
    global events_db
    now = datetime.now(TIMEZONE)
    current_date = now.strftime("%Y-%m-%d")
    initial_count = len(events_db)
    events_db = [
        event for event in events_db
        if event.get('repeat', False) or event.get('date', '') >= current_date
    ]
    removed_count = initial_count - len(events_db)
    if removed_count > 0:
        save_events()  # Сохраняем обновленный список событий
        logging.info(f"Удалено {removed_count} устаревших событий.")
        await bot.send_message(SERVICE_CHAT_ID, f"🧹 Автоматически удалено {removed_count} устаревших событий.")

# Команда /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Я Scrum-бот. Вот что я умею:",
        reply_markup=get_main_keyboard()
    )

# Команда /sprint_status
@dp.message_handler(commands=['sprint_status'])
async def sprint_status(message: types.Message):
    now = datetime.now(TIMEZONE)
    current_sprint_day = calculate_sprint_day(now)
    await message.reply(f"Сегодня {current_sprint_day}-й день спринта.")

# Обработка кнопки "Добавить событие"
@dp.message_handler(lambda message: message.text == 'Добавить событие')
async def add_event_start(message: types.Message):
    await EventStates.waiting_for_event_name.set()
    await message.reply("Введите название события:")

@dp.message_handler(state=EventStates.waiting_for_event_name)
async def add_event_name(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['name'] = message.text
    now = datetime.now(TIMEZONE)
    await EventStates.next()
    await message.reply(
        "Выберите дату события:",
        reply_markup=generate_calendar(now.year, now.month)
    )

@dp.callback_query_handler(lambda c: c.data.startswith('date_'), state=EventStates.waiting_for_event_date)
async def process_date(callback_query: types.CallbackQuery, state: FSMContext):
    date_str = callback_query.data.replace('date_', '')
    async with state.proxy() as data:
        data['date'] = date_str
    await EventStates.next()
    await bot.send_message(
        callback_query.from_user.id,
        "Введите время события в формате ЧЧ:ММ (например, 10:00):"
    )
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data.startswith('nav_'), state=EventStates.waiting_for_event_date)
async def process_navigation(callback_query: types.CallbackQuery, state: FSMContext):
    _, year, month = callback_query.data.split('_')
    await bot.edit_message_reply_markup(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=generate_calendar(int(year), int(month))
    )
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=EventStates.waiting_for_event_time)
async def add_event_time(message: types.Message, state: FSMContext):
    try:
        datetime.strptime(message.text, "%H:%M")
    except ValueError:
        await message.reply("Неверный формат времени. Введите время в формате ЧЧ:ММ (например, 10:00).")
        return
    async with state.proxy() as data:
        data['time'] = message.text
    await EventStates.next()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Однократное", callback_data="repeat_no"))
    keyboard.add(InlineKeyboardButton("Повторяющееся", callback_data="repeat_yes"))
    await message.reply("Выберите тип события:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('repeat_'), state=EventStates.waiting_for_event_repeat)
async def process_repeat(callback_query: types.CallbackQuery, state: FSMContext):
    repeat = callback_query.data.replace('repeat_', '') == 'yes'
    async with state.proxy() as data:
        event = {
            'name': data['name'],
            'time': data['time'],
            'repeat': repeat
        }
        if not repeat:
            event['date'] = data['date']
        events_db.append(event)
        save_events()  # Сохраняем события в файл
    await state.finish()
    await bot.send_message(
        callback_query.from_user.id,
        f"Событие '{data['name']}' добавлено на {data['time']} ({'повторяющееся' if repeat else 'однократное'})!",
        reply_markup=get_main_keyboard()
    )
    await bot.answer_callback_query(callback_query.id)

# Обработка кнопки "Список событий"
@dp.message_handler(lambda message: message.text == 'Список событий')
async def list_events(message: types.Message):
    if not events_db:
        await message.reply("Нет активных событий.")
    else:
        events_list = []
        for i, event in enumerate(events_db, 1):
            event_type = "🔁 Повторяющееся" if event.get('repeat', False) else "📅 Однократное"
            date_info = f" ({event['date']})" if 'date' in event else ""
            events_list.append(f"{i}. {event['name']} в {event['time']}{date_info} - {event_type}")
        await message.reply("Список событий:\n" + "\n".join(events_list))

# Обработка кнопки "Удалить событие"
@dp.message_handler(lambda message: message.text == 'Удалить событие')
async def delete_event_start(message: types.Message):
    if not events_db:
        await message.reply("Нет событий для удаления.")
    else:
        keyboard = InlineKeyboardMarkup()
        for i, event in enumerate(events_db, 1):
            keyboard.add(InlineKeyboardButton(
                text=f"{i}. {event['name']} ({event['time']})",
                callback_data=f"delete_{i-1}"
            ))
        await message.reply("Выберите событие для удаления:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('delete_'))
async def process_delete(callback_query: types.CallbackQuery):
    event_index = int(callback_query.data.replace('delete_', ''))
    if 0 <= event_index < len(events_db):
        deleted_event = events_db.pop(event_index)
        save_events()  # Обновляем файл после удаления
        await bot.send_message(
            callback_query.from_user.id,
            f"Событие '{deleted_event['name']}' удалено!",
            reply_markup=get_main_keyboard()
        )
    else:
        await bot.send_message(callback_query.from_user.id, "Ошибка: событие не найдено.")
    await bot.answer_callback_query(callback_query.id)

# Обработка ошибок и перезапуск
async def on_startup(dp):
    load_events()  # Загружаем события из файла при старте
    scheduler.start()
    logging.info("Планировщик задач запущен.")
    await bot.send_message(SERVICE_CHAT_ID, "Бот \"МФО\" для ИС 3624 запущен!")

async def on_shutdown(dp):
    scheduler.shutdown()
    logging.info("Планировщик задач остановлен.")
    await bot.send_message(SERVICE_CHAT_ID, "Бот \"МФО\" для ИС 3624 остановлен.")

# узнать ID группы. При эксплуатации можно выключать. Добавить бота в группу. Сделать админом(чтобы мог читать сообщения чата) написать сообщение в чат, поймать в логах чат_ИД
#@dp.message_handler()
#async def get_chat_id(message: types.Message):
#    print(f"Group Chat ID: {message.chat.id}")

# Запуск планировщика
scheduler.add_job(
    send_daily_notification,
    trigger=CronTrigger(hour=9, minute=29),  # Уведомление в 09:29 по МСК
)
scheduler.add_job(
    send_event_notifications,
    trigger=CronTrigger(minute="*"),  # Проверка каждую минуту
)
scheduler.add_job(
    cleanup_old_events,
    trigger=CronTrigger(hour=0, minute=0),  # Очистка событий раз в сутки в полночь
)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)
