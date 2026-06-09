import discord
from discord.ext import commands, tasks
from discord import ui
import io
import json
import os
import datetime
from PIL import Image
import imagehash
from threading import Thread
from flask import Flask, render_template

# ═══════════════════════════════════════════════════════════
#  1. WEB SERVICE KEEP ALIVE (ORIGINAL — PRESERVED)
# ═══════════════════════════════════════════════════════════

app = Flask(__name__)

@app.route('/')
def home():
    s = data.get("stats", {})
    verified = len(data.get("verified_users", []))
    approved = len(data.get("approved_users", []))
    rejected = len(data.get("rejected_users", []))
    teams = len(data.get("team_names", {}))
    pending = verified - approved - rejected
    
    return render_template('index.html', 
                           submissions=s.get("total_submissions", 0),
                           approved=approved, 
                           pending=pending, 
                           teams=teams)

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# ═══════════════════════════════════════════════════════════
#  2. BOT SETUP
# ═══════════════════════════════════════════════════════════

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

# ═══════════════════════════════════════════════════════════
#  3. CHANNEL IDs
# ═══════════════════════════════════════════════════════════

VERIFY_HERE_CHANNEL_ID   = 1508730526532501504
MOD_LOG_CHANNEL_ID       = 1508761687233269861
SYNDICATE_VERIFY_CHANNEL = 1461666929516347453
TEAM_NAME_CHANNEL_ID     = 1508730691964244041

VERIFIED_ROLE_ID = None

# ═══════════════════════════════════════════════════════════
#  4. PERSISTENT DATA
# ═══════════════════════════════════════════════════════════

DATA_FILE = "data.json"
SCRIM_CONFIG_FILE = "server_setup.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            defaults = {
                "verified_users": [],
                "approved_users": [],
                "rejected_users": [],
                "blacklisted_users": [],
                "team_names": {},
                "scrim_channels": {},
                "stats": {"total_submissions": 0, "total_approved": 0, "total_rejected": 0},
                "verified_role_id": None,
                "welcome_channel_id": None,
                "cooldowns": {}
            }
            for key, val in defaults.items():
                if key not in data:
                    data[key] = val
            return data
    return {
        "verified_users": [],
        "approved_users": [],
        "rejected_users": [],
        "blacklisted_users": [],
        "team_names": {},
        "scrim_channels": {},
        "stats": {"total_submissions": 0, "total_approved": 0, "total_rejected": 0},
        "verified_role_id": None,
        "welcome_channel_id": None,
        "cooldowns": {}
    }

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_scrim_config():
    if os.path.exists(SCRIM_CONFIG_FILE):
        with open(SCRIM_CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_scrim_config(config):
    with open(SCRIM_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

data = load_data()

# ═══════════════════════════════════════════════════════════
#  5. DESIGN SYSTEM
# ═══════════════════════════════════════════════════════════

class Theme:
    SUCCESS  = discord.Color.from_rgb(0, 255, 170)
    ERROR    = discord.Color.from_rgb(255, 42, 85)
    WARNING  = discord.Color.from_rgb(255, 184, 0)
    INFO     = discord.Color.from_rgb(0, 195, 255)
    PREMIUM  = discord.Color.from_rgb(180, 0, 255)
    ACCENT   = discord.Color.from_rgb(138, 43, 226)
    TEAL     = discord.Color.from_rgb(0, 255, 204)
    GOLD     = discord.Color.from_rgb(255, 215, 0)
    SEP      = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    THIN_SEP = "──────────────────────────────"
    FOOTER   = "⚡ Mack Bot │ Premium Verification"

def make_embed(title, desc=None, color=None, footer=None):
    e = discord.Embed(title=title, description=desc, color=color or Theme.INFO,
                      timestamp=datetime.datetime.utcnow())
    e.set_footer(text=footer or Theme.FOOTER)
    return e

# ═══════════════════════════════════════════════════════════
#  6. ANTI-SPAM / COOLDOWN SYSTEM
# ═══════════════════════════════════════════════════════════

COOLDOWN_SECONDS = 60

def check_cooldown(user_id):
    uid = str(user_id)
    cooldowns = data.get("cooldowns", {})
    if uid in cooldowns:
        last_time = datetime.datetime.fromisoformat(cooldowns[uid])
        elapsed = (datetime.datetime.utcnow() - last_time).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            return True, int(COOLDOWN_SECONDS - elapsed)
    return False, 0

def set_cooldown(user_id):
    uid = str(user_id)
    if "cooldowns" not in data:
        data["cooldowns"] = {}
    data["cooldowns"][uid] = datetime.datetime.utcnow().isoformat()
    save_data()

# ═══════════════════════════════════════════════════════════
#  7. SCRIM REGISTRATION UI
# ═══════════════════════════════════════════════════════════

def create_setup_embed(role_name, current_slots, max_slots):
    return make_embed(
        f"🎮 {role_name} — Scrim Registration",
        f"{Theme.SEP}\n\n"
        f"Click the button below to register!\n\n"
        f"╭── 📋 **Info** ──╮\n"
        f"│  🎭 **Role:** `{role_name}`\n"
        f"│  📊 **Slots:** `{current_slots}/{max_slots}`\n"
        f"╰──────────────╯\n\n"
        f"⏳ *Resets daily at 12:00 AM IST*\n\n{Theme.SEP}",
        Theme.ACCENT, "🎮 Scrim Registration Panel"
    )

def build_roster_embed(role_name, teams, max_slots):
    """Reusable roster embed builder — used by !list and auto-update."""
    current_filled = len(teams)
    status_icon = "🟢" if current_filled < max_slots else "🔴"
    status_text = "Slots Open" if current_filled < max_slots else "Registration Full"

    bar_length = 10
    filled_length = int(round(bar_length * current_filled / float(max_slots))) if max_slots > 0 else 0
    progress_bar = ("▰" * filled_length) + ("▱" * (bar_length - filled_length))

    description_header = f"{status_icon} {status_text} • **{current_filled}/{max_slots}** slots filled\n`{progress_bar}`\n\n"

    list_content = "```text\n"
    list_content += "##   |  TEAM NAME\n"
    list_content += "—————|————————————————————————\n"

    for i in range(max_slots):
        slot_num = str(i + 1).zfill(2)
        if i < current_filled:
            team = teams[i]
            team_name = team['team_name']
            if len(team_name) > 20:
                team_name = team_name[:17] + "..."
            list_content += f"{slot_num}   |  ◇  {team_name}\n"
        else:
            list_content += f"{slot_num}   |  ◇  — Open —\n"

    list_content += "```"

    embed = discord.Embed(
        title=f"🏆 {role_name} — Live Roster",
        description=description_header + list_content,
        color=discord.Color.brand_green() if current_filled < max_slots else discord.Color.red()
    )
    embed.set_footer(text="🔄 Auto-updates • Do not type here")
    return embed


async def update_list_message(ctx_or_channel, channel_data, scrim_config):
    """Fetch the stored list message and edit it with fresh roster data."""
    list_msg_id = channel_data.get("list_message_id")
    if not list_msg_id:
        return

    role = ctx_or_channel.guild.get_role(channel_data["role_id"])
    role_name = role.name if role else "MATCH"
    teams = channel_data.get("teams", [])
    max_slots = channel_data["max_slots"]

    try:
        channel = ctx_or_channel if isinstance(ctx_or_channel, discord.TextChannel) else ctx_or_channel.channel
        list_msg = await channel.fetch_message(list_msg_id)
        await list_msg.edit(embed=build_roster_embed(role_name, teams, max_slots))
    except discord.NotFound:
        # Message was deleted — clear stored ID
        channel_data["list_message_id"] = None
        save_scrim_config(scrim_config)

class RegistrationModal(ui.Modal, title='Scrim Registration'):
    team_name = ui.TextInput(label='Team Name', style=discord.TextStyle.short, required=True)
    discord_tag = ui.TextInput(label='Discord Tag', style=discord.TextStyle.short, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        scrim_config = load_scrim_config()
        channel_data = scrim_config.get(str(interaction.channel.id))

        if not channel_data:
            return await interaction.response.send_message(
                embed=make_embed("⚠️ Error", "This channel is not configured for scrim registration.", Theme.ERROR),
                ephemeral=True)

        role_id = channel_data["role_id"]
        max_slots = channel_data["max_slots"]
        role = interaction.guild.get_role(role_id)

        if not role:
            return await interaction.response.send_message(
                embed=make_embed("❌ Error", "Configured role not found. Contact an admin.", Theme.ERROR),
                ephemeral=True)

        if len(channel_data.get("teams", [])) >= max_slots:
            return await interaction.response.send_message(
                embed=make_embed("❌ Registration Full",
                    f"All **{max_slots}** slots are taken!", Theme.ERROR),
                ephemeral=True)

        try:
            await interaction.user.add_roles(role)
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=make_embed("❌ Error", "Bot lacks permission to assign roles.", Theme.ERROR),
                ephemeral=True)

        if "teams" not in channel_data:
            channel_data["teams"] = []
        channel_data["teams"].append({
            "team_name": self.team_name.value,
            "leader": self.discord_tag.value,
            "user_id": interaction.user.id
        })
        save_scrim_config(scrim_config)

        current_slots = len(channel_data.get("teams", []))

        # Update panel embed
        setup_msg_id = channel_data.get("setup_message_id")
        if setup_msg_id:
            try:
                setup_msg = await interaction.channel.fetch_message(setup_msg_id)
                updated_embed = create_setup_embed(role.name, current_slots, max_slots)
                await setup_msg.edit(embed=updated_embed)
            except discord.NotFound:
                pass

        # Auto-update list message
        list_msg_id = channel_data.get("list_message_id")
        if list_msg_id:
            try:
                list_msg = await interaction.channel.fetch_message(list_msg_id)
                await list_msg.edit(embed=build_roster_embed(role.name, channel_data["teams"], max_slots))
            except discord.NotFound:
                channel_data["list_message_id"] = None
                save_scrim_config(scrim_config)

        slots_left = max_slots - current_slots
        success_embed = make_embed(
            "✅ Scrim Registration Successful",
            f"{Theme.SEP}\n\n"
            f"╭── 📋 **Registration Details** ──╮\n"
            f"│\n"
            f"│  🏷️ **Team:** `{self.team_name.value}`\n"
            f"│  🏷️ **Tag:** `{self.discord_tag.value}`\n"
            f"│  🎭 **Role:** `{role.name}`\n"
            f"│\n"
            f"╰────────────────────────────╯\n\n"
            f"**Slots remaining:** `{slots_left}/{max_slots}`\n\n{Theme.SEP}",
            Theme.SUCCESS, "🎮 Scrim Registration"
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)


class RegisterView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="📝 Register", style=discord.ButtonStyle.blurple, custom_id="scrim_register_btn")
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        scrim_config = load_scrim_config()
        channel_data = scrim_config.get(str(interaction.channel.id))

        if not channel_data:
            return await interaction.response.send_message(
                embed=make_embed("⚠️ Error", "Admin has not set up this channel.", Theme.ERROR),
                ephemeral=True)

        if not channel_data.get("is_open", True):
            return await interaction.response.send_message(
                embed=make_embed("🔒 Locked", "Registration is currently closed.", Theme.ERROR),
                ephemeral=True)

        role_id = channel_data["role_id"]
        max_slots = channel_data["max_slots"]
        role = interaction.guild.get_role(role_id)

        if len(channel_data.get("teams", [])) >= max_slots:
            return await interaction.response.send_message(
                embed=make_embed("❌ Registration Closed",
                    f"All **{max_slots}** slots are full!", Theme.ERROR),
                ephemeral=True)

        if role and role in interaction.user.roles:
            return await interaction.response.send_message(
                embed=make_embed("⚠️ Already Registered",
                    f"You already have the **{role.name}** role.", Theme.WARNING),
                ephemeral=True)

        await interaction.response.send_modal(RegistrationModal())

# ═══════════════════════════════════════════════════════════
#  8. ON_READY EVENT
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f'✅ {bot.user.name} is online!')
    bot.add_view(RegisterView())

    missing = []
    if not bot.get_channel(VERIFY_HERE_CHANNEL_ID):
        missing.append(f"VERIFY_HERE_CHANNEL_ID ({VERIFY_HERE_CHANNEL_ID})")
    if not bot.get_channel(MOD_LOG_CHANNEL_ID):
        missing.append(f"MOD_LOG_CHANNEL_ID ({MOD_LOG_CHANNEL_ID})")
    if not bot.get_channel(SYNDICATE_VERIFY_CHANNEL):
        missing.append(f"SYNDICATE_VERIFY_CHANNEL ({SYNDICATE_VERIFY_CHANNEL})")
    if not bot.get_channel(TEAM_NAME_CHANNEL_ID):
        missing.append(f"TEAM_NAME_CHANNEL_ID ({TEAM_NAME_CHANNEL_ID})")

    if missing:
        print(f"⚠️ WARNING - Channels not found: {', '.join(missing)}")
    else:
        print("✅ All channels verified.")

    if not midnight_reset.is_running():
        midnight_reset.start()

    print(f"📊 Loaded {len(data['verified_users'])} verified users from storage.")
    print(f"🚫 {len(data['blacklisted_users'])} blacklisted users loaded.")

# ═══════════════════════════════════════════════════════════
#  9. ON_MESSAGE
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.channel.id == VERIFY_HERE_CHANNEL_ID:

        if str(message.author.id) in data["blacklisted_users"]:
            embed = make_embed(
                "🚫 Blacklisted",
                f"{message.author.mention}, you are blacklisted from verification.",
                Theme.ERROR
            )
            await message.channel.send(embed=embed, delete_after=5)
            await message.delete()
            return

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

        if message.author.id in [int(u) for u in data["verified_users"]]:
            embed = discord.Embed(
                title="🚫 Already Submitted",
                description=f"{message.author.mention}, you already submitted. Wait for mod review.",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed, delete_after=10)
            await message.delete()
            return

        on_cooldown, remaining = check_cooldown(message.author.id)
        if on_cooldown:
            embed = make_embed(
                "⏳ Cooldown Active",
                f"{message.author.mention}, please wait **{remaining}s** before submitting again.",
                Theme.WARNING
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

        data["verified_users"].append(str(message.author.id))
        data["stats"]["total_submissions"] += 1
        set_cooldown(message.author.id)
        save_data()

        await message.delete()

        verified_role_id = data.get("verified_role_id")
        if verified_role_id and message.guild:
            role = message.guild.get_role(int(verified_role_id))
            if role:
                try:
                    await message.author.add_roles(role)
                except discord.Forbidden:
                    print(f"⚠️ Cannot assign verified role to {message.author}")

        success_embed = discord.Embed(
            title="✅ Screenshots Accepted",
            description=f"Great job, {message.author.mention}! Under mod review.\n\n**Next Step:** Go to <#{SYNDICATE_VERIFY_CHANNEL}> and click **Verify Your Squad**.",
            color=discord.Color.green()
        )
        await message.channel.send(embed=success_embed, delete_after=30)

    elif message.channel.id == TEAM_NAME_CHANNEL_ID:

        if str(message.author.id) in data["blacklisted_users"]:
            embed = make_embed(
                "🚫 Blacklisted",
                f"{message.author.mention}, you are blacklisted.",
                Theme.ERROR
            )
            await message.channel.send(embed=embed, delete_after=5)
            await message.delete()
            return

        if len(message.attachments) > 0:
            if not message.author.guild_permissions.administrator:
                embed = discord.Embed(
                    title="❌ Text Only",
                    description=f"{message.author.mention}, please only type your team name and tag here. No images.",
                    color=discord.Color.red()
                )
                await message.channel.send(embed=embed, delete_after=5)
                await message.delete()
            return

        team_name_text = message.content

        try:
            log_channel = bot.get_channel(MOD_LOG_CHANNEL_ID) or await bot.fetch_channel(MOD_LOG_CHANNEL_ID)
            log_embed = discord.Embed(
                title="📝 New Team Name Submission",
                description=f"**Player:** {message.author.mention}\n**Team Info:** {team_name_text}",
                color=discord.Color.purple()
            )
            await log_channel.send(embed=log_embed)
        except Exception as e:
            print(f"❌ Cannot access MOD_LOG_CHANNEL: {e}")

        data["team_names"][str(message.author.id)] = {
            "name": team_name_text,
            "submitted_at": datetime.datetime.utcnow().isoformat()
        }
        save_data()

        success_embed = discord.Embed(
            title="✅ Team Name Registered",
            description=f"Got it, {message.author.mention}!\nYour team **{team_name_text}** is now pending final mod review.",
            color=discord.Color.green()
        )
        await message.channel.send(embed=success_embed, delete_after=15)
        await message.delete()

    await bot.process_commands(message)

# ═══════════════════════════════════════════════════════════
#  10. WELCOME MESSAGE
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_member_join(member):
    welcome_channel_id = data.get("welcome_channel_id")

    try:
        dm_embed = make_embed(
            f"👋 Welcome to {member.guild.name}!",
            f"{Theme.SEP}\n\n"
            f"Hey {member.mention}, welcome aboard! 🎉\n\n"
            f"**📋 Verification Steps:**\n\n"
            f"> **` 1 `** Go to <#{VERIFY_HERE_CHANNEL_ID}> and upload **4 unique screenshots**\n"
            f"> **` 2 `** Wait for mod review ✅\n"
            f"> **` 3 `** Go to <#{SYNDICATE_VERIFY_CHANNEL}> and click **Verify Your Squad**\n"
            f"> **` 4 `** Submit your team name in <#{TEAM_NAME_CHANNEL_ID}>\n\n"
            f"{Theme.THIN_SEP}\n"
            f"*Good luck and have fun!* 🎮\n\n{Theme.SEP}",
            Theme.ACCENT, f"Welcome to {member.guild.name}"
        )
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass

    if welcome_channel_id:
        channel = member.guild.get_channel(int(welcome_channel_id))
        if channel:
            welcome_embed = make_embed(
                "👋 New Member!",
                f"Welcome {member.mention} to the server!\n"
                f"Head to <#{VERIFY_HERE_CHANNEL_ID}> to start verification.",
                Theme.TEAL
            )
            await channel.send(embed=welcome_embed, delete_after=60)

# ═══════════════════════════════════════════════════════════
#  11. MOD COMMANDS
# ═══════════════════════════════════════════════════════════

@bot.command()
@commands.has_permissions(administrator=True)
async def approve(ctx, member: discord.Member):
    uid = str(member.id)

    if uid in data["approved_users"]:
        await ctx.send(embed=make_embed("⚠️ Already Approved",
            f"{member.mention} was already approved.", Theme.WARNING))
        return

    if uid in data["rejected_users"]:
        data["rejected_users"].remove(uid)

    data["approved_users"].append(uid)
    data["stats"]["total_approved"] += 1
    save_data()

    verified_role_id = data.get("verified_role_id")
    if verified_role_id:
        role = ctx.guild.get_role(int(verified_role_id))
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

    embed = make_embed(
        "✅ User Approved",
        f"{Theme.SEP}\n\n"
        f"**Player:** {member.mention}\n"
        f"**Approved by:** {ctx.author.mention}\n\n{Theme.SEP}",
        Theme.SUCCESS
    )
    await ctx.send(embed=embed)

    try:
        log_channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(embed=embed)
    except Exception:
        pass

    try:
        dm_embed = make_embed("✅ You've Been Approved!",
            f"Your verification in **{ctx.guild.name}** has been approved! 🎉",
            Theme.SUCCESS)
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass


@bot.command()
@commands.has_permissions(administrator=True)
async def reject(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    uid = str(member.id)

    if uid in data["verified_users"]:
        data["verified_users"].remove(uid)
    if uid in data["approved_users"]:
        data["approved_users"].remove(uid)

    if uid not in data["rejected_users"]:
        data["rejected_users"].append(uid)
    data["stats"]["total_rejected"] += 1
    save_data()

    embed = make_embed(
        "❌ User Rejected",
        f"{Theme.SEP}\n\n"
        f"**Player:** {member.mention}\n"
        f"**Reason:** {reason}\n"
        f"**Rejected by:** {ctx.author.mention}\n\n{Theme.SEP}",
        Theme.ERROR
    )
    await ctx.send(embed=embed)

    try:
        log_channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(embed=embed)
    except Exception:
        pass

    try:
        dm_embed = make_embed("❌ Verification Rejected",
            f"Your verification in **{ctx.guild.name}** was rejected.\n**Reason:** {reason}\n\n"
            f"You may resubmit your screenshots.",
            Theme.ERROR)
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass

# ═══════════════════════════════════════════════════════════
#  12. BLACKLIST SYSTEM
# ═══════════════════════════════════════════════════════════

@bot.command()
@commands.has_permissions(administrator=True)
async def blacklist(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    uid = str(member.id)
    if uid in data["blacklisted_users"]:
        await ctx.send(embed=make_embed("⚠️ Already Blacklisted",
            f"{member.mention} is already blacklisted.", Theme.WARNING))
        return

    data["blacklisted_users"].append(uid)
    save_data()

    embed = make_embed(
        "🚫 User Blacklisted",
        f"{Theme.SEP}\n\n"
        f"**Player:** {member.mention}\n"
        f"**Reason:** {reason}\n"
        f"**By:** {ctx.author.mention}\n\n{Theme.SEP}",
        Theme.ERROR
    )
    await ctx.send(embed=embed)

    try:
        log_channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(embed=embed)
    except Exception:
        pass


@bot.command()
@commands.has_permissions(administrator=True)
async def unblacklist(ctx, member: discord.Member):
    uid = str(member.id)
    if uid not in data["blacklisted_users"]:
        await ctx.send(embed=make_embed("⚠️ Not Blacklisted",
            f"{member.mention} is not blacklisted.", Theme.WARNING))
        return

    data["blacklisted_users"].remove(uid)
    save_data()

    embed = make_embed(
        "✅ User Unblacklisted",
        f"{member.mention} has been removed from the blacklist by {ctx.author.mention}.",
        Theme.SUCCESS
    )
    await ctx.send(embed=embed)

# ═══════════════════════════════════════════════════════════
#  13. STATUS COMMAND
# ═══════════════════════════════════════════════════════════

@bot.command()
async def status(ctx):
    uid = str(ctx.author.id)

    if uid in data["blacklisted_users"]:
        step = "🚫 **BLACKLISTED** — Contact a moderator."
        color = Theme.ERROR
    elif uid in data["approved_users"]:
        step = "✅ **FULLY APPROVED** — You're all set!"
        color = Theme.SUCCESS
    elif uid in data["rejected_users"]:
        step = "❌ **REJECTED** — Please resubmit your screenshots."
        color = Theme.ERROR
    elif uid in data["verified_users"]:
        step = "⏳ **SCREENSHOTS SUBMITTED** — Waiting for mod review."
        color = Theme.WARNING
    else:
        step = "📸 **NOT STARTED** — Submit 4 screenshots in the verification channel."
        color = Theme.INFO

    team = data["team_names"].get(uid)
    team_status = f"✅ **{team['name']}**" if team else "❌ Not submitted yet"

    embed = make_embed(
        f"📋 Verification Status — {ctx.author.display_name}",
        f"{Theme.SEP}\n\n"
        f"**Step 1 — Screenshots:** {step}\n\n"
        f"**Step 2 — Team Name:** {team_status}\n\n"
        f"{Theme.SEP}",
        color
    )
    await ctx.send(embed=embed, delete_after=30)

# ═══════════════════════════════════════════════════════════
#  14. STATS COMMAND
# ═══════════════════════════════════════════════════════════

@bot.command()
@commands.has_permissions(administrator=True)
async def stats(ctx):
    s = data["stats"]
    total_verified = len(data["verified_users"])
    total_approved = len(data["approved_users"])
    total_rejected = len(data["rejected_users"])
    total_blacklisted = len(data["blacklisted_users"])
    total_teams = len(data["team_names"])

    embed = make_embed(
        "📊 Verification Statistics",
        f"{Theme.SEP}\n\n"
        f"╭── 📋 **Overview** ──╮\n"
        f"│\n"
        f"│  📸 **Submissions:** `{s.get('total_submissions', 0)}`\n"
        f"│  ⏳ **Pending Review:** `{total_verified - total_approved - total_rejected}`\n"
        f"│  ✅ **Approved:** `{total_approved}`\n"
        f"│  ❌ **Rejected:** `{total_rejected}`\n"
        f"│  🚫 **Blacklisted:** `{total_blacklisted}`\n"
        f"│  📝 **Teams Registered:** `{total_teams}`\n"
        f"│\n"
        f"╰────────────────────╯\n\n{Theme.SEP}",
        Theme.PREMIUM
    )
    await ctx.send(embed=embed)

# ═══════════════════════════════════════════════════════════
#  15. CONFIGURATION COMMANDS
# ═══════════════════════════════════════════════════════════

@bot.command()
@commands.has_permissions(administrator=True)
async def setrole(ctx, role: discord.Role):
    data["verified_role_id"] = str(role.id)
    save_data()
    embed = make_embed("✅ Verified Role Set",
        f"Users will now receive **{role.name}** upon screenshot approval.",
        Theme.SUCCESS)
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def setwelcome(ctx, channel: discord.TextChannel):
    data["welcome_channel_id"] = str(channel.id)
    save_data()
    embed = make_embed("✅ Welcome Channel Set",
        f"New member welcomes will be posted in {channel.mention}.",
        Theme.SUCCESS)
    await ctx.send(embed=embed)


@bot.command(name="scrim_setup")
@commands.has_permissions(administrator=True)
async def scrim_setup(ctx, role: discord.Role, slots: int):
    if slots < 1 or slots > 100:
        await ctx.send(embed=make_embed("❌ Invalid Slots", "Must be between 1 and 100.", Theme.ERROR))
        return

    scrim_config = load_scrim_config()

    embed = create_setup_embed(role.name, 0, slots)
    msg = await ctx.send(embed=embed, view=RegisterView())

    scrim_config[str(ctx.channel.id)] = {
        "role_id": role.id,
        "max_slots": slots,
        "setup_message_id": msg.id,
        "teams": [],
        "is_open": True
    }
    save_scrim_config(scrim_config)
    await ctx.message.delete()


@bot.command(name="open")
@commands.has_permissions(administrator=True)
async def cmd_open(ctx):
    scrim_config = load_scrim_config()
    channel_data = scrim_config.get(str(ctx.channel.id))
    if not channel_data:
        return await ctx.send(embed=make_embed("⚠️ Error", "Not a registration channel.", Theme.ERROR))

    channel_data["is_open"] = True
    save_scrim_config(scrim_config)
    await ctx.send(embed=make_embed("🔓 Unlocked", "Registration is now open.", Theme.SUCCESS))


@bot.command(name="close")
@commands.has_permissions(administrator=True)
async def cmd_close(ctx):
    scrim_config = load_scrim_config()
    channel_data = scrim_config.get(str(ctx.channel.id))
    if not channel_data:
        return await ctx.send(embed=make_embed("⚠️ Error", "Not a registration channel.", Theme.ERROR))

    channel_data["is_open"] = False
    save_scrim_config(scrim_config)
    await ctx.send(embed=make_embed("🔒 Locked", "Registration is now closed.", Theme.ERROR))


@bot.command(name="wipe")
@commands.has_permissions(administrator=True)
async def cmd_wipe(ctx):
    scrim_config = load_scrim_config()
    channel_data = scrim_config.get(str(ctx.channel.id))

    if not channel_data:
        return await ctx.send(embed=make_embed("⚠️ Error", "Not a registration channel.", Theme.ERROR))

    role = ctx.guild.get_role(channel_data["role_id"])
    if role:
        for member in role.members:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                pass

    channel_data["teams"] = []
    save_scrim_config(scrim_config)

    # Update panel embed
    setup_msg_id = channel_data.get("setup_message_id")
    if setup_msg_id:
        try:
            setup_msg = await ctx.channel.fetch_message(setup_msg_id)
            updated_embed = create_setup_embed(role.name if role else "Scrim", 0, channel_data["max_slots"])
            await setup_msg.edit(embed=updated_embed)
        except discord.NotFound:
            pass

    # Auto-update list message
    await update_list_message(ctx, channel_data, scrim_config)

    await ctx.send(embed=make_embed("🧹 Roster Wiped",
        "All teams cleared, roles removed, panel reset to 0.", Theme.SUCCESS))


@bot.command(name="removeslot")
@commands.has_permissions(administrator=True)
async def cmd_removeslot(ctx, slot: int):
    scrim_config = load_scrim_config()
    channel_data = scrim_config.get(str(ctx.channel.id))

    if not channel_data:
        return await ctx.send(embed=make_embed("⚠️ Error", "Not a registration channel.", Theme.ERROR))

    teams = channel_data.get("teams", [])
    if slot < 1 or slot > len(teams):
        return await ctx.send(embed=make_embed("❌ Error",
            f"Invalid slot number. Must be between 1 and {len(teams)}.", Theme.ERROR))

    removed_team = teams.pop(slot - 1)
    user_id = removed_team.get("user_id")

    if user_id:
        role = ctx.guild.get_role(channel_data["role_id"])
        if role:
            member = ctx.guild.get_member(user_id)
            if member:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    pass

    save_scrim_config(scrim_config)

    # Update panel embed
    role = ctx.guild.get_role(channel_data["role_id"])
    setup_msg_id = channel_data.get("setup_message_id")
    if setup_msg_id:
        try:
            setup_msg = await ctx.channel.fetch_message(setup_msg_id)
            updated_embed = create_setup_embed(role.name if role else "Scrim", len(teams), channel_data["max_slots"])
            await setup_msg.edit(embed=updated_embed)
        except discord.NotFound:
            pass

    # ── Auto-update live roster embed ──
    await update_list_message(ctx, channel_data, scrim_config)

    await ctx.send(embed=make_embed("🗑️ Slot Removed",
        f"Successfully removed **{removed_team['team_name']}** from Slot {slot}.", Theme.SUCCESS))


@bot.command()
@commands.has_permissions(administrator=True)
async def announce(ctx, role: discord.Role, *, message: str = "Registration is now open! Grab your slots before they fill up."):
    await ctx.message.delete()
    embed = make_embed(
        "📢 Scrim Announcement",
        f"{Theme.SEP}\n\n{message}\n\n{Theme.SEP}",
        Theme.GOLD
    )
    await ctx.send(content=f"{role.mention}", embed=embed)


@bot.command(name="list")
async def cmd_list(ctx):
    scrim_config = load_scrim_config()
    channel_data = scrim_config.get(str(ctx.channel.id))

    if not channel_data:
        return await ctx.send("⚠️ This channel is not set up for registration.")

    role_id = channel_data["role_id"]
    role = ctx.guild.get_role(role_id)
    teams = channel_data.get("teams", [])
    max_slots = channel_data["max_slots"]
    role_name = role.name if role else "MATCH"

    embed = build_roster_embed(role_name, teams, max_slots)
    msg = await ctx.send(embed=embed)

    # ── Store list message ID for auto-update ──
    channel_data["list_message_id"] = msg.id
    save_scrim_config(scrim_config)

# ═══════════════════════════════════════════════════════════
#  16. HELP COMMAND
# ═══════════════════════════════════════════════════════════

@bot.command(name="help")
async def cmd_help(ctx):
    is_admin = ctx.author.guild_permissions.administrator

    embed = make_embed(
        "⚡ Mack Bot — Command Center",
        f"{Theme.SEP}\n\n"
        f"**👤 Player Commands**\n\n"
        f"> `!status` — Check your verification progress\n"
        f"> `!list` — View live esports roster for this channel\n"
        f"> `!help` — Show this help menu\n\n"
        f"{Theme.THIN_SEP}\n\n"
        f"**📋 Verification Steps**\n\n"
        f"> **` 1 `** Upload **4 unique screenshots** in <#{VERIFY_HERE_CHANNEL_ID}>\n"
        f"> **` 2 `** Wait for mod approval ✅\n"
        f"> **` 3 `** Verify your squad in <#{SYNDICATE_VERIFY_CHANNEL}>\n"
        f"> **` 4 `** Submit team name in <#{TEAM_NAME_CHANNEL_ID}>\n",
        Theme.PREMIUM
    )

    if is_admin:
        embed.description += (
            f"\n{Theme.THIN_SEP}\n\n"
            f"**🔧 Admin Commands**\n\n"
            f"> `!approve @user` — Approve a user's verification\n"
            f"> `!reject @user [reason]` — Reject with optional reason\n"
            f"> `!blacklist @user [reason]` — Permanently block a user\n"
            f"> `!unblacklist @user` — Remove from blacklist\n"
            f"> `!stats` — View verification statistics\n"
            f"> `!setrole @Role` — Set the verified role\n"
            f"> `!setwelcome #channel` — Set welcome channel\n"
            f"> `!resetuser @user` — Reset a user's verification data\n\n"
            f"**🏆 Scrim Admin Commands**\n\n"
            f"> `!scrim_setup @Role <slots>` — Setup scrim registration panel\n"
            f"> `!open` — Manually unlock the registration button\n"
            f"> `!close` — Manually lock the registration button\n"
            f"> `!removeslot <slot_number>` — Force remove a team from a slot\n"
            f"> `!announce @Role [msg]` — Announce registration is open\n"
            f"> `!wipe` — Wipe roster and reset panel\n"
        )

    embed.description += f"\n{Theme.SEP}"
    await ctx.send(embed=embed, delete_after=120)

# ═══════════════════════════════════════════════════════════
#  17. UTILITY COMMANDS
# ═══════════════════════════════════════════════════════════

@bot.command()
@commands.has_permissions(administrator=True)
async def resetuser(ctx, member: discord.Member):
    uid = str(member.id)
    changed = False

    if uid in data["verified_users"]:
        data["verified_users"].remove(uid)
        changed = True
    if uid in data["approved_users"]:
        data["approved_users"].remove(uid)
        changed = True
    if uid in data["rejected_users"]:
        data["rejected_users"].remove(uid)
        changed = True
    if uid in data.get("cooldowns", {}):
        del data["cooldowns"][uid]
        changed = True

    if changed:
        save_data()
        embed = make_embed("🔄 User Reset",
            f"{member.mention}'s verification data has been cleared.\nThey can re-submit.",
            Theme.SUCCESS)
    else:
        embed = make_embed("⚠️ No Data",
            f"{member.mention} has no verification data to reset.",
            Theme.WARNING)

    await ctx.send(embed=embed)

# ═══════════════════════════════════════════════════════════
#  18. MIDNIGHT RESET TASK
# ═══════════════════════════════════════════════════════════

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
MIDNIGHT_IST = datetime.time(hour=0, minute=0, second=0, tzinfo=IST)

@tasks.loop(time=MIDNIGHT_IST)
async def midnight_reset():
    print("🕛 MIDNIGHT RESET: Cleaning up scrim roles...")
    scrim_config = load_scrim_config()

    for channel_id_str, channel_data in scrim_config.items():
        channel_data["teams"] = []

        for guild in bot.guilds:
            role = guild.get_role(channel_data["role_id"])
            if role:
                for member in role.members:
                    try:
                        await member.remove_roles(role)
                    except discord.Forbidden:
                        pass

                try:
                    channel = guild.get_channel(int(channel_id_str))
                    if channel:
                        setup_msg = await channel.fetch_message(channel_data["setup_message_id"])
                        updated_embed = create_setup_embed(role.name, 0, channel_data["max_slots"])
                        await setup_msg.edit(embed=updated_embed)
                except Exception:
                    pass

                # Auto-update list message on midnight reset
                list_msg_id = channel_data.get("list_message_id")
                if list_msg_id:
                    try:
                        channel = guild.get_channel(int(channel_id_str))
                        if channel:
                            list_msg = await channel.fetch_message(list_msg_id)
                            await list_msg.edit(embed=build_roster_embed(role.name, [], channel_data["max_slots"]))
                    except Exception:
                        pass

    save_scrim_config(scrim_config)

    now = datetime.datetime.utcnow()
    expired = []
    for uid, ts in data.get("cooldowns", {}).items():
        try:
            t = datetime.datetime.fromisoformat(ts)
            if (now - t).total_seconds() > 86400:
                expired.append(uid)
        except Exception:
            expired.append(uid)
    for uid in expired:
        del data["cooldowns"][uid]
    save_data()

    print("✅ Midnight reset complete.")

# ═══════════════════════════════════════════════════════════
#  19. ERROR HANDLER
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = make_embed("🔒 Access Denied",
            "You don't have permission to use this command.", Theme.ERROR)
        await ctx.send(embed=embed, delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = make_embed("⚠️ Missing Argument",
            f"Required: `{error.param.name}`\nUse `!help` for command syntax.", Theme.WARNING)
        await ctx.send(embed=embed, delete_after=10)
    elif isinstance(error, commands.BadArgument):
        embed = make_embed("⚠️ Invalid Argument",
            "Check your command syntax. Use `!help` for reference.", Theme.WARNING)
        await ctx.send(embed=embed, delete_after=10)
    elif isinstance(error, commands.CommandNotFound):
        embed = make_embed("❓ Unknown Command",
            "Use `!help` to see available commands.", Theme.INFO)
        await ctx.send(embed=embed, delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        pass
    else:
        embed = make_embed("❌ Error", f"`{str(error)[:200]}`", Theme.ERROR)
        await ctx.send(embed=embed, delete_after=15)
    print(f"[ERROR] {error}")

# ═══════════════════════════════════════════════════════════
#  20. STARTUP
# ═══════════════════════════════════════════════════════════

keep_alive()
bot.run(os.environ.get('DISCORD_TOKEN'))
