import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import asyncio
import requests
import os
import json
import traceback
import atexit
from datetime import datetime
from dateutil.relativedelta import relativedelta

TOKEN = os.getenv('DISCORD_TOKEN', "pastetokenhere")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN is required!")

FLAGGED_GROUP_IDS = [12960473, 35488582, 32418149, 35576099, 1051291555, 34532432, 34107403, 15872214, 35988727, 34202968, 35448137, 12877535, 13835630, 35942619, 8487267, 33301603, 35788564, 35868778, 172319536]
WHITELIST = [528953104939483186, 713929689768656999] 
ADMIN_USER = "wizardstrike1"
GUILD_ID = 1455289006475448505
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

cuts_data = {} 
DEFAULT_CUTS = 5

ROBLOX_API = "https://users.roblox.com/v1/usernames/users"
GROUPS_API = "https://groups.roblox.com/v2/users/{user_id}/groups/roles"
FRIENDS_API = "https://friends.roblox.com/v1/users/{user_id}/friends"
GROUP_INFO_API = "https://groups.roblox.com/v1/groups/{group_id}"
USER_INFO_API = "https://users.roblox.com/v1/users/{user_id}"
THUMBNAIL_API = "https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=720x720&format=Png&isCircular=false"
BADGES_API = "https://badges.roblox.com/v1/users/{user_id}/badges?limit=100&sortOrder=Asc"

# Mococo API configuration
MOCOCO_API_BASE = "https://api.moco-co.org"
MOCOCO_CHECK_ENDPOINT = f"{MOCOCO_API_BASE}/check"
MOCOCO_USER_ENDPOINT = f"{MOCOCO_API_BASE}/user"

async def check_user_with_mococo(session, roblox_user_id):
    """Check a Roblox user using Mococo API for suspicious/condo associations"""
    try:
        # Try the user endpoint first
        url = f"{MOCOCO_USER_ENDPOINT}/{roblox_user_id}"
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'RobloxModerationBot/1.0'
        }
        
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data
            elif resp.status == 404:
                return {"flagged": False, "message": "User not in database"}
            else:
                print(f"Mococo API error: {resp.status}")
                return None
    except Exception as e:
        print(f"Error calling Mococo API: {e}")
        return None

async def get_user_badges_count(user_id):
    """Get the total badge count for a Roblox user."""
    try:
        all_badges = []
        cursor = ""
        
        while True:
            if cursor:
                badges_url = BADGES_API.format(user_id=user_id) + f"&cursor={cursor}"
            else:
                badges_url = BADGES_API.format(user_id=user_id)
            
            response = requests.get(badges_url)
            if response.status_code == 200:
                data = response.json()
                all_badges.extend(data.get("data", []))
                
                # Check if there are more badges to fetch
                cursor = data.get("nextPageCursor")
                if not cursor:
                    break
            else:
                print(f"Error fetching badges: {response.status_code}")
                return None
        
        return len(all_badges)
    except Exception as e:
        print(f"Error in get_user_badges_count: {e}")
        return None


async def get_user_info(user_id):
    """Get user information including creation date."""
    try:
        user_url = USER_INFO_API.format(user_id=user_id)
        response = requests.get(user_url)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching user info: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error in get_user_info: {e}")
        return None


async def check_account_age(user_data):
    """Check if the account is older than 1 month."""
    try:
        created_date = user_data.get("created")
        if not created_date:
            return False, "Could not determine account creation date"
        
        # Parse the creation date (format: "2023-01-01T00:00:00.000Z")
        created_datetime = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
        current_datetime = datetime.now(created_datetime.tzinfo)
        
        # Calculate the difference
        account_age = current_datetime - created_datetime
        
        # Check if the account is older than 1 month (30 days)
        if account_age.days >= 30:
            return True, f"Account is {account_age.days} days old"
        else:
            return False, f"Account is only {account_age.days} days old (minimum 30 days required)"
    except Exception as e:
        print(f"Error in check_account_age: {e}")
        return False, "Error checking account age"

group_name_cache = {}
user_group_cache = {}
tracking_channel_id = None
tracked_users = set()
is_tracking = False
rally_starter_id = None  # Track who started the rally

# User linking system
user_links = {}  # Discord user ID -> Roblox username

# Data persistence functions
def load_data():
    """Load data from JSON files"""
    global cuts_data, user_links
    try:
        if os.path.exists('cuts_data.json'):
            with open('cuts_data.json', 'r') as f:
                cuts_data = {int(k): v for k, v in json.load(f).items()}
        if os.path.exists('user_links.json'):
            with open('user_links.json', 'r') as f:
                user_links = {int(k): v for k, v in json.load(f).items()}
        print("✅ Loaded data from files")
    except Exception as e:
        print(f"⚠️ Error loading data: {e}")

def save_data():
    """Save data to JSON files"""
    try:
        with open('cuts_data.json', 'w') as f:
            json.dump(cuts_data, f, indent=2)
        with open('user_links.json', 'w') as f:
            json.dump(user_links, f, indent=2)
        print("💾 Data saved to files")
    except Exception as e:
        print(f"⚠️ Error saving data: {e}")

def check_whitelist(user_id: int) -> bool:
    return user_id in WHITELIST

def check_admin(user: discord.User) -> bool:
    """Check if user is the admin (wizardstrike1) or additional admin"""
    return user.name == ADMIN_USER or user.id in [528953104939483186, 713929689768656999]

def check_admin_or_whitelist(user: discord.User) -> bool:
    """Check if user is admin or on whitelist"""
    return check_admin(user) or check_whitelist(user.id)

def get_cuts(user_id: int) -> int:
    return cuts_data.get(user_id, DEFAULT_CUTS)

@tree.command(name="cut", description="Issue cuts (punishments) to a user")
@app_commands.describe(
    member="The Discord user to punish",
    amount="Number of cuts",
    reason="Reason for the punishment (optional)"
)
async def cut(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int = 1,
    reason: str | None = None  # <-- None is important!
):
    """Issue cuts to a member with an optional reason."""
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return

    if amount < 1:
        await interaction.response.send_message("❌ Amount must be at least 1.", ephemeral=True)
        return

    current_cuts = get_cuts(member.id)
    new_cuts = max(current_cuts - amount, 0)
    cuts_data[member.id] = new_cuts
    save_data()  # Save data after modification

    highest_role = member.top_role.name if member.top_role and member.top_role.name != "@everyone" else "No Role"

    reason = reason or "no reason added"

    message = (
        f"{member.mention}\n"
        f"Rank: {highest_role}\n"
        f"Reason: {reason}\n"
        f"Punishment: {amount} cuts\n"
        f"Cuts left: {new_cuts}"
    )

    await interaction.response.send_message(message)



@tree.command(name="set", description="Set the number of cuts a user has remaining")
@app_commands.describe(member="The Discord user", amount="Number of cuts to set")
async def set_cuts(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return

    cuts_data[member.id] = max(amount, 0)
    save_data()  # Save data after modification
    await interaction.response.send_message(
        f"✅ Set {member.mention}'s cuts to **{cuts_data[member.id]}**."
    )

@tree.command(name="cuts", description="Check how many cuts a user has remaining")
@app_commands.describe(member="The Discord user")
async def cuts(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    remaining = get_cuts(member.id)
    await interaction.response.send_message(
        f"🪓 {member.mention} has **{remaining}** cuts remaining."
    )

@tree.command(name="config", description="Configure auto-check settings (Admin only)")
@app_commands.describe(
    auto_check_channel="Channel for main verification results",
    privacy_channel="Channel for privacy issue notifications",
    enable_auto_check="Enable or disable automatic verification",
    verified_role="Role name to monitor for verification",
    flagged_role="Role name to assign to flagged users"
)
async def config(
    interaction: discord.Interaction,
    auto_check_channel: discord.TextChannel = None,
    privacy_channel: discord.TextChannel = None,
    enable_auto_check: bool = None,
    verified_role: str = None,
    flagged_role: str = None
):
    """Configure auto-check settings"""
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    
    global AUTO_CHECK_CHANNEL_ID, PRIVACY_ISSUE_CHANNEL_ID, ENABLE_AUTO_CHECK, AUTO_CHECK_ROLE_NAME, FLAGGED_ROLE_NAME
    
    changes = []
    
    # Update auto-check channel
    if auto_check_channel:
        AUTO_CHECK_CHANNEL_ID = auto_check_channel.id
        changes.append(f"Main verification channel: {auto_check_channel.mention}")
    
    # Update privacy issue channel
    if privacy_channel is not None:
        PRIVACY_ISSUE_CHANNEL_ID = privacy_channel.id
        changes.append(f"Privacy issue channel: {privacy_channel.mention}")
    
    # Update auto-check enable/disable
    if enable_auto_check is not None:
        ENABLE_AUTO_CHECK = enable_auto_check
        status = "enabled" if enable_auto_check else "disabled"
        changes.append(f"Auto-check: {status}")
    
    # Update role names
    if verified_role:
        AUTO_CHECK_ROLE_NAME = verified_role
        changes.append(f"Verified role: `{verified_role}`")
    
    if flagged_role:
        FLAGGED_ROLE_NAME = flagged_role
        changes.append(f"Flagged role: `{flagged_role}`")
    
    if not changes:
        # Show current settings
        embed = discord.Embed(
            title="🔧 Auto-Check Configuration",
            color=discord.Color.blue()
        )
        
        main_channel = bot.get_channel(AUTO_CHECK_CHANNEL_ID) if AUTO_CHECK_CHANNEL_ID else None
        privacy_channel_obj = bot.get_channel(PRIVACY_ISSUE_CHANNEL_ID) if PRIVACY_ISSUE_CHANNEL_ID else None
        
        embed.add_field(
            name="Channels",
            value=f"**Main:** {main_channel.mention if main_channel else 'Not set'}\n"
                  f"**Privacy Issues:** {privacy_channel_obj.mention if privacy_channel_obj else 'Same as main'}\n"
                  f"**Privacy Method:** Ephemeral messages (when possible), fallback to channel",
            inline=False
        )
        
        embed.add_field(
            name="Settings",
            value=f"**Auto-check:** {'✅ Enabled' if ENABLE_AUTO_CHECK else '❌ Disabled'}\n"
                  f"**Verified role:** `{AUTO_CHECK_ROLE_NAME}`\n"
                  f"**Flagged role:** `{FLAGGED_ROLE_NAME}`",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)
    else:
        # Show what was changed
        embed = discord.Embed(
            title="✅ Configuration Updated",
            description="The following settings have been changed:",
            color=discord.Color.green()
        )
        embed.add_field(name="Changes", value="\n".join(changes), inline=False)
        await interaction.response.send_message(embed=embed)



async def get_group_name(session, group_id):
    if group_id in group_name_cache:
        return group_name_cache[group_id]
    async with session.get(GROUP_INFO_API.format(group_id=group_id)) as resp:
        data = await resp.json()
        name = data.get("name", f"Group {group_id}")
        group_name_cache[group_id] = name
        return name

async def get_user_id(session, username):
    async with session.post(ROBLOX_API, json={"usernames": [username]}) as resp:
        data = await resp.json()
        if data.get("data"):
            return data["data"][0]["id"]
    return None

async def get_user_groups(session, user_id):
    if user_id in user_group_cache:
        return user_group_cache[user_id]
    async with session.get(GROUPS_API.format(user_id=user_id)) as resp:
        data = await resp.json()
        groups = [group["group"]["id"] for group in data.get("data", [])]
        user_group_cache[user_id] = groups
        return groups

async def get_usernames_from_ids(session, user_ids):
    """Get usernames from a list of user IDs using the Users API"""
    if not user_ids:
        return {}
    
    # Roblox Users API can handle up to 100 IDs at once
    user_id_to_username = {}
    
    for i in range(0, len(user_ids), 100):
        batch = user_ids[i:i+100]
        url = f"https://users.roblox.com/v1/users"
        async with session.post(url, json={"userIds": batch}) as resp:
            if resp.status == 200:
                data = await resp.json()
                for user in data.get("data", []):
                    user_id_to_username[user["id"]] = user.get("name", f"User_{user['id']}")
    
    return user_id_to_username

async def get_all_friends(session, user_id, max_friends=200):
    friends = []
    cursor = None
    while len(friends) < max_friends:
        url = f"{FRIENDS_API.format(user_id=user_id)}?limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        async with session.get(url) as resp:
            data = await resp.json()
            friends.extend(data.get("data", []))
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
    return friends[:max_friends]

async def check_friend_groups(session, friend_name, friend_id):
    try:
        friend_groups = await get_user_groups(session, friend_id)
        flagged_names = []
        for gid in friend_groups:
            if gid in FLAGGED_GROUP_IDS:
                name = await get_group_name(session, gid)
                flagged_names.append(name)
        if flagged_names:
            return f"❗ **Friend {friend_name}** is in flagged groups: {', '.join(flagged_names)}"
    except Exception as e:
        print(f"Error checking friend {friend_name} (ID: {friend_id}): {e}")
        return None

@tree.command(name="check", description="Check Roblox user and their friends for flagged groups")
@app_commands.describe(target="Roblox username to scan or Discord user with linked account")
async def check(interaction: discord.Interaction, target: str):
    await interaction.response.defer(thinking=True)
    
    # Determine if target is a Discord mention or Roblox username
    username = None
    if target.startswith('<@') and target.endswith('>'):
        # Extract Discord user ID from mention
        user_id_str = target.strip('<@!>')
        try:
            mentioned_user_id = int(user_id_str)
            if mentioned_user_id in user_links:
                username = user_links[mentioned_user_id]
                mentioned_user = interaction.guild.get_member(mentioned_user_id)
                display_name = mentioned_user.display_name if mentioned_user else f"User ID {mentioned_user_id}"
                await interaction.followup.send(f"🔗 Using linked account for {display_name}: `{username}`")
            else:
                await interaction.followup.send(f"❌ The mentioned user does not have a linked Roblox account.")
                return
        except ValueError:
            await interaction.followup.send(f"❌ Invalid Discord mention format.")
            return
    else:
        username = target
    
    async with aiohttp.ClientSession() as session:
        user_id = await get_user_id(session, username)
        if not user_id:
            await interaction.followup.send(f"❌ Could not find Roblox user `{username}`.")
            return

        # Check badge count requirement (at least 600 badges)
        badge_count = await get_user_badges_count(user_id)
        badge_warning = None
        if badge_count is None:
            badge_warning = f"⚠️ Could not fetch badge count for `{username}`."
        elif badge_count == 0:
            badge_warning = f"⚠️ `{username}` has badges set to private."
        elif badge_count < 600:
            badge_warning = f"⚠️ `{username}` only has **{badge_count}** badges (minimum 600 required)."
        
        # Check account age requirement (at least 1 month old)
        user_info = await get_user_info(user_id)
        age_warning = None
        if user_info is None:
            age_warning = f"⚠️ Could not fetch account information for `{username}`."
        else:
            age_valid, age_message = await check_account_age(user_info)
            if not age_valid:
                age_warning = f"⚠️ `{username}` account age validation failed: {age_message}"

        friends = await get_all_friends(session, user_id, max_friends=200)
        total_friends = len(friends)

        # Include validation status in the scanning message
        validation_info = ""
        if badge_count is not None:
            validation_info += f" (Badges: {badge_count})"
        if user_info is not None:
            age_valid, age_message = await check_account_age(user_info)
            validation_info += f" ({age_message})"
        
        # Send any warnings before starting the scan
        warnings = []
        if badge_warning:
            warnings.append(badge_warning)
        if age_warning:
            warnings.append(age_warning)
        
        if warnings:
            await interaction.followup.send("\n".join(warnings))
        
        # Optional: Quick Mococo check for main user
        mococo_result = await check_user_with_mococo(session, user_id)
        if mococo_result and mococo_result.get("flagged"):
            await interaction.followup.send(f"🚨 **Mococo Alert**: `{username}` flagged for suspicious content associations!")
        
        await interaction.followup.send(f"🔍 Scanning `{username}`{validation_info} and **{total_friends}** friends for flagged groups. This may take a moment...")

        # Get usernames for all friends
        friend_ids = [friend["id"] for friend in friends if friend["id"] != -1]  # Filter out invalid IDs
        id_to_username = await get_usernames_from_ids(session, friend_ids)

        flagged = []
        
        # Check main user groups (local flagged groups)
        user_groups = await get_user_groups(session, user_id)
        for gid in user_groups:
            if gid in FLAGGED_GROUP_IDS:
                name = await get_group_name(session, gid)
                flagged.append(f"⚠️ **{username}** is in flagged group: {name}")

        # Enhanced friend checking with both local groups AND Mococo API
        sem = asyncio.Semaphore(5)  # Reduced from 10 to respect Mococo API limits

        async def enhanced_friend_check(friend):
            async with sem:
                friend_id = friend["id"]
                if friend_id == -1:  # Skip invalid friend IDs
                    return None
                
                friend_name = id_to_username.get(friend_id, f"User_{friend_id}")
                results = []
                
                # Check local flagged groups
                local_result = await check_friend_groups(session, friend_name, friend_id)
                if local_result:
                    results.append(local_result)
                
                # Check with Mococo API
                mococo_friend_result = await check_user_with_mococo(session, friend_id)
                if mococo_friend_result and mococo_friend_result.get("flagged"):
                    results.append(f"🚨 **Friend {friend_name}** flagged by Mococo for suspicious content!")
                
                return results if results else None

        # Check friends with enhanced detection
        tasks = [enhanced_friend_check(friend) for friend in friends]
        results = await asyncio.gather(*tasks)

        # Flatten results and add to flagged list
        for result_set in results:
            if result_set:
                flagged.extend(result_set)

        if flagged:
            # Add summary header
            summary = f"🚨 **Found {len(flagged)} issues:**\n\n"
            message = summary + "\n".join(flagged)
            if len(message) > 1900:
                await interaction.followup.send(summary)
                chunks = [("\n".join(flagged))[i:i+1800] for i in range(0, len("\n".join(flagged)), 1800)]
                for chunk in chunks:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(message)
        else:
            await interaction.followup.send(f"✅ `{username}` and their friends are clean (checked local groups + Mococo database).")

@tree.command(name="deepcheck", description="Advanced check using Mococo API for suspicious content associations")
@app_commands.describe(target="Roblox username to scan or Discord user with linked account")
async def deepcheck(interaction: discord.Interaction, target: str):
    await interaction.response.defer(thinking=True)
    
    # Determine if target is a Discord mention or Roblox username
    username = None
    if target.startswith('<@') and target.endswith('>'):
        # Extract Discord user ID from mention
        user_id_str = target.strip('<@!>')
        try:
            mentioned_user_id = int(user_id_str)
            if mentioned_user_id in user_links:
                username = user_links[mentioned_user_id]
                mentioned_user = interaction.guild.get_member(mentioned_user_id)
                display_name = mentioned_user.display_name if mentioned_user else f"User ID {mentioned_user_id}"
                await interaction.followup.send(f"🔗 Using linked account for {display_name}: `{username}`")
            else:
                await interaction.followup.send(f"❌ The mentioned user does not have a linked Roblox account.")
                return
        except ValueError:
            await interaction.followup.send(f"❌ Invalid Discord mention format.")
            return
    else:
        username = target
    
    async with aiohttp.ClientSession() as session:
        user_id = await get_user_id(session, username)
        if not user_id:
            await interaction.followup.send(f"❌ Could not find Roblox user `{username}`.")
            return

        await interaction.followup.send(f"🔍 Running deep scan on `{username}` using Mococo API and local checks...")

        # Check with Mococo API
        mococo_result = await check_user_with_mococo(session, user_id)
        
        # Run standard checks
        badge_count = await get_user_badges_count(user_id)
        user_info = await get_user_info(user_id)
        friends = await get_all_friends(session, user_id, max_friends=200)
        user_groups = await get_user_groups(session, user_id)
        
        # Build comprehensive report
        report = [f"📊 **Deep Scan Report for `{username}`**\n"]
        
        # Mococo API results
        if mococo_result:
            if mococo_result.get("flagged"):
                report.append(f"🚨 **MOCOCO ALERT**: User flagged for suspicious content associations")
                if "reason" in mococo_result:
                    report.append(f"   Reason: {mococo_result['reason']}")
                if "confidence" in mococo_result:
                    report.append(f"   Confidence: {mococo_result['confidence']}%")
            else:
                report.append(f"✅ **Mococo Check**: Clean (no suspicious associations found)")
        else:
            report.append(f"⚠️ **Mococo Check**: API unavailable")
        
        # Badge and account checks
        if badge_count is not None:
            if badge_count == 0:
                report.append(f"🔒 **Badge Count**: Private ({badge_count} visible)")
            elif badge_count < 600:
                report.append(f"⚠️ **Badge Count**: {badge_count} (below recommended 600)")
            else:
                report.append(f"✅ **Badge Count**: {badge_count}")
        
        # Account age check
        if user_info:
            age_valid, age_message = await check_account_age(user_info)
            if age_valid:
                report.append(f"✅ **Account Age**: {age_message}")
            else:
                report.append(f"⚠️ **Account Age**: {age_message}")
        
        # Group checks (local flagged groups)
        flagged_groups = []
        for gid in user_groups:
            if gid in FLAGGED_GROUP_IDS:
                name = await get_group_name(session, gid)
                flagged_groups.append(name)
        
        if flagged_groups:
            report.append(f"🚨 **Flagged Groups**: {', '.join(flagged_groups)}")
        else:
            report.append(f"✅ **Local Group Check**: Clean")
        
        # Friend analysis summary
        report.append(f"📱 **Friends**: {len(friends)} total")
        
        # Check a sample of friends with Mococo
        if len(friends) > 0:
            await interaction.followup.send("🔄 Checking friends with Mococo API (this may take a moment)...")
            
            friend_ids = [friend["id"] for friend in friends[:20]]  # Check first 20 friends
            flagged_friends = []
            
            for friend_id in friend_ids:
                friend_result = await check_user_with_mococo(session, friend_id)
                if friend_result and friend_result.get("flagged"):
                    # Get friend username
                    id_to_username = await get_usernames_from_ids(session, [friend_id])
                    friend_name = id_to_username.get(friend_id, f"User_{friend_id}")
                    flagged_friends.append(friend_name)
            
            if flagged_friends:
                report.append(f"🚨 **Flagged Friends**: {', '.join(flagged_friends)}")
            else:
                report.append(f"✅ **Friend Sample Check**: Clean (checked {len(friend_ids)} friends)")
        
        # Send the complete report
        final_report = "\n".join(report)
        
        if len(final_report) > 1900:
            chunks = [final_report[i:i+1900] for i in range(0, len(final_report), 1900)]
            for chunk in chunks:
                await interaction.followup.send(chunk)
        else:
            await interaction.followup.send(final_report)

# Auto-check configuration
AUTO_CHECK_ROLE_NAME = "Bloxlink Verified"  # Change this to match your Bloxlink verification role
AUTO_CHECK_CHANNEL_ID = 1456399524775067648  # Set to a specific channel ID, or None to post in general channel
PRIVACY_ISSUE_CHANNEL_ID = None  # Channel for privacy issue messages, None to use AUTO_CHECK_CHANNEL_ID
ENABLE_AUTO_CHECK = True  # Set to False to disable auto-checking
FLAGGED_ROLE_NAME = "Flagged"  # Role given to users who fail verification standards
PERMS_ROLE_NAME = "perms"  # Role for administrators who can access flagged channels

async def auto_check_user(member, roblox_username, channel, test_mode=False, interaction=None):
    """Automatically run check command on a newly verified user"""
    try:
        print(f"🔄 Auto-checking {member.display_name} ({roblox_username})")
        
        async with aiohttp.ClientSession() as session:
            user_id = await get_user_id(session, roblox_username)
            if not user_id:
                await channel.send(f"⚠️ Auto-check failed: Could not find Roblox user `{roblox_username}` for {member.mention}")
                return

            # Run the same checks as the main /check command
            badge_count = await get_user_badges_count(user_id)
            user_info = await get_user_info(user_id)
            friends = await get_all_friends(session, user_id, max_friends=200)
            
            # Build validation info and track issues
            validation_info = ""
            verification_failed = False
            privacy_issues = []
            standard_issues = []
            
            # Badge check
            if badge_count is None:
                privacy_issues.append(f"⚠️ Could not fetch badge count for `{roblox_username}`")
            elif badge_count == 0:
                privacy_issues.append(f"⚠️ `{roblox_username}` has badges set to private")
            elif badge_count < 600:
                standard_issues.append(f"⚠️ `{roblox_username}` only has **{badge_count}** badges (minimum 600 required)")
                verification_failed = True
            
            if badge_count is not None:
                validation_info += f" (Badges: {badge_count})"
            
            # Age check
            if user_info is None:
                privacy_issues.append(f"⚠️ Could not fetch account information for `{roblox_username}`")
            else:
                age_valid, age_message = await check_account_age(user_info)
                validation_info += f" ({age_message})"
                if not age_valid:
                    standard_issues.append(f"⚠️ `{roblox_username}` account age validation failed: {age_message}")
                    verification_failed = True

            # Send initial message
            prefix = "🧪 **Test Mode** - " if test_mode else ""
            await channel.send(f"{prefix}🤖 **Auto-Check Triggered** for {member.mention}\n"
                             f"🔍 Scanning `{roblox_username}`{validation_info} and **{len(friends)}** friends...")
            
            # Quick Mococo check
            mococo_result = await check_user_with_mococo(session, user_id)
            if mococo_result and mococo_result.get("flagged"):
                await channel.send(f"🚨 **MOCOCO ALERT**: `{roblox_username}` flagged for suspicious content associations!")
                verification_failed = True
            
            # Get friend usernames
            friend_ids = [friend["id"] for friend in friends if friend["id"] != -1]
            id_to_username = await get_usernames_from_ids(session, friend_ids)

            flagged_content = []
            
            # Check main user groups
            user_groups = await get_user_groups(session, user_id)
            for gid in user_groups:
                if gid in FLAGGED_GROUP_IDS:
                    name = await get_group_name(session, gid)
                    flagged_content.append(f"⚠️ **{roblox_username}** is in flagged group: {name}")
                    verification_failed = True

            # Enhanced friend checking
            sem = asyncio.Semaphore(3)  # Lower limit for auto-checks to be more gentle

            async def enhanced_friend_check(friend):
                async with sem:
                    friend_id = friend["id"]
                    if friend_id == -1:
                        return None
                    
                    friend_name = id_to_username.get(friend_id, f"User_{friend_id}")
                    results = []
                    
                    # Check local flagged groups
                    local_result = await check_friend_groups(session, friend_name, friend_id)
                    if local_result:
                        results.append(local_result)
                    
                    # Check with Mococo API
                    mococo_friend_result = await check_user_with_mococo(session, friend_id)
                    if mococo_friend_result and mococo_friend_result.get("flagged"):
                        results.append(f"🚨 **Friend {friend_name}** flagged by Mococo for suspicious content!")
                    
                    return results if results else None

            # Check friends
            tasks = [enhanced_friend_check(friend) for friend in friends]
            results = await asyncio.gather(*tasks)

            # Collect flagged friend results
            for result_set in results:
                if result_set:
                    flagged_content.extend(result_set)
                    verification_failed = True

            # Determine verification outcome and assign roles
            if privacy_issues and not test_mode:
                # Privacy issues - don't assign any role, prompt to make info public
                # Use privacy issue channel if configured, otherwise use main channel
                privacy_channel = None
                if PRIVACY_ISSUE_CHANNEL_ID:
                    privacy_channel = bot.get_channel(PRIVACY_ISSUE_CHANNEL_ID)
                
                if not privacy_channel:
                    privacy_channel = channel
                
                privacy_message = (
                    f"🔒 **Privacy Issue Detected** for {member.mention}\n\n"
                    f"The following information needs to be made public:\n" + 
                    "\n".join(privacy_issues) + 
                    f"\n\n📋 **Next Steps:**\n"
                    f"1. Make your Roblox profile information public (badges, games, etc.)\n"
                    f"2. Press the **Bloxlink verify button** to verify again\n"
                    f"3. Contact staff if you need help with privacy settings"
                )
                
                # Try to send as ephemeral if we have an interaction, otherwise use channel
                if interaction:
                    try:
                        await interaction.followup.send(privacy_message, ephemeral=True)
                    except Exception as e:
                        print(f"Failed to send ephemeral message: {e}")
                        await privacy_channel.send(privacy_message)
                else:
                    await privacy_channel.send(privacy_message)
                    
            elif verification_failed and not test_mode:
                # Failed verification - remove verified role, assign Flagged role and create private channel
                role_actions = []
                
                try:
                    # Remove the verified role
                    verified_role = discord.utils.get(member.guild.roles, name=AUTO_CHECK_ROLE_NAME)
                    if verified_role and verified_role in member.roles:
                        await member.remove_roles(verified_role, reason="Auto-verification failed")
                        role_actions.append(f"🔻 Removed **{AUTO_CHECK_ROLE_NAME}** role")
                    
                    # Add the flagged role
                    flagged_role = discord.utils.get(member.guild.roles, name=FLAGGED_ROLE_NAME)
                    if flagged_role:
                        await member.add_roles(flagged_role, reason="Auto-verification failed")
                        role_actions.append(f"🔺 Assigned **{FLAGGED_ROLE_NAME}** role")
                        
                        # Create private channel for the flagged user
                        flagged_channel = await create_flagged_channel(member, standard_issues + flagged_content)
                        if flagged_channel:
                            role_actions.append(f"📨 Created appeal channel {flagged_channel.mention}")
                        else:
                            role_actions.append("⚠️ Failed to create appeal channel")
                    else:
                        role_actions.append(f"⚠️ **{FLAGGED_ROLE_NAME}** role not found in server")
                        
                except Exception as e:
                    role_actions.append(f"❌ Failed to update roles: {str(e)}")
                
                # Send detailed failure report
                all_issues = standard_issues + flagged_content
                role_status = "\n".join(role_actions)
                summary = f"❌ **Verification FAILED** for {member.mention}\n{role_status}\n\n"
                summary += f"**Issues Found ({len(all_issues)}):**\n" + "\n".join(all_issues)
                
                if len(summary) > 1900:
                    await channel.send(f"❌ **Verification FAILED** for {member.mention}\n{role_status}")
                    chunks = [all_issues[i:i+10] for i in range(0, len(all_issues), 10)]
                    for i, chunk in enumerate(chunks):
                        await channel.send(f"**Issues ({i+1}/{len(chunks)}):**\n" + "\n".join(chunk))
                else:
                    await channel.send(summary)
            else:
                # Passed verification - user keeps their verified role
                await channel.send(f"✅ **Verification PASSED** for {member.mention}\n"
                                 f"`{roblox_username}` and their friends meet all requirements!")
                
    except Exception as e:
        print(f"❌ Error in auto_check_user: {e}")
        await channel.send(f"⚠️ Auto-check failed for {member.mention}: {str(e)}")

async def create_flagged_channel(member, flagged_issues):
    """Create a private channel for a flagged user to discuss with administrators"""
    try:
        guild = member.guild
        
        # Get the perms role
        perms_role = discord.utils.get(guild.roles, name=PERMS_ROLE_NAME)
        if not perms_role:
            print(f"⚠️ '{PERMS_ROLE_NAME}' role not found in server")
            return None
        
        # Find a unique channel name
        channel_number = 1
        while True:
            channel_name = f"flagged-{channel_number}"
            existing_channel = discord.utils.get(guild.channels, name=channel_name)
            if not existing_channel:
                break
            channel_number += 1
        
        # Create channel with specific permissions
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),  # @everyone cannot see
            member: discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                read_message_history=True,
                attach_files=True
            ),  # Flagged user can read/write
            perms_role: discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                read_message_history=True,
                manage_messages=True,
                attach_files=True
            ),  # Perms role can read/write/manage
            guild.me: discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                manage_messages=True
            )  # Bot can read/write/manage
        }
        
        # Create the channel
        category = None
        # Try to find the "check thingy" category first, then fallback to others
        for cat in guild.categories:
            if cat.name.lower() == "check thingy":
                category = cat
                break
        
        # If "check thingy" not found, try other common categories
        if not category:
            for cat in guild.categories:
                if cat.name.lower() in ['flagged', 'support', 'tickets', 'appeals']:
                    category = cat
                    break
        
        channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            category=category,
            topic=f"Appeal channel for {member.display_name} - Account flagged for verification issues"
        )
        
        # Send initial message
        embed = discord.Embed(
            title="🚨 Account Flagged",
            description=f"Hello {member.mention}, your account has been flagged as suspicious during our verification process.",
            color=discord.Color.red()
        )
        
        embed.add_field(
            name="Why was I flagged?",
            value="Your Roblox account or associated friends failed our security checks. This could be due to:\n"
                  "• Association with flagged groups or users\n"
                  "• Suspicious content detection\n"
                  "• Other security concerns",
            inline=False
        )
        
        embed.add_field(
            name="What happens next?",
            value=f"• Please wait for a member with the {perms_role.mention} role to review your case\n"
                  "• You can explain your situation in this channel\n"
                  "• An administrator will manually verify your account\n"
                  "• This channel will be deleted once resolved",
            inline=False
        )
        
        embed.add_field(
            name="Issues Found:",
            value=f"```{chr(10).join(flagged_issues[:5])}```" if flagged_issues else "See verification channel for details",
            inline=False
        )
        
        embed.set_footer(text="Please be patient while we review your account. Do not create additional tickets.")
        
        await channel.send(embed=embed)
        
        # Ping perms role (but delete the ping after a few seconds to reduce spam)
        ping_message = await channel.send(f"📢 {perms_role.mention} - New flagged user needs review")
        
        # Delete the ping after 10 seconds to keep channel clean
        await asyncio.sleep(10)
        try:
            await ping_message.delete()
        except:
            pass  # Ignore if already deleted
        
        print(f"✅ Created flagged channel: #{channel_name} for {member.display_name}")
        return channel
        
    except Exception as e:
        print(f"❌ Error creating flagged channel for {member.display_name}: {e}")
        return None

@bot.event
async def on_voice_state_update(member, before, after):
    global tracking_channel_id, tracked_users, is_tracking, rally_starter_id
    
    # Add new users who join the tracked channel
    if is_tracking and after.channel and after.channel.id == tracking_channel_id:
        tracked_users.add(member.display_name)
    
    # Auto-end rally if the starter leaves the voice channel
    if (is_tracking and rally_starter_id and member.id == rally_starter_id and 
        (not after.channel or after.channel.id != tracking_channel_id)):
        
        # End the rally automatically
        is_tracking = False
        channel_name = discord.utils.get(member.guild.voice_channels, id=tracking_channel_id).name if tracking_channel_id else "Unknown Channel"
        
        # Find a general channel to send the message
        general_channel = None
        for channel in member.guild.text_channels:
            if channel.name.lower() in ['general', 'chat', 'main']:
                general_channel = channel
                break
        
        if not general_channel:
            general_channel = member.guild.text_channels[0]  # Use first available text channel 
        
        if general_channel:
            if tracked_users:
                user_list = "\n".join(f"- {user}" for user in tracked_users)
                await general_channel.send(
                    f"📊 Rally in **{channel_name}** automatically ended because {member.display_name} left the voice channel.\nUsers who joined:\n{user_list}"
                )
            else:
                await general_channel.send(f"📊 Rally in **{channel_name}** automatically ended. No users joined during the rally.")
        
        tracking_channel_id = None
        rally_starter_id = None

@tree.command(name="whitelist", description="Add a user to the whitelist (Admin only)")
@app_commands.describe(user="The Discord user to add to whitelist")
async def whitelist(interaction: discord.Interaction, user: discord.Member):
    if not check_admin(interaction.user):
        await interaction.response.send_message("❌ Only wizardstrike1 can use this command.", ephemeral=True)
        return
    
    if user.id in WHITELIST:
        await interaction.response.send_message(f"⚠️ {user.mention} is already whitelisted.", ephemeral=True)
        return
    
    WHITELIST.append(user.id)
    await interaction.response.send_message(f"✅ Added {user.mention} to the whitelist.")

@tree.command(name="removewhitelist", description="Remove a user from the whitelist (Admin only)")
@app_commands.describe(user="The Discord user to remove from whitelist")
async def removewhitelist(interaction: discord.Interaction, user: discord.Member):
    if not check_admin(interaction.user):
        await interaction.response.send_message("❌ Only wizardstrike1 can use this command.", ephemeral=True)
        return
    
    if user.id not in WHITELIST:
        await interaction.response.send_message(f"⚠️ {user.mention} is not whitelisted.", ephemeral=True)
        return
    
    WHITELIST.remove(user.id)
    await interaction.response.send_message(f"✅ Removed {user.mention} from the whitelist.")

@tree.command(name="addgroup", description="Add a group to the flagged groups list (Whitelist required)")
@app_commands.describe(group_id="The Roblox group ID to add to the blacklist")
async def addgroup(interaction: discord.Interaction, group_id: int):
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    
    if group_id in FLAGGED_GROUP_IDS:
        await interaction.response.send_message(f"⚠️ Group ID `{group_id}` is already in the flagged groups list.", ephemeral=True)
        return
    
    # Verify the group exists by trying to get its name
    async with aiohttp.ClientSession() as session:
        try:
            group_name = await get_group_name(session, group_id)
            FLAGGED_GROUP_IDS.append(group_id)
            await interaction.response.send_message(f"✅ Added group **{group_name}** (ID: `{group_id}`) to the flagged groups list.")
        except Exception:
            await interaction.response.send_message(f"❌ Could not find a group with ID `{group_id}`. Please verify the group ID is correct.", ephemeral=True)

@tree.command(name="removegroup", description="Remove a group from the flagged groups list (Whitelist required)")
@app_commands.describe(group_id="The Roblox group ID to remove from the blacklist")
async def removegroup(interaction: discord.Interaction, group_id: int):
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    
    if group_id not in FLAGGED_GROUP_IDS:
        await interaction.response.send_message(f"⚠️ Group ID `{group_id}` is not in the flagged groups list.", ephemeral=True)
        return
    
    # Get group name for confirmation message
    async with aiohttp.ClientSession() as session:
        try:
            group_name = await get_group_name(session, group_id)
            FLAGGED_GROUP_IDS.remove(group_id)
            await interaction.response.send_message(f"✅ Removed group **{group_name}** (ID: `{group_id}`) from the flagged groups list.")
        except Exception:
            # Remove anyway if we can't get the name
            FLAGGED_GROUP_IDS.remove(group_id)
            await interaction.response.send_message(f"✅ Removed group ID `{group_id}` from the flagged groups list.")

@tree.command(name="listgroups", description="List all flagged groups (Whitelist required)")
async def listgroups(interaction: discord.Interaction):
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    
    await interaction.response.defer(thinking=True)
    
    if not FLAGGED_GROUP_IDS:
        await interaction.followup.send("📋 No groups are currently flagged.")
        return
    
    async with aiohttp.ClientSession() as session:
        group_list = []
        for group_id in FLAGGED_GROUP_IDS[:20]:  # Limit to first 20 to avoid message length issues
            try:
                group_name = await get_group_name(session, group_id)
                group_list.append(f"• **{group_name}** (ID: `{group_id}`)")
            except Exception:
                group_list.append(f"• Group ID: `{group_id}` (Name unavailable)")
    
    total_groups = len(FLAGGED_GROUP_IDS)
    message = f"📋 **Flagged Groups** ({total_groups} total):\n\n" + "\n".join(group_list)
    
    if total_groups > 20:
        message += f"\n\n*Showing first 20 of {total_groups} groups*"
    
    await interaction.followup.send(message)

@tree.command(name="mocostatus", description="Check Mococo API status and information")
async def mocostatus(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    
    async with aiohttp.ClientSession() as session:
        try:
            # Test API connectivity
            url = f"{MOCOCO_API_BASE}/status"  # Assuming there's a status endpoint
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    status = "🟢 Online"
                else:
                    status = f"🟡 Issues (Status: {resp.status})"
        except:
            # Try with a test user ID if status endpoint doesn't exist
            try:
                url = f"{MOCOCO_USER_ENDPOINT}/1"  # Test with Roblox user ID 1
                async with session.get(url, timeout=5) as resp:
                    status = "🟢 Online" if resp.status in [200, 404] else f"🟡 Issues (Status: {resp.status})"
            except:
                status = "🔴 Offline"
    
    embed = discord.Embed(
        title="🤖 Mococo API Status",
        description="Integration status with Mococo API for enhanced suspicious content detection",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="API Status", value=status, inline=True)
    embed.add_field(name="Base URL", value=MOCOCO_API_BASE, inline=True)
    embed.add_field(name="Purpose", value="Detects suspicious/condo content associations", inline=False)
    embed.add_field(name="Commands Using Mococo", value="• `/deepcheck` - Full scan with Mococo\n• `/check` - Quick Mococo alert", inline=False)
    
    embed.set_footer(text="Mococo API helps identify users associated with inappropriate Roblox content")
    
    await interaction.followup.send(embed=embed)

@tree.command(name="autoconfig", description="Configure automatic Bloxlink verification checking (Admin only)")
@app_commands.describe(
    enable="Enable or disable auto-checking (true/false)",
    role_name="Name of the verification role to monitor",
    channel="Channel to post auto-check results (optional)"
)
async def autoconfig(
    interaction: discord.Interaction, 
    enable: bool = None,
    role_name: str = None,
    channel: discord.TextChannel = None
):
    if not check_admin(interaction.user):
        await interaction.response.send_message("❌ Only admins can configure auto-check settings.", ephemeral=True)
        return
    
    global ENABLE_AUTO_CHECK, AUTO_CHECK_ROLE_NAME, AUTO_CHECK_CHANNEL_ID
    
    # Update settings if provided
    if enable is not None:
        ENABLE_AUTO_CHECK = enable
    
    if role_name is not None:
        AUTO_CHECK_ROLE_NAME = role_name
    
    if channel is not None:
        AUTO_CHECK_CHANNEL_ID = channel.id
    
    # Show current settings
    status_emoji = "🟢" if ENABLE_AUTO_CHECK else "🔴"
    status_text = "Enabled" if ENABLE_AUTO_CHECK else "Disabled"
    
    channel_name = "Not set (uses general channel)" 
    if AUTO_CHECK_CHANNEL_ID:
        target_channel = bot.get_channel(AUTO_CHECK_CHANNEL_ID)
        channel_name = target_channel.name if target_channel else f"Channel ID: {AUTO_CHECK_CHANNEL_ID}"
    
    embed = discord.Embed(
        title="🤖 Auto-Check Configuration",
        description="Automatically checks users when they get verified by Bloxlink",
        color=discord.Color.green() if ENABLE_AUTO_CHECK else discord.Color.red()
    )
    
    embed.add_field(name="Status", value=f"{status_emoji} {status_text}", inline=True)
    embed.add_field(name="Role to Monitor", value=f"`{AUTO_CHECK_ROLE_NAME}`", inline=True)
    embed.add_field(name="Flagged Role", value=f"`{FLAGGED_ROLE_NAME}`", inline=True)
    embed.add_field(name="Perms Role", value=f"`{PERMS_ROLE_NAME}`", inline=True)
    embed.add_field(name="Results Channel", value=channel_name, inline=False)
    embed.add_field(
        name="How it works", 
        value="• Monitors for users getting the verification role\n"
              "• Uses their nickname as Roblox username\n"
              "• Runs full check (local groups + Mococo API)\n"
              "• **PASS**: User keeps verified role\n"
              "• **FAIL**: User gets flagged role + private appeal channel\n"
              "• **PRIVATE**: No role, prompted to make profile public",
        inline=False
    )
    
    # Show example usage
    if enable is None and role_name is None and channel is None:
        embed.add_field(
            name="Example Usage",
            value="`/autoconfig enable:True role_name:Verified channel:#verification-logs`",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    """Bot startup event"""
    print(f'✅ Bot logged in as {bot.user}')
    print(f'📊 Bot is in {len(bot.guilds)} guilds')
    
    # List all registered commands
    commands = tree.get_commands()
    print(f"🔧 Registered commands ({len(commands)}):")
    for cmd in commands:
        print(f"  • /{cmd.name} - {cmd.description}")
    
    # Try to sync commands automatically
    try:
        # Clear any existing commands first, then sync
        tree.clear_commands(guild=discord.Object(id=GUILD_ID))
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"🔄 Auto-synced {len(synced)} commands to guild {GUILD_ID}")
        if len(synced) == 0:
            print("⚠️ No commands were synced! This might be a permissions issue.")
            print("   Make sure the bot has 'Use Application Commands' permission in the server.")
    except Exception as e:
        print(f"❌ Auto-sync failed: {e}")
        print("Use /sync command manually or check bot permissions")

@tree.command(name="sync", description="Sync slash commands (Admin only)")
async def sync(interaction: discord.Interaction):
    """Manually sync slash commands to the guild"""
    if not check_admin(interaction.user):
        await interaction.response.send_message("❌ Only admins can sync commands.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Clear existing commands first
        tree.clear_commands(guild=discord.Object(id=GUILD_ID))
        
        # Sync commands
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        
        if len(synced) > 0:
            await interaction.followup.send(f"✅ Synced {len(synced)} commands to this guild.\nCommands: {', '.join([cmd.name for cmd in synced])}", ephemeral=True)
            print(f"Manual sync successful: {[cmd.name for cmd in synced]}")
        else:
            await interaction.followup.send("⚠️ No commands were synced. Check bot permissions:\n• Use Application Commands\n• Send Messages\n• Embed Links", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync commands: {str(e)}", ephemeral=True)
        print(f"Sync error: {e}")
        traceback.print_exc()

@tree.command(name="testcheck", description="🧪 Test the auto-check system on yourself")
async def testcheck(interaction: discord.Interaction):
    """Test the auto-check system by simulating a role addition"""
    
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ You need `Manage Roles` permission to use this command.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Get the user's current state
    member = interaction.user
    roblox_username = member.nick if member.nick else member.display_name
    
    # Skip if username looks like a Discord username
    if '#' in roblox_username:
        await interaction.followup.send(f"❌ Your nickname `{roblox_username}` doesn't look like a Roblox username. Please set your nickname to your Roblox username first.")
        return
    
    # Find target channel
    target_channel = None
    if AUTO_CHECK_CHANNEL_ID:
        target_channel = bot.get_channel(AUTO_CHECK_CHANNEL_ID)
    
    if not target_channel:
        target_channel = interaction.channel
    
    embed = discord.Embed(
        title="🧪 Testing Auto-Check System",
        description=f"Testing auto-check for: **{roblox_username}**",
        color=discord.Color.blue()
    )
    embed.add_field(name="Target Channel", value=target_channel.mention, inline=True)
    embed.add_field(name="Auto-Check Enabled", value="✅ Yes" if ENABLE_AUTO_CHECK else "❌ No", inline=True)
    embed.add_field(name="Monitoring Role", value=f"`{AUTO_CHECK_ROLE_NAME}`", inline=True)
    
    await interaction.followup.send(embed=embed)
    
    # Run the auto-check
    try:
        await auto_check_user(member, roblox_username, target_channel, test_mode=True, interaction=interaction)
        success_embed = discord.Embed(
            title="✅ Test Complete",
            description="Auto-check test completed successfully!",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=success_embed, ephemeral=True)
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Test Failed",
            description=f"Auto-check test failed: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)
        print(f"❌ Test auto-check failed: {e}")
        traceback.print_exc()

@tree.command(name="debugroles", description="🔧 Debug role information for testing auto-check")
async def debugroles(interaction: discord.Interaction, user: discord.Member = None):
    """Debug role information to help troubleshoot auto-check"""
    
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ You need `Manage Roles` permission to use this command.", ephemeral=True)
        return
    
    target = user if user else interaction.user
    
    embed = discord.Embed(
        title="🔧 Role Debug Information",
        description=f"Debugging info for {target.mention}",
        color=discord.Color.orange()
    )
    
    # Basic info
    embed.add_field(
        name="Basic Info",
        value=f"**Username:** {target.name}\n**Display Name:** {target.display_name}\n**Nickname:** {target.nick if target.nick else 'None'}",
        inline=False
    )
    
    # Auto-check settings
    embed.add_field(
        name="Auto-Check Settings",
        value=f"**Enabled:** {'✅' if ENABLE_AUTO_CHECK else '❌'}\n"
              f"**Monitoring Role:** `{AUTO_CHECK_ROLE_NAME}`\n"
              f"**Flagged Role:** `{FLAGGED_ROLE_NAME}`\n"
              f"**Main Channel ID:** {AUTO_CHECK_CHANNEL_ID if AUTO_CHECK_CHANNEL_ID else 'Not set'}\n"
              f"**Privacy Channel ID:** {PRIVACY_ISSUE_CHANNEL_ID if PRIVACY_ISSUE_CHANNEL_ID else 'Same as main'}",
        inline=False
    )
    
    # Role information
    role_names = [role.name for role in target.roles if role.name != "@everyone"]
    has_target_role = AUTO_CHECK_ROLE_NAME in role_names
    
    embed.add_field(
        name=f"Roles ({len(role_names)})",
        value=f"**Has '{AUTO_CHECK_ROLE_NAME}' role:** {'✅' if has_target_role else '❌'}\n"
              f"**All roles:** {', '.join(role_names) if role_names else 'None (only @everyone)'}",
        inline=False
    )
    
    # Channel info
    target_channel = None
    if AUTO_CHECK_CHANNEL_ID:
        target_channel = bot.get_channel(AUTO_CHECK_CHANNEL_ID)
    
    channel_info = "Not found" if AUTO_CHECK_CHANNEL_ID and not target_channel else target_channel.name if target_channel else "Using current channel"
    
    embed.add_field(
        name="Target Channel",
        value=f"**Channel:** {channel_info}\n**Can send messages:** {'✅' if target_channel and target_channel.permissions_for(interaction.guild.me).send_messages else '❌' if target_channel else '?'}",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# CHANGELOG for Privacy Issue and Verification Updates:
# 1. Added PRIVACY_ISSUE_CHANNEL_ID configuration variable
# 2. Updated auto_check_user function to accept interaction parameter for ephemeral messages
# 3. Privacy issue messages now try ephemeral first, then fallback to channel
# 4. Added /config command to set privacy issue channel
# 5. Added /privacy_reset command to reset privacy channel to main
# 6. Updated verify command to pass interaction for ephemeral messaging
# 7. Verification failures now remove verified role before adding flagged role
# 8. Updated privacy message text to mention "Bloxlink verify button" instead of /verify command
# 9. Config display now shows ephemeral messaging capability

# Load data at startup
load_data()

# Save data on exit
import atexit
atexit.register(save_data)

@tree.command(name="verify", description="Manually verify your Roblox account after making profile public")
async def verify(interaction: discord.Interaction):
    """Manual verification command for users who need to re-verify after privacy changes"""
    
    # Get user's Roblox username from their nickname
    member = interaction.user
    roblox_username = member.nick if member.nick else member.display_name
    
    # Skip if username looks like a Discord username
    if '#' in roblox_username:
        await interaction.response.send_message(
            f"❌ Your nickname `{roblox_username}` doesn't look like a Roblox username.\n"
            f"Please set your server nickname to your Roblox username and try again.",
            ephemeral=True
        )
        return
    
    await interaction.response.defer()
    
    # Find target channel for results
    target_channel = None
    if AUTO_CHECK_CHANNEL_ID:
        target_channel = bot.get_channel(AUTO_CHECK_CHANNEL_ID)
    
    if not target_channel:
        target_channel = interaction.channel
    
    # Notify that verification is starting
    await interaction.followup.send(f"🔄 **Manual Verification Started**\nRunning verification for `{roblox_username}`...", ephemeral=True)
    
    # Run the auto-check function
    try:
        await auto_check_user(member, roblox_username, target_channel, test_mode=False, interaction=interaction)
        
        success_embed = discord.Embed(
            title="✅ Verification Complete",
            description=f"Manual verification completed for `{roblox_username}`. Check {target_channel.mention} for results.",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=success_embed, ephemeral=True)
        
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Verification Failed",
            description=f"Manual verification failed: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)
        print(f"❌ Manual verification failed: {e}")

@tree.command(name="createappeal", description="Create an appeal channel for a flagged user (Admin only)")
@app_commands.describe(user="The flagged user to create an appeal channel for")
async def createappeal(interaction: discord.Interaction, user: discord.Member):
    """Manually create an appeal channel for a flagged user"""
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    
    # Check if user has the flagged role
    flagged_role = discord.utils.get(interaction.guild.roles, name=FLAGGED_ROLE_NAME)
    if not flagged_role or flagged_role not in user.roles:
        await interaction.response.send_message(f"❌ {user.mention} does not have the {FLAGGED_ROLE_NAME} role.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Create the appeal channel
    channel = await create_flagged_channel(user, ["Manual appeal channel created by staff"])
    
    if channel:
        await interaction.followup.send(f"✅ Created appeal channel {channel.mention} for {user.mention}")
    else:
        await interaction.followup.send(f"❌ Failed to create appeal channel for {user.mention}")

@tree.command(name="closeappeal", description="Close and delete an appeal channel (Admin only)")
@app_commands.describe(
    reason="Reason for closing the appeal (optional)",
    resolved="Whether the appeal was resolved positively (true/false)"
)
async def closeappeal(interaction: discord.Interaction, reason: str = "No reason provided", resolved: bool = True):
    """Close and delete the current appeal channel"""
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    
    # Check if this is a flagged channel
    channel = interaction.channel
    if not channel.name.startswith("flagged-"):
        await interaction.response.send_message("❌ This command can only be used in flagged appeal channels.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    # Find the flagged user from channel permissions
    flagged_user = None
    for member in interaction.guild.members:
        perms = channel.permissions_for(member)
        if (perms.read_messages and perms.send_messages and 
            not member.bot and member != interaction.guild.me):
            # Check if they have the flagged role
            flagged_role = discord.utils.get(interaction.guild.roles, name=FLAGGED_ROLE_NAME)
            if flagged_role and flagged_role in member.roles:
                flagged_user = member
                break
    
    # Send closure message
    status = "✅ RESOLVED" if resolved else "❌ DENIED"
    embed = discord.Embed(
        title=f"Appeal {status}",
        description=f"This appeal has been {status.lower()} by {interaction.user.mention}",
        color=discord.Color.green() if resolved else discord.Color.red()
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Closed by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Date", value=f"<t:{int(datetime.now().timestamp())}:F>", inline=True)
    
    if flagged_user:
        embed.add_field(name="User", value=flagged_user.mention, inline=True)
        
        # If resolved, remove the flagged role
        if resolved:
            try:
                flagged_role = discord.utils.get(interaction.guild.roles, name=FLAGGED_ROLE_NAME)
                if flagged_role:
                    await flagged_user.remove_roles(flagged_role, reason=f"Appeal resolved by {interaction.user}")
                    embed.add_field(name="Action", value=f"Removed {FLAGGED_ROLE_NAME} role", inline=False)
            except Exception as e:
                embed.add_field(name="Warning", value=f"Failed to remove role: {str(e)}", inline=False)
    
    await channel.send(embed=embed)
    
    await interaction.followup.send(f"Appeal channel will be deleted in 30 seconds...")
    
    # Wait 30 seconds then delete the channel
    await asyncio.sleep(30)
    try:
        await channel.delete(reason=f"Appeal closed by {interaction.user}")
    except:
        pass  # Channel might already be deleted

@tree.command(name="privacy_reset", description="Reset privacy channel to use main verification channel (Admin only)")
async def privacy_reset(interaction: discord.Interaction):
    """Reset privacy issue channel to use the same as main verification channel"""
    if not check_admin_or_whitelist(interaction.user):
        await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
        return
    
    global PRIVACY_ISSUE_CHANNEL_ID
    PRIVACY_ISSUE_CHANNEL_ID = None
    
    embed = discord.Embed(
        title="✅ Privacy Channel Reset",
        description="Privacy issue messages will now use the main verification channel.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_member_update(before, after):
    """Detect when a user gets the verification role and auto-check them"""
    if not ENABLE_AUTO_CHECK:
        return
    
    # Check if the user gained the verification role
    before_role_names = {role.name for role in before.roles}
    after_role_names = {role.name for role in after.roles}
    
    # If user gained the verification role
    if AUTO_CHECK_ROLE_NAME not in before_role_names and AUTO_CHECK_ROLE_NAME in after_role_names:
        print(f"🔄 Auto-check triggered: {after.display_name} gained {AUTO_CHECK_ROLE_NAME} role")
        
        # Get Roblox username from their nickname
        roblox_username = after.nick if after.nick else after.display_name
        
        # Skip if username looks like a Discord username
        if '#' in roblox_username:
            print(f"⚠️ Skipping auto-check for {after.display_name}: nickname looks like Discord username")
            return
        
        # Find target channel
        target_channel = None
        if AUTO_CHECK_CHANNEL_ID:
            target_channel = bot.get_channel(AUTO_CHECK_CHANNEL_ID)
        
        # Fallback to a general channel if no specific channel is set
        if not target_channel:
            for channel in after.guild.text_channels:
                if channel.name.lower() in ['general', 'chat', 'main', 'verification']:
                    target_channel = channel
                    break
            
            # If still no channel found, use the first available text channel
            if not target_channel and after.guild.text_channels:
                target_channel = after.guild.text_channels[0]
        
        if target_channel:
            try:
                await auto_check_user(after, roblox_username, target_channel, test_mode=False)
            except Exception as e:
                print(f"❌ Auto-check failed for {after.display_name}: {e}")
                try:
                    await target_channel.send(f"⚠️ Auto-check failed for {after.mention}: {str(e)}")
                except:
                    pass  # If we can't send the error message, just log it
        else:
            print(f"❌ No suitable channel found for auto-check of {after.display_name}")


bot.run(TOKEN)
