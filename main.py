import discord
from discord.ext import commands
import io
from PIL import Image
import imagehash
from threading import Thread
from flask import Flask
import os

# --- WEB SERVICE KEEP ALIVE ---
app = Flask('')

@app.route('/')
def home():
    return "Mack Bot is Alive!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()
# ------------------------------

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- CHANNEL IDs ---
VERIFY_HERE_CHANNEL_ID   = 1508730526532501504
MOD_LOG_CHANNEL_ID       = 1508761687233269861
SYNDICATE_VERIFY_CHANNEL = 1461666929516347453
# -------------------

verified_users = set()

@bot.event
async def on_ready():
    print(f'✅ {bot.user.name} is online!')

    missing = []
    if not bot.get_channel(VERIFY_HERE_CHANNEL_ID):
        missing.append(f"VERIFY_HERE_CHANNEL_ID ({VERIFY_HERE_CHANNEL_ID})")
    if not bot.get_channel(MOD_LOG_CHANNEL_ID):
        missing.append(f"MOD_LOG_CHANNEL_ID ({MOD_LOG_CHANNEL_ID})")
    if not bot.get_channel(SYNDICATE_VERIFY_CHANNEL):
        missing.append(f"SYNDICATE_VERIFY_CHANNEL ({SYNDICATE_VERIFY_CHANNEL})")

    if missing:
        print(f"⚠️ WARNING - Channels not found: {', '.join(missing)}")
    else:
        print("✅ All channels verified.")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.channel.id == VERIFY_HERE_CHANNEL_ID:

        if len(message.attachments) == 0:
            if not message.author.guild_permissions.administrator:
                embed = discord.Embed(
                    title="❌ Text Not Allowed",
                    description=f"{message.author.mention}, this channel is strictly for screenshots.",
                    color=discord.Color.red()
                )
                await message.channel.send(embed=embed, delete_after=5)
                await message.delete()
            return

        if len(message.attachments) != 4:
            embed = discord.Embed(
                title="⚠️ Incorrect Count",
                description=f"{message.author.mention}, upload exactly **4 screenshots**.",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed, delete_after=10)
            await message.delete()
            return

        if message.author.id in verified_users:
            embed = discord.Embed(
                title="🚫 Already Submitted",
                description=f"{message.author.mention}, you already submitted. Wait for mod review.",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed, delete_after=10)
            await message.delete()
            return

        await message.add_reaction("⏳")
        image_hashes = []
        duplicate_found = False

        for attachment in message.attachments:
            if not (attachment.content_type and attachment.content_type.startswith('image/')):
                embed = discord.Embed(
                    title="❌ Invalid File Type",
                    description=f"{message.author.mention}, only JPG/PNG allowed.",
                    color=discord.Color.red()
                )
                await message.channel.send(embed=embed, delete_after=10)
                await message.delete()
                return

            try:
                image_bytes = await attachment.read()
                img = Image.open(io.BytesIO(image_bytes))
                img_hash = imagehash.phash(img, hash_size=16)

                if any(abs(img_hash - h) < 5 for h in image_hashes):
                    duplicate_found = True
                    break
                image_hashes.append(img_hash)

            except Exception:
                embed = discord.Embed(
                    title="⚠️ Processing Error",
                    description="Error reading one of your images. Please try again.",
                    color=discord.Color.orange()
                )
                await message.channel.send(embed=embed, delete_after=10)
                return

        if duplicate_found:
            embed = discord.Embed(
                title="🚨 Verification Rejected",
                description=f"{message.author.mention}, duplicate screenshots detected!\nAll 4 must be unique.",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed, delete_after=15)
            await message.delete()
            return

        try:
            log_channel = bot.get_channel(MOD_LOG_CHANNEL_ID) or await bot.fetch_channel(MOD_LOG_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"❌ Cannot access MOD_LOG_CHANNEL: {e}")
            return

        files_to_send = [await a.to_file() for a in message.attachments]
        log_embed = discord.Embed(
            title="🔍 New Screenshot Submission",
            description=f"**Player:** {message.author.mention}\n**User ID:** {message.author.id}\n**Status:** Passed Duplicate Check.",
            color=discord.Color.blue()
        )
        await log_channel.send(embed=log_embed, files=files_to_send)

        verified_users.add(message.author.id)
        await message.delete()

        success_embed = discord.Embed(
            title="✅ Screenshots Accepted",
            description=f"Great job, {message.author.mention}! Under mod review.\n\n**Next Step:** Go to <#{SYNDICATE_VERIFY_CHANNEL}> and click **Verify Your Squad**.",
            color=discord.Color.green()
        )
        await message.channel.send(embed=success_embed, delete_after=30)

    await bot.process_commands(message)

# Web Service — Flask + Bot together
keep_alive()
bot.run(os.environ.get('DISCORD_TOKEN'))
