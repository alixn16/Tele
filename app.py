import os
import asyncio
import logging
from typing import List, Dict
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN') or input("Token: ").strip()  # طلب التوكن بالإنجليزي فقط
ADMINS: List[int] = list(map(int, os.getenv('ADMINS', '8061618834').split(',')))

logging.basicConfig(level=logging.INFO, filename='bot.log',
                    format='%(asctime)s - %(levelname)s - %(message)s')

class CmdStates(StatesGroup):
    wait_exec = State()
    wait_kill = State()
    wait_confirm = State()

RATE_LIMIT: Dict[int, float] = {}
RATE_LIMIT_SEC = 2.0

def rate_limited(uid: int) -> bool:
    now = asyncio.get_event_loop().time()
    last = RATE_LIMIT.get(uid, 0)
    if now - last < RATE_LIMIT_SEC:
        return True
    RATE_LIMIT[uid] = now
    return False

ALLOWED_CMDS = {
    'uname -a', 'free -h', 'lscpu', 'df -h', 'uptime',
    'top -b -n 1 | head -20', 'curl -s ifconfig.me',
    'netstat -tulnp', 'speedtest-cli --simple',
    'ping -c 4 google.com', 'traceroute google.com',
    'ls -lah /', 'rm -rf /tmp/*',
    'ps aux --sort=-%cpu | head -15',
}

def build_kb() -> InlineKeyboardMarkup:
    btns = [
        ('🖥️ معلومات النظام', 'uname -a'),
        ('🧠 الرام', 'free -h'),
        ('🧮 المعالج', 'lscpu'),
        ('💾 القرص', 'df -h'),
        ('⏱️ مدة التشغيل', 'uptime'),
        ('📊 أفضل العمليات', 'top -b -n 1 | head -20'),
        ('🌐 عنوان IP', 'curl -s ifconfig.me'),
        ('📡 الشبكة', 'netstat -tulnp'),
        ('🚀 اختبار سرعة', 'speedtest-cli --simple'),
        ('📶 اختبار Ping', 'ping -c 4 google.com'),
        ('📍 تتبع المسار', 'traceroute google.com'),
        ('📂 قائمة الجذر', 'ls -lah /'),
        ('🗑️ تنظيف المؤقت', 'rm -rf /tmp/*'),
        ('⚙️ العمليات', 'ps aux --sort=-%cpu | head -15'),
        ('❌ قتل PID', 'confirm_kill'),
        ('📝 تنفيذ أمر', 'confirm_exec'),
        ('🔄 إعادة تشغيل', 'confirm_reboot'),
        ('⏹️ إيقاف النظام', 'confirm_shutdown'),
    ]
    kb = InlineKeyboardMarkup(row_width=3)
    for t, d in btns:
        kb.insert(InlineKeyboardButton(t, callback_data=d))
    return kb

async def run_cmd(cmd: str, timeout=15) -> str:
    if cmd not in ALLOWED_CMDS:
        return "❌ هذا الأمر غير مسموح."
    proc = await asyncio.create_subprocess_shell(cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return out.decode().strip() or "✅ تم التنفيذ"
    except asyncio.TimeoutError:
        proc.kill()
        return "⏱️ انتهى الوقت المسموح"
    except Exception as e:
        logging.error(f"run_cmd error: {e}")
        return f"❌ خطأ: {e}"

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(bot, storage=MemoryStorage())
    kb = build_kb()

    @dp.message_handler(commands=['start'])
    async def start(msg: types.Message):
        if msg.from_user.id not in ADMINS:
            return await msg.reply("🚫 غير مصرح لك.")
        if rate_limited(msg.from_user.id):
            return await msg.reply("⏳ يرجى الانتظار قليلاً.")
        await msg.reply("🔧 لوحة التحكم الرئيسية:", reply_markup=kb)

    @dp.callback_query_handler(lambda c: c.data.startswith('confirm_'))
    async def confirm(c: types.CallbackQuery, state: FSMContext):
        action = c.data.split('_', 1)[1]
        await c.answer()
        await c.message.edit_reply_markup(
            InlineKeyboardMarkup().row(
                InlineKeyboardButton("✅ تأكيد", callback_data=f"do_{action}"),
                InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
            ))
        await state.set_state(CmdStates.wait_confirm.state)
        await state.update_data(action=action)

    @dp.callback_query_handler(lambda c: c.data == 'cancel', state=CmdStates.wait_confirm)
    async def cancel(c: types.CallbackQuery, state: FSMContext):
        await c.answer("❌ تم الإلغاء", show_alert=True)
        await state.finish()
        await c.message.edit_reply_markup(reply_markup=kb)

    @dp.callback_query_handler(lambda c: c.data.startswith('do_'), state=CmdStates.wait_confirm)
    async def do_action(c: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        action = data.get('action')
        await c.answer(f"⚠️ جاري تنفيذ: {action}")
        await state.finish()
        if action in ('reboot', 'shutdown'):
            await bot.send_message(c.message.chat.id, f"⚠️ جاري تنفيذ الأمر: {action}")
            await run_cmd(action)
        await c.message.edit_reply_markup(reply_markup=kb)

    @dp.callback_query_handler(lambda c: c.data in ALLOWED_CMDS)
    async def exec_cmd(c: types.CallbackQuery):
        if c.from_user.id not in ADMINS:
            return await c.answer("🚫 غير مصرح", show_alert=True)
        await c.answer("⏳ جارٍ التنفيذ...")
        res = await run_cmd(c.data)
        await c.message.reply(f"📥 `{c.data}`:\n```\n{res}\n```", parse_mode='Markdown')

    @dp.callback_query_handler(lambda c: c.data == 'confirm_exec')
    async def ask_exec(c: types.CallbackQuery):
        await c.answer()
        await c.message.reply("✍️ أرسل الأمر للتنفيذ:")
        await CmdStates.wait_exec.set()

    @dp.message_handler(state=CmdStates.wait_exec)
    async def do_exec(m: types.Message, state: FSMContext):
        res = await run_cmd(m.text.strip())
        await m.reply(f"📥 `{m.text.strip()}`:\n```\n{res}\n```", parse_mode='Markdown')
        await state.finish()

    @dp.callback_query_handler(lambda c: c.data == 'confirm_kill')
    async def ask_kill(c: types.CallbackQuery):
        await c.answer()
        await c.message.reply("✍️ أرسل رقم PID للقتل:")
        await CmdStates.wait_kill.set()

    @dp.message_handler(state=CmdStates.wait_kill)
    async def do_kill(m: types.Message, state: FSMContext):
        pid = m.text.strip()
        if not pid.isdigit():
            return await m.reply("❌ الرجاء إدخال أرقام فقط.")
        res = await run_cmd(f"kill {pid}")
        await m.reply(f"📥 `kill {pid}`:\n```\n{res}\n```", parse_mode='Markdown')
        await state.finish()

    print("✅ البوت يعمل الآن...")
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
