import os
import sys
import re
import json
import random
import asyncio
import aiohttp
import aiofiles
import pendulum
from telethon import TelegramClient, events, errors, functions, types
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty, Channel, Chat, User

class XAXABotManager:
    def __init__(self):
        self.api_id = None
        self.api_hash = None
        self.phone_number = None
        self.client = None
        self.running = False
        self.tasks = []

        # Configuration
        self.config = {
            'spam_enabled': 'on',
            'spam_delay_between_iterations': 60,
            'spam_delay_between_messages': 5,
            'welcome_enabled': 'on',
            'reply_enabled': 'on',
            'check_spambot': 'on',
            'check_spambot_delay': 21600,
            'hide_phone_number': 'on',
            'discord_enabled': 'on',
            'discord_webhook_url': '',
            'telegram_log_enabled': 'on',
            'telegram_log_user': 'marlboro_pln',
            'aggressive_mode': 'off'
        }

        # Collections
        self.target_groups = set()
        self.sent_messages = set()
        self.banned_groups = set()
        self.reply_messages = []  # Will store (chat_id, message_id) tuples
        self.welcome_messages = []  # Will store (chat_id, message_id) tuples

        # Spam message
        self.spam_message = None  # Will store (chat_id, message_id) tuple

        # Command handlers
        self.main_commands = {
            '.start': self.cmd_start,
            '.stop': self.cmd_stop,
            '.config': self.cmd_config,
            '.xaxa': self.cmd_xaxa,
            '.help': self.cmd_help
        }

        self.config_commands = {
            '.setmsg': self.cmd_setmsg,
            '.setreply': self.cmd_setreply,
            '.setwelcome': self.cmd_setwelcome,
            '.set': self.cmd_set,
            '.welcome': self.cmd_welcome_toggle,
            '.reply': self.cmd_reply_toggle,
            '.spambot': self.cmd_spambot_toggle,
            '.discord': self.cmd_discord_toggle,
            '.status': self.cmd_status,
            '.groups': self.cmd_groups,
            '.stats': self.cmd_stats,
            '.logs': self.cmd_logs,
            '.telegram': self.cmd_telegram,
            '.aggressive': self.cmd_aggressive_toggle
        }

        # Statistics
        self.start_time = None
        self.message_count = 0
        self.iteration_count = 0
        self.last_stats_time = None

        # Load config
        self.load_main_config()

    async def interactive_login(self):
        print("XAXABotManager - Interactive Login")
        print("==================================")

        # Always ask for API ID and API HASH first
        self.api_id = int(input("Enter your API ID: "))
        self.api_hash = input("Enter your API Hash: ")

        # Check for existing sessions
        sessions = [f for f in os.listdir() if f.startswith('xaxa_manager_') and f.endswith('.session')]

        if sessions:
            print("\nExisting sessions found:")
            for i, session in enumerate(sessions, 1):
                phone = session.replace('xaxa_manager_', '').replace('.session', '')
                print(f"{i}. {phone}")

            choice = input("\nSelect a session number or press Enter for a new login: ")

            if choice.strip() and choice.isdigit() and 1 <= int(choice) <= len(sessions):
                session_file = sessions[int(choice) - 1]
                phone = session_file.replace('xaxa_manager_', '').replace('.session', '')
                self.phone_number = f"+{phone}"
                print(f"Using session for {self.phone_number}")
            else:
                self.phone_number = input("Enter your phone number (with country code, e.g., +1234567890): ")
        else:
            self.phone_number = input("Enter your phone number (with country code, e.g., +1234567890): ")

        # Create client
        session_name = f"xaxa_manager_{self.phone_number.replace('+', '')}"
        self.client = TelegramClient(session_name, self.api_id, self.api_hash)

        # Connect and login
        await self.client.connect()

        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone_number)
            code = input("Enter the code you received: ")

            try:
                await self.client.sign_in(self.phone_number, code)
            except errors.SessionPasswordNeededError:
                password = input("Two-factor authentication is enabled. Please enter your password: ")
                await self.client.sign_in(password=password)

        # Save config
        self.config['phone_number'] = self.phone_number
        self.save_main_config()

        # Send welcome message to Saved Messages
        me = await self.client.get_me()
        welcome_text = (
            "# XAXABotManager\n\n"
            "Successfully logged in!\n\n"
            f"**Account**: {me.first_name} {me.last_name if me.last_name else ''} (@{me.username})\n"
            f"**Phone**: {self.phone_number if self.config['hide_phone_number'] == 'off' else '********'}\n\n"
            "Use `.xaxa` to see available commands."
        )

        await self.client.send_message('me', welcome_text)
        print(f"Successfully logged in as {me.first_name} {me.last_name if me.last_name else ''} (@{me.username})")

        return True

    async def refresh_groups(self):
        self.target_groups.clear()

        result = await self.client(GetDialogsRequest(
            offset_date=None,
            offset_id=0,
            offset_peer=InputPeerEmpty(),
            limit=1000,
            hash=0
        ))

        for dialog in result.dialogs:
            entity = await self.client.get_entity(dialog.peer)

            if isinstance(entity, (Channel, Chat)):
                if entity.id not in self.banned_groups:
                    self.target_groups.add(entity.id)

        await self.log_message(f"Refreshed groups: {len(self.target_groups)} active groups", "INFO")
        return len(self.target_groups)

    async def check_permissions_for_all_groups(self):
        count = 0
        for group_id in list(self.target_groups):
            try:
                entity = await self.client.get_entity(group_id)
                await self.client.get_permissions(entity)
                count += 1
            except Exception as e:
                self.target_groups.discard(group_id)
                self.banned_groups.add(group_id)
                await self.log_message(f"No permissions in group {group_id}: {str(e)}", "WARNING")

        await self.log_message(f"Checked permissions: {count} groups with permissions", "INFO")
        return count

    async def forward_messages_loop(self):
        if not self.spam_message:
            await self.log_message("No spam message set. Use .setmsg to set a message.", "ERROR")
            return

        self.iteration_count = 0
        aggressive_mode = self.config['aggressive_mode'] == 'on'

        while self.running:
            self.iteration_count += 1
            sent_count = 0

            # Clear banned groups every 10 iterations or always in aggressive mode
            if self.iteration_count % 10 == 0 or aggressive_mode:
                self.banned_groups.clear()
                if not aggressive_mode:
                    await self.log_message("Cleared banned groups list", "INFO")

            for group_id in list(self.target_groups):
                if not self.running:
                    break

                try:
                    entity = await self.client.get_entity(group_id)
                    chat_id, msg_id = self.spam_message
                    await self.client.forward_messages(entity, msg_id, chat_id)
                    sent_count += 1
                    self.message_count += 1
                    self.sent_messages.add(group_id)

                    # Skip delay between messages if aggressive mode is on
                    if not aggressive_mode:
                        await asyncio.sleep(int(self.config['spam_delay_between_messages']))
                except errors.FloodWaitError as e:
                    await self.log_message(f"FloodWaitError: Need to wait {e.seconds} seconds", "ERROR")
                    # Skip waiting for FloodWaitError if aggressive mode is on
                    if not aggressive_mode:
                        await asyncio.sleep(e.seconds)
                except Exception as e:
                    # Don't add to banned groups if aggressive mode is on
                    if not aggressive_mode:
                        self.target_groups.discard(group_id)
                        self.banned_groups.add(group_id)
                    await self.log_message(f"Failed to forward message to group {group_id}: {str(e)}", "ERROR")

            await self.log_message(f"Iteration {self.iteration_count} completed: forwarded {sent_count} messages", "SUCCESS")
            # Skip delay between iterations if aggressive mode is on
            if not aggressive_mode:
                await asyncio.sleep(int(self.config['spam_delay_between_iterations']))

    async def setup_event_handlers(self):
        @self.client.on(events.ChatAction)
        async def handle_new_users(event):
            if self.config['welcome_enabled'] != 'on' or not self.welcome_messages:
                return

            if event.user_joined or event.user_added:
                try:
                    await asyncio.sleep(60)  # 60 seconds delay
                    chat_id, msg_id = random.choice(self.welcome_messages)
                    await self.client.forward_messages(event.chat_id, msg_id, chat_id)
                    await self.log_message(f"Forwarded welcome message in {event.chat_id}", "INFO")
                except Exception as e:
                    await self.log_message(f"Failed to forward welcome message: {str(e)}", "ERROR")

        @self.client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def handle_private_messages(event):
            if self.config['reply_enabled'] != 'on' or not self.reply_messages:
                return

            try:
                chat_id, msg_id = random.choice(self.reply_messages)
                await self.client.forward_messages(event.sender_id, msg_id, chat_id)
                await self.log_message(f"Forwarded auto-reply to {event.sender_id}", "INFO")
            except Exception as e:
                await self.log_message(f"Failed to forward auto-reply: {str(e)}", "ERROR")

    async def log_message(self, message, level="INFO"):
        timestamp = pendulum.now().to_datetime_string()
        log_entry = f"[{timestamp}] [{level}] {message}"

        # Console logging
        print(log_entry)

        # Discord webhook logging
        if self.config['discord_enabled'] == 'on' and self.config['discord_webhook_url']:
            await self.send_discord_notification(message, level)

        # Telegram logging
        if self.config['telegram_log_enabled'] == 'on' and self.config['telegram_log_user']:
            await self.send_telegram_log(message, level)

    async def send_discord_notification(self, message, level="INFO"):
        if not self.config['discord_webhook_url']:
            return

        colors = {
            "SUCCESS": 0x00FF00,
            "ERROR": 0xFF0000,
            "WARNING": 0xFFFF00,
            "INFO": 0x0000FF
        }

        embed = {
            "title": f"XAXABotManager - {level}",
            "description": message,
            "color": colors.get(level, 0x0000FF),
            "timestamp": pendulum.now().to_iso8601_string()
        }

        try:
            async with aiohttp.ClientSession() as session:
                webhook_data = {
                    "embeds": [embed]
                }

                async with session.post(
                    self.config['discord_webhook_url'],
                    json=webhook_data
                ) as response:
                    if response.status != 204:
                        print(f"Failed to send Discord notification: {response.status}")
        except Exception as e:
            print(f"Error sending Discord notification: {str(e)}")

    async def send_telegram_log(self, message, level="INFO"):
        if not self.config['telegram_log_user']:
            return

        try:
            username = self.config['telegram_log_user'].replace('@', '')
            user = await self.client.get_entity(username)

            log_message = f"**[{level}]** {message}"
            await self.client.send_message(user, log_message)
        except Exception as e:
            print(f"Error sending Telegram log: {str(e)}")

    async def send_hourly_stats(self):
        while self.running:
            await asyncio.sleep(3600)  # 1 hour

            if not self.running:
                break

            stats = await self.generate_stats()

            # Send to Discord
            if self.config['discord_enabled'] == 'on' and self.config['discord_webhook_url']:
                await self.send_discord_notification(stats, "INFO")

            # Send to Telegram
            if self.config['telegram_log_enabled'] == 'on' and self.config['telegram_log_user']:
                await self.send_telegram_log(stats, "INFO")

    async def generate_stats(self):
        uptime = pendulum.now() - self.start_time if self.start_time else pendulum.duration(seconds=0)
        uptime_str = f"{uptime.days}d {uptime.hours}h {uptime.minutes}m {uptime.seconds}s" if self.start_time else "Not running"

        me = await self.client.get_me()

        stats = (
            "# XAXABotManager Stats\n\n"
            f"**Account**: {me.first_name} {me.last_name if me.last_name else ''} (@{me.username})\n"
            f"**Phone**: {self.phone_number if self.config['hide_phone_number'] == 'off' else '********'}\n"
            f"**Uptime**: {uptime_str}\n"
            f"**Messages Sent**: {self.message_count}\n"
            f"**Iterations**: {self.iteration_count}\n"
            f"**Active Groups**: {len(self.target_groups)}\n"
            f"**Banned Groups**: {len(self.banned_groups)}\n\n"
            "**Configuration**:\n"
            f"- Spam Enabled: {self.config['spam_enabled']}\n"
            f"- Welcome Enabled: {self.config['welcome_enabled']}\n"
            f"- Reply Enabled: {self.config['reply_enabled']}\n"
            f"- SpamBot Check: {self.config['check_spambot']}\n"
            f"- Discord Integration: {self.config['discord_enabled']}\n"
            f"- Telegram Logging: {self.config['telegram_log_enabled']}"
        )

        return stats

    async def check_spambot(self):
        while self.running and self.config['check_spambot'] == 'on':
            try:
                spambot = await self.client.get_entity('SpamBot')
                await self.client.send_message(spambot, '/start')

                # Wait for response
                async for message in self.client.iter_messages(spambot, limit=1):
                    if "no limits" in message.text.lower():
                        await self.log_message("SpamBot check: No restrictions", "SUCCESS")
                    else:
                        await self.log_message(f"SpamBot check: {message.text}", "WARNING")
            except Exception as e:
                await self.log_message(f"SpamBot check failed: {str(e)}", "ERROR")

            # Wait for next check
            await asyncio.sleep(int(self.config['check_spambot_delay']))

    async def start(self):
        if self.running:
            return "Bot is already running"

        self.running = True
        self.start_time = pendulum.now()
        self.last_stats_time = self.start_time

        # Clear collections
        self.reply_messages.clear()
        self.welcome_messages.clear()
        self.banned_groups.clear()

        # Setup event handlers
        await self.setup_event_handlers()

        # Refresh groups
        await self.refresh_groups()

        # Check permissions
        await self.check_permissions_for_all_groups()

        # Start tasks
        self.tasks = [
            asyncio.create_task(self.forward_messages_loop()),
            asyncio.create_task(self.send_hourly_stats()),
            asyncio.create_task(self.check_spambot())
        ]

        await self.log_message("Bot started successfully", "SUCCESS")
        return "Bot started successfully"

    async def stop(self):
        if not self.running:
            return "Bot is not running"

        self.running = False

        # Cancel tasks
        for task in self.tasks:
            task.cancel()

        self.tasks.clear()

        await self.log_message("Bot stopped", "INFO")
        return "Bot stopped"

    # Command handlers
    async def cmd_start(self, event):
        result = await self.start()
        await event.reply(f"Program wystartowal\n{result}")
        # Log to Saved Messages
        await self.client.send_message('me', "Bot został włączony")

    async def cmd_stop(self, event):
        result = await self.stop()
        await event.reply(result)
        # Log to Saved Messages
        await self.client.send_message('me', "Bot został wyłączony")

    async def cmd_config(self, event):
        config_menu = (
            "# XAXABotManager Configuration\n\n"
            "**Message Settings**:\n"
            "- `.setmsg` - Set spam message (reply to a message)\n"
            "- `.setreply` - Set auto-reply message (reply to a message)\n"
            "- `.setwelcome` - Set welcome message (reply to a message)\n"
            "- `.welcome on/off` - Toggle welcome messages\n"
            "- `.reply on/off` - Toggle auto-replies\n\n"

            "**Spam Settings**:\n"
            "- `.set spam_delay [iterations_delay] [messages_delay]` - Set delays\n\n"

            "**Integration**:\n"
            "- `.discord on/off` - Toggle Discord integration\n"
            "- `.set discord_webhook_url [url]` - Set Discord webhook URL\n"
            "- `.spambot on/off` - Toggle SpamBot checking\n"
            "- `.telegram log on/off` - Toggle Telegram logging\n"
            "- `.telegram loguser [username]` - Set Telegram log user\n\n"

            "**Status**:\n"
            "- `.status` - Show bot status\n"
            "- `.groups` - Show groups info\n"
            "- `.stats` - Show detailed statistics\n"
            "- `.logs` - Show system logs"
        )

        await event.reply(config_menu)

    async def cmd_xaxa(self, event):
        main_menu = (
            "# XAXABotManager\n\n"
            "**Main Commands**:\n"
            "- `.start` - Start the bot\n"
            "- `.stop` - Stop the bot\n"
            "- `.config` - Show configuration menu\n"
            "- `.help` - Show help\n\n"

            "**Quick Status**:\n"
            f"- Running: {'Yes' if self.running else 'No'}\n"
            f"- Messages Sent: {self.message_count}\n"
            f"- Active Groups: {len(self.target_groups)}\n\n"

            "Use `.config` for more options."
        )

        await event.reply(main_menu)

    async def cmd_help(self, event):
        help_text = (
            "# XAXABotManager Help\n\n"
            "XAXABotManager is a Telegram bot for managing message distribution across multiple groups.\n\n"

            "**Getting Started**:\n"
            "1. Use `.start` to start the bot\n"
            "2. Set a spam message with `.setmsg` (reply to a message)\n"
            "3. Configure delays with `.set spam_delay 60 5`\n"
            "4. Monitor status with `.status`\n\n"

            "**Main Features**:\n"
            "- Automated message distribution to groups\n"
            "- Welcome messages for new group members\n"
            "- Auto-replies to private messages\n"
            "- Discord integration for statistics\n"
            "- Telegram logging\n"
            "- SpamBot monitoring\n\n"

            "**Configuration**:\n"
            "Use `.config` to see all configuration options.\n\n"

            "**Monitoring**:\n"
            "- `.status` - Current bot status\n"
            "- `.groups` - Group information\n"
            "- `.stats` - Detailed statistics\n\n"

            "For more information, use `.config` to explore all available commands."
        )

        await event.reply(help_text)

    async def cmd_setmsg(self, event):
        if event.is_reply:
            replied_msg = await event.get_reply_message()
            self.spam_message = (replied_msg.chat_id, replied_msg.id)
            await event.reply("Spam message set successfully")
        else:
            await event.reply("Please reply to a message to set it as the spam message")

    async def cmd_setreply(self, event):
        if event.is_reply:
            replied_msg = await event.get_reply_message()
            self.reply_messages = [(replied_msg.chat_id, replied_msg.id)]
            await event.reply("Auto-reply message set successfully")
        else:
            await event.reply("Please reply to a message to set it as the auto-reply message")

    async def cmd_setwelcome(self, event):
        if event.is_reply:
            replied_msg = await event.get_reply_message()
            self.welcome_messages = [(replied_msg.chat_id, replied_msg.id)]
            await event.reply("Welcome message set successfully")
        else:
            await event.reply("Please reply to a message to set it as the welcome message")

    async def cmd_set(self, event):
        args = event.text.split(maxsplit=2)
        if len(args) < 3:
            await event.reply("Usage: `.set [setting] [value]`")
            return

        setting = args[1]
        value = args[2]

        if setting == "spam_delay":
            try:
                delays = value.split()
                if len(delays) == 2:
                    self.config['spam_delay_between_iterations'] = int(delays[0])
                    self.config['spam_delay_between_messages'] = int(delays[1])
                    await event.reply(f"Spam delays set: {delays[0]}s between iterations, {delays[1]}s between messages")
                else:
                    await event.reply("Usage: `.set spam_delay [iterations_delay] [messages_delay]`")
            except ValueError:
                await event.reply("Delays must be numbers")
        elif setting == "discord_webhook_url":
            self.config['discord_webhook_url'] = value
            self.save_main_config()
            await event.reply("Discord webhook URL set successfully")
        else:
            await event.reply(f"Unknown setting: {setting}")

    async def cmd_welcome_toggle(self, event):
        args = event.text.split()
        if len(args) != 2 or args[1] not in ['on', 'off']:
            await event.reply("Usage: `.welcome on/off`")
            return

        self.config['welcome_enabled'] = args[1]
        self.save_main_config()
        await event.reply(f"Welcome messages: {args[1]}")

    async def cmd_reply_toggle(self, event):
        args = event.text.split()
        if len(args) != 2 or args[1] not in ['on', 'off']:
            await event.reply("Usage: `.reply on/off`")
            return

        self.config['reply_enabled'] = args[1]
        self.save_main_config()
        await event.reply(f"Auto-replies: {args[1]}")

    async def cmd_spambot_toggle(self, event):
        args = event.text.split()
        if len(args) != 2 or args[1] not in ['on', 'off']:
            await event.reply("Usage: `.spambot on/off`")
            return

        self.config['check_spambot'] = args[1]
        self.save_main_config()
        await event.reply(f"SpamBot checking: {args[1]}")

    async def cmd_discord_toggle(self, event):
        args = event.text.split()
        if len(args) != 2 or args[1] not in ['on', 'off']:
            await event.reply("Usage: `.discord on/off`")
            return

        self.config['discord_enabled'] = args[1]
        self.save_main_config()
        await event.reply(f"Discord integration: {args[1]}")

    async def cmd_aggressive_toggle(self, event):
        args = event.text.split()
        if len(args) != 2 or args[1] not in ['on', 'off']:
            await event.reply("Usage: `.aggressive on/off`")
            return

        self.config['aggressive_mode'] = args[1]
        self.save_main_config()
        await event.reply(f"Aggressive mode: {args[1]}")
        await self.client.send_message('me', f"Aggressive mode został {args[1] == 'on' and 'włączony' or 'wyłączony'}")

    async def cmd_status(self, event):
        uptime = pendulum.now() - self.start_time if self.start_time else pendulum.duration(seconds=0)
        uptime_str = f"{uptime.days}d {uptime.hours}h {uptime.minutes}m {uptime.seconds}s" if self.start_time else "Not running"

        status = (
            "# XAXABotManager Status\n\n"
            f"**Running**: {'Yes' if self.running else 'No'}\n"
            f"**Uptime**: {uptime_str}\n"
            f"**Messages Sent**: {self.message_count}\n"
            f"**Iterations**: {self.iteration_count}\n\n"

            "**Configuration**:\n"
            f"- Spam Enabled: {self.config['spam_enabled']}\n"
            f"- Welcome Enabled: {self.config['welcome_enabled']}\n"
            f"- Reply Enabled: {self.config['reply_enabled']}\n"
            f"- SpamBot Check: {self.config['check_spambot']}\n"
            f"- Discord Integration: {self.config['discord_enabled']}\n"
            f"- Telegram Logging: {self.config['telegram_log_enabled']}\n"
            f"- Aggressive Mode: {self.config['aggressive_mode']}\n\n"

            "**Delays**:\n"
            f"- Between Iterations: {self.config['spam_delay_between_iterations']}s\n"
            f"- Between Messages: {self.config['spam_delay_between_messages']}s\n\n"

            "**Groups**:\n"
            f"- Active Groups: {len(self.target_groups)}\n"
            f"- Banned Groups: {len(self.banned_groups)}"
        )

        await event.reply(status)

    async def cmd_groups(self, event):
        groups_info = (
            "# Groups Information\n\n"
            f"**Active Groups**: {len(self.target_groups)}\n"
            f"**Banned Groups**: {len(self.banned_groups)}\n\n"
        )

        if self.target_groups:
            groups_info += "**Active Group IDs**:\n"
            for group_id in list(self.target_groups)[:10]:  # Show first 10
                try:
                    entity = await self.client.get_entity(group_id)
                    name = getattr(entity, 'title', 'Unknown')
                    groups_info += f"- {name} (ID: {group_id})\n"
                except:
                    groups_info += f"- Unknown (ID: {group_id})\n"

            if len(self.target_groups) > 10:
                groups_info += f"...and {len(self.target_groups) - 10} more\n\n"

        await event.reply(groups_info)

    async def cmd_stats(self, event):
        stats = await self.generate_stats()
        await event.reply(stats)

    async def cmd_logs(self, event):
        await event.reply("System logs are available in the console and through Telegram logging")

    async def cmd_telegram(self, event):
        args = event.text.split()

        if len(args) < 2:
            await event.reply("Usage: `.telegram [log/loguser/testlog] [options]`")
            return

        if args[1] == "log":
            if len(args) != 3 or args[2] not in ['on', 'off']:
                await event.reply("Usage: `.telegram log on/off`")
                return

            self.config['telegram_log_enabled'] = args[2]
            self.save_main_config()
            await event.reply(f"Telegram logging: {args[2]}")

        elif args[1] == "loguser":
            if len(args) != 3:
                await event.reply("Usage: `.telegram loguser [username]`")
                return

            username = args[2].replace('@', '')
            self.config['telegram_log_user'] = username
            self.save_main_config()
            await event.reply(f"Telegram log user set to: {username}")

        elif args[1] == "testlog":
            if not self.config['telegram_log_user']:
                await event.reply("No log user set. Use `.telegram loguser [username]` first.")
                return

            try:
                username = self.config['telegram_log_user']
                test_message = "This is a test log message from XAXABotManager"
                await self.send_telegram_log(test_message, "INFO")
                await event.reply(f"Test log sent to @{username}")
            except Exception as e:
                await event.reply(f"Failed to send test log: {str(e)}")

        else:
            await event.reply("Unknown subcommand. Use `log`, `loguser`, or `testlog`.")

    def load_main_config(self):
        try:
            with open('main_config.txt', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith('['):
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        if key == 'api_id':
                            self.api_id = int(value)
                        elif key == 'api_hash':
                            self.api_hash = value
                        elif key == 'phone_number':
                            self.phone_number = value
                        else:
                            self.config[key] = value
        except FileNotFoundError:
            print("Config file not found, using defaults")
        except Exception as e:
            print(f"Error loading config: {str(e)}")

    def save_main_config(self):
        try:
            with open('main_config.txt', 'w') as f:
                f.write("[DEFAULT]\n")
                f.write("# ======================\n")
                f.write("# xaxa solutions config\n\n")

                f.write(f"api_id = {self.api_id}\n")
                f.write(f"api_hash = {self.api_hash}\n")
                f.write(f"phone_number = {self.phone_number}\n")

                for key, value in self.config.items():
                    if key not in ['api_id', 'api_hash', 'phone_number']:
                        f.write(f"{key} = {value}\n")
        except Exception as e:
            print(f"Error saving config: {str(e)}")

    async def process_command(self, event):
        # Check if event.text exists and is not empty
        if not event.text or not event.text.strip():
            self.log_message(f"Received empty message event: {event}", level="DEBUG")
            return False

        # Split the text and check if there are any parts
        parts = event.text.split()
        if not parts:
            self.log_message(f"Message split resulted in empty list: {event.text}", level="DEBUG")
            return False

        text = parts[0].lower()

        if text in self.main_commands:
            await self.main_commands[text](event)
            return True

        if text in self.config_commands:
            await self.config_commands[text](event)
            return True

        return False

async def main():
    bot = XAXABotManager()

    # Always use interactive login to ensure proper sequence of credential input
    await bot.interactive_login()

    @bot.client.on(events.NewMessage(outgoing=True))
    async def command_handler(event):
        try:
            await bot.process_command(event)
        except Exception as e:
            bot.log_message(f"Error in command_handler: {str(e)}", level="ERROR")
            # Log additional debug information
            if hasattr(event, 'text'):
                bot.log_message(f"Message that caused error: '{event.text}'", level="DEBUG")
            else:
                bot.log_message(f"Event without text attribute: {event}", level="DEBUG")

    print("XAXABotManager is running. Press Ctrl+C to stop.")

    try:
        await bot.client.run_until_disconnected()
    except KeyboardInterrupt:
        if bot.running:
            await bot.stop()
        print("Bot stopped by user")

if __name__ == "__main__":
    asyncio.run(main())
