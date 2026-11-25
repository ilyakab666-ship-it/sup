import asyncio
import html
import logging
import os
import re
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("SUPPORT_ADMIN_ID", "8334034304"))
MAIN_BOT_URL = "https://t.me/hutzvpn_bot"
CHANNEL_URL = "https://t.me/hutzvpn"
PER_PAGE = 5

if not BOT_TOKEN:
    raise RuntimeError("Не задан SUPPORT_BOT_TOKEN в переменных окружения")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# База быстрых ответов. Можно добавлять сколько угодно пунктов — пагинация сработает сама.
FAQ: list[tuple[str, str]] = [
    (
        "📱 Как подключиться за 1 минуту?",
        "1. Перейдите в основной бот @hutzvpn_bot и оформите тариф или введите промокод.\n"
        "2. Установите приложение <b>Happ</b> (ссылки на iOS, Android, Windows и macOS есть внутри бота).\n"
        "3. Нажмите кнопку <b>«Открыть в Happ»</b> и включите соединение."
    ),
    (
        "📶 Плохо грузит на мобильном интернете",
        "В приложении <b>Happ</b> откройте список серверов и выберите локацию <b>«NL #1 · Мобильная связь»</b> или <b>«NL #2 · Мобильная связь»</b> — они настроены специально для стабильной работы в сотовых сетях."
    ),
    (
        "💳 Не прошла оплата / не пришла подписка",
        "Обычно активация происходит за 5–10 секунд после перевода по СБП или крипте.\n"
        "Если прошло больше 2 минут — нажмите <b>«👨‍💻 Позвать специалиста»</b> и отправьте чек или скриншот оплаты."
    ),
    (
        "💻 На скольких устройствах работает?",
        "Зависит от вашего тарифа: базовый рассчитан на <b>1 устройство</b>, расширенный — на <b>3 устройства</b> одновременно. В разделе «Статус» основного бота можно докупить дополнительные слоты."
    ),
    (
        "🚫 Ошибка «Достигнут лимит устройств»",
        "Подписка привязывается к вашим устройствам автоматически. Если вы переустановили приложение или сменили телефон, напишите специалисту — мы сбросим старую привязку."
    ),
    (
        "📊 Какой лимит трафика и скорости?",
        "На каждом тарифе доступно <b>1000 ГБ</b> трафика в месяц на максимальной скорости канала без искусственных ограничений."
    ),
    (
        "🔄 Не обновляется список серверов в Happ",
        "В приложении Happ нажмите иконку обновления (круговая стрелка) справа от названия подписки <b>HUTZ Vpn</b>. Убедитесь, что в этот момент не включён другой VPN."
    ),
    (
        "🎁 Где взять промокод или бесплатный тест?",
        "Актуальные промокоды и розыгрыши подписок регулярно публикуются в нашем Telegram-канале: @hutzvpn."
    ),
    (
        "🍏 Где скачать Happ на iPhone / Mac?",
        "Приложение <b>Happ</b> доступно в российском App Store. Прямую кнопку скачивания можно получить в @hutzvpn_bot в разделе «Подключить»."
    ),
    (
        "💸 Как оформить возврат?",
        "Условия возврата описаны в публичной оферте (раздел «Документы и поддержка» в @hutzvpn_bot). Для оформления заявки позовите специалиста в этом боте."
    ),
]


class SupportState(StatesGroup):
    waiting_question = State()


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ Частые вопросы (FAQ)", callback_data="faq:0")],
        [InlineKeyboardButton(text="👨‍💻 Позвать специалиста", callback_data="call_support")],
        [
            InlineKeyboardButton(text="🚀 Основной бот", url=MAIN_BOT_URL),
            InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL),
        ],
    ])


def faq_list_kb(page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(FAQ) + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * PER_PAGE
    rows = [
        [InlineKeyboardButton(text=q, callback_data=f"ans:{idx}:{page}")]
        for idx, (q, _) in enumerate(FAQ[start:start + PER_PAGE], start=start)
    ]
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"faq:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"faq:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="👨‍💻 Нет моего вопроса — позвать специалиста", callback_data="call_support")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def answer_kb(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К списку вопросов", callback_data=f"faq:{page}")],
        [InlineKeyboardButton(text="👨‍💻 Вопрос не решён — позвать специалиста", callback_data="call_support")],
    ])


@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "👋 <b>Поддержка HUTZ Vpn</b>\n\n"
        "Выберите готовый ответ из списка частых вопросов или вызовите специалиста — "
        "ответим максимально быстро.",
        reply_markup=main_kb(),
    )


@dp.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


@dp.callback_query(F.data == "home")
async def cb_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text(
        "👋 <b>Поддержка HUTZ Vpn</b>\n\n"
        "Выберите готовый ответ из списка частых вопросов или вызовите специалиста.",
        reply_markup=main_kb(),
    )
    await c.answer()


@dp.callback_query(F.data.startswith("faq:"))
async def cb_faq(c: CallbackQuery):
    page = int(c.data.split(":")[1])
    await c.message.edit_text(
        "❓ <b>Частые вопросы</b>\n\nНажмите на нужный пункт, чтобы получить инструкцию:",
        reply_markup=faq_list_kb(page),
    )
    await c.answer()


@dp.callback_query(F.data.startswith("ans:"))
async def cb_ans(c: CallbackQuery):
    _, idx_s, page_s = c.data.split(":")
    idx, page = int(idx_s), int(page_s)
    q, a = FAQ[idx]
    await c.message.edit_text(f"<b>{html.escape(q)}</b>\n\n{a}", reply_markup=answer_kb(page))
    await c.answer()


@dp.callback_query(F.data == "call_support")
async def cb_call_support(c: CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_question)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="home")]
    ])
    await c.message.edit_text(
        "👨‍💻 <b>Вызов специалиста</b>\n\n"
        "Опишите вашу проблему одним сообщением (можно прикрепить скриншот). "
        "Специалист получит обращение и ответит прямо сюда.",
        reply_markup=kb,
    )
    await c.answer()


@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def admin_reply(m: Message):
    ref = m.reply_to_message.text or m.reply_to_message.caption or ""
    match = re.search(r"#uid_(\d+)", ref)
    if not match:
        return
    user_id = int(match.group(1))
    try:
        if m.text:
            await bot.send_message(user_id, f"💬 <b>Ответ специалиста:</b>\n\n{html.escape(m.text)}")
        else:
            await m.copy_to(user_id)
        await m.reply("✅ Ответ отправлен пользователю.")
    except Exception as e:
        await m.reply(f"❌ Не удалось отправить (пользователь заблокировал бота): {e}")


@dp.message(F.from_user.id != ADMIN_ID)
async def user_message(m: Message, state: FSMContext):
    u = m.from_user
    uname = f"@{u.username}" if u.username else "без юзернейма"
    header = (
        f"📩 <b>Новое обращение в поддержку</b>\n"
        f"От: {html.escape(u.full_name)} ({uname})\n"
        f"ID: <code>{u.id}</code> | #uid_{u.id}\n"
        f"<i>Ответьте (Reply) на это сообщение, чтобы написать клиенту.</i>"
    )
    await bot.send_message(ADMIN_ID, header)
    if m.text:
        await bot.send_message(ADMIN_ID, f"{html.escape(m.text)}\n\n#uid_{u.id}")
    else:
        await m.copy_to(ADMIN_ID, caption=f"{html.escape(m.caption or '')}\n\n#uid_{u.id}".strip())

    await state.clear()
    await m.answer(
        "✅ <b>Обращение передано специалисту!</b>\n"
        "Ожидайте ответ в этом чате в ближайшее время.",
        reply_markup=main_kb(),
    )


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())