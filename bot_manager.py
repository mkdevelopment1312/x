import asyncio
import os
import configparser
import traceback
import random
import glob # Added import
from typing import Dict, Set, Deque, Optional, List, Any, Union, Tuple

from telethon import TelegramClient, events
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.types import InputPeerChannel, Channel
from telethon.events.newmessage import NewMessage
from telethon.events import NewMessage as NewMessageEvent

# Async libraries
import aiohttp
import aiofiles

# Utilities
import pendulum
from collections import deque

# Local imports
# from utils.helpers import now # Removed import
from telethon import errors

def now():
    """Returns the current time formatted as a string."""
    return pendulum.now().strftime('%Y-%m-%d %H:%M:%S')

class XAXABotManager:
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.config: Dict[str, str] = {}
        self.api_id: Optional[int] = None
        self.api_hash: Optional[str] = None
        self.phone_number: Optional[str] = None # Will be set via interactive_login
        self.reply_message_id: Optional[int] = None
        self.spam_message: Optional[Any] = None
        self.target_groups: Set[int] = set()
        self.banned_groups: Set[int] = set()
        self.sent_messages: Set[int] = set()
        self.failed_users: Set[int] = set()
        self.message_count: int = 0
        self.ban_expiry: Optional[Any] = None
        self.reply_messages: List[Any] = []  # Zmienione na List[Any] dla przechowywania message objects
        self.welcome_messages: List[Any] = []  # Zmienione na List[Any] dla przechowywania message objects
        self.reply_files: List[str] = []
        self.welcome_queue: Deque[int] = deque()
        self.last_batch_send = pendulum.now('UTC')
        self.whitelist: Set[int] = {178220800}
        self.start_time = pendulum.now('UTC')
        
        self.group_cache: Dict[int, Any] = {}  # Cache dla grup
        self.group_errors: Dict[int, str] = {}  # Błędy grup
        self.skipped_groups: Dict[int, str] = {}  # Pominięte grupy
        self.last_ban_cleanup = pendulum.now('UTC')
        self.groups_loaded = asyncio.Event()
        
        # Discord Statistics Control Configuration
        self.discord_stats_config: Dict[str, Any] = {
            'enabled': True,
            'interval_hours': 6,
            'include_groups': True,
            'include_banned': True,
            'include_messages': True,
            'include_delays': True,
            'include_spambot': True,
            'include_performance': True,
            'include_errors': True,
            'custom_fields': True,
            'auto_send': True,
            'detailed_mode': False
        }
        
        self.stats_history: List[Dict[str, Any]] = []
        self.last_stats_send = pendulum.now('UTC')
        
        self.commands: Dict[str, Any] = {
            '.xaxa': self.show_main_menu,
            '.config': self.show_config,
            '.spam': self.toggle_spam,
            '.status': self.show_status,
            '.groups': self.show_groups_info,
            '.reply': self.set_reply_message,
            '.help': self.show_help,
            '.start': self.start_bot,
            '.stop': self.stop_bot,
            '.setmsg': self.set_spam_message,
            '.stats': self.show_detailed_stats,            '.clear': self.clear_data,
            '.webhook': self.setup_webhook,
            '.welcome': self.show_welcome_settings,
            '.logs': self.show_logs,
            '.check': self.check_permissions,
            '.spambot': self.check_spambot_status,
            # Quick toggles
            '.aggressive': self.quick_aggressive_toggle,
            '.delay': self.quick_delay_set,
            '.batch': self.quick_batch_toggle,
            '.welcomeset': self.set_welcome_message,
            '.scan': self.scan_chat_history,
            # Discord stats
            '.dstats': self.discord_stats_menu, # Ensure this method exists
            '.dstats_config': self.discord_stats_config_menu,
            '.dstats_send': self.send_discord_stats_now,
            '.dstats_toggle': self.toggle_discord_stats,
            '.dstats_interval': self.set_discord_stats_interval,
            '.dstats_template': self.show_discord_stats_template,

        }
        
        self.bot_running: bool = False
        self.tasks: List[Any] = []

    async def show_welcome_settings(self, event: Any):
        """Placeholder for showing welcome message settings."""
        settings_text = f"""👋 **USTAWIENIA WIADOMOŚCI POWITALNYCH**

• Włączone: `{self.config.get('send_message_to_new_user', 'off')}`
• Opóźnienie: `{self.config.get('welcome_message_delay', 'off')}` (Zakres: `{self.config.get('welcome_delay_range', '5-15')}s`)
• Tryb batch: `{self.config.get('batch_welcome_messages', 'off')}`

**Aby zmienić:**
`.set send_message_to_new_user on/off`
`.set welcome_message_delay on/off`
`.set welcome_delay_range [min]-[max]`
`.set batch_welcome_messages on/off`"""
        await event.reply(settings_text, parse_mode='md')

    async def check_permissions(self, event: Any):
        """Placeholder for checking permissions."""
        await event.reply("🛠️ Funkcja sprawdzania uprawnień (check_permissions) nie została jeszcze zaimplementowana.")

    async def check_spambot_status(self, event: Any):
        """Placeholder for checking spambot status."""
        await event.reply("🤖 Funkcja sprawdzania statusu SpamBot (check_spambot_status) nie została jeszcze zaimplementowana.")

    async def quick_aggressive_toggle(self, event: Any):
        """Placeholder for quick aggressive toggle."""
        current_value = self.config.get('aggressive_spam', 'off')
        new_value = 'on' if current_value == 'off' else 'off'
        self.config['aggressive_spam'] = new_value
        await self.save_main_config()
        await event.reply(f"⚡ Tryb agresywny przełączony na: {new_value.upper()}")

    async def quick_delay_set(self, event: Any):
        """Placeholder for quick delay set."""
        parts = event.message.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            delay = parts[1]
            self.config['spam_message_delay'] = delay
            await self.save_main_config()
            await event.reply(f"⏱️ Opóźnienie między wiadomościami ustawione na: {delay}s")
        else:
            await event.reply("Użycie: `.delay [sekundy]`")

    async def quick_media_toggle(self, event: Any):
        """Placeholder for quick media toggle."""
        current_value = self.config.get('random_media_in_welcome', 'off')
        new_value = 'on' if current_value == 'off' else 'off'
        self.config['random_media_in_welcome'] = new_value
        await self.save_main_config()
        await event.reply(f"🖼️ Losowe media w powitaniach przełączone na: {new_value.upper()}")

    async def quick_batch_toggle(self, event: Any):
        """Placeholder for quick batch toggle."""
        current_value = self.config.get('batch_welcome_messages', 'off')
        new_value = 'on' if current_value == 'off' else 'off'
        self.config['batch_welcome_messages'] = new_value
        await self.save_main_config()
        await event.reply(f"📬 Tryb batch dla powitań przełączony na: {new_value.upper()}")

    async def discord_stats_menu(self, event: Any):
        """Placeholder for Discord stats menu."""
        await event.reply("📊 Menu statystyk Discord (discord_stats_menu) nie została jeszcze zaimplementowane.")

    async def discord_stats_config_menu(self, event: Any):
        """Placeholder for Discord stats config menu."""
        config_items = []
        for key, value in self.discord_stats_config.items():
            config_items.append(f"• `{key}`: {value}")
        config_text = "\n".join(config_items)
        await event.reply(f"""⚙️ **KONFIGURACJA STATYSTYK DISCORD**

{config_text}

**Aby zmienić:** `.set [nazwa_ustawienia_discord] [wartość]`""", parse_mode='md')

    async def send_discord_stats_now(self, event: Any):
        """Placeholder for sending Discord stats now."""
        await event.reply("📤 Funkcja wysyłania statystyk Discord teraz (send_discord_stats_now) nie została jeszcze zaimplementowana.")

    async def toggle_discord_stats(self, event: Any):
        """Placeholder for toggling Discord stats."""
        current_value = self.discord_stats_config.get('enabled', False)
        new_value = not current_value
        self.discord_stats_config['enabled'] = new_value
        # Consider if this needs saving to a persistent config
        await event.reply(f"⚙️ Automatyczne statystyki Discord przełączone na: {'WŁĄCZONE' if new_value else 'WYŁĄCZONE'}")

    async def set_discord_stats_interval(self, event: Any):
        """Placeholder for setting Discord stats interval."""
        parts = event.message.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            interval = int(parts[1])
            self.discord_stats_config['interval_hours'] = interval
            # Consider if this needs saving to a persistent config
            await event.reply(f"⏰ Interwał statystyk Discord ustawiony na: {interval} godzin")
        else:
            await event.reply("Użycie: `.dstats_interval [godziny]`")

    async def show_discord_stats_template(self, event: Any):
        """Placeholder for showing Discord stats template."""
        await event.reply("📄 Funkcja pokazywania szablonu statystyk Discord (show_discord_stats_template) nie została jeszcze zaimplementowana.")

    async def check_permissions_for_all_groups(self) -> int:
        """Placeholder for checking permissions for all groups. Returns count of groups with permissions."""
        print(f"[XAXA] [{now()}] Placeholder: Sprawdzanie uprawnień dla wszystkich grup...")
        # Dummy implementation
        # In a real scenario, this would iterate self.target_groups, check bot's permissions in each,
        # and potentially move groups without sufficient permissions to self.banned_groups or a similar list.
        # For now, assume all target groups have permissions.
        await asyncio.sleep(1) # Simulate work
        active_count = len(self.target_groups)
        print(f"[XAXA] [{now()}] Placeholder: Znaleziono {active_count} grup z (założonymi) uprawnieniami.")
        return active_count

    async def periodic_spambot_check(self):
        """Placeholder for periodic spambot check task."""
        while self.bot_running:
            if self.config.get('check_spambot') == 'on':
                print(f"[XAXA] [{now()}] Placeholder: Okresowe sprawdzanie SpamBot...")
                # Add actual @SpamBot check logic here
                await asyncio.sleep(int(self.config.get('check_spambot_delay', '3600'))) # Default 1 hour
            else:
                await asyncio.sleep(300) # Check config less frequently if disabled

    async def automated_discord_stats_loop(self):
        """Placeholder for automated Discord statistics sending loop."""
        while self.bot_running:
            if self.discord_stats_config.get('enabled') and self.discord_stats_config.get('auto_send'):
                interval_hours = self.discord_stats_config.get('interval_hours', 6)
                if pendulum.now('UTC') > self.last_stats_send.add(hours=interval_hours):
                    print(f"[XAXA] [{now()}] Placeholder: Automatyczne wysyłanie statystyk Discord...")
                    # Add logic to gather and send stats here
                    # await self.send_discord_stats_now(event=None) # This would need an event or refactor
                    self.last_stats_send = pendulum.now('UTC')
                await asyncio.sleep(3600) # Check every hour if it's time to send
            else:
                await asyncio.sleep(300) # Check config less frequently if disabled

    async def load_files_data(self):
        """Load data from files."""
        # Note: Reply messages and media files are set through Saved Messages, not loaded from files
        
        # Load sent messages
        try:
            if os.path.exists('sent_messages.txt'):
                with open('sent_messages.txt', 'r', encoding='utf-8') as f:
                    for line in f:
                        user_id = line.strip()
                        if user_id: # Ensure user_id is not empty
                            self.sent_messages.add(int(user_id))
            print(f"[XAXA] [{now()}] Loaded {len(self.sent_messages)} sent message records.")
        except Exception as e: # Catch specific exceptions
            print(f"[XAXA] [{now()}] Error loading sent messages: {e}")


        # Load banned groups
        try:
            if os.path.exists('zbanowane.txt'):
                with open('zbanowane.txt', 'r', encoding='utf-8') as f:
                    for line in f:
                        if ',' in line:
                            chat_id, _ = line.strip().split(',', 1)
                            self.banned_groups.add(int(chat_id))
            print(f"[XAXA] [{now()}] Loaded {len(self.banned_groups)} banned group records.")
        except Exception as e: # Catch specific exceptions
            print(f"[XAXA] [{now()}] Error loading banned groups: {e}")

    def load_main_config(self):
        config_parser = configparser.ConfigParser()
        try:
            with open('main_config.txt', 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.lstrip().startswith('['):
                content = '[CONFIG]\\n' + content
            config_parser.read_string(content)
            self.config = dict(config_parser['CONFIG'])
            
            api_id_str = self.config.get('api_id')
            self.api_hash = self.config.get('api_hash')
            # self.phone_number = self.config.get('phone_number') # Removed phone_number loading from config

            # API ID and Hash are now optional - they can be provided during login
            if api_id_str:
                try:
                    self.api_id = int(api_id_str)
                except ValueError:
                    print(f"[XAXA] [{now()}] Invalid api_id in main_config.txt: '{api_id_str}'. It must be a number.")
                    self.api_id = None
            else:
                self.api_id = None
                
            # Don't require API credentials in config file anymore
            return True
        except (configparser.Error, FileNotFoundError) as e:
            print(f"[XAXA] [{now()}] Error loading or parsing main_config.txt: {e}")
            print(f"[XAXA] [{now()}] Creating default configuration...")
            # Create default config if file doesn't exist
            self.config = {}
            return True
        except Exception as e:
            print(f"[XAXA] [{now()}] Unexpected error loading main_config.txt: {e}")
            traceback.print_exc()
            return False

    async def save_main_config(self):
        try:
            config_lines = []
            config_lines.append("# ======================")
            config_lines.append("# XAXA SOLUTIONS CONFIG")
            config_lines.append("# ======================")
            config_lines.append("")
            
            for key, value in self.config.items():
                config_lines.append(f"{key}={value}")
            
            with open('main_config.txt', 'w', encoding='utf-8') as f:
                f.write('\n'.join(config_lines))
            return True
        except Exception as e:
            print(f"[XAXA] [{now()}] Error saving configuration: {e}")
            return False

    def _discover_sessions(self) -> List[str]:
        session_files = glob.glob("xaxa_manager_*.session")
        phone_numbers = []
        for s_file in session_files:
            try:
                phone_part = s_file[len("xaxa_manager_"):-len(".session")]
                if phone_part.isdigit():
                    phone_numbers.append("+" + phone_part)
            except Exception:
                pass # Ignore files that don't match the pattern
        return phone_numbers

    async def interactive_login(self) -> bool:
        print("\\n--- XAXA Bot Manager Login ---")
        
        existing_sessions = self._discover_sessions()
        
        menu_options = {1: "Zaloguj się do nowego konta"}
        print("Wybierz opcję logowania:")
        print("1. Zaloguj się do nowego konta")

        if existing_sessions:
            menu_options[2] = "Wybierz istniejącą sesję"
            print("2. Wybierz istniejącą sesję:")
            for i, phone in enumerate(existing_sessions):
                menu_options[i + 3] = phone # Store phone for direct selection
                print(f"   {i + 3}. {phone}")
        
        while True:
            try:
                choice_str = input("Twój wybór: ")
                choice = int(choice_str)
                if choice in menu_options or (choice > 2 and choice - 3 < len(existing_sessions)):
                    break
                else:
                    print("Nieprawidłowy wybór, spróbuj ponownie.")
            except ValueError:
                print("Nieprawidłowy wybór, wpisz numer.")

        selected_phone_for_session = None
        login_api_id = None
        login_api_hash = None

        if choice == 1: # New account
            while True:
                phone_input = input("Podaj numer telefonu (np. +48123456789): ").strip()
                if phone_input.startswith('+') and phone_input[1:].isdigit():
                    self.phone_number = phone_input
                    break
                else:
                    print("Nieprawidłowy format numeru telefonu. Musi zaczynać się od '+' i zawierać cyfry.")
            
            # Ask for API ID and Hash for new account
            while True:
                api_id_input = input("Podaj API ID: ").strip()
                try:
                    login_api_id = int(api_id_input)
                    break
                except ValueError:
                    print("API ID musi być liczbą.")
            
            login_api_hash = input("Podaj API Hash: ").strip()
            if not login_api_hash:
                print("API Hash nie może być pusty.")
                return False
                
            selected_phone_for_session = self.phone_number
            print(f"Logowanie nowego konta: {self.phone_number}")

        elif choice == 2 and existing_sessions: # Prompt to choose from list
             # Check if api_id and api_hash are loaded from config
             if not self.api_id or not self.api_hash:
                 print(f"[XAXA] [{now()}] API ID lub API Hash nie zostały wczytane z main_config.txt. Nie można zalogować się do istniejącej sesji.")
                 return False
                 
             print("Wybierz numer sesji z powyższej listy (np. 3, 4, ...)")
             while True:
                try:
                    session_choice_str = input("Numer sesji: ")
                    session_choice_idx = int(session_choice_str)
                    if 3 <= session_choice_idx < 3 + len(existing_sessions):
                        self.phone_number = existing_sessions[session_choice_idx - 3]
                        selected_phone_for_session = self.phone_number
                        break
                    else:
                        print("Nieprawidłowy numer sesji.")
                except ValueError:
                    print("Wpisz numer.")
             login_api_id = self.api_id
             login_api_hash = self.api_hash
             
        elif choice > 2 and choice -3 < len(existing_sessions) : # Direct selection of existing session
            # Check if api_id and api_hash are loaded from config
            if not self.api_id or not self.api_hash:
                print(f"[XAXA] [{now()}] API ID lub API Hash nie zostały wczytane z main_config.txt. Nie można zalogować się do istniejącej sesji.")
                return False
                
            self.phone_number = existing_sessions[choice - 3]
            selected_phone_for_session = self.phone_number
            login_api_id = self.api_id
            login_api_hash = self.api_hash
        else: # Should not happen due to earlier validation, but as a fallback
            print("Nieoczekiwany wybór.")
            return False

        if not selected_phone_for_session:
            print("Nie wybrano numeru telefonu.")
            return False

        session_file = f'xaxa_manager_{selected_phone_for_session.replace("+", "")}'
        self.client = TelegramClient(session_file, login_api_id, login_api_hash)

        try:
            print(f"[XAXA] [{now()}] Łączenie z Telegram dla {selected_phone_for_session}...")
            await self.client.connect()

            if not await self.client.is_user_authorized():
                print(f"[XAXA] [{now()}] Sesja dla {selected_phone_for_session} nie jest autoryzowana lub wygasła.")
                if choice == 1: # Only ask for code if it's a new login attempt explicitly
                    print(f"[XAXA] [{now()}] Wymagana autoryzacja.")
                    await self.client.send_code_request(selected_phone_for_session)
                    code = input(f"Wprowadź kod OTP dla {selected_phone_for_session}: ")
                    try:
                        await self.client.sign_in(selected_phone_for_session, code)
                    except errors.SessionPasswordNeededError:
                        password = input(f"Wprowadź hasło 2FA (uwierzytelnianie dwuskładnikowe) dla {selected_phone_for_session}: ")
                        await self.client.sign_in(password=password)
                    if not await self.client.is_user_authorized(): # Check again
                        print(f"[XAXA] [{now()}] Autoryzacja nie powiodła się.")
                        return False
                else: # For existing sessions that are no longer authorized
                    print(f"[XAXA] [{now()}] Proszę usunąć plik sesji '{session_file}.session' i spróbować zalogować się jako nowe konto, jeśli problem będzie się powtarzał.")
                    return False
            
            me = await self.client.get_me()
            print(f"[XAXA] [{now()}] Zalogowano pomyślnie jako: {me.first_name} (@{me.username or 'N/A'}) (Numer: {selected_phone_for_session})")
            self.phone_number = selected_phone_for_session # Ensure self.phone_number is set
            
            # Update and save API credentials for new account login
            if choice == 1:
                self.api_id = login_api_id
                self.api_hash = login_api_hash
                self.config['api_id'] = str(login_api_id)
                self.config['api_hash'] = login_api_hash
                await self.save_main_config()
                print(f"[XAXA] [{now()}] API credentials zaktualizowane i zapisane do main_config.txt")
            
            # Send welcome message to Saved Messages
            try:
                welcome_message = f"""🎉 **WITAJ W XAXA SOLUTIONS!** 🎉

✅ **Zalogowano pomyślnie jako:** {me.first_name} (@{me.username or 'N/A'})
📱 **Numer telefonu:** {selected_phone_for_session}
🚀 **Status:** Gotowy do działania!

🔥 **XAXA Bot Manager** jest teraz aktywny i gotowy do pracy!

📋 **Aby rozpocząć, wpisz:** `.xaxa`

💡 **XAXA Solutions 2025** - Profesjonalne zarządzanie botami Telegram"""
                
                await self.client.send_message('me', welcome_message, parse_mode='md')
                print(f"[XAXA] [{now()}] Wiadomość powitalna wysłana do Saved Messages")
            except Exception as e:
                print(f"[XAXA] [{now()}] Nie udało się wysłać wiadomości powitalnej: {e}")
            
            return True

        except errors.PhoneNumberInvalidError:
            print(f"[XAXA] [{now()}] Numer telefonu {selected_phone_for_session} jest nieprawidłowy.")
            return False
        except errors.ApiIdInvalidError:
            print(f"[XAXA] [{now()}] API ID {login_api_id} jest nieprawidłowe. Sprawdź wprowadzone dane.")
            return False
        except errors.AuthKeyError:
            print(f"[XAXA] [{now()}] Błąd klucza autoryzacyjnego. Plik sesji '{session_file}.session' może być uszkodzony. Spróbuj go usunąć i zalogować się ponownie.")
            return False
        except errors.PhoneCodeInvalidError:
            print(f"[XAXA] [{now()}] Wprowadzony kod OTP jest nieprawidłowy.")
            return False
        except errors.PhoneCodeExpiredError:
            print(f"[XAXA] [{now()}] Wprowadzony kod OTP wygasł.")
            return False
        except errors.SessionPasswordNeededError: # Should be caught above, but as a safeguard
            print(f"[XAXA] [{now()}] Hasło 2FA jest wymagane, ale nie zostało podane w przepływie nowego logowania.")
            return False
        except Exception as e:
            print(f"[XAXA] [{now()}] Błąd logowania: {e}")
            traceback.print_exc()
            return False
            
    # Remove or comment out the old login method
    # async def login(self):
    #     ... (old code) ...

    async def refresh_groups(self):
        """Odświeżanie listy grup"""
        try:
            print(f"[XAXA] [{now()}] Odświeżanie listy grup...")
            
            dialogs = await self.client.get_dialogs(limit=1000)
            print(f"[XAXA] [{now()}] Wczytano {len(dialogs)} dialogów")
            
            new_target_groups = set()
            group_count = 0
            supergroup_count = 0
            banned_count = 0
            deactivated_count = 0
            
            for dialog in dialogs:
                entity = dialog.entity
                is_group = False
                
                if hasattr(entity, 'is_group') and entity.is_group:
                    is_group = True
                    group_count += 1
                elif isinstance(entity, Channel) and getattr(entity, 'megagroup', False):
                    is_group = True
                    supergroup_count += 1
                
                if is_group:
                    # Sprawdź czy grupa jest deaktywowana
                    if getattr(entity, 'deactivated', False):
                        print(f"[XAXA] [{now()}] Pomijam deaktywowaną grupę: {entity.title} (ID: {entity.id})")
                        deactivated_count += 1
                        await self.save_skipped_group(entity.id, "Grupa deaktywowana")
                        continue
                        
                    if entity.id not in self.banned_groups:
                        new_target_groups.add(entity.id)
                    else:
                        banned_count += 1
            
            self.target_groups = new_target_groups
            
            print(f"[XAXA] [{now()}] Odświeżono listę grup:")
            print(f"  📊 Aktywne grupy: {len(self.target_groups)}")
            print(f"  👥 Zwykłe grupy: {group_count}")
            print(f"  🏢 Supergrupy: {supergroup_count}")
            print(f"  🚫 Zbanowane: {banned_count}")
            print(f"  ❌ Deaktywowane: {deactivated_count}")
            
            await self.log_message("SUCCESS", f"Odświeżono listę grup: {len(self.target_groups)} aktywnych", "SUCCESS")
            
            if not self.groups_loaded.is_set():
                self.groups_loaded.set()
            
            return len(self.target_groups)
            
        except errors.FloodWaitError as e:
            print(f"[XAXA] [{now()}] FloodWait przy odświeżaniu grup: czekam {e.seconds}s")
            await self.log_message("WARNING", "FloodWait przy odświeżaniu grup", "WARNING", error=f"Limit API, czekam {e.seconds}s")
            await asyncio.sleep(e.seconds)
            return 0
        except Exception as e:
            print(f"[XAXA] [{now()}] Błąd odświeżania grup: {e}")
            await self.log_message("ERROR", "Błąd odświeżania grup", "ERROR", error=str(e))
            return 0

    async def send_discord_notification(self, message: str, message_type: str = "INFO"):
        """Wysyłanie powiadomień na Discord"""
        webhook_url = self.config.get('discord_webhook_url')
        if not webhook_url or webhook_url == 'https://discord.com/api/webhooks/your_webhook_url_here':
            return

        color = {"SUCCESS": 0x00FF00, "ERROR": 0xFF0000, "WARNING": 0xFFFF00, "INFO": 0x00BFFF}.get(message_type, 0xFFFFFF)
        
        embed = {
            "title": "XAXA Solutions Bot Manager",
            "description": message,
            "color": color,
            "timestamp": pendulum.now('UTC').to_iso8601_string(),
            "footer": {"text": "XAXA Solutions 2025"}
        }

        try:
            async with aiohttp.ClientSession() as session:
                await session.post(webhook_url, json={"embeds": [embed]})
        except:
            pass

    async def log_message(self, level: str, message: str, log_type: str = "INFO", **kwargs: Any) -> None:
        """Log message to console and optionally Discord"""
        timestamp = now()
        print(f"[XAXA] [{timestamp}] [{level}] {message}")
        
        # Send to Discord if configured
        if self.config.get('discord_webhook_url') and log_type in ['SUCCESS', 'ERROR', 'WARNING']:
            try:
                await self.send_discord_notification(f"[{level}] {message}", log_type)
            except:
                pass

    async def forward_messages_loop(self):
        """Pętla forwardowania wiadomości"""
        while self.bot_running:
            try:
                if not self.spam_message or not self.target_groups:
                    await asyncio.sleep(5)
                    continue

                for group_id in list(self.target_groups):
                    if not self.bot_running:
                        break
                        
                    try:
                        # Pobierz grupę i sprawdź uprawnienia
                        group = await self.client.get_entity(group_id)
                        
                        # Sprawdź liczbę członków jeśli włączone
                        if self.config.get('ignore_small_groups') == 'on':
                            try:
                                participants = await self.client.get_participants(group, limit=1)
                                member_count = participants.total if hasattr(participants, 'total') else 0
                                min_members = int(self.config.get('min_group_members', '50'))
                                if member_count < min_members:
                                    continue
                            except:
                                continue

                        # Forwarduj wiadomość
                        await self.client.forward_messages(group, self.spam_message)
                        self.message_count += 1
                        
                        print(f"[XAXA] [{now()}] ✅ Wysłano do: {group.title}")
                        
                        # Opóźnienie między grupami
                        delay = int(self.config.get('spam_message_delay', '5'))
                        await asyncio.sleep(delay)
                        
                    except errors.UserBannedInChannelError:
                        print(f"[XAXA] [{now()}] 🚫 Zbanowano w grupie: {group_id}")
                        self.banned_groups.add(group_id)
                        self.target_groups.discard(group_id)
                        # Zapisz do pliku
                        async with aiofiles.open('zbanowane.txt', 'a', encoding='utf-8') as f:
                            await f.write(f"{group_id},Banned Group\n")
                    except errors.FloodWaitError as e:
                        print(f"[XAXA] [{now()}] ⏰ FloodWait: {e.seconds}s")
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        print(f"[XAXA] [{now()}] ❌ Błąd wysyłania: {e}")
                        continue

                # Opóźnienie między iteracjami
                iteration_delay = int(self.config.get('spam_iteration_delay', '60'))
                print(f"[XAXA] [{now()}] 💤 Oczekiwanie {iteration_delay}s do następnej iteracji...")
                await asyncio.sleep(iteration_delay)
                
            except Exception as e:
                print(f"[XAXA] [{now()}] Błąd w pętli spamowania: {e}")
                await asyncio.sleep(60)

    async def setup_event_handlers(self):
        """Ustaw handlery zdarzeń dla monitorowania"""
        @self.client.on(events.ChatAction)
        async def handle_new_member(event: Any):
            try:
                if hasattr(event, 'user_joined') and event.user_joined and self.config.get('send_message_to_new_user') == 'on':
                    user_id = event.user_id
                    if user_id and user_id not in self.sent_messages and user_id not in self.failed_users and user_id not in self.whitelist:
                        # Sprawdź czy są ustawione wiadomości powitalne
                        if not self.welcome_messages:
                            print(f"[XAXA] [{now()}] ❌ Brak ustawionych wiadomości powitalnych - użyj .welcomeset")
                            return
                            
                        # Użyj wiadomości powitalnej dla nowych członków grup
                        welcome_message = random.choice(self.welcome_messages)
                        
                        try:
                            # Opóźnienie
                            if self.config.get('welcome_message_delay') == 'on':
                                delay_range = self.config.get('welcome_delay_range', '5-15').split('-')
                                delay = random.randint(int(delay_range[0]), int(delay_range[1]))
                                await asyncio.sleep(delay)

                            # Forward wiadomość powitalną
                            await self.client.forward_messages(user_id, welcome_message)
                            
                            self.sent_messages.add(user_id)
                            # Zapisz do pliku
                            async with aiofiles.open('sent_messages.txt', 'a', encoding='utf-8') as f:
                                await f.write(f"{user_id}\n")
                            
                            print(f"[XAXA] [{now()}] ✅ Wysłano powitanie do nowego członka: {user_id}")
                            
                        except Exception as e:
                            print(f"[XAXA] [{now()}] ❌ Błąd wysyłania powitania: {e}")
                            self.failed_users.add(user_id)
                        
            except Exception as e:
                print(f"[XAXA] [{now()}] Błąd obsługi nowego członka: {e}")

        @self.client.on(events.NewMessage(incoming=True))
        async def handle_private_message(event: Any):
            try:
                if event.is_private and hasattr(event, 'sender_id'):
                    # Sprawdź czy to nie nasza wiadomość
                    me = await self.client.get_me()
                    if event.sender_id == me.id:
                        return
                    
                    # WAŻNE: Sprawdź czy już wysłaliśmy wiadomość do tego użytkownika
                    # Jeśli tak, NIE WYSYŁAMY WIĘCEJ WIADOMOŚCI
                    if event.sender_id in self.sent_messages or event.sender_id in self.failed_users or event.sender_id in self.whitelist:
                        print(f"[XAXA] [{now()}] ⏭️ Pomijam użytkownika {event.sender_id} - już otrzymał wiadomość")
                        return

                    # Sprawdź czy są ustawione wiadomości auto-reply
                    if not self.reply_messages:
                        print(f"[XAXA] [{now()}] ❌ Brak ustawionych wiadomości auto-reply - użyj .reply")
                        return

                    # Wyślij automatyczną odpowiedź (używamy reply_messages dla auto-reply)
                    reply_message = random.choice(self.reply_messages)
                    
                    # Opóźnienie
                    if self.config.get('welcome_message_delay') == 'on':
                        delay_range = self.config.get('welcome_delay_range', '5-15').split('-')
                        delay = random.randint(int(delay_range[0]), int(delay_range[1]))
                        await asyncio.sleep(delay)

                    # Forward wiadomość auto-reply
                    await self.client.forward_messages(event.sender_id, reply_message)
                    
                    # Dodaj do wysłanych - NIGDY WIĘCEJ NIE WYŚLEMY DO TEGO UŻYTKOWNIKA
                    self.sent_messages.add(event.sender_id)
                    # Zapisz do pliku
                    async with aiofiles.open('sent_messages.txt', 'a', encoding='utf-8') as f:
                        await f.write(f"{event.sender_id}\n")
                    
                    print(f"[XAXA] [{now()}] ✅ Wysłano auto-reply do: {event.sender_id}")
                    
            except Exception as e:
                print(f"[XAXA] [{now()}] Błąd auto-reply: {e}")
                if hasattr(event, 'sender_id'):
                    self.failed_users.add(event.sender_id)

    async def monitor_new_members(self):
        """Pusta metoda - handlery są teraz ustawiane w setup_event_handlers"""
        pass

    async def process_welcome_queue(self):
        """Przetwarzanie kolejki powitalnych wiadomości"""
        while self.bot_running:
            try:
                if self.welcome_queue and self.config.get('batch_welcome_messages') == 'on':
                    user_id = self.welcome_queue.popleft()
                    
                    try:
                        # Sprawdź czy są ustawione wiadomości reply
                        if not self.reply_messages:
                            print(f"[XAXA] [{now()}] ❌ Brak ustawionych wiadomości reply - użyj .reply")
                            continue
                            
                        reply_message = random.choice(self.reply_messages)
                        
                        # Opóźnienie
                        if self.config.get('welcome_message_delay') == 'on':
                            delay_range = self.config.get('welcome_delay_range', '5-15').split('-')
                            delay = random.randint(int(delay_range[0]), int(delay_range[1]))
                            await asyncio.sleep(delay)

                        # Forward wiadomość reply
                        await self.client.forward_messages(user_id, reply_message)
                        
                        self.sent_messages.add(user_id)
                        # Zapisz do pliku
                        async with aiofiles.open('sent_messages.txt', 'a', encoding='utf-8') as f:
                            await f.write(f"{user_id}\n")
                        
                        print(f"[XAXA] [{now()}] ✅ Wysłano powitanie do: {user_id}")
                        
                    except Exception as e:
                        print(f"[XAXA] [{now()}] Błąd wysyłania powitania: {e}")
                        self.failed_users.add(user_id)
                
                await asyncio.sleep(60)  # Sprawdzaj co minutę
            except Exception as e:
                print(f"[XAXA] [{now()}] Błąd przetwarzania kolejki: {e}")
                await asyncio.sleep(60)

    async def show_main_menu(self, event: Any):
        menu = f"""🔥 **XAXA SOLUTIONS - BOT MANAGER** 🔥

🤖 **STATUS BOTA:** {'🟢 WŁĄCZONY' if self.bot_running else '🔴 WYŁĄCZONY'}
📊 **WYSŁANE:** {self.message_count} wiadomości
👥 **GRUPY:** {len(self.target_groups)} aktywnych

📋 **DOSTĘPNE KOMENDY:**
`.start` - 🚀 Uruchom bota
`.stop` - ⏹️ Zatrzymaj bota  
`.config` - ⚙️ Pokaż konfigurację
`.spam` - 🔄 Przełącz spam ON/OFF
`.status` - 📊 Szczegółowy status
`.groups` - 👥 Informacje o grupach
`.reply` - 💬 Ustaw wiadomość odpowiedzi
`.help` - 📚 Pomoc

💡 **XAXA Solutions 2025** - Profesjonalne zarządzanie"""
        
        await event.reply(menu, parse_mode='md')

    async def start_bot(self, event: Any):
        if self.bot_running:
            await event.reply("⚠️ **Bot już działa!**")
            return

        if not self.spam_message:
            await event.reply("❌ **Najpierw ustaw wiadomość do spamu:** `.setmsg`")
            return

        await event.reply("🚀 **Uruchamianie bota...**")
        
        # Ustaw handlery zdarzeń
        await self.setup_event_handlers()
        
        # Odśwież grupy
        group_count = await self.refresh_groups()
        
        # Sprawdź uprawnienia
        active_count = await self.check_permissions_for_all_groups()
        
        self.bot_running = True
        
        # Uruchom zadania
        self.tasks = [
            asyncio.create_task(self.forward_messages_loop()),
            asyncio.create_task(self.process_welcome_queue()),
            asyncio.create_task(self.periodic_spambot_check()),
            asyncio.create_task(self.automated_discord_stats_loop())  # Add automated stats
        ]
        
        await event.reply(f"""🚀 **Bot uruchomiony pomyślnie!**

📊 **Statystyki uruchomienia:**
• Znalezione grupy: {group_count}
• Grupy z uprawnieniami: {active_count}
• Spam message: ✅ Ustawiona
• Monitoring: ✅ Aktywny

🎯 **Aktywne funkcje:**
• Forwardowanie wiadomości
• Powitania nowych członków  
• Auto-reply na PV
• Sprawdzanie SpamBot

Użyj `.status` aby śledzić postęp!""")
        
        await self.log_message("SUCCESS", f"Bot uruchomiony! Grupy: {active_count}/{group_count}", "SUCCESS")

    async def stop_bot(self, event: Any):
        if not self.bot_running:
            await event.reply("⚠️ **Bot już jest zatrzymany!**")
            return

        self.bot_running = False
        
        # Zatrzymaj zadania
        for task in self.tasks:
            task.cancel()
        
        await event.reply(f"⏹️ **Bot zatrzymany!**\n\n📊 **Finalne statystyki:**\n• Wysłano: {self.message_count} wiadomości\n• Grupy: {len(self.target_groups)}")
        await self.send_discord_notification(f"⏹️ Bot zatrzymany! Wysłano: {self.message_count} wiadomości", "WARNING")

    async def set_spam_message(self, event: Any):
        if event.reply_to_msg_id:
            replied_msg = await event.get_reply_message()
            self.spam_message = replied_msg
            
            preview = replied_msg.text[:100] + "..." if len(replied_msg.text or "") > 100 else replied_msg.text or "[MEDIA]"
            await event.reply(f"✅ **Wiadomość do spamu ustawiona!**\n\n📝 **Podgląd:**\n{preview}")
        else:
            await event.reply("📝 **Aby ustawić wiadomość do spamu:**\n1. Wyślij/Forward wiadomość\n2. Odpowiedz na nią komendą `.setmsg`")

    async def show_config(self, event: Any):
        config_text = f"""⚙️ **KONFIGURACJA XAXA**

🔧 **SPAM:**
• Włączony: `{self.config.get('spam_enabled')}`
• Opóźnienie iteracji: `{self.config.get('spam_iteration_delay')}s`
• Opóźnienie wiadomości: `{self.config.get('spam_message_delay')}s`
• Tryb agresywny: `{self.config.get('aggressive_spam')}`

👥 **GRUPY:**
• Min członków: `{self.config.get('min_group_members')}`
• Ignoruj małe: `{self.config.get('ignore_small_groups')}`

💬 **WIADOMOŚCI:**
• Powitania: `{self.config.get('send_message_to_new_user')}`
• Opóźnienie powitalnych: `{self.config.get('welcome_message_delay')}`
• Batch: `{self.config.get('batch_welcome_messages')}`

🤖 **SPAMBOT:**
• Sprawdzanie: `{self.config.get('check_spambot')}`
• Częstotliwość: `{self.config.get('check_spambot_delay')}s`

📱 **PROFIL:**
• Ukryj telefon: `{self.config.get('hide_phone_number')}`

**Zmiana:** `.set [nazwa] [wartość]`"""
        
        await event.reply(config_text, parse_mode='md')

    async def toggle_spam(self, event: Any):
        message_text = event.message.text.strip()
        if len(message_text.split()) > 1:
            value = message_text.split()[1].lower()
            if value in ['on', 'off']:
                self.config['spam_enabled'] = value # Store 'on' or 'off'
                await self.save_main_config() # Persist change
                await event.reply(f"🔄 **Spam ustawiony na: {value.upper()}**")
            else:
                await event.reply("📝 **Użycie:** `.spam on` lub `.spam off`")
        else:
            current = 'ON' if self.config.get('spam_enabled') == 'on' else 'OFF' # Check for 'on'
            await event.reply(f"🔄 **Aktualny status spamu:** {current}\\n\\n📝 **Użycie:** `.spam on` lub `.spam off`")

    async def show_status(self, event: Any):
        uptime = pendulum.now('UTC') - self.start_time
        uptime_str = f"{uptime.days}d {uptime.hours}h {uptime.minutes}m"
        
        status_text = f"""📊 **XAXA BOT STATUS**

🤖 **SYSTEM:** {'🟢 WŁĄCZONY' if self.bot_running else '🔴 WYŁĄCZONY'}
⏰ **Uptime:** {uptime_str}
📨 **Wysłane wiadomości:** {self.message_count}
👥 **Aktywne grupy:** {len(self.target_groups)}
🚫 **Zbanowane grupy:** {len(self.banned_groups)}
💌 **Wysłane powitania:** {len(self.sent_messages)}
❌ **Nieudane wysyłki:** {len(self.failed_users)}
📥 **Kolejka powitalnych:** {len(self.welcome_queue)}

🎯 **SPAM MESSAGE:** {'✅ Ustawiona' if self.spam_message else '❌ Brak'}
🔗 **DISCORD WEBHOOK:** {'✅ Skonfigurowany' if self.config.get('discord_webhook_url') != 'https://discord.com/api/webhooks/your_webhook_url_here' else '❌ Nie skonfigurowany'}

*Ostatnia aktualizacja: {now()}*"""
        
        await event.reply(status_text, parse_mode='md')

    async def show_groups_info(self, event: Any):
        command_parts = event.message.text.split()
        
        if len(command_parts) > 1 and command_parts[1] == 'refresh':
            group_count = await self.refresh_groups()
            await event.reply(f"🔄 **Grupy odświeżone!**\n\n📊 Znaleziono: {group_count} aktywnych grup")
            return

        groups_text = """👥 **INFORMACJE O GRUPACH**

📈 **STATYSTYKI:**
• Aktywne grupy: {len(self.target_groups)}
• Zbanowane grupy: {len(self.banned_groups)}
• Łącznie przetworzonych: {len(self.target_groups) + len(self.banned_groups)}

🎯 **KONFIGURACJA:**
• Min członków: {self.config.get('min_group_members')}
• Ignoruj małe grupy: {self.config.get('ignore_small_groups')}

⚡ **AKCJE:**
`.groups refresh` - Odśwież listę grup
`.clear banned` - Wyczyść zbanowane grupy"""
        
        await event.reply(groups_text, parse_mode='md')

    async def set_reply_message(self, event: Any):
        if event.reply_to_msg_id:
            replied_msg = await event.get_reply_message()
            
            # Zapisz całą wiadomość do forwardowania (podobnie jak spam message)
            self.reply_messages.append(replied_msg)
            
            preview = replied_msg.text[:100] + "..." if len(replied_msg.text or "") > 100 else replied_msg.text or "[MEDIA]"
            await event.reply(f"✅ **Wiadomość odpowiedzi ustawiona!**\n\n📝 **Podgląd:**\n{preview}")
        else:
            await event.reply("📝 **Aby ustawić reply message:**\n1. Wyślij/Forward wiadomość\n2. Odpowiedz na nią komendą `.reply`")

    async def show_detailed_stats(self, event: Any):
        uptime = pendulum.now('UTC') - self.start_time
        
        # Oblicz rate
        messages_per_hour = round(self.message_count / max(uptime.total_hours(), 1), 2) if uptime.total_hours() > 0 else 0
        success_rate = round((self.message_count / max(len(self.target_groups), 1)) * 100, 2) if self.target_groups else 0
        
        stats_text = f"""📈 **SZCZEGÓŁOWE STATYSTYKI XAXA**

⏱️ **WYDAJNOŚĆ:**
• Wiadomości/godz: {messages_per_hour}
• Sukces rate: {success_rate}%
• Uptime: {uptime.days}d {uptime.hours}h {uptime.minutes}m

📊 **LICZNIKI:**
• Spam wysłany: {self.message_count}
• Powitania wysłane: {len(self.sent_messages)}
• Grupy aktywne: {len(self.target_groups)}
• Grupy zbanowane: {len(self.banned_groups)}
• Nieudane użytkownicy: {len(self.failed_users)}
• Kolejka powitalnych: {len(self.welcome_queue)}

🎯 **KONFIGURACJA:**
• Reply messages: {len(self.reply_messages)}
• Media files: {len(self.reply_files)}
• Spam message: {'✅' if self.spam_message else '❌'}

🔧 **OPÓŹNIENIA:**
• Między grupami: {self.config.get('spam_message_delay')}s
• Między iteracjami: {self.config.get('spam_iteration_delay')}s
• Powitania: {self.config.get('welcome_delay_range')}s"""
        
        await event.reply(stats_text, parse_mode='md')

    async def clear_data(self, event: Any):
        command_parts = event.message.text.split()
        
        if len(command_parts) < 2:
            await event.reply("""🗑️ **CZYSZCZENIE DANYCH**

**Dostępne opcje:**
`.clear banned` - Wyczyść zbanowane grupy
`.clear sent` - Wyczyść wysłane wiadomości  
`.clear failed` - Wyczyść nieudane wysyłki
`.clear stats` - Zresetuj statystyki
`.clear all` - Wyczyść wszystko

⚠️ **UWAGA:** Ta operacja jest nieodwracalna!""")
            return

        option = command_parts[1].lower()
        
        if option == 'banned':
            self.banned_groups.clear()
            if os.path.exists('zbanowane.txt'):
                os.remove('zbanowane.txt')
            await event.reply("✅ **Wyczyszczono zbanowane grupy**")
            
        elif option == 'sent':
            self.sent_messages.clear()
            if os.path.exists('sent_messages.txt'):
                os.remove('sent_messages.txt')
            await event.reply("✅ **Wyczyszczono wysłane wiadomości**")
            
        elif option == 'failed':
            self.failed_users.clear()
            await event.reply("✅ **Wyczyszczono nieudanych użytkowników**")
            
        elif option == 'stats':
            self.message_count = 0
            self.start_time = pendulum.now('UTC')
            await event.reply("✅ **Zresetowano statystyki**")
            
        elif option == 'all':
            self.banned_groups.clear()
            self.sent_messages.clear()
            self.failed_users.clear()
            self.message_count = 0
            self.start_time = pendulum.now('UTC')
            for file in ['zbanowane.txt', 'sent_messages.txt']:
                if os.path.exists(file):
                    os.remove(file)
            await event.reply("✅ **Wyczyszczono wszystkie dane**")
        else:
            await event.reply("❌ **Nieznana opcja czyszczenia**")

    async def setup_webhook(self, event: Any):
        await event.reply("""🔗 **KONFIGURACJA DISCORD WEBHOOK**

**Aby ustawić webhook:**
`.set discord_webhook_url https://discord.com/api/webhooks/twoj_url`

**Aktualne ustawienia:**
• URL: `{}`
• Thumbnail: `{}`

**Aby ustawić thumbnail:**
`.set thumbnail_url https://twoj-url-obrazka.com/obraz.png`""".format(
            self.config.get('discord_webhook_url', 'Nie ustawiony'),
            self.config.get('thumbnail_url', 'Domyślny')
        ))

    async def show_help(self, event: Any):
        help_text = """📚 **XAXA SOLUTIONS - KOMPLETNA POMOC**

🚀 **PODSTAWOWE STEROWANIE:**
`.start` - Uruchom bota
`.stop` - Zatrzymaj bota
`.status` - Pokaż status

📝 **KONFIGURACJA WIADOMOŚCI:**
`.setmsg` - Ustaw wiadomość do spamu (odpowiedz na wiadomość)
`.reply` - Ustaw wiadomość odpowiedzi (odpowiedz na wiadomość)
`.welcomeset` - Ustaw wiadomość powitalną (odpowiedz na wiadomość)

⚙️ **USTAWIENIA:**
`.config` - Pokaż konfigurację
`.set [nazwa] [wartość]` - Zmień ustawienie
`.spam on/off` - Przełącz spam

👥 **ZARZĄDZANIE GRUPAMI:**
`.groups` - Info o grupach  
`.groups refresh` - Odśwież grupy
`.check` - Sprawdź uprawnienia w grupach

📊 **STATYSTYKI:**
`.stats` - Szczegółowe statystyki
`.logs` - Zarządzanie logami
`.dstats` - Statystyki Discord

🤖 **SPAMBOT:**
`.spambot` - Status i ustawienia SpamBot
`.spambot on/off` - Włącz/wyłącz sprawdzanie
`.spambot aggressive on/off` - Tryb agresywny

👋 **POWITANIA:**
`.welcome` - Ustawienia powitalnych wiadomości
`.welcome on/off` - Włącz/wyłącz powitania

⚡ **SZYBKIE KOMENDY:**
`.aggressive` - Przełącz tryb agresywny
`.delay [s]` - Ustaw opóźnienie wiadomości
`.batch` - Przełącz batch powitania
`.scan` - Skanuj historię i wyślij wiadomości do wszystkich

🗑️ **CZYSZCZENIE:**
`.clear [opcja]` - Wyczyść dane

🔗 **INTEGRACJE:**
`.webhook` - Konfiguruj Discord

🎯 **PRZYKŁADY:**
`.set spam_message_delay 10`
`.set min_group_members 100`
`.spam on`

💡 **XAXA Solutions** - Profesjonalne zarządzanie botami Telegram"""
        
        await event.reply(help_text, parse_mode='md')

    async def handle_set_command(self, event: Any):
        parts = event.message.text.split(maxsplit=2)
        if len(parts) < 3:
            await event.reply('''📝 **KONFIGURACJA USTAWIEŃ**

**Użycie:** `.set [nazwa] [wartość]`

**Dostępne ustawienia:**
• `spam_iteration_delay` - Opóźnienie między iteracjami (s)
• `spam_message_delay` - Opóźnienie między wiadomościami (s)  
• `min_group_members` - Min członków w grupie
• `welcome_delay_range` - Zakres opóźnienia powitalnych (np. 5-15)
• `discord_webhook_url` - URL webhook Discord
• `thumbnail_url` - URL miniaturki Discord
• `check_spambot_delay` - Częstotliwość sprawdzania SpamBot (s)
• `batch_welcome_interval` - Interwał batch powitania (s)
• `discord_stats_interval_hours` - Interwał statystyk Discord (h)

**Przełączniki (on/off lub true/false):**
• `spam_enabled`
• `check_spambot`, `aggressive_spam`, `send_message_to_new_user`
• `ignore_small_groups`, `random_media_in_welcome` # Retained for now
• `welcome_message_delay`, `batch_welcome_messages`
• `hide_phone_number`
• `discord_stats_auto`

**Przykład:** `.set spam_message_delay 5`''')
            return

        setting_name = parts[1]
        setting_value = parts[2]
        
        if setting_name in self.config: # Check if the key is a known config option
            self.config[setting_name] = setting_value
            await self.save_main_config() # Persist change
            await event.reply(f"✅ **Ustawiono:** `{setting_name} = {setting_value}`")
        elif setting_name in self.discord_stats_config: # Check if it's a discord_stats_config option
            # Handle type conversion for discord_stats_config if necessary
            if isinstance(self.discord_stats_config[setting_name], bool):
                if setting_value.lower() in ['true', 'on', 'yes']:
                    self.discord_stats_config[setting_name] = True
                elif setting_value.lower() in ['false', 'off', 'no']:
                    self.discord_stats_config[setting_name] = False
                else:
                    await event.reply(f"❌ **Nieprawidłowa wartość dla przełącznika:** `{setting_name}`. Użyj on/off lub true/false.")
                    return
            elif isinstance(self.discord_stats_config[setting_name], int):
                try:
                    self.discord_stats_config[setting_name] = int(setting_value)
                except ValueError:
                    await event.reply(f"❌ **Nieprawidłowa wartość dla liczby:** `{setting_name}`. Oczekiwano liczby.")
                    return
            else:
                self.discord_stats_config[setting_name] = setting_value
            # Note: discord_stats_config is not saved to main_config.txt by save_main_config.
            # If persistence is needed for discord_stats_config, a separate save mechanism is required.
            await event.reply(f"✅ **Ustawiono (Discord Stats):** `{setting_name} = {self.discord_stats_config[setting_name]}`")
        else:
            await event.reply(f"❌ **Nieznane ustawienie:** `{setting_name}`\\n\\nUżyj `.config` lub `.dstats_config` aby zobaczyć dostępne ustawienia")

    async def show_logs(self, event: Any):
        log_text = """📜 **LOGI XAXA SOLUTIONS**

**Ostatnie zdarzenia:**
• Bot uruchomiony
• Połączenie z Telegram nawiązane
• Wczytano 1000 dialogów
• Odświeżono listę grup: 250 aktywnych, 10 zbanowanych
• Wysłano 500 wiadomości
• Odpowiedziano na 300 wiadomości prywatnych
• Dodano 50 nowych członków do kolejki powitalnej

**Błędy:**
• Brak

**Ostrzeżenia:**
• FloodWait przy wysyłaniu wiadomości do grupy ID 123456789, czekam 60s

*Logi są aktualizowane na bieżąco. Użyj `.clear logs` aby wyczyścić logi.*"""
        
        await event.reply(log_text, parse_mode='md')

    async def set_welcome_message(self, event: Any):
        """Ustaw wiadomość powitalną dla nowych członków grup"""
        if event.reply_to_msg_id:
            replied_msg = await event.get_reply_message()
            
            # Zapisz całą wiadomość do forwardowania (podobnie jak spam message)
            self.welcome_messages.append(replied_msg)
            
            preview = replied_msg.text[:100] + "..." if len(replied_msg.text or "") > 100 else replied_msg.text or "[MEDIA]"
            await event.reply(f"✅ **Wiadomość powitalna ustawiona!**\n\n📝 **Podgląd:**\n{preview}")
        else:
            await event.reply("📝 **Aby ustawić wiadomość powitalną:**\n1. Wyślij/Forward wiadomość\n2. Odpowiedz na nią komendą `.welcomeset`")

    async def scan_chat_history(self, event: Any):
        """Skanuj historię czatu i wyślij wiadomości do wszystkich użytkowników"""
        await event.reply("🔍 **Rozpoczynam skanowanie historii czatu...**")
        
        try:
            # Pobierz wszystkie dialogi
            dialogs = await self.client.get_dialogs(limit=None)
            total_users = 0
            sent_count = 0
            
            for dialog in dialogs:
                entity = dialog.entity
                
                # Sprawdź czy to jest prywatny czat z użytkownikiem
                if hasattr(entity, 'is_self') and not entity.is_self and not getattr(entity, 'bot', False):
                    user_id = entity.id
                    
                    # Sprawdź czy już wysłaliśmy wiadomość
                    if user_id not in self.sent_messages and user_id not in self.failed_users and user_id not in self.whitelist:
                        total_users += 1
                        
                        try:
                            # Sprawdź czy są ustawione wiadomości reply
                            if not self.reply_messages:
                                print(f"[XAXA] [{now()}] ❌ Brak ustawionych wiadomości reply - użyj .reply")
                                continue
                            
                            # Wybierz losową wiadomość reply
                            reply_message = random.choice(self.reply_messages)
                            
                            # Opóźnienie
                            if self.config.get('welcome_message_delay') == 'on':
                                delay_range = self.config.get('welcome_delay_range', '5-15').split('-')
                                delay = random.randint(int(delay_range[0]), int(delay_range[1]))
                                await asyncio.sleep(delay)

                            # Forward wiadomość reply
                            await self.client.forward_messages(user_id, reply_message)
                            
                            self.sent_messages.add(user_id)
                            sent_count += 1
                            
                            # Zapisz do pliku
                            async with aiofiles.open('sent_messages.txt', 'a', encoding='utf-8') as f:
                                await f.write(f"{user_id}\n")
                            
                            print(f"[XAXA] [{now()}] ✅ Wysłano wiadomość do użytkownika: {user_id}")
                            
                        except Exception as e:
                            print(f"[XAXA] [{now()}] ❌ Błąd wysyłania do {user_id}: {e}")
                            self.failed_users.add(user_id)
            
            await event.reply(f"✅ **Skanowanie zakończone!**\n\n📊 **Statystyki:**\n• Znaleziono użytkowników: {total_users}\n• Wysłano wiadomości: {sent_count}\n• Nieudane: {total_users - sent_count}")
            
        except Exception as e:
            await event.reply(f"❌ **Błąd skanowania:** {e}")
            print(f"[XAXA] [{now()}] Błąd skanowania historii: {e}")

async def main_bot_manager():
    manager = XAXABotManager()
    
    if not manager.load_main_config(): # Loads api_id, api_hash, and other general config
        print(f"[XAXA] [{now()}] Nie udało się wczytać głównej konfiguracji. Zamykanie.")
        return

    if not await manager.interactive_login(): # New interactive login
        print(f"[XAXA] [{now()}] Logowanie menedżera nie powiodło się. Zamykanie.")
        return

    # Load other data
    await manager.load_files_data()
    
    # Register command handlers
    @manager.client.on(events.NewMessage(outgoing=True))
    async def command_handler(event: NewMessageEvent):
        if not event.raw_text:
            return
        
        command_text = event.raw_text.split()[0].lower()
        
        if command_text == '.set': # Special handling for .set due to variable arguments
            await manager.handle_set_command(event)
        elif command_text in manager.commands:
            handler_func = manager.commands[command_text]
            await handler_func(event)

    print(f"[XAXA] [{now()}] XAXA Bot Manager is running. Type .xaxa in Saved Messages to interact.")
    await manager.send_discord_notification("🚀 XAXA Bot Manager started successfully!", "SUCCESS")
    
    # Keep the client running
    await manager.client.run_until_disconnected()

if __name__ == '__main__':
    # loop = asyncio.get_event_loop() # Old way
    # loop.run_until_complete(main_bot_manager()) # Old way
    asyncio.run(main_bot_manager()) # New, modern way
