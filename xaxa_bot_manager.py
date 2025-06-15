import os,sys,re,json,random,asyncio,aiohttp,aiofiles,pendulum
from telethon import TelegramClient,events,errors,functions,types
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty,Channel,Chat,User
class XAXABotManager:
    def __init__(self):
        self.api_id=None;self.api_hash=None;self.phone_number=None;self.client=None;self.running=False;self.tasks=[]
        self.config={'spam_enabled':'on','spam_delay_between_iterations':60,'spam_delay_between_messages':5,'welcome_enabled':'on',
            'reply_enabled':'on','check_spambot':'on','check_spambot_delay':21600,'hide_phone_number':'on','discord_enabled':'on',
            'discord_webhook_url':'','telegram_log_enabled':'on','telegram_log_user':'marlboro_pln','aggressive_mode':'off'}
        self.target_groups=set();self.sent_messages=set();self.banned_groups=set();self.reply_messages=[]
        self.welcome_messages=[];self.spam_message=None;self.replied_users=set()
        self.main_commands={'.start':self.cmd_start,'.stop':self.cmd_stop,'.config':self.cmd_config,'.xaxa':self.cmd_xaxa,'.help':self.cmd_help}
        self.config_commands={'.setmsg':self.cmd_setmsg,'.setreply':self.cmd_setreply,'.setwelcome':self.cmd_setwelcome,'.set':self.cmd_set,
            '.welcome':lambda e:self.cmd_toggle(e,'welcome_enabled','Welcome messages'),
            '.reply':lambda e:self.cmd_toggle(e,'reply_enabled','Auto-replies'),
            '.spambot':lambda e:self.cmd_toggle(e,'check_spambot','SpamBot checking'),
            '.discord':lambda e:self.cmd_toggle(e,'discord_enabled','Discord integration'),
            '.aggressive':lambda e:self.cmd_toggle(e,'aggressive_mode','Aggressive mode',notify_me=True,
                notify_msg=lambda v:f"Aggressive mode został {'włączony' if v=='on' else 'wyłączony'}"),
            '.clearreplied':self.cmd_clearreplied,
            '.status':self.cmd_status,'.groups':self.cmd_groups,'.stats':self.cmd_stats,'.logs':self.cmd_logs,'.telegram':self.cmd_telegram}
        self.start_time=None;self.message_count=0;self.iteration_count=0;self.last_stats_time=None
        self.load_main_config()

    async def interactive_login(self):
        print("XAXABotManager - Interactive Login")
        print("==================================")
        if not self.api_id or not self.api_hash:
            self.load_main_config()
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
                await self._request_credentials()
        else:
            await self._request_credentials()
        session_name = f"xaxa_manager_{self.phone_number.replace('+', '')}"
        self.client = TelegramClient(session_name, self.api_id, self.api_hash)
        await self.client.connect()
        if not await self.client.is_user_authorized():
            try:
                await self.client.send_code_request(self.phone_number)
                code = input("Enter the code you received: ")
                try:
                    await self.client.sign_in(self.phone_number, code)
                except errors.SessionPasswordNeededError:
                    password = input("Two-factor authentication is enabled. Please enter your password: ")
                    await self.client.sign_in(password=password)
                except errors.PhoneNumberBannedError:
                    print(f"Error: The phone number {self.phone_number} has been banned from Telegram.")
                    return False
            except errors.PhoneNumberBannedError:
                print(f"Error: The phone number {self.phone_number} has been banned from Telegram.")
                return False
            except Exception as e:
                print(f"Error during login: {str(e)}")
                return False
        self.config['phone_number'] = self.phone_number
        self.save_main_config()
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

    async def _request_credentials(self):
        if not self.api_id or not self.api_hash:
            self.api_id = int(input("Enter your API ID: "))
            self.api_hash = input("Enter your API Hash: ")
        self.phone_number = input("Enter your phone number (with country code, e.g., +48 123 456 789): ")
        self.phone_number = self.phone_number.replace(" ", "")

    async def refresh_groups(self):
        self.target_groups.clear()
        result = await self.client(GetDialogsRequest(
            offset_date=None,offset_id=0,offset_peer=InputPeerEmpty(),limit=1000,hash=0))
        for dialog in result.dialogs:
            entity = await self.client.get_entity(dialog.peer)
            if isinstance(entity, (Channel, Chat)) and entity.id not in self.banned_groups:
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
                    if not aggressive_mode:
                        await asyncio.sleep(int(self.config['spam_delay_between_messages']))
                except errors.FloodWaitError as e:
                    await self.log_message(f"FloodWaitError: Need to wait {e.seconds} seconds", "ERROR")
                    if not aggressive_mode:
                        await asyncio.sleep(e.seconds)
                except Exception as e:
                    if not aggressive_mode:
                        self.target_groups.discard(group_id)
                        self.banned_groups.add(group_id)
                    await self.log_message(f"Failed to forward message to group {group_id}: {str(e)}", "ERROR")
            await self.log_message(f"Iteration {self.iteration_count} completed: forwarded {sent_count} messages", "SUCCESS")
            if not aggressive_mode:
                await asyncio.sleep(int(self.config['spam_delay_between_iterations']))

    async def setup_event_handlers(self):
        @self.client.on(events.ChatAction)
        async def handle_new_users(event):
            try:
                if self.config['welcome_enabled'] != 'on' or not self.welcome_messages:
                    return
                if event.user_joined or event.user_added:
                    try:
                        await asyncio.sleep(60)
                        if not self.welcome_messages:
                            await self.log_message("No welcome messages set", "WARNING")
                            return
                        chat_id, msg_id = random.choice(self.welcome_messages)
                        await self.client.forward_messages(event.chat_id, msg_id, chat_id)
                        await self.log_message(f"Forwarded welcome message in {event.chat_id}", "INFO")
                    except Exception as e:
                        await self.log_message(f"Failed to forward welcome message: {str(e)}", "ERROR")
            except Exception as e:
                await self.log_message(f"Error in handle_new_users: {str(e)}", "ERROR")
        @self.client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def handle_private_messages(event):
            try:
                if self.config['reply_enabled'] != 'on':
                    return
                # Check if we've already replied to this user
                if event.sender_id in self.replied_users:
                    await self.log_message(f"Ignoring message from {event.sender_id} (already replied)", "INFO")
                    return
                if not self.reply_messages:
                    await self._handle_missing_reply_messages(event)
                    return
                try:
                    chat_id, msg_id = random.choice(self.reply_messages)
                    await self.client.forward_messages(event.sender_id, msg_id, chat_id)
                    # Add user to the replied_users set
                    self.replied_users.add(event.sender_id)
                    await self.log_message(f"Forwarded auto-reply to {event.sender_id}", "INFO")
                except Exception as e:
                    await self.log_message(f"Failed to forward auto-reply: {str(e)}", "ERROR")
            except Exception as e:
                await self.log_message(f"Error in handle_private_messages: {str(e)}", "ERROR")

    async def _handle_missing_reply_messages(self, event):
        await self.log_message("Auto-reply enabled but no reply messages set", "WARNING")
        if self.spam_message:
            try:
                chat_id, msg_id = self.spam_message
                await self.client.forward_messages(event.sender_id, msg_id, chat_id)
                # Add user to the replied_users set
                self.replied_users.add(event.sender_id)
                await self.log_message(f"Forwarded spam message as auto-reply to {event.sender_id}", "INFO")
                return
            except Exception as e:
                await self.log_message(f"Failed to forward spam message as auto-reply: {str(e)}", "ERROR")
        try:
            me = await self.client.get_me()
            await self.client.send_message(me.id, "Warning: Auto-reply is enabled but no reply messages are set. Use .setreply to set a reply message.")
        except Exception as e:
            await self.log_message(f"Failed to send warning to user: {str(e)}", "ERROR")

    async def log_message(self, message, level="INFO"):
        timestamp = pendulum.now().to_datetime_string()
        log_entry = f"[{timestamp}] [{level}] {message}"
        print(log_entry)
        if self.config['discord_enabled'] == 'on' and self.config['discord_webhook_url']:
            await self.send_discord_notification(message, level)
        if self.config['telegram_log_enabled'] == 'on' and self.config['telegram_log_user']:
            await self.send_telegram_log(message, level)

    async def send_discord_notification(self, message, level="INFO"):
        if not self.config['discord_webhook_url']:
            return
        colors = {"SUCCESS": 0x00FF00,"ERROR": 0xFF0000,"WARNING": 0xFFFF00,"INFO": 0x0000FF}
        embed = {"title": f"XAXABotManager - {level}","description": message,"color": colors.get(level, 0x0000FF),
            "timestamp": pendulum.now().to_iso8601_string()}
        try:
            async with aiohttp.ClientSession() as session:
                webhook_data = {"embeds": [embed]}
                async with session.post(self.config['discord_webhook_url'], json=webhook_data) as response:
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
            await asyncio.sleep(3600)
            if not self.running:
                break
            stats = await self.generate_stats()
            if self.config['discord_enabled'] == 'on' and self.config['discord_webhook_url']:
                await self.send_discord_notification(stats, "INFO")
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
            f"**Banned Groups**: {len(self.banned_groups)}\n"
            f"**Users Replied To**: {len(self.replied_users)}\n\n"
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
                try:
                    async for message in self.client.iter_messages(spambot, limit=1):
                        if "no limits" in message.text.lower():
                            await self.log_message("SpamBot check: No restrictions", "SUCCESS")
                        else:
                            await self.log_message(f"SpamBot check: {message.text}", "WARNING")
                except asyncio.TimeoutError:
                    await self.log_message("SpamBot check timed out", "WARNING")
            except Exception as e:
                await self.log_message(f"SpamBot check failed: {str(e)}", "ERROR")
            await asyncio.sleep(int(self.config['check_spambot_delay']))

    async def start(self):
        if self.running:
            return "Bot is already running"
        if not self.spam_message:
            await self.log_message("No spam message set. Use .setmsg to set a message before starting the bot.", "WARNING")
            return "Error: No spam message set. Use .setmsg to set a message before starting the bot."
        self.running = True
        self.start_time = pendulum.now()
        self.last_stats_time = self.start_time
        self.welcome_messages.clear()
        self.banned_groups.clear()
        self.replied_users.clear()
        await self.setup_event_handlers()
        await self.refresh_groups()
        await self.check_permissions_for_all_groups()
        self.tasks = [
            asyncio.create_task(self.forward_messages_loop()),
            asyncio.create_task(self.send_hourly_stats()),
            asyncio.create_task(self.check_spambot())
        ]
        if self.config['reply_enabled'] == 'on' and not self.reply_messages:
            await self.log_message("Warning: Auto-reply is enabled but no reply messages are set.", "WARNING")
            try:
                me = await self.client.get_me()
                await self.client.send_message(me.id, "Warning: Auto-reply is enabled but no reply messages are set. Use .setreply to set a reply message.")
            except Exception as e:
                await self.log_message(f"Failed to send warning to user: {str(e)}", "ERROR")
        await self.log_message("Bot started successfully", "SUCCESS")
        return "Bot started successfully"

    async def stop(self):
        if not self.running:
            return "Bot is not running"
        self.running = False
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        await self.log_message("Bot stopped", "INFO")
        return "Bot stopped"

    async def cmd_start(self, event):
        result = await self.start()
        await event.reply(f"Program wystartowal\n{result}")
        await self.client.send_message('me', "Bot został włączony")

    async def cmd_stop(self, event):
        result = await self.stop()
        await event.reply(result)
        await self.client.send_message('me', "Bot został wyłączony")

    async def cmd_config(self, event):
        config_menu = (
            "# XAXABotManager Configuration\n\n"
            "**Message Settings**:\n"
            "- `.setmsg` - Set spam message (reply to a message)\n"
            "- `.setreply` - Set auto-reply message (reply to a message)\n"
            "- `.setwelcome` - Set welcome message (reply to a message)\n"
            "- `.welcome on/off` - Toggle welcome messages\n"
            "- `.reply on/off` - Toggle auto-replies\n"
            "- `.clearreplied` - Clear the list of users who have received replies\n\n"
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
            "- Auto-replies to private messages (only once per user)\n"
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
        try:
            if event.is_reply:
                replied_msg = await event.get_reply_message()
                # Store the message reference
                self.spam_message = (replied_msg.chat_id, replied_msg.id)

                # Make sure spam_enabled is on
                if self.config['spam_enabled'] != 'on':
                    self.config['spam_enabled'] = 'on'
                    self.save_main_config()
                    await event.reply("Spam message set successfully and spam enabled")
                else:
                    await event.reply("Spam message set successfully")

                # Log the action
                await self.log_message(f"Spam message set by {event.sender_id}", "INFO")
            else:
                await event.reply("Please reply to a message to set it as the spam message")
        except Exception as e:
            await self.log_message(f"Error in cmd_setmsg: {str(e)}", "ERROR")
            await event.reply(f"Failed to set spam message: {str(e)}")

    async def cmd_setreply(self, event):
        try:
            if event.is_reply:
                replied_msg = await event.get_reply_message()
                # Store the message reference by appending to the list
                self.reply_messages.append((replied_msg.chat_id, replied_msg.id))

                # Make sure reply_enabled is on
                if self.config['reply_enabled'] != 'on':
                    self.config['reply_enabled'] = 'on'
                    self.save_main_config()
                    await event.reply("Auto-reply message set successfully and auto-reply enabled")
                else:
                    await event.reply("Auto-reply message set successfully")

                # Check if spam message is set
                if not self.spam_message:
                    await event.reply("Warning: Auto-reply message set, but no spam message is set. Use .setmsg to set a spam message.")

                # Log the action
                await self.log_message(f"Auto-reply message set by {event.sender_id}", "INFO")
            else:
                await event.reply("Please reply to a message to set it as the auto-reply message")
        except Exception as e:
            await self.log_message(f"Error in cmd_setreply: {str(e)}", "ERROR")
            await event.reply(f"Failed to set auto-reply message: {str(e)}")

    async def cmd_setwelcome(self, event):
        try:
            if event.is_reply:
                replied_msg = await event.get_reply_message()
                # Store the message reference
                self.welcome_messages = [(replied_msg.chat_id, replied_msg.id)]

                # Make sure welcome_enabled is on
                if self.config['welcome_enabled'] != 'on':
                    self.config['welcome_enabled'] = 'on'
                    self.save_main_config()
                    await event.reply("Welcome message set successfully and welcome messages enabled")
                else:
                    await event.reply("Welcome message set successfully")

                # Log the action
                await self.log_message(f"Welcome message set by {event.sender_id}", "INFO")
            else:
                await event.reply("Please reply to a message to set it as the welcome message")
        except Exception as e:
            await self.log_message(f"Error in cmd_setwelcome: {str(e)}", "ERROR")
            await event.reply(f"Failed to set welcome message: {str(e)}")

    async def cmd_toggle(self, event, config_key, display_name, notify_me=False, notify_msg=None):
        args = event.text.split()
        if len(args) != 2 or args[1] not in ['on', 'off']:
            await event.reply(f"Usage: `{args[0]} on/off`")
            return

        value = args[1]
        self.config[config_key] = value
        self.save_main_config()
        await event.reply(f"{display_name}: {value}")

        if notify_me:
            msg = notify_msg(value) if notify_msg else f"{display_name} set to {value}"
            await self.client.send_message('me', msg)

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
                    self.save_main_config()
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
            f"- Banned Groups: {len(self.banned_groups)}\n\n"
            "**Users**:\n"
            f"- Users Replied To: {len(self.replied_users)}"
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

    async def cmd_clearreplied(self, event):
        count = len(self.replied_users)
        self.replied_users.clear()
        await event.reply(f"Cleared {count} users from the replied users list. The bot will now reply to all users again.")
        await self.log_message(f"Cleared {count} users from the replied users list", "INFO")

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
                        try:
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
                        except ValueError:
                            continue  # Skip malformed lines
        except FileNotFoundError:
            print("Config file not found, using defaults")
        except Exception as e:
            print(f"Error loading config: {str(e)}")

    def save_main_config(self):
        try:
            with open('main_config.txt', 'w') as f:
                f.write("[DEFAULT]\n# ======================\n# xaxa solutions config\n\n")

                if self.api_id:
                    f.write(f"api_id = {self.api_id}\n")
                if self.api_hash:
                    f.write(f"api_hash = {self.api_hash}\n")
                if self.phone_number:
                    f.write(f"phone_number = {self.phone_number}\n")

                for key, value in self.config.items():
                    if key not in ['api_id', 'api_hash', 'phone_number']:
                        f.write(f"{key} = {value}\n")
        except Exception as e:
            print(f"Error saving config: {str(e)}")

    async def process_command(self, event):
        # Check if event.text exists and is not empty
        if not hasattr(event, 'text') or not event.text or not event.text.strip():
            return False

        # Split the text and check if there are any parts
        parts = event.text.split()
        if not parts:
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
    while True:
        try:
            bot = XAXABotManager()

            # Always use interactive login to ensure proper sequence of credential input
            login_result = await bot.interactive_login()
            if login_result is False:
                print("Login failed. Please try again with different credentials.")
                await asyncio.sleep(5)
                continue

            @bot.client.on(events.NewMessage(outgoing=True))
            async def command_handler(event):
                try:
                    await bot.process_command(event)
                except Exception as e:
                    await bot.log_message(f"Error in command_handler: {str(e)}", level="ERROR")
                    if hasattr(event, 'text'):
                        await bot.log_message(f"Message that caused error: '{event.text}'", level="DEBUG")

            print("XAXABotManager is running. Press Ctrl+C to stop.")

            try:
                await bot.client.run_until_disconnected()
            except KeyboardInterrupt:
                if bot.running:
                    await bot.stop()
                print("Bot stopped by user")
                break
            except Exception as e:
                print(f"Critical error: {str(e)}")
                print("Bot will restart in 10 seconds...")
                if bot.running:
                    try:
                        await bot.stop()
                    except Exception as e:
                        print(f"Error stopping bot: {str(e)}")
                await asyncio.sleep(10)
        except Exception as e:
            print(f"Initialization error: {str(e)}")
            print("Retrying in 30 seconds...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
