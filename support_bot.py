import asyncio
import html
import logging
import os
import re
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
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
SITE_URL = "https://hutzvpn.bothost.tech"
PER_PAGE = 5
TICKETS_PER_PAGE = 6

if not BOT_TOKEN:
    raise RuntimeError("Не задан SUPPORT_BOT_TOKEN в переменных окружения")

_default_db = "/app/data/support.db" if os.path.isdir("/app/data") else "support.db"
DB_PATH = os.getenv("SUPPORT_DB_PATH", _default_db).strip()
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT DEFAULT '',
    full_name TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    unread INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
""")
db.commit()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
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
    admin_replying = State()


def _now() -> str:
    return datetime.now().strftime("%d.%m %H:%M")


def _open_tickets_count() -> int:
    row = db.execute("SELECT COUNT(*) AS cnt FROM tickets WHERE status='open'").fetchone()
    return row["cnt"] if row else 0


def _get_or_create_ticket(user_id: int, username: str, full_name: str) -> tuple[int, bool]:
    row = db.execute(
        "SELECT id FROM tickets WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    now = _now()
    if row:
        db.execute(
            "UPDATE tickets SET username=?, full_name=?, unread=1, updated_at=? WHERE id=?",
            (username, full_name, now, row["id"]),
        )
        db.commit()
        return row["id"], False
    cur = db.execute(
        "INSERT INTO tickets (user_id, username, full_name, status, unread, created_at, updated_at) "
        "VALUES (?, ?, ?, 'open', 1, ?, ?)",
        (user_id, username, full_name, now, now),
    )
    db.commit()
    return cur.lastrowid, True


def _add_ticket_msg(ticket_id: int, sender: str, text: str):
    db.execute(
        "INSERT INTO ticket_messages (ticket_id, sender, text, created_at) VALUES (?, ?, ?, ?)",
        (ticket_id, sender, text, _now()),
    )
    db.commit()


# ---------- Клавиатуры ----------
def main_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="❓ Частые вопросы (FAQ)", callback_data="faq:0")],
        [InlineKeyboardButton(text="👨‍💻 Позвать специалиста", callback_data="call_support")],
        [
            InlineKeyboardButton(text="🚀 Основной бот", url=MAIN_BOT_URL),
            InlineKeyboardButton(text="🌐 Сайт", url=SITE_URL),
        ],
    ]
    if is_admin:
        cnt = _open_tickets_count()
        rows.insert(0, [InlineKeyboardButton(text=f"🎫 Открытые тикеты ({cnt})", callback_data="tickets:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def tickets_list_kb(page: int) -> InlineKeyboardMarkup:
    rows_db = db.execute(
        "SELECT id, user_id, username, full_name, unread, updated_at FROM tickets "
        "WHERE status='open' ORDER BY unread DESC, id DESC"
    ).fetchall()
    total = len(rows_db)
    total_pages = max(1, (total + TICKETS_PER_PAGE - 1) // TICKETS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * TICKETS_PER_PAGE

    buttons = []
    for r in rows_db[start:start + TICKETS_PER_PAGE]:
        mark = "🔴" if r["unread"] else "🟢"
        who = f"@{r['username']}" if r["username"] else (r["full_name"] or str(r["user_id"]))
        label = f"{mark} Тикет #{r['id']} · {who} ({r['updated_at']})"
        buttons.append([InlineKeyboardButton(text=label[:60], callback_data=f"tk:{r['id']}:{page}")])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"tickets:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"tickets:{page + 1}"))
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data=f"tickets:{page}")])
    buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def ticket_view_kb(ticket_id: int, page: int, is_open: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_open:
        rows.append([
            InlineKeyboardButton(text="✍️ Ответить", callback_data=f"tk_reply:{ticket_id}:{page}"),
            InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"tk_close:{ticket_id}:{page}"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ К списку тикетов", callback_data=f"tickets:{page}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_ticket(ticket_id: int) -> tuple[str, bool] | None:
    tk = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    if not tk:
        return None
    db.execute("UPDATE tickets SET unread=0 WHERE id=?", (ticket_id,))
    db.commit()

    msgs = db.execute(
        "SELECT sender, text, created_at FROM ticket_messages WHERE ticket_id=? ORDER BY id DESC LIMIT 12",
        (ticket_id,),
    ).fetchall()
    msgs = list(reversed(msgs))

    who = f"@{tk['username']}" if tk["username"] else "без юзернейма"
    st = "🟢 Открыт" if tk["status"] == "open" else "⚪️ Закрыт"
    lines = [
        f"🎫 <b>Тикет #{tk['id']}</b> ({st})",
        f"👤 Клиент: {html.escape(tk['full_name'])} ({who}) · <code>{tk['user_id']}</code>",
        "━━━━━━━━━━━━━━",
    ]
    for item in msgs:
        role = "👤 Клиент" if item["sender"] == "user" else "👨‍💻 Вы"
        lines.append(f"<b>{role}</b> [{item['created_at']}]:\n{html.escape(item['text'])}")
    return "\n\n".join(lines)[:3900], (tk["status"] == "open")


async def _send_admin_answer(user_id: int, ticket_id: int, m: Message):
    footer = (
        "\n\n━━━━━━━━━━━━━━\n"
        "📢 Будем рады видеть вас в нашем Telegram-канале — там публикуем новости "
        "и разыгрываем промокоды: @hutzvpn"
    )
    if m.text:
        await bot.send_message(
            user_id,
            f"👋 <b>Здравствуйте! Специалист HUTZ Vpn на связи:</b>\n\n"
            f"{html.escape(m.text)}{footer}",
        )
        _add_ticket_msg(ticket_id, "admin", m.text)
    else:
        await m.copy_to(user_id)
        await bot.send_message(user_id, f"☝️ Ответ специалиста.{footer}")
        _add_ticket_msg(ticket_id, "admin", m.caption or "[Медиафайл]")

    db.execute("UPDATE tickets SET unread=0, updated_at=? WHERE id=?", (_now(), ticket_id))
    db.commit()


# ---------- Обработчики пользователя ----------
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    is_adm = m.from_user.id == ADMIN_ID
    await m.answer(
        "👋 <b>Поддержка HUTZ Vpn</b>\n\n"
        "Выберите готовый ответ из списка частых вопросов или вызовите специалиста — "
        "ответим максимально быстро.",
        reply_markup=main_kb(is_admin=is_adm),
    )


@dp.message(Command("tickets"), F.from_user.id == ADMIN_ID)
async def cmd_tickets(m: Message, state: FSMContext):
    await state.clear()
    cnt = _open_tickets_count()
    text = f"🎫 <b>Открытые тикеты ({cnt})</b>\n\nВыберите заявку из списка:" if cnt else "🎫 <b>Открытых тикетов нет.</b>"
    await m.answer(text, reply_markup=tickets_list_kb(0))


@dp.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


@dp.callback_query(F.data == "home")
async def cb_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    is_adm = c.from_user.id == ADMIN_ID
    await c.message.edit_text(
        "👋 <b>Поддержка HUTZ Vpn</b>\n\n"
        "Выберите готовый ответ из списка частых вопросов или вызовите специалиста.",
        reply_markup=main_kb(is_admin=is_adm),
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
        "👨‍💻 <b>Специалист на связи.</b>\n\n"
        "Подробно опишите вашу проблему, вопрос или предложение одним сообщением "
        "(при необходимости прикрепите скриншот или чек). Ответим прямо в этот чат.",
        reply_markup=kb,
    )
    await c.answer()


# ---------- Обработчики тикетов (админ) ----------
@dp.callback_query(F.data.startswith("tickets:"), F.from_user.id == ADMIN_ID)
async def cb_tickets(c: CallbackQuery, state: FSMContext):
    await state.clear()
    page = int(c.data.split(":")[1])
    cnt = _open_tickets_count()
    text = f"🎫 <b>Открытые тикеты ({cnt})</b>\n\n🔴 — есть непрочитанное сообщение:" if cnt else "🎫 <b>Открытых тикетов нет.</b>"
    await c.message.edit_text(text, reply_markup=tickets_list_kb(page))
    await c.answer()


@dp.callback_query(F.data.startswith("tk:"), F.from_user.id == ADMIN_ID)
async def cb_ticket_view(c: CallbackQuery, state: FSMContext):
    await state.clear()
    _, tid_s, page_s = c.data.split(":")
    tid, page = int(tid_s), int(page_s)
    rendered = _render_ticket(tid)
    if not rendered:
        await c.answer("Тикет не найден", show_alert=True)
        return
    text, is_open = rendered
    await c.message.edit_text(text, reply_markup=ticket_view_kb(tid, page, is_open))
    await c.answer()


@dp.callback_query(F.data.startswith("tk_reply:"), F.from_user.id == ADMIN_ID)
async def cb_ticket_reply(c: CallbackQuery, state: FSMContext):
    _, tid_s, page_s = c.data.split(":")
    tid, page = int(tid_s), int(page_s)
    await state.set_state(SupportState.admin_replying)
    await state.update_data(ticket_id=tid, page=page)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"tk:{tid}:{page}")]
    ])
    await c.message.answer(f"✍️ Введите ответ для клиента по <b>тикету #{tid}</b> (можно отправить текст или фото):", reply_markup=kb)
    await c.answer()


@dp.callback_query(F.data.startswith("tk_close:"), F.from_user.id == ADMIN_ID)
async def cb_ticket_close(c: CallbackQuery, state: FSMContext):
    await state.clear()
    _, tid_s, page_s = c.data.split(":")
    tid, page = int(tid_s), int(page_s)
    tk = db.execute("SELECT user_id, status FROM tickets WHERE id=?", (tid,)).fetchone()
    if tk and tk["status"] == "open":
        db.execute("UPDATE tickets SET status='closed', unread=0, updated_at=? WHERE id=?", (_now(), tid))
        db.commit()
        try:
            await bot.send_message(
                tk["user_id"],
                f"✅ <b>Обращение #{tid} закрыто специалистом.</b>\n"
                "Если появятся новые вопросы — просто напишите сюда снова!",
            )
        except Exception:
            pass
    await c.answer(f"Тикет #{tid} закрыт")
    cnt = _open_tickets_count()
    text = f"🎫 <b>Открытые тикеты ({cnt})</b>\n\n🔴 — есть непрочитанное сообщение:" if cnt else "🎫 <b>Открытых тикетов нет.</b>"
    await c.message.edit_text(text, reply_markup=tickets_list_kb(page))


@dp.message(SupportState.admin_replying, F.from_user.id == ADMIN_ID)
async def admin_state_reply(m: Message, state: FSMContext):
    data = await state.get_data()
    tid = data.get("ticket_id")
    page = data.get("page", 0)
    await state.clear()
    tk = db.execute("SELECT user_id FROM tickets WHERE id=?", (tid,)).fetchone()
    if not tk:
        await m.answer("❌ Тикет не найден.")
        return
    try:
        await _send_admin_answer(tk["user_id"], tid, m)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Открыть тикет", callback_data=f"tk:{tid}:{page}"),
                InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"tk_close:{tid}:{page}"),
            ],
            [InlineKeyboardButton(text="🎫 Все тикеты", callback_data=f"tickets:{page}")],
        ])
        await m.answer(f"✅ Ответ отправлен клиенту по <b>тикету #{tid}</b>.", reply_markup=kb)
    except Exception as e:
        await m.answer(f"❌ Не удалось отправить (пользователь заблокировал бота): {e}")


@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def admin_quick_reply(m: Message, state: FSMContext):
    ref = m.reply_to_message.text or m.reply_to_message.caption or ""
    match = re.search(r"#tk_(\d+)", ref)
    if not match:
        return
    await state.clear()
    tid = int(match.group(1))
    tk = db.execute("SELECT user_id FROM tickets WHERE id=?", (tid,)).fetchone()
    if not tk:
        await m.reply("❌ Тикет не найден.")
        return
    try:
        await _send_admin_answer(tk["user_id"], tid, m)
        await m.reply(f"✅ Ответ отправлен по тикету #{tid}.")
    except Exception as e:
        await m.reply(f"❌ Не удалось отправить: {e}")


# ---------- Входящие сообщения клиентов ----------
@dp.message(F.from_user.id != ADMIN_ID)
async def user_message(m: Message, state: FSMContext):
    await state.clear()
    u = m.from_user
    uname = u.username or ""
    tid, is_new = _get_or_create_ticket(u.id, uname, u.full_name)
    msg_text = m.text or m.caption or "[Медиафайл / вложение]"
    _add_ticket_msg(tid, "user", msg_text)

    who = f"@{uname}" if uname else "без юзернейма"
    badge = "🆕 Новый тикет" if is_new else "💬 Новое сообщение в тикете"
    notify_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"📂 Открыть тикет #{tid}", callback_data=f"tk:{tid}:0"),
            InlineKeyboardButton(text="✍️ Ответить", callback_data=f"tk_reply:{tid}:0"),
        ],
        [InlineKeyboardButton(text=f"🎫 Все тикеты ({_open_tickets_count()})", callback_data="tickets:0")],
    ])
    header = (
        f"📩 <b>{badge} #{tid}</b> #tk_{tid}\n"
        f"👤 {html.escape(u.full_name)} ({who}) · <code>{u.id}</code>\n\n"
        f"{html.escape(msg_text[:1000])}"
    )
    await bot.send_message(ADMIN_ID, header, reply_markup=notify_kb)
    if not m.text:
        await m.copy_to(ADMIN_ID, caption=f"📎 Вложение к тикету #{tid} #tk_{tid}")

    if is_new:
        await m.answer(
            f"✅ <b>Обращение #{tid} зарегистрировано!</b>\n"
            "Специалист получил вашу заявку и скоро ответит прямо в этот чат.",
            reply_markup=main_kb(is_admin=False),
        )
    else:
        await m.answer(f"💬 Сообщение добавлено к вашему открытому обращению <b>#{tid}</b>.")


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
