import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional
import re
import random

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# Токен бота
BOT_TOKEN = "8489477150:AAGaipKgwWfiSgH3IdRyAnyNBXwAE_bknf0"
ADMIN_ID = 8423212939

# Глобальная переменная для ID группы
GROUP_ID = None

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Хранилище заказов и тикетов поддержки
orders: Dict[int, dict] = {}
support_tickets: Dict[int, dict] = {}
user_tickets: Dict[int, int] = {}

# Генератор четырехзначных номеров
def generate_ticket_number() -> int:
    while True:
        number = random.randint(1000, 9999)
        if number not in support_tickets:
            return number

def generate_order_number() -> int:
    while True:
        number = random.randint(1000, 9999)
        used = False
        for order in orders.values():
            if order.get('order_number') == number:
                used = True
                break
        if not used:
            return number

# Состояния для FSM
class OrderStates(StatesGroup):
    waiting_for_description = State()
    waiting_for_review_link = State()
    waiting_for_payment_confirm = State()

class SupportStates(StatesGroup):
    waiting_for_user_message = State()
    waiting_for_admin_reply = State()

class AdminStates(StatesGroup):
    waiting_for_group_id = State()
    waiting_for_ticket_reply = State()
    waiting_for_user_message = State()
    waiting_for_order_link = State()
    waiting_for_order_number = State()

# Функция для отправки уведомлений в группу
async def send_group_notification(text: str, parse_mode: str = "Markdown"):
    global GROUP_ID
    if GROUP_ID:
        try:
            await bot.send_message(GROUP_ID, text, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Ошибка отправки в группу: {e}")

# Функция проверки админа
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# Функции для работы с тикетами
def get_or_create_ticket(user_id: int, username: str = None) -> dict:
    if user_id in user_tickets:
        ticket_id = user_tickets[user_id]
        if ticket_id in support_tickets:
            return support_tickets[ticket_id]
    
    ticket_id = generate_ticket_number()
    support_tickets[ticket_id] = {
        'ticket_id': ticket_id,
        'user_id': user_id,
        'username': username,
        'messages': [],
        'status': 'open',
        'created_at': datetime.now().strftime("%d.%m.%Y %H:%M"),
        'updated_at': datetime.now().strftime("%d.%m.%Y %H:%M")
    }
    user_tickets[user_id] = ticket_id
    return support_tickets[ticket_id]

def get_ticket_by_user(user_id: int) -> Optional[dict]:
    if user_id in user_tickets:
        ticket_id = user_tickets[user_id]
        return support_tickets.get(ticket_id)
    return None

def add_message_to_ticket(ticket_id: int, message: str, sender: str):
    if ticket_id in support_tickets:
        support_tickets[ticket_id]['messages'].append({
            'text': message,
            'sender': sender,
            'time': datetime.now().strftime("%d.%m.%Y %H:%M")
        })
        support_tickets[ticket_id]['updated_at'] = datetime.now().strftime("%d.%m.%Y %H:%M")

# Функция для завершения заказа
async def complete_order(user_id: int, hosting_paid: bool = False):
    if user_id in orders:
        order_num = orders[user_id].get('order_number', 'N/A')
        
        hosting_text = "с хостингом" if hosting_paid else "без хостинга"
        try:
            await bot.send_message(
                user_id,
                f"✅ **Заказ #{order_num} завершен {hosting_text}!**\n\n"
                f"Спасибо за сотрудничество! 🤝\n"
                f"Если вам понадобится помощь, обращайтесь в поддержку.",
                parse_mode="Markdown"
            )
        except:
            pass
        
        order_number = orders[user_id]['order_number']
        del orders[user_id]
        
        await bot.send_message(
            ADMIN_ID,
            f"✅ Заказ #{order_number} завершен {hosting_text} и удален из списка активных."
        )
        
        group_text = f"✅ Заказ #{order_number} завершен {hosting_text}"
        await send_group_notification(group_text)
        
        return True
    return False

# ==================== КЛАВИАТУРЫ ====================

# Главное меню для пользователей
def get_main_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📝 Сделать заказ", callback_data="new_order"))
    builder.add(InlineKeyboardButton(text="📊 Мой заказ", callback_data="my_order"))
    builder.add(InlineKeyboardButton(text="📞 Поддержка", callback_data="support"))
    
    if is_admin(user_id):
        builder.add(InlineKeyboardButton(text="👑 Админ панель", callback_data="admin_panel"))
    
    builder.adjust(1)
    return builder.as_markup()

# Меню поддержки для пользователей
def get_support_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✏️ Написать сообщение", callback_data="support_write"))
    builder.add(InlineKeyboardButton(text="❌ Закрыть тикет", callback_data="support_close"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    builder.adjust(1)
    return builder.as_markup()

# ==================== АДМИН КЛАВИАТУРЫ ====================

# Главная админ панель
def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Управление заказами", callback_data="admin_orders_menu"))
    builder.add(InlineKeyboardButton(text="📞 Тикеты поддержки", callback_data="admin_support_menu"))
    builder.add(InlineKeyboardButton(text="⚙️ Настройки группы", callback_data="admin_group_menu"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    builder.adjust(1)
    return builder.as_markup()

# Меню управления заказами
def get_admin_orders_menu():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Список всех заказов", callback_data="admin_list_orders"))
    builder.add(InlineKeyboardButton(text="🔍 Найти заказ по номеру", callback_data="admin_find_order"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    builder.adjust(1)
    return builder.as_markup()

# Список заказов
def get_admin_orders_list_keyboard():
    builder = InlineKeyboardBuilder()
    
    if orders:
        for user_id, order in orders.items():
            # Выбираем эмодзи для статуса
            status_emoji = {
                "Ожидание": "⏳",
                "Принят в работу": "📥",
                "В разработке": "💻",
                "Готов к просмотру": "👀",
                "Отклонён": "❌",
                "Завершён": "✅"
            }.get(order['status'], "📋")
            
            payment_status = ""
            if order.get('bot_paid'):
                payment_status += "💰"
            if order.get('hosting_paid'):
                payment_status += "🌐"
            
            builder.add(InlineKeyboardButton(
                text=f"{status_emoji} #{order['order_number']} {payment_status} - @{order['username']}", 
                callback_data=f"admin_order_{user_id}"
            ))
    else:
        builder.add(InlineKeyboardButton(text="📭 Нет активных заказов", callback_data="no_action"))
    
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_orders_menu"))
    builder.adjust(1)
    return builder.as_markup()

# Кнопки для конкретного заказа
def get_admin_order_actions_keyboard(user_id: int, current_status: str):
    builder = InlineKeyboardBuilder()
    
    # Все доступные статусы
    all_statuses = ["Ожидание", "Принят в работу", "В разработке", "Готов к просмотру", "Отклонён"]
    
    # Добавляем кнопки для всех статусов, кроме текущего
    for status in all_statuses:
        if status != current_status:
            builder.add(InlineKeyboardButton(
                text=f"➡️ {status}", 
                callback_data=f"admin_change_status_{user_id}_{status}"
            ))
    
    # Кнопка отправки ссылки (только если статус не "Отклонён" и нет ссылки)
    if not orders[user_id].get('review_link') and current_status != "Отклонён" and current_status != "Готов к просмотру":
        builder.add(InlineKeyboardButton(
            text="🔗 Отправить ссылку на бота", 
            callback_data=f"admin_send_link_{user_id}"
        ))
    
    builder.add(InlineKeyboardButton(text="📞 Написать пользователю", callback_data=f"admin_message_user_{user_id}"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_list_orders"))
    builder.adjust(1)
    return builder.as_markup()

# Меню поддержки для админа
def get_admin_support_menu():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📋 Список открытых тикетов", callback_data="admin_list_tickets"))
    builder.add(InlineKeyboardButton(text="🔍 Найти тикет", callback_data="admin_find_ticket"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    builder.adjust(1)
    return builder.as_markup()

# Список тикетов
def get_admin_tickets_list_keyboard():
    builder = InlineKeyboardBuilder()
    
    open_tickets = {tid: ticket for tid, ticket in support_tickets.items() if ticket['status'] == 'open'}
    
    if open_tickets:
        for ticket_id, ticket in open_tickets.items():
            builder.add(InlineKeyboardButton(
                text=f"📞 #{ticket_id} - @{ticket.get('username', 'Неизвестно')}", 
                callback_data=f"admin_ticket_{ticket_id}"
            ))
    else:
        builder.add(InlineKeyboardButton(text="📭 Нет открытых тикетов", callback_data="no_action"))
    
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_support_menu"))
    builder.adjust(1)
    return builder.as_markup()

# Кнопки для конкретного тикета
def get_admin_ticket_keyboard(ticket_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✏️ Ответить", callback_data=f"admin_reply_ticket_{ticket_id}"))
    
    if ticket_id in support_tickets and support_tickets[ticket_id]['status'] == 'open':
        builder.add(InlineKeyboardButton(text="❌ Закрыть тикет", callback_data=f"admin_close_ticket_{ticket_id}"))
    
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_list_tickets"))
    builder.adjust(2)
    return builder.as_markup()

# Меню настроек группы
def get_admin_group_menu():
    global GROUP_ID
    status = "✅ Настроена" if GROUP_ID else "❌ Не настроена"
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔧 Установить ID группы", callback_data="admin_set_group"))
    if GROUP_ID:
        builder.add(InlineKeyboardButton(text="❌ Отключить уведомления", callback_data="admin_disable_group"))
    builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    builder.adjust(1)
    return builder.as_markup()

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    user = message.from_user
    welcome_text = (
        f"👋 Добро пожаловать, {user.first_name}!\n\n"
        "🤖 Я бот для заказа разработки Telegram ботов.\n\n"
        "📌 **Услуги:**\n"
        "• Разработка бота: **100 ⭐**\n"
        "• Хостинг (месяц): **+100 ⭐** (не обязательно)\n"
        "• Поддержка 24/7\n\n"
        "Выберите действие в меню ниже:"
    )
    
    await message.answer(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user.id)
    )

# ==================== ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ====================

@dp.message(lambda message: message.successful_payment is not None)
async def process_successful_payment(message: types.Message):
    """Обработка успешной оплаты"""
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload
    
    if payload.startswith("bot_"):
        # Оплата бота
        order_num = int(payload.replace("bot_", ""))
        
        # Находим заказ по номеру
        for uid, order in orders.items():
            if order.get('order_number') == order_num:
                order['bot_paid'] = True
                
                await message.answer(
                    f"✅ **Оплата бота #{order_num} успешно выполнена!**\n\n"
                    f"Бот будет передан вам.\n\n"
                    f"Теперь вы можете:\n"
                    f"• Оплатить хостинг (100⭐/месяц)\n"
                    f"• Отказаться от хостинга",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🌐 Оплатить хостинг (100⭐)", callback_data="pay_hosting")],
                            [InlineKeyboardButton(text="❌ Без хостинга", callback_data="decline_hosting")]
                        ]
                    )
                )
                
                # Уведомление админу
                await bot.send_message(
                    ADMIN_ID,
                    f"💰 **Бот #{order_num} оплачен!**\n\n"
                    f"Пользователь: @{message.from_user.username or 'Неизвестно'} (ID: {user_id})"
                )
                await send_group_notification(f"💰 Бот #{order_num} оплачен")
                break
                
    elif payload.startswith("hosting_"):
        # Оплата хостинга
        order_num = int(payload.replace("hosting_", ""))
        
        # Находим заказ по номеру
        for uid, order in orders.items():
            if order.get('order_number') == order_num:
                await complete_order(uid, hosting_paid=True)
                
                await message.answer(
                    f"✅ **Оплата хостинга #{order_num} успешно выполнена!**\n\n"
                    f"Заказ завершен. Спасибо за сотрудничество!",
                    parse_mode="Markdown"
                )
                
                # Уведомление админу
                await bot.send_message(
                    ADMIN_ID,
                    f"🌐 **Хостинг #{order_num} оплачен, заказ завершен!**\n\n"
                    f"Пользователь: @{message.from_user.username or 'Неизвестно'} (ID: {user_id})"
                )
                await send_group_notification(f"🌐 Хостинг #{order_num} оплачен, заказ завершен")
                break

# ==================== АДМИН ОБРАБОТЧИКИ ====================

@dp.callback_query(F.data == "admin_panel")
async def process_admin_panel(callback: CallbackQuery):
    """Главная админ панель"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return
    
    try:
        await callback.message.edit_text(
            "👑 **Административная панель**\n\nВыберите раздел для управления:",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "👑 **Административная панель**\n\nВыберите раздел для управления:",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
    await callback.answer()

@dp.callback_query(F.data == "admin_orders_menu")
async def process_admin_orders_menu(callback: CallbackQuery):
    """Меню управления заказами"""
    if not is_admin(callback.from_user.id):
        return
    
    try:
        await callback.message.edit_text(
            "📋 **Управление заказами**\n\nВыберите действие:",
            parse_mode="Markdown",
            reply_markup=get_admin_orders_menu()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "📋 **Управление заказами**\n\nВыберите действие:",
            parse_mode="Markdown",
            reply_markup=get_admin_orders_menu()
        )
    await callback.answer()

@dp.callback_query(F.data == "admin_list_orders")
async def process_admin_list_orders(callback: CallbackQuery):
    """Список всех заказов"""
    if not is_admin(callback.from_user.id):
        return
    
    try:
        await callback.message.edit_text(
            "📋 **Список активных заказов:**\n\nВыберите заказ для управления:",
            parse_mode="Markdown",
            reply_markup=get_admin_orders_list_keyboard()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "📋 **Список активных заказов:**\n\nВыберите заказ для управления:",
            parse_mode="Markdown",
            reply_markup=get_admin_orders_list_keyboard()
        )
    await callback.answer()

@dp.callback_query(F.data == "admin_find_order")
async def process_admin_find_order(callback: CallbackQuery, state: FSMContext):
    """Поиск заказа по номеру"""
    if not is_admin(callback.from_user.id):
        return
    
    await state.set_state(AdminStates.waiting_for_order_number)
    try:
        await callback.message.edit_text(
            "🔍 **Введите номер заказа** (четырехзначное число):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_orders_menu")]]
            )
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "🔍 **Введите номер заказа** (четырехзначное число):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_orders_menu")]]
            )
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith('admin_order_'))
async def process_admin_order(callback: CallbackQuery):
    """Просмотр конкретного заказа"""
    if not is_admin(callback.from_user.id):
        return
    
    user_id = int(callback.data.split('_')[2])
    
    if user_id not in orders:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    
    order = orders[user_id]
    
    # Выбираем эмодзи для статуса
    status_emoji = {
        "Ожидание": "⏳",
        "Принят в работу": "📥",
        "В разработке": "💻",
        "Готов к просмотру": "👀",
        "Отклонён": "❌",
        "Завершён": "✅"
    }.get(order['status'], "📋")
    
    text = (
        f"📋 **ЗАКАЗ #{order['order_number']}**\n\n"
        f"👤 **Пользователь:** @{order['username']} (ID: {user_id})\n"
        f"📊 **Статус:** {status_emoji} {order['status']}\n"
        f"📅 **Дата:** {order['date']}\n\n"
        f"📝 **Описание:**\n{order['description']}\n\n"
    )
    
    if order.get('review_link'):
        text += f"🔗 **Ссылка:** {order['review_link']}\n\n"
    
    text += f"💰 **Оплата:**\n"
    text += f"• Бот: {'✅' if order.get('bot_paid') else '❌'} (100⭐)\n"
    text += f"• Хостинг: {'✅' if order.get('hosting_paid') else '❌'} (100⭐)\n"
    
    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_order_actions_keyboard(user_id, order['status'])
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_order_actions_keyboard(user_id, order['status'])
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith('admin_change_status_'))
async def process_admin_change_status(callback: CallbackQuery):
    """Изменение статуса заказа"""
    if not is_admin(callback.from_user.id):
        return
    
    parts = callback.data.split('_')
    user_id = int(parts[3])
    new_status = parts[4]
    
    if user_id in orders:
        orders[user_id]['status'] = new_status
        order_num = orders[user_id]['order_number']
        
        # Если статус "Отклонён", отправляем соответствующее сообщение
        if new_status == "Отклонён":
            try:
                await bot.send_message(
                    user_id,
                    f"❌ **Заказ #{order_num} отклонен**\n\n"
                    f"К сожалению, ваш заказ был отклонен. "
                    f"Подробности вы можете узнать в поддержке.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя: {e}")
        else:
            try:
                await bot.send_message(
                    user_id,
                    f"📊 **Статус вашего заказа #{order_num} изменен!**\n\n"
                    f"Новый статус: **{new_status}**",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя: {e}")
        
        await callback.answer(f"✅ Статус изменен на {new_status}")
        await send_group_notification(f"📊 Статус заказа #{order_num} изменен на: {new_status}")
        
        await process_admin_order(callback)
    else:
        await callback.answer("❌ Заказ не найден", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith('admin_send_link_'))
async def process_admin_send_link(callback: CallbackQuery, state: FSMContext):
    """Запрос ссылки для заказа"""
    if not is_admin(callback.from_user.id):
        return
    
    user_id = int(callback.data.split('_')[3])
    
    if user_id not in orders:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    
    await state.update_data(link_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_order_link)
    
    order_num = orders[user_id]['order_number']
    
    try:
        await callback.message.edit_text(
            f"🔗 **Введите ссылку на готового бота** для заказа #{order_num}:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"admin_order_{user_id}")]]
            )
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"🔗 **Введите ссылку на готового бота** для заказа #{order_num}:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"admin_order_{user_id}")]]
            )
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith('admin_message_user_'))
async def process_admin_message_user(callback: CallbackQuery, state: FSMContext):
    """Написать сообщение пользователю"""
    if not is_admin(callback.from_user.id):
        return
    
    user_id = int(callback.data.split('_')[3])
    await state.update_data(message_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_user_message)
    
    try:
        await callback.message.edit_text(
            f"✏️ **Введите сообщение** для пользователя (ID: {user_id}):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"admin_order_{user_id}")]]
            )
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"✏️ **Введите сообщение** для пользователя (ID: {user_id}):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"admin_order_{user_id}")]]
            )
        )
    await callback.answer()

# ==================== ПОДДЕРЖКА ====================

@dp.callback_query(F.data == "admin_support_menu")
async def process_admin_support_menu(callback: CallbackQuery):
    """Меню поддержки"""
    if not is_admin(callback.from_user.id):
        return
    
    try:
        await callback.message.edit_text(
            "📞 **Управление поддержкой**\n\nВыберите действие:",
            parse_mode="Markdown",
            reply_markup=get_admin_support_menu()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "📞 **Управление поддержкой**\n\nВыберите действие:",
            parse_mode="Markdown",
            reply_markup=get_admin_support_menu()
        )
    await callback.answer()

@dp.callback_query(F.data == "admin_list_tickets")
async def process_admin_list_tickets(callback: CallbackQuery):
    """Список открытых тикетов"""
    if not is_admin(callback.from_user.id):
        return
    
    try:
        await callback.message.edit_text(
            "📞 **Список открытых тикетов:**\n\nВыберите тикет для ответа:",
            parse_mode="Markdown",
            reply_markup=get_admin_tickets_list_keyboard()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "📞 **Список открытых тикетов:**\n\nВыберите тикет для ответа:",
            parse_mode="Markdown",
            reply_markup=get_admin_tickets_list_keyboard()
        )
    await callback.answer()

@dp.callback_query(F.data == "admin_find_ticket")
async def process_admin_find_ticket(callback: CallbackQuery, state: FSMContext):
    """Поиск тикета по номеру"""
    if not is_admin(callback.from_user.id):
        return
    
    await state.set_state("waiting_for_ticket_number")
    try:
        await callback.message.edit_text(
            "🔍 **Введите номер тикета** (четырехзначное число):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_support_menu")]]
            )
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "🔍 **Введите номер тикета** (четырехзначное число):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_support_menu")]]
            )
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith('admin_ticket_'))
async def process_admin_ticket(callback: CallbackQuery):
    """Просмотр тикета"""
    if not is_admin(callback.from_user.id):
        return
    
    ticket_id = int(callback.data.split('_')[2])
    
    if ticket_id not in support_tickets:
        await callback.answer("❌ Тикет не найден", show_alert=True)
        return
    
    ticket = support_tickets[ticket_id]
    
    text = f"📞 **ТИКЕТ #{ticket_id}**\n\n"
    text += f"👤 **Пользователь:** @{ticket.get('username', 'Неизвестно')} (ID: {ticket['user_id']})\n"
    text += f"📊 **Статус:** {'🟢 Открыт' if ticket['status'] == 'open' else '🔴 Закрыт'}\n\n"
    
    if ticket['messages']:
        text += "**Последние сообщения:**\n"
        for msg in ticket['messages'][-5:]:
            sender = "👤" if msg['sender'] == 'user' else "👑"
            text += f"{sender} [{msg['time']}]: {msg['text'][:50]}...\n"
    else:
        text += "Нет сообщений\n"
    
    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_ticket_keyboard(ticket_id)
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_ticket_keyboard(ticket_id)
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith('admin_reply_ticket_'))
async def process_admin_reply_ticket(callback: CallbackQuery, state: FSMContext):
    """Ответ в тикет"""
    if not is_admin(callback.from_user.id):
        return
    
    ticket_id = int(callback.data.split('_')[3])
    await state.update_data(reply_ticket_id=ticket_id)
    await state.set_state(AdminStates.waiting_for_ticket_reply)
    
    try:
        await callback.message.edit_text(
            f"✏️ **Введите ответ** в тикет #{ticket_id}:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"admin_ticket_{ticket_id}")]]
            )
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"✏️ **Введите ответ** в тикет #{ticket_id}:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"admin_ticket_{ticket_id}")]]
            )
        )
    await callback.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith('admin_close_ticket_'))
async def process_admin_close_ticket(callback: CallbackQuery):
    """Закрытие тикета"""
    if not is_admin(callback.from_user.id):
        return
    
    ticket_id = int(callback.data.split('_')[3])
    
    if ticket_id in support_tickets:
        support_tickets[ticket_id]['status'] = 'closed'
        user_id = support_tickets[ticket_id]['user_id']
        
        try:
            await bot.send_message(
                user_id,
                f"📞 **Тикет #{ticket_id} закрыт администратором.**",
                parse_mode="Markdown"
            )
        except:
            pass
        
        await callback.answer(f"✅ Тикет #{ticket_id} закрыт")
        await process_admin_list_tickets(callback)
    else:
        await callback.answer("❌ Тикет не найден", show_alert=True)

# ==================== НАСТРОЙКИ ГРУППЫ ====================

@dp.callback_query(F.data == "admin_group_menu")
async def process_admin_group_menu(callback: CallbackQuery):
    """Меню настроек группы"""
    if not is_admin(callback.from_user.id):
        return
    
    status = "✅ Настроена" if GROUP_ID else "❌ Не настроена"
    text = f"⚙️ **Настройки группы**\n\nТекущий статус: {status}\nID группы: {GROUP_ID or 'Не указан'}"
    
    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_group_menu()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_group_menu()
        )
    await callback.answer()

@dp.callback_query(F.data == "admin_set_group")
async def process_admin_set_group(callback: CallbackQuery, state: FSMContext):
    """Установка ID группы"""
    if not is_admin(callback.from_user.id):
        return
    
    await state.set_state(AdminStates.waiting_for_group_id)
    try:
        await callback.message.edit_text(
            "📝 **Введите ID группы** (можно получить командой /groupid в группе):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_group_menu")]]
            )
        )
    except TelegramBadRequest:
        await callback.message.answer(
            "📝 **Введите ID группы** (можно получить командой /groupid в группе):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_group_menu")]]
            )
        )
    await callback.answer()

@dp.callback_query(F.data == "admin_disable_group")
async def process_admin_disable_group(callback: CallbackQuery):
    """Отключение уведомлений в группу"""
    global GROUP_ID
    if not is_admin(callback.from_user.id):
        return
    
    GROUP_ID = None
    await callback.answer("✅ Уведомления отключены")
    await process_admin_group_menu(callback)

# ==================== ОБРАБОТЧИКИ ВВОДА ====================

@dp.message(AdminStates.waiting_for_group_id)
async def process_group_id_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        group_id = int(message.text.strip())
        global GROUP_ID
        GROUP_ID = group_id
        await message.answer(
            f"✅ ID группы установлен: {GROUP_ID}",
            reply_markup=get_admin_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число.")

@dp.message(AdminStates.waiting_for_order_link)
async def process_order_link_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    user_id = data.get('link_user_id')
    link = message.text
    
    if user_id in orders:
        orders[user_id]['review_link'] = link
        orders[user_id]['status'] = 'Готов к просмотру'
        order_num = orders[user_id]['order_number']
        
        try:
            await bot.send_message(
                user_id,
                f"🎉 **Ваш бот готов к просмотру!**\n\n"
                f"📋 **Номер заказа:** #{order_num}\n"
                f"🔗 **Ссылка:** {link}\n\n"
                f"💰 **Для получения бота:**\n"
                f"1. Проверьте работу бота\n"
                f"2. Если всё устраивает, нажмите кнопку '💰 Оплатить бота (100⭐)'",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(text="💰 Оплатить бота (100⭐)", callback_data="pay_bot")
                    ]]
                )
            )
            
            await message.answer(
                f"✅ Ссылка отправлена пользователю #{order_num}",
                reply_markup=get_admin_keyboard()
            )
            await send_group_notification(f"🔗 Ссылка на бота отправлена для заказа #{order_num}")
            
        except Exception as e:
            await message.answer(f"❌ Ошибка при отправке: {e}")
    else:
        await message.answer("❌ Заказ не найден")
    
    await state.clear()

@dp.message(AdminStates.waiting_for_ticket_reply)
async def process_ticket_reply_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    ticket_id = data.get('reply_ticket_id')
    reply_text = message.text
    
    if ticket_id in support_tickets:
        ticket = support_tickets[ticket_id]
        user_id = ticket['user_id']
        
        add_message_to_ticket(ticket_id, reply_text, 'admin')
        
        try:
            await bot.send_message(
                user_id,
                f"📨 **Ответ от поддержки в тикет #{ticket_id}:**\n\n{reply_text}",
                parse_mode="Markdown"
            )
            
            await message.answer(
                f"✅ Ответ отправлен в тикет #{ticket_id}",
                reply_markup=get_admin_keyboard()
            )
            await send_group_notification(f"📞 Админ ответил в тикет #{ticket_id}")
            
        except Exception as e:
            await message.answer(f"❌ Ошибка при отправке: {e}")
    else:
        await message.answer("❌ Тикет не найден")
    
    await state.clear()

@dp.message(AdminStates.waiting_for_user_message)
async def process_admin_user_message(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    user_id = data.get('message_user_id')
    msg_text = message.text
    
    try:
        await bot.send_message(
            user_id,
            f"📨 **Сообщение от администратора:**\n\n{msg_text}",
            parse_mode="Markdown"
        )
        
        await message.answer(
            f"✅ Сообщение отправлено пользователю {user_id}",
            reply_markup=get_admin_keyboard()
        )
        await send_group_notification(f"📞 Админ отправил сообщение пользователю {user_id}")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {e}")
    
    await state.clear()

@dp.message(AdminStates.waiting_for_order_number)
async def process_order_number_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        order_num = int(message.text.strip())
        
        found = False
        for user_id, order in orders.items():
            if order.get('order_number') == order_num:
                found = True
                
                # Выбираем эмодзи для статуса
                status_emoji = {
                    "Ожидание": "⏳",
                    "Принят в работу": "📥",
                    "В разработке": "💻",
                    "Готов к просмотру": "👀",
                    "Отклонён": "❌",
                    "Завершён": "✅"
                }.get(order['status'], "📋")
                
                text = (
                    f"🔍 **Найден заказ #{order_num}**\n\n"
                    f"👤 **Пользователь:** @{order['username']} (ID: {user_id})\n"
                    f"📊 **Статус:** {status_emoji} {order['status']}\n"
                    f"📅 **Дата:** {order['date']}\n\n"
                    f"📝 **Описание:**\n{order['description']}\n\n"
                )
                
                if order.get('review_link'):
                    text += f"🔗 **Ссылка:** {order['review_link']}\n\n"
                
                text += f"💰 **Оплата:**\n"
                text += f"• Бот: {'✅' if order.get('bot_paid') else '❌'}\n"
                text += f"• Хостинг: {'✅' if order.get('hosting_paid') else '❌'}\n"
                
                builder = InlineKeyboardBuilder()
                builder.add(InlineKeyboardButton(text="📋 Управлять заказом", callback_data=f"admin_order_{user_id}"))
                builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_orders_menu"))
                builder.adjust(1)
                
                await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())
                break
        
        if not found:
            await message.answer(f"❌ Заказ #{order_num} не найден.")
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введите корректное число.")

@dp.message(lambda message: message.text and message.text.startswith('/groupid'))
async def command_groupid_handler(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return
    
    if message.chat.type in ["group", "supergroup"]:
        await message.answer(f"✅ ID этой группы: `{message.chat.id}`", parse_mode="Markdown")

# ==================== ПОЛЬЗОВАТЕЛЬСКИЕ ОБРАБОТЧИКИ ====================

@dp.callback_query(F.data == "new_order")
async def process_new_order(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(
            "📝 **Опишите техническое задание** для вашего бота:\n\n"
            "Укажите:\n"
            "• Какие функции должен выполнять бот\n"
            "• Примерный дизайн/оформление\n"
            "• Сроки разработки\n"
            "• Дополнительные пожелания",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_to_main")]]
            )
        )
        await state.set_state(OrderStates.waiting_for_description)
    except TelegramBadRequest:
        await callback.message.answer(
            "📝 **Опишите техническое задание** для вашего бота:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_to_main")]]
            )
        )
        await state.set_state(OrderStates.waiting_for_description)
    await callback.answer()

@dp.callback_query(F.data == "my_order")
async def process_my_order(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id in orders:
        order = orders[user_id]
        
        # Выбираем эмодзи для статуса
        status_emoji = {
            "Ожидание": "⏳",
            "Принят в работу": "📥",
            "В разработке": "💻",
            "Готов к просмотру": "👀",
            "Отклонён": "❌",
            "Завершён": "✅"
        }.get(order['status'], "📋")
        
        order_info = (
            f"📋 **Ваш заказ #{order['order_number']}**\n\n"
            f"📝 **Описание:**\n{order['description']}\n\n"
            f"📊 **Статус:** {status_emoji} {order['status']}\n"
            f"📅 **Дата:** {order['date']}\n\n"
        )
        
        if order.get('review_link'):
            order_info += f"🔗 **Ссылка:** {order['review_link']}\n\n"
        
        order_info += f"💰 **Оплата:**\n"
        order_info += f"• Бот: {'✅' if order.get('bot_paid') else '❌'} 100⭐\n"
        order_info += f"• Хостинг: {'✅' if order.get('hosting_paid') else '❌'} 100⭐\n"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="my_order"))
        
        # Показываем кнопки только если заказ не отклонен
        if order['status'] != "Отклонён":
            if order.get('review_link') and not order.get('bot_paid'):
                builder.add(InlineKeyboardButton(text="💰 Оплатить бота (100⭐)", callback_data="pay_bot"))
            
            if order.get('bot_paid') and not order.get('hosting_paid'):
                builder.add(InlineKeyboardButton(text="🌐 Оплатить хостинг (100⭐)", callback_data="pay_hosting"))
                builder.add(InlineKeyboardButton(text="❌ Без хостинга", callback_data="decline_hosting"))
        
        builder.add(InlineKeyboardButton(text="📞 Поддержка", callback_data="support"))
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
        builder.adjust(1)
        
        try:
            await callback.message.edit_text(order_info, parse_mode="Markdown", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            await callback.message.answer(order_info, parse_mode="Markdown", reply_markup=builder.as_markup())
    else:
        text = "❌ У вас пока нет активных заказов.\nНажмите '📝 Сделать заказ'."
        try:
            await callback.message.edit_text(text, reply_markup=get_main_keyboard(user_id))
        except TelegramBadRequest:
            await callback.message.answer(text, reply_markup=get_main_keyboard(user_id))
    await callback.answer()

@dp.callback_query(F.data == "pay_bot")
async def process_pay_bot(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in orders:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    
    order = orders[user_id]
    
    if order.get('bot_paid'):
        await callback.answer("✅ Бот уже оплачен", show_alert=True)
        return
    
    if not order.get('review_link'):
        await callback.answer("❌ Ссылка на бота еще не готова", show_alert=True)
        return
    
    if order['status'] == "Отклонён":
        await callback.answer("❌ Заказ отклонен", show_alert=True)
        return
    
    # Создаем счет на оплату (100 звезд)
    prices = [LabeledPrice(label="Разработка бота", amount=100)]
    
    await bot.send_invoice(
        chat_id=user_id,
        title=f"Оплата бота #{order['order_number']}",
        description=f"Оплата разработки бота. Заказ #{order['order_number']}",
        payload=f"bot_{order['order_number']}",
        provider_token="",  # Пустой для Stars
        currency="XTR",  # XTR = Telegram Stars
        prices=prices,
        start_parameter="pay_bot",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💫 Оплатить 100⭐", pay=True)]]
        )
    )
    
    await callback.answer()

@dp.callback_query(F.data == "pay_hosting")
async def process_pay_hosting(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in orders:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    
    order = orders[user_id]
    
    if not order.get('bot_paid'):
        await callback.answer("❌ Сначала оплатите бота", show_alert=True)
        return
    
    if order.get('hosting_paid'):
        await callback.answer("✅ Хостинг уже оплачен", show_alert=True)
        return
    
    if order['status'] == "Отклонён":
        await callback.answer("❌ Заказ отклонен", show_alert=True)
        return
    
    # Создаем счет на оплату (100 звезд)
    prices = [LabeledPrice(label="Хостинг на месяц", amount=100)]
    
    await bot.send_invoice(
        chat_id=user_id,
        title=f"Оплата хостинга #{order['order_number']}",
        description=f"Оплата хостинга для бота. Заказ #{order['order_number']}",
        payload=f"hosting_{order['order_number']}",
        provider_token="",  # Пустой для Stars
        currency="XTR",  # XTR = Telegram Stars
        prices=prices,
        start_parameter="pay_hosting",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💫 Оплатить 100⭐", pay=True)]]
        )
    )
    
    await callback.answer()

@dp.callback_query(F.data == "decline_hosting")
async def process_decline_hosting(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in orders:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    
    order = orders[user_id]
    
    if not order.get('bot_paid'):
        await callback.answer("❌ Сначала оплатите бота", show_alert=True)
        return
    
    await complete_order(user_id, hosting_paid=False)
    
    text = "✅ Заказ завершен без хостинга. Спасибо!"
    
    try:
        await callback.message.edit_text(text, reply_markup=get_main_keyboard(user_id))
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=get_main_keyboard(user_id))
    await callback.answer()

@dp.callback_query(F.data == "support")
async def process_support(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    ticket = get_ticket_by_user(user_id)
    
    text = "📞 **Поддержка**\n\n"
    
    if ticket and ticket['status'] == 'open':
        text += f"У вас есть открытый тикет. Напишите сообщение."
    else:
        text += "Создайте тикет и задайте вопрос."
    
    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_support_keyboard(user_id)
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=get_support_keyboard(user_id)
        )
    await callback.answer()

@dp.callback_query(F.data == "support_write")
async def process_support_write(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.full_name
    
    ticket = get_or_create_ticket(user_id, username)
    ticket['status'] = 'open'
    
    text = f"✏️ **Тикет #{ticket['ticket_id']}**\n\nНапишите ваше сообщение:"
    
    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="support")]]
            )
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="support")]]
            )
        )
    
    await state.set_state(SupportStates.waiting_for_user_message)
    await callback.answer()

@dp.callback_query(F.data == "support_close")
async def process_support_close(callback: CallbackQuery):
    user_id = callback.from_user.id
    ticket = get_ticket_by_user(user_id)
    
    if ticket:
        ticket['status'] = 'closed'
        text = f"✅ Тикет #{ticket['ticket_id']} закрыт."
        
        await bot.send_message(
            ADMIN_ID,
            f"📞 Пользователь @{callback.from_user.username or 'Неизвестно'} закрыл тикет #{ticket['ticket_id']}."
        )
    else:
        text = "❌ Тикет не найден."
    
    try:
        await callback.message.edit_text(text, reply_markup=get_main_keyboard(user_id))
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=get_main_keyboard(user_id))
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def process_back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = "Главное меню:"
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_main_keyboard(callback.from_user.id)
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            reply_markup=get_main_keyboard(callback.from_user.id)
        )
    await callback.answer()

# ==================== ОБРАБОТЧИКИ СООБЩЕНИЙ ====================

@dp.message(OrderStates.waiting_for_description)
async def process_description(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    description = message.text
    
    order_number = generate_order_number()
    
    orders[user_id] = {
        'order_number': order_number,
        'description': description,
        'status': 'Ожидание',
        'date': datetime.now().strftime("%d.%m.%Y %H:%M"),
        'username': message.from_user.username or message.from_user.full_name,
        'bot_paid': False,
        'hosting_paid': False
    }
    
    await message.answer(
        f"✅ **Заказ #{order_number} принят!**\n\nСтатус: Ожидание",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )
    
    admin_text = (
        f"🆕 **НОВЫЙ ЗАКАЗ!**\n\n"
        f"📋 **Номер:** #{order_number}\n"
        f"👤 **Пользователь:** @{message.from_user.username or 'Неизвестно'} (ID: {user_id})\n"
        f"📝 **ТЗ:**\n{description}\n\n"
        f"⏳ Статус: Ожидание"
    )
    
    await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    await send_group_notification(f"🆕 Новый заказ #{order_number} от @{message.from_user.username or 'Неизвестно'} (Ожидание)")
    
    await state.clear()

@dp.message(SupportStates.waiting_for_user_message)
async def process_user_support_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name
    
    ticket = get_or_create_ticket(user_id, username)
    ticket['status'] = 'open'
    
    add_message_to_ticket(ticket['ticket_id'], message.text, 'user')
    
    await message.answer(
        f"✅ Сообщение в тикет #{ticket['ticket_id']} отправлено.",
        reply_markup=get_main_keyboard(user_id)
    )
    
    admin_text = (
        f"📞 **НОВОЕ СООБЩЕНИЕ В ПОДДЕРЖКУ!**\n\n"
        f"🎫 **Тикет:** #{ticket['ticket_id']}\n"
        f"👤 **Пользователь:** @{username} (ID: {user_id})\n"
        f"📝 **Сообщение:**\n{message.text}"
    )
    
    await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    await send_group_notification(f"📞 Новое сообщение в тикет #{ticket['ticket_id']} от @{username}")
    
    await state.clear()

# ==================== ЗАПУСК ====================

async def main():
    logger.info("Бот запущен!")
    logger.info(f"Админ ID: {ADMIN_ID}")
    logger.info("Админ панель доступна через кнопку 👑 Админ панель")
    logger.info("Оплата производится автоматически через Telegram Stars")
    logger.info("Доступные статусы: Ожидание, Принят в работу, В разработке, Готов к просмотру, Отклонён")
    
    commands = [
        types.BotCommand(command="start", description="Запустить бота"),
    ]
    await bot.set_my_commands(commands)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
