import os, json, asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import ParseMode, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn import Config, Server
from config import *

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

class WithdrawState(StatesGroup):
    waiting_method = State()
    waiting_number = State()
    waiting_amount = State()

class VerifState(StatesGroup):
    waiting_input = State()

class KirimPoinState(StatesGroup):
    waiting_userid = State()
    waiting_jumlah = State()

# === JSON UTILS ===
def load_json(filename):
    return json.load(open(filename)) if os.path.exists(filename) else {}

def save_json(filename, data):
    json.dump(data, open(filename, "w"))

# === FASTAPI ENDPOINT UNTUK TELEGA.IO ===
@app.post("/add_poin")
async def add_poin(req: Request):
    data = await req.json()
    uid = str(data['user_id'])
    reward = int(data['amount'])

    poin = load_json(POIN_FILE)
    riwayat = load_json(RIWAYAT_FILE)

    poin[uid] = poin.get(uid, 0) + reward
    save_json(POIN_FILE, poin)

    if uid not in riwayat:
        riwayat[uid] = []
    riwayat[uid].append({"type": "telega_reward", "amount": reward, "time": datetime.now().isoformat()})
    save_json(RIWAYAT_FILE, riwayat)

    try:
        await bot.send_message(int(uid), f"🎥 Kamu mendapatkan {reward} poin dari iklan Telega.io!")
    except: pass

    return {"status": "ok"}

@app.get("/admin", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/admin", response_class=HTMLResponse)
def dashboard(request: Request, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Password salah."})
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "data": load_json(POIN_FILE),
        "penarikan": load_json(TARIKAN_FILE),
        "verifikasi": load_json(VERIFIKASI_FILE),
        "riwayat": load_json(RIWAYAT_FILE),
        "user": load_json(USER_FILE),
        "ref": load_json(REF_FILE)
    })

# === BOT HANDLERS ===
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    args = msg.get_args()
    uid = str(msg.from_user.id)
    users = load_json(USER_FILE)
    poin = load_json(POIN_FILE)
    ref = load_json(REF_FILE)

    if uid not in users:
        users[uid] = {"username": msg.from_user.username}
        save_json(USER_FILE, users)

        if args and args != uid:
            ref[args] = ref.get(args, []) + [uid]
            save_json(REF_FILE, ref)
            poin[args] = poin.get(args, 0) + 1000
            save_json(POIN_FILE, poin)
            try:
                await bot.send_message(int(args), f"🎉 Kamu mendapat 1000 poin dari referral @{msg.from_user.username or uid}")
            except: pass

    teks = (
        "👋 Selamat datang di *Fluxion Faucet!*\n\n"
        "Gunakan tombol di bawah ini untuk mulai."
    )
    btn = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton(
            "🚀 Mini App", 
            web_app=WebAppInfo(url=f"https://teamababilcoded.github.io/telega/?id={uid}")),
        InlineKeyboardButton("💰 Cek Saldo", callback_data="saldo"),
        InlineKeyboardButton("📜 Riwayat", callback_data="riwayat"),
        InlineKeyboardButton("🏧 Tarik", callback_data="tarik"),
        InlineKeyboardButton("🛡️ Verifikasi", callback_data="verifikasi"),
        InlineKeyboardButton("👥 Referral", callback_data="referral")
    )
    await msg.answer(teks, reply_markup=btn, parse_mode=ParseMode.MARKDOWN)

@dp.callback_query_handler(lambda c: c.data == "saldo")
async def saldo(callback: types.CallbackQuery):
    data = load_json(POIN_FILE)
    jumlah = data.get(str(callback.from_user.id), 0)
    await callback.message.answer(f"💰 Saldo kamu: {jumlah} poin")

@dp.callback_query_handler(lambda c: c.data == "riwayat")
async def riwayat(callback: types.CallbackQuery):
    riwayat = load_json(RIWAYAT_FILE).get(str(callback.from_user.id), [])
    if not riwayat:
        return await callback.message.answer("📭 Belum ada riwayat.")
    teks = "🧾 *Riwayat Terakhir:*\n"
    for i in riwayat[-5:]:
        teks += f"• {i['type']} +{i['amount']} ({i['time'].split('T')[0]})\n"
    await callback.message.answer(teks, parse_mode=ParseMode.MARKDOWN)

@dp.callback_query_handler(lambda c: c.data == "verifikasi")
async def verifikasi(callback: types.CallbackQuery):
    await callback.message.answer("Silakan kirim data verifikasi kamu (email atau ID).")
    await VerifState.waiting_input.set()

@dp.message_handler(state=VerifState.waiting_input)
async def simpan_verif(msg: types.Message, state: FSMContext):
    data = load_json(VERIFIKASI_FILE)
    data[str(msg.from_user.id)] = {"input": msg.text, "time": datetime.now().isoformat()}
    save_json(VERIFIKASI_FILE, data)
    await msg.answer("✅ Verifikasi berhasil disimpan.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "tarik")
async def tarik(callback: types.CallbackQuery):
    await callback.message.answer("Pilih metode penarikan:", reply_markup=InlineKeyboardMarkup().add(
        InlineKeyboardButton("Dana", callback_data="metode_dana"),
        InlineKeyboardButton("OVO", callback_data="metode_ovo"),
        InlineKeyboardButton("GoPay", callback_data="metode_gopay")
    ))
    await WithdrawState.waiting_method.set()

@dp.callback_query_handler(lambda c: c.data.startswith("metode_"), state=WithdrawState.waiting_method)
async def metode_terpilih(callback: types.CallbackQuery, state: FSMContext):
    metode = callback.data.split("_")[1]
    await state.update_data(metode=metode)
    await callback.message.answer("Masukkan nomor e-wallet:")
    await WithdrawState.waiting_number.set()

@dp.message_handler(state=WithdrawState.waiting_number)
async def input_nomor(msg: types.Message, state: FSMContext):
    await state.update_data(nomor=msg.text)
    await msg.answer("Masukkan jumlah poin yang ingin ditarik:")
    await WithdrawState.waiting_amount.set()

@dp.message_handler(state=WithdrawState.waiting_amount)
async def proses_tarik(msg: types.Message, state: FSMContext):
    jumlah = int(msg.text)
    data = await state.get_data()
    uid = str(msg.from_user.id)
    poin = load_json(POIN_FILE)

    if poin.get(uid, 0) < jumlah:
        await msg.answer("❌ Saldo tidak cukup.")
        return await state.finish()

    penarikan = load_json(TARIKAN_FILE)
    penarikan.setdefault(uid, []).append({
        "amount": jumlah,
        "metode": data['metode'],
        "nomor": data['nomor'],
        "time": datetime.now().isoformat()
    })
    save_json(TARIKAN_FILE, penarikan)
    poin[uid] -= jumlah
    save_json(POIN_FILE, poin)

    tombol = InlineKeyboardMarkup().add(
        InlineKeyboardButton("✅ Terima", callback_data=f"approve_{uid}_{jumlah}"),
        InlineKeyboardButton("❌ Tolak", callback_data=f"reject_{uid}_{jumlah}")
    )
    await bot.send_message(ADMIN_ID,
        f"📥 @{msg.from_user.username or uid} mengajukan penarikan.\nMetode: {data['metode']}\nNomor: {data['nomor']}\nJumlah: {jumlah}",
        reply_markup=tombol)
    await msg.answer("✅ Penarikan diajukan.")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("approve_"))
async def approve_tarik(callback: types.CallbackQuery):
    await callback.message.edit_text("✅ Penarikan disetujui.")

@dp.callback_query_handler(lambda c: c.data.startswith("reject_"))
async def reject_tarik(callback: types.CallbackQuery):
    await callback.message.edit_text("❌ Penarikan ditolak.")

@dp.message_handler(commands=["admin_menu"])
async def admin_menu(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("❌ Akses ditolak.")
    user_data = load_json(USER_FILE)
    poin = load_json(POIN_FILE)
    verif = load_json(VERIFIKASI_FILE)
    tarik = load_json(TARIKAN_FILE)

    teks = (
        "📊 Statistik Admin\n\n"
        f"👥 Total User: {len(user_data)}\n"
        f"💰 Total Poin: {sum(poin.values())}\n"
        f"🏧 Permintaan Tarik: {sum(len(x) for x in tarik.values())}\n"
        f"🛡️ User Terverifikasi: {len(verif)}"
    )
    btn = InlineKeyboardMarkup().add(
        InlineKeyboardButton("➕ Kirim Poin", callback_data="kirim_poin")
    )
    await msg.answer(teks, reply_markup=btn)

@dp.callback_query_handler(lambda c: c.data == "kirim_poin")
async def mulai_kirim_poin(cb: types.CallbackQuery):
    await cb.message.answer("Masukkan ID user:")
    await KirimPoinState.waiting_userid.set()

@dp.message_handler(state=KirimPoinState.waiting_userid)
async def input_id(msg: types.Message, state: FSMContext):
    await state.update_data(userid=msg.text)
    await msg.answer("Masukkan jumlah poin:")
    await KirimPoinState.waiting_jumlah.set()

@dp.message_handler(state=KirimPoinState.waiting_jumlah)
async def proses_kirim(msg: types.Message, state: FSMContext):
    jumlah = int(msg.text)
    data = await state.get_data()
    uid = data["userid"]

    poin = load_json(POIN_FILE)
    poin[uid] = poin.get(uid, 0) + jumlah
    save_json(POIN_FILE, poin)

    await msg.answer("✅ Poin berhasil dikirim.")
    try:
        await bot.send_message(int(uid), f"🎁 Kamu menerima bonus {jumlah} poin!")
    except: pass
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "referral")
async def referral_btn(cb: types.CallbackQuery):
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={cb.from_user.id}"
    data = load_json(REF_FILE).get(str(cb.from_user.id), [])
    await cb.message.answer(f"🔗 Link referral kamu:\n{ref_link}\n\n👥 Total referral: {len(data)}")

# === RUN ===
async def main():
    config = Config(app=app, host="0.0.0.0", port=8000)
    server = Server(config)
    asyncio.create_task(server.serve())
    await dp.start_polling()

if __name__ == "__main__":
    asyncio.run(main())
