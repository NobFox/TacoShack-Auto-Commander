import time
import random
import threading
import pyautogui
import pygetwindow as gw
import pyperclip
import sys
import os
import json
import msvcrt
import winsound
import keyboard
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
#  DEFAULTS — used if no config file exists
# ─────────────────────────────────────────────
CONFIG_FILE = "discord_auto_config.json"
LOG_FILE    = "logfile.txt"

DEFAULTS = {
    "random_extra_min":   10,
    "random_extra_max":   25,
    "taskbar_hover_time": 10,
    "msgbox_hover_time":  10,
    "commands": {
        "/tips":     120,
        "/work":     360,
        "/overtime": 1800,
    },
    "taskbar": None,
    "msgbox":  None,
}

# ─────────────────────────────────────────────

GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

pyautogui.FAILSAFE = False
pyautogui.PAUSE    = 0.05

next_run   = {}
last_sent  = {}
run_counts = {}
lock       = threading.Lock()
paused      = False
busy        = False
calibrating = False
start_time  = None
beeped_for  = set()
last_keypress_time = 0.0
current_log_date   = None  # tracks date for midnight rollover

# Config values — populated from JSON at startup
RANDOM_EXTRA_MIN   = None
RANDOM_EXTRA_MAX   = None
TASKBAR_HOVER_TIME = None
MSGBOX_HOVER_TIME  = None
COMMANDS           = {}
discord_taskbar_pos = None
discord_msgbox_pos  = None


# ─────────────────────────────────────────────
#  CONFIG FILE
# ─────────────────────────────────────────────

def load_config():
    global RANDOM_EXTRA_MIN, RANDOM_EXTRA_MAX, TASKBAR_HOVER_TIME, MSGBOX_HOVER_TIME, COMMANDS
    global discord_taskbar_pos, discord_msgbox_pos

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        for key, val in DEFAULTS.items():
            if key not in data:
                data[key] = val
    else:
        data = dict(DEFAULTS)

    RANDOM_EXTRA_MIN    = data["random_extra_min"]
    RANDOM_EXTRA_MAX    = data["random_extra_max"]
    TASKBAR_HOVER_TIME  = data["taskbar_hover_time"]
    MSGBOX_HOVER_TIME   = data["msgbox_hover_time"]
    COMMANDS            = data["commands"]
    discord_taskbar_pos = tuple(data["taskbar"]) if data["taskbar"] else None
    discord_msgbox_pos  = tuple(data["msgbox"])  if data["msgbox"]  else None

    return data


def save_config():
    data = {
        "random_extra_min":   RANDOM_EXTRA_MIN,
        "random_extra_max":   RANDOM_EXTRA_MAX,
        "taskbar_hover_time": TASKBAR_HOVER_TIME,
        "msgbox_hover_time":  MSGBOX_HOVER_TIME,
        "commands":           COMMANDS,
        "taskbar":            list(discord_taskbar_pos) if discord_taskbar_pos else None,
        "msgbox":             list(discord_msgbox_pos)  if discord_msgbox_pos  else None,
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

def today_str() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def read_log() -> dict:
    """Read logfile and return a dict of date -> {cmd: count}."""
    entries = {}
    if not os.path.exists(LOG_FILE):
        return entries
    with open(LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Format: DD/MM/YYYY - /tips:14 /work:5 /overtime:1
            try:
                date_part, counts_part = line.split(" - ", 1)
                counts = {}
                for item in counts_part.split("\t"):
                    cmd, val = item.strip().split(":")
                    counts[cmd.strip()] = int(val.strip())
                entries[date_part.strip()] = counts
            except Exception:
                pass  # skip malformed lines
    return entries


def write_log(entries: dict):
    """Write all log entries back to file, newest date first."""
    lines = []
    for date, counts in entries.items():
        counts_str = "\t".join(
            f"{cmd.lstrip('/')}:{counts.get(cmd.lstrip('/'), 0)}" for cmd in COMMANDS
        )
        lines.append(f"{date} - {counts_str}")
    lines.sort(key=lambda l: datetime.strptime(l[:10], "%d/%m/%Y"), reverse=True)
    try:
        with open(LOG_FILE, "w") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        log("Logfile is locked — skipping write.", YELLOW)


def update_log():
    """Update today's row in the logfile with current run_counts."""
    global current_log_date
    today = today_str()

    # Midnight rollover — reset counts for new date
    if current_log_date and current_log_date != today:
        current_log_date = today
        for cmd in COMMANDS:
            run_counts[cmd] = 0
        log("Midnight rollover — counts reset for new day.", CYAN)

    entries = read_log()
    entries[today] = {cmd.lstrip('/'): run_counts.get(cmd, 0) for cmd in COMMANDS}
    write_log(entries)


def load_todays_counts():
    """On startup, load today's existing counts into run_counts."""
    global current_log_date
    current_log_date = today_str()
    entries = read_log()
    if current_log_date in entries:
        for cmd, count in entries[current_log_date].items():
            full_cmd = f"/{cmd}" if not cmd.startswith("/") else cmd
            run_counts[full_cmd] = count
        log(f"Resumed today's counts from logfile.", CYAN)


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def log(msg: str, colour: str = RESET):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{colour}[{ts}] {msg}{RESET}")


def random_delay() -> int:
    return random.randint(RANDOM_EXTRA_MIN, RANDOM_EXTRA_MAX)


def format_countdown(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_uptime() -> str:
    if not start_time:
        return "00:00:00"
    delta = datetime.now() - start_time
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ─────────────────────────────────────────────
#  SETUP / CALIBRATION
# ─────────────────────────────────────────────

def get_discord_taskbar_position():
    print(f"\n{BOLD}{YELLOW}CALIBRATE STEP 1: Hover your mouse over the Discord icon in the taskbar.{RESET}")
    print(f"You have {TASKBAR_HOVER_TIME} seconds — move your mouse there now...\n")
    for i in range(TASKBAR_HOVER_TIME, 0, -1):
        print(f"  Recording in {i}...", end="\r")
        time.sleep(1)
    pos = pyautogui.position()
    print(f"\n{GREEN}  Discord taskbar position recorded: {pos}{RESET}\n")
    return tuple(pos)


def get_discord_msgbox_position():
    print(f"{BOLD}{YELLOW}CALIBRATE STEP 2: Switch to Discord and navigate to your channel manually,")
    print(f"then hover your mouse over the message input box at the bottom.{RESET}")
    print(f"You have {MSGBOX_HOVER_TIME} seconds — move your mouse there now...\n")
    for i in range(MSGBOX_HOVER_TIME, 0, -1):
        print(f"  Recording in {i}...", end="\r")
        time.sleep(1)
    pos = pyautogui.position()
    print(f"\n{GREEN}  Message box position recorded: {pos}{RESET}\n")
    return tuple(pos)


def run_calibration():
    global discord_taskbar_pos, discord_msgbox_pos
    old_commands = dict(COMMANDS)  # snapshot before reload
    load_config()

    # Adjust in-flight countdowns to reflect any cooldown changes.
    # e.g. /work had 360s, config now says 540s, 3 min left on the
    # countdown -> shift next_run by +180s so it shows 6 min left.
    with lock:
        now = datetime.now()
        for cmd, new_cd in COMMANDS.items():
            if cmd in old_commands and cmd in next_run:
                delta = new_cd - old_commands[cmd]
                if delta:
                    next_run[cmd] = max(now, next_run[cmd] + timedelta(seconds=delta))
                    log(f"{cmd} cooldown {old_commands[cmd]}s -> {new_cd}s, countdown adjusted", CYAN)
            elif cmd not in old_commands:
                # brand new command from the config: schedule a full cooldown
                next_run[cmd] = now + timedelta(seconds=new_cd)
                log(f"{cmd} added, first run in {new_cd}s", CYAN)
        # commands removed from the config: stop tracking them
        for cmd in list(next_run):
            if cmd not in COMMANDS:
                del next_run[cmd]
                log(f"{cmd} removed from config", YELLOW)

    print(f"\n{BOLD}{CYAN}─────────────────────────────────────────────────")
    print(f"  CALIBRATION")
    print(f"─────────────────────────────────────────────────{RESET}")
    print(f"\nWe need to record two positions on your screen:")
    print(f"  1. The Discord icon in your taskbar")
    print(f"  2. The message input box inside Discord")
    print(f"\nFor each step you'll have a countdown timer.")
    print(f"Move your mouse to the correct position before time runs out.")
    print(f"\n{YELLOW}Press any key when you're ready to start...{RESET}")
    msvcrt.getwch()
    discord_taskbar_pos = get_discord_taskbar_position()
    discord_msgbox_pos  = get_discord_msgbox_position()
    save_config()
    log("Calibration saved.", GREEN)


# ─────────────────────────────────────────────
#  DISCORD INTERACTION
# ─────────────────────────────────────────────

def check_discord_open() -> bool:
    return bool(gw.getWindowsWithTitle("Discord"))


def focus_discord():
    if discord_taskbar_pos:
        active = gw.getActiveWindow()
        if active and "Discord" in active.title:
            return
        pyautogui.click(discord_taskbar_pos)
        time.sleep(1.0)


def send_discord_command(command: str) -> bool:
    global busy

    while busy:
        time.sleep(3)

    busy = True
    try:
        previous_window = gw.getActiveWindow()
    except Exception:
        previous_window = None

    try:
        if not check_discord_open():
            log("Discord is not open — skipping command.", RED)
            busy = False
            return False

        focus_discord()

        pyautogui.click(discord_msgbox_pos)
        time.sleep(0.4)

        # Wait for a 2 second gap in keyboard input before proceeding
        log("Waiting for typing gap before sending...", YELLOW)
        while (time.time() - last_keypress_time) < 2.0:
            time.sleep(0.5)

        # Safety check — make sure Discord is still the active window before clearing
        active = gw.getActiveWindow()
        if not active or "Discord" not in active.title:
            log("Discord lost focus before clear — aborting command.", RED)
            busy = False
            return False

        # Clear anything that may have landed in the box
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("delete")
        time.sleep(1.5)

        # Save clipboard, paste command, then restore
        try:
            previous_clipboard = pyperclip.paste()
        except Exception:
            previous_clipboard = ""

        pyperclip.copy(command)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.6)
        pyautogui.press("enter")  # selects from autocomplete
        time.sleep(0.8)
        pyautogui.press("enter")  # actually sends
        time.sleep(0.4)

        pyperclip.copy(previous_clipboard)

        log(f"Sent {command}", GREEN)

        if previous_window:
            try:
                previous_window.activate()
            except Exception:
                pass

        busy = False
        return True

    except Exception as e:
        log(f"Error sending {command}: {e}", RED)
        busy = False
        return False


# ─────────────────────────────────────────────
#  SCHEDULER
# ─────────────────────────────────────────────

def scheduler():
    while True:
        if not paused and not calibrating:
            if not check_discord_open():
                log("Discord not found — commands paused until it's open.", YELLOW)
                while not check_discord_open():
                    time.sleep(5)
                log("Discord detected — resuming.", GREEN)

            now = datetime.now()
            due = []
            with lock:
                for cmd, run_at in list(next_run.items()):
                    if now >= run_at:
                        due.append(cmd)

            for cmd in due:
                success = send_discord_command(cmd)
                cooldown = COMMANDS[cmd]
                extra    = random_delay()
                with lock:
                    next_run[cmd]  = datetime.now() + timedelta(seconds=cooldown + extra)
                    last_sent[cmd] = datetime.now()
                if success:
                    run_counts[cmd] = run_counts.get(cmd, 0) + 1
                    update_log()
                    log(
                        f"{cmd} → next run in {cooldown//60}m + {extra}s "
                        f"(at {next_run[cmd].strftime('%H:%M:%S')})",
                        CYAN,
                    )
        time.sleep(1)


# ─────────────────────────────────────────────
#  KEY LISTENER
# ─────────────────────────────────────────────

def key_listener():
    global paused, calibrating
    while True:
        if msvcrt.kbhit():
            key = msvcrt.getwch().lower()
            if key == 'p':
                paused = not paused
            elif key == 'c' and not calibrating:
                calibrating = True
                paused_before = paused
                paused = True
                run_calibration()
                paused = paused_before
                calibrating = False
        time.sleep(0.1)


# ─────────────────────────────────────────────
#  DISPLAY
# ─────────────────────────────────────────────

def display_loop():
    while True:
        if calibrating:
            time.sleep(1)
            continue

        os.system("cls")

        discord_open = check_discord_open()

        if not discord_open:
            status = f"{RED}DISCORD CLOSED — waiting for Discord to open{RESET}"
        elif paused:
            status = f"{YELLOW}PAUSED — press P to resume{RESET}"
        else:
            status = f"{GREEN}RUNNING — press P to pause{RESET}"

        print(f"{BOLD}{CYAN}{'─'*52}")
        print(f"  TacoShack Auto-Commander  |  Close window to stop")
        print(f"{'─'*52}{RESET}")
        print(f"  {status}")
        print(f"  Uptime: {format_uptime()}   |   Press C to recalibrate")
        print()
        print(f"  {'Command':<14} {'Next in':>8}   {'Last sent':<10}")
        print(f"  {'─'*13} {'─'*8}   {'─'*10}")

        now = datetime.now()
        with lock:
            for cmd in COMMANDS:
                run_at  = next_run.get(cmd)
                sent_at = last_sent.get(cmd)
                if paused or not discord_open:
                    countdown = "paused" if paused else "waiting"
                    colour    = YELLOW
                else:
                    secs_left = (run_at - now).total_seconds() if run_at else 999
                    countdown = format_countdown(secs_left) if run_at else "--:--"
                    if secs_left <= 10:
                        colour = RED
                        if cmd not in beeped_for:
                            beeped_for.add(cmd)
                            # No beeps during the first 45s — startup volley
                            # doesn't need a warning, you just launched it
                            uptime = (now - start_time).total_seconds() if start_time else 0
                            if uptime > 45:
                                winsound.Beep(1000, 200)
                                time.sleep(0.1)
                                winsound.Beep(1000, 200)
                    elif secs_left <= 30:
                        colour = YELLOW
                        beeped_for.discard(cmd)  # reset so it beeps again next countdown
                    else:
                        colour = GREEN
                        beeped_for.discard(cmd)
                sent_str = sent_at.strftime("%H:%M:%S") if sent_at else "not yet"
                print(f"  {colour}{cmd:<14}{RESET} {countdown:>8}   {sent_str:<10}")

        with lock:
            parts = [f"{cmd.lstrip('/')} ×{run_counts.get(cmd, 0):<3}" for cmd in COMMANDS]
        print(f"\n  Sent:   {'   |   '.join(parts)}\n")
        time.sleep(1)


def ask_minutes(prompt: str, default: int) -> int:
    """Ask for a cooldown in minutes, falling back to default on bad input."""
    while True:
        raw = input(f"  {prompt} (default: {default}m): ").strip()
        if raw == "":
            return default
        try:
            val = int(raw)
            if val > 0:
                return val
            print(f"  {RED}Please enter a number greater than 0.{RESET}")
        except ValueError:
            print(f"  {RED}Please enter a whole number.{RESET}")


def ask_seconds(prompt: str, default: int) -> int:
    """Ask for a duration in seconds, falling back to default on bad input."""
    while True:
        raw = input(f"  {prompt} (default: {default}s): ").strip()
        if raw == "":
            return default
        try:
            val = int(raw)
            if val > 0:
                return val
            print(f"  {RED}Please enter a number greater than 0.{RESET}")
        except ValueError:
            print(f"  {RED}Please enter a whole number.{RESET}")


def first_boot_setup():
    """Run the first-time setup questionnaire and save defaults to config."""
    global COMMANDS, RANDOM_EXTRA_MIN, RANDOM_EXTRA_MAX, TASKBAR_HOVER_TIME, MSGBOX_HOVER_TIME
    print(f"{BOLD}{YELLOW}First time setup — let's get you configured.{RESET}\n")

    tips_mins     = ask_minutes("Minutes between /tips",     2)
    work_mins     = ask_minutes("Minutes between /work",     6)
    overtime_mins = ask_minutes("Minutes between /overtime", 30)

    print()
    TASKBAR_HOVER_TIME = ask_seconds("Seconds to hover over taskbar icon during calibration", 10)
    MSGBOX_HOVER_TIME  = ask_seconds("Seconds to hover over message box during calibration",  10)

    COMMANDS = {
        "/tips":     tips_mins     * 60,
        "/work":     work_mins     * 60,
        "/overtime": overtime_mins * 60,
    }
    RANDOM_EXTRA_MIN = DEFAULTS["random_extra_min"]
    RANDOM_EXTRA_MAX = DEFAULTS["random_extra_max"]

    print()
    save_config()
    log("Settings saved.", GREEN)
    print()
    print(f"{CYAN}Next we'll calibrate the mouse positions.")
    print(f"Read each step carefully before the countdown starts.{RESET}\n")
    print(f"{YELLOW}Press any key to continue to calibration...{RESET}")
    msvcrt.getwch()
    print()

def setup_keyboard_hook():
    """Track the last time a key was pressed, ignoring mouse input."""
    def on_key(_):
        global last_keypress_time
        last_keypress_time = time.time()
    keyboard.hook(on_key)


def main():
    global start_time

    print(f"{BOLD}{GREEN}TacoShack Auto-Commander starting...{RESET}\n")

    setup_keyboard_hook()

    if not os.path.exists(CONFIG_FILE):
        first_boot_setup()

    data = load_config()

    if discord_taskbar_pos and discord_msgbox_pos:
        print(f"{GREEN}  Saved config loaded:{RESET}")
        print(f"  Jitter:     +{RANDOM_EXTRA_MIN}s to +{RANDOM_EXTRA_MAX}s")
        print(f"  Commands:   {', '.join(COMMANDS.keys())}")
        print(f"  Taskbar:    {discord_taskbar_pos}")
        print(f"  Msg box:    {discord_msgbox_pos}")
        print(f"\n{YELLOW}  Press C at any time to recalibrate if positions have changed.{RESET}\n")
    else:
        print(f"{YELLOW}  No saved calibration found — running setup now.{RESET}\n")
        run_calibration()

    start_time = datetime.now()

    load_todays_counts()

    now = datetime.now()
    for i, (cmd, cooldown) in enumerate(COMMANDS.items()):
        next_run[cmd]   = now + timedelta(seconds=10 + i * 8)
        run_counts[cmd] = run_counts.get(cmd, 0)  # preserve loaded count
        log(f"{cmd} firing in {10 + i * 8}s", CYAN)

    print()

    threading.Thread(target=scheduler,    daemon=True).start()
    threading.Thread(target=key_listener, daemon=True).start()

    try:
        display_loop()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Stopped by user.{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()