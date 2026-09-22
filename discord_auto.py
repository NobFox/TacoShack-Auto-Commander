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
    "sleepy_mode":  False,
    "sleep_start":  "00:00",
    "sleep_end":    "07:30",
    "sleep_jitter": 20,
    "lazy_mode":       False,
    "lazy_work_min":   60,
    "lazy_work_max":   120,
    "lazy_break_min":  30,
    "lazy_break_max":  60,
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
beeps_enabled = True
busy        = False
calibrating = False
adjusting   = False
pending_logs = []   # log lines held back while a prompt is on screen
lazy_break_until = None   # set while a lazy break is in progress
lazy_next_break  = None   # when the next lazy break is due
sleep_window     = None   # (start, end, end_base) for the current/next night
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

def parse_hhmm(value, fallback):
    """'07:30' -> (7, 30). Falls back if the config has something daft in it."""
    try:
        h, m = str(value).split(":")
        h, m = int(h), int(m)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return (h, m)
    except (ValueError, AttributeError):
        h, m = str(fallback).split(":")
        return (int(h), int(m))


def plan_sleep_window(end_base: datetime):
    """Build one night's concrete sleep window around the configured end
    time, with each edge nudged by a random offset rolled once per night."""
    global sleep_window
    start_mins = SLEEP_START[0] * 60 + SLEEP_START[1]
    end_mins   = SLEEP_END[0]   * 60 + SLEEP_END[1]
    duration   = (end_mins - start_mins) % (24 * 60)   # handles crossing midnight

    # Never let the jitter be big enough to flip start past end
    jitter = max(0.0, min(SLEEP_JITTER, duration / 2 - 1))

    start = end_base - timedelta(minutes=duration) + timedelta(minutes=random.uniform(-jitter, jitter))
    end   = end_base + timedelta(minutes=random.uniform(-jitter, jitter))
    sleep_window = (start.replace(second=0, microsecond=0),
                    end.replace(second=0, microsecond=0),
                    end_base)


def in_sleep_window(now: datetime = None) -> bool:
    """True if we're inside tonight's (jittered) sleep window."""
    now = now or datetime.now()

    start_mins = SLEEP_START[0] * 60 + SLEEP_START[1]
    end_mins   = SLEEP_END[0]   * 60 + SLEEP_END[1]
    if start_mins == end_mins:
        return False                              # zero-length window, never sleeps

    if sleep_window is None:
        # First plan: today's configured end time, or tomorrow's if today's
        # window has definitely finished even with the latest possible jitter
        end_base = now.replace(hour=SLEEP_END[0], minute=SLEEP_END[1], second=0, microsecond=0)
        if end_base + timedelta(minutes=SLEEP_JITTER) <= now:
            end_base += timedelta(days=1)
        plan_sleep_window(end_base)

    # Window over — roll the next night. Stepping from the previous base
    # (not from "now") stops an early wake-up replanning the same morning.
    replanned = False
    while now >= sleep_window[1]:
        plan_sleep_window(sleep_window[2] + timedelta(days=1))
        replanned = True
    if replanned:
        s, e, _ = sleep_window
        log(f"Next sleep window: {s.strftime('%H:%M')} to {e.strftime('%H:%M')}.", CYAN)

    return sleep_window[0] <= now < sleep_window[1]


def sleep_until() -> datetime:
    """When the current sleep window ends."""
    return sleep_window[1] if sleep_window else datetime.now()


def sane_range(data, min_key, max_key):
    """Read a min/max pair of minutes, falling back on junk and swapping
    them if they're the wrong way round."""
    try:
        lo = float(data[min_key])
        hi = float(data[max_key])
        if lo <= 0 or hi <= 0:
            raise ValueError
        return (min(lo, hi), max(lo, hi))
    except (ValueError, TypeError, KeyError):
        return (float(DEFAULTS[min_key]), float(DEFAULTS[max_key]))


def load_config():
    global RANDOM_EXTRA_MIN, RANDOM_EXTRA_MAX, TASKBAR_HOVER_TIME, MSGBOX_HOVER_TIME, COMMANDS
    global discord_taskbar_pos, discord_msgbox_pos
    global sleepy_mode, SLEEP_START, SLEEP_END, SLEEP_JITTER, sleep_window
    global lazy_mode, LAZY_WORK_MIN, LAZY_WORK_MAX, LAZY_BREAK_MIN, LAZY_BREAK_MAX

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

    sleepy_mode = bool(data["sleepy_mode"])
    SLEEP_START = parse_hhmm(data["sleep_start"], DEFAULTS["sleep_start"])
    SLEEP_END   = parse_hhmm(data["sleep_end"],   DEFAULTS["sleep_end"])
    try:
        SLEEP_JITTER = max(0.0, float(data["sleep_jitter"]))
    except (ValueError, TypeError):
        SLEEP_JITTER = float(DEFAULTS["sleep_jitter"])
    sleep_window = None   # replan with the new settings

    lazy_mode = bool(data["lazy_mode"])
    LAZY_WORK_MIN, LAZY_WORK_MAX   = sane_range(data, "lazy_work_min",  "lazy_work_max")
    LAZY_BREAK_MIN, LAZY_BREAK_MAX = sane_range(data, "lazy_break_min", "lazy_break_max")

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
        "sleepy_mode":        sleepy_mode,
        "sleep_start":        f"{SLEEP_START[0]:02d}:{SLEEP_START[1]:02d}",
        "sleep_end":          f"{SLEEP_END[0]:02d}:{SLEEP_END[1]:02d}",
        "sleep_jitter":       SLEEP_JITTER,
        "lazy_mode":          lazy_mode,
        "lazy_work_min":      LAZY_WORK_MIN,
        "lazy_work_max":      LAZY_WORK_MAX,
        "lazy_break_min":     LAZY_BREAK_MIN,
        "lazy_break_max":     LAZY_BREAK_MAX,
    }
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CONFIG_FILE)  # atomic — never leaves a half-written config


# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

def today_str() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def read_log():
    """Read logfile. Returns (entries, leftovers) where entries is a dict of
    date -> {cmd: count} and leftovers is any line we couldn't parse —
    kept so a stray line never gets silently deleted on the next write."""
    entries, leftovers = {}, []
    if not os.path.exists(LOG_FILE):
        return entries, leftovers
    with open(LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                date_part, counts_part = line.split(" - ", 1)
                counts = {}
                # new format separates with |, older files used tabs — accept both
                items = []
                for chunk in counts_part.split("\t"):
                    items.extend(chunk.split("|"))
                for item in items:
                    cmd, val = item.strip().rsplit(":", 1)  # split from the right — command names may contain colons
                    counts[cmd.strip()] = int(val.strip())
                entries[date_part.strip()] = counts
            except Exception:
                leftovers.append(line)  # keep it, don't lose it
    return entries, leftovers


def write_log(entries: dict, leftovers=()):
    """Write all log entries, newest date first, via an atomic replace so an
    interrupted write can never leave a truncated/empty logfile."""
    lines = []
    for date, counts in entries.items():
        # historical rows keep exactly the counts they had — only today's
        # row (rebuilt in update_log) tracks the current command list
        counts_str = " | ".join(f"{cmd}:{n}" for cmd, n in counts.items())
        lines.append(f"{date} - {counts_str}")
    try:
        lines.sort(key=lambda l: datetime.strptime(l[:10], "%d/%m/%Y"), reverse=True)
    except ValueError:
        pass  # a weird date sneaked in — write unsorted rather than crash
    lines.extend(leftovers)
    tmp = LOG_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, LOG_FILE)  # atomic — old file intact until this succeeds
    except OSError:
        log("Logfile is locked — skipping write.", YELLOW)


def update_log(just_sent: str = None):
    """Update today's row in the logfile with current run_counts."""
    global current_log_date
    today = today_str()

    # Midnight rollover — reset counts for new date
    if current_log_date and current_log_date != today:
        current_log_date = today
        for cmd in COMMANDS:
            run_counts[cmd] = 0
        if just_sent:
            run_counts[just_sent] = 1  # the send that crossed midnight counts for the new day
        log("Midnight rollover — counts reset for new day.", CYAN)

    entries, leftovers = read_log()
    # merge onto today's existing row: commands removed from the config
    # mid-day keep the count they'd racked up rather than vanishing
    today_row = entries.get(today, {})
    today_row.update({cmd.lstrip('/'): run_counts.get(cmd, 0) for cmd in COMMANDS})
    entries[today] = today_row
    write_log(entries, leftovers)


def load_todays_counts():
    """On startup, load today's existing counts into run_counts."""
    global current_log_date
    current_log_date = today_str()
    entries, _ = read_log()
    if current_log_date in entries:
        for cmd, count in entries[current_log_date].items():
            full_cmd = f"/{cmd}" if not cmd.startswith("/") else cmd
            run_counts[full_cmd] = count
        log(f"Resumed today's counts from logfile.", CYAN)


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def log(msg: str, colour: str = RESET):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"{colour}[{ts}] {msg}{RESET}"
    # A prompt is on screen — hold the line rather than scribbling over
    # what the user is typing. Flushed when the prompt closes.
    if adjusting:
        pending_logs.append(line)
        return
    print(line)


def flush_pending_logs():
    """Print anything logged while a prompt was open."""
    if not pending_logs:
        return
    for line in pending_logs:
        print(line)
    pending_logs.clear()


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
            # SetForegroundWindow (what .activate() uses) is unreliable on
            # Windows: the OS blocks background focus-stealing and sometimes
            # throws even on success. Alt-tap grants foreground permission;
            # retry and verify by window handle rather than trusting one shot.
            for _ in range(3):
                try:
                    if previous_window.isMinimized:
                        previous_window.restore()
                    pyautogui.press("alt")
                    previous_window.activate()
                except Exception:
                    pass
                time.sleep(0.3)
                try:
                    active = gw.getActiveWindow()
                    if active and active._hWnd == previous_window._hWnd:
                        break
                except Exception:
                    break
            else:
                log("Couldn't return focus to previous window.", YELLOW)

        busy = False
        return True

    except Exception as e:
        log(f"Error sending {command}: {e}", RED)
        busy = False
        return False


# ─────────────────────────────────────────────
#  SCHEDULER
# ─────────────────────────────────────────────

def restagger_overdue(reason: str):
    """Everything that went overdue while we were paused gets spread out
    rather than firing in the same second when we resume."""
    with lock:
        now     = datetime.now()
        overdue = [c for c in COMMANDS if next_run.get(c) and next_run[c] <= now]
        random.shuffle(overdue)            # no fixed order either
        at = now + timedelta(seconds=random.uniform(10, 40))
        for cmd in overdue:
            next_run[cmd] = at
            beeped_for.discard(cmd)
            at += timedelta(seconds=random.uniform(6, 15))
    log(f"{reason} — {len(overdue)} command(s) restaggered.", GREEN)


def scheduler():
    global lazy_break_until, lazy_next_break
    was_sleeping = False
    while True:
        now      = datetime.now()
        sleeping = sleepy_mode and in_sleep_window(now)

        if sleeping and not was_sleeping:
            log(f"Sleepy mode — pausing until {sleep_until().strftime('%H:%M')}.", CYAN)
        elif was_sleeping and not sleeping:
            restagger_overdue("Sleepy mode over")
        was_sleeping = sleeping

        # ── Lazy mode ────────────────────────────────────────────
        on_break = False
        if not lazy_mode:
            lazy_break_until = lazy_next_break = None
        elif sleeping:
            # Don't burn the lazy clock overnight, and don't wake up
            # straight into a break — start the cycle fresh after sleeping
            lazy_break_until = None
            lazy_next_break  = None
        elif lazy_break_until:
            if now < lazy_break_until:
                on_break = True
            else:
                lazy_break_until = None
                lazy_next_break  = now + timedelta(minutes=random.uniform(LAZY_WORK_MIN, LAZY_WORK_MAX))
                restagger_overdue("Lazy break over")
                log(f"Next lazy break at {lazy_next_break.strftime('%H:%M')}.", CYAN)
        elif lazy_next_break is None:
            lazy_next_break = now + timedelta(minutes=random.uniform(LAZY_WORK_MIN, LAZY_WORK_MAX))
            log(f"Lazy mode — first break at {lazy_next_break.strftime('%H:%M')}.", CYAN)
        elif now >= lazy_next_break:
            mins = random.uniform(LAZY_BREAK_MIN, LAZY_BREAK_MAX)
            lazy_break_until = now + timedelta(minutes=mins)
            on_break = True
            log(f"Lazy break for {mins:.0f}m — back at {lazy_break_until.strftime('%H:%M')}.", CYAN)

        if not paused and not calibrating and not adjusting and not sleeping and not on_break:
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
                    update_log(just_sent=cmd)
                    log(
                        f"{cmd} → next run in {cooldown//60}m + {extra}s "
                        f"(at {next_run[cmd].strftime('%H:%M:%S')})",
                        CYAN,
                    )
        time.sleep(1)


# ─────────────────────────────────────────────
#  KEY LISTENER
# ─────────────────────────────────────────────

def prompt_header(title: str):
    # A send may already be in flight — let it finish before we draw,
    # otherwise it steals focus and logs over the prompt
    if busy:
        os.system("cls")
        print(f"\n  {YELLOW}Waiting for a command in progress to finish...{RESET}")
        while busy:
            time.sleep(0.2)
    os.system("cls")
    print(f"{BOLD}{CYAN}{'─'*57}")
    print(f"  {title}")
    print(f"{'─'*57}{RESET}\n")


def pick_command(show: str = "remaining"):
    """Show the numbered command list and return the chosen command,
    or None if cancelled / bad input. `show` picks the right-hand column."""
    with lock:
        cmds     = list(COMMANDS)
        snapshot = {c: next_run.get(c) for c in cmds}
        cooldowns = dict(COMMANDS)

    if not cmds:
        print(f"  {YELLOW}No commands configured.{RESET}")
        time.sleep(2)
        return None

    now    = datetime.now()
    name_w = max(len(c) for c in cmds)
    for i, cmd in enumerate(cmds, 1):
        if show == "cooldown":
            mins  = cooldowns[cmd] / 60
            right = f"{mins:g}m cooldown"
        else:
            run_at = snapshot.get(cmd)
            right  = (format_countdown((run_at - now).total_seconds()) if run_at else "--:--") + " remaining"
        print(f"    {i}. {cmd:<{name_w}}   {right}")

    print(f"\n  {YELLOW}Press Enter on its own at any point to cancel.{RESET}\n")

    raw = input("  Which command? (number): ").strip()
    if not raw:
        return None
    try:
        choice = int(raw)
        if not 1 <= choice <= len(cmds):
            raise ValueError
    except ValueError:
        print(f"  {RED}Not a valid number from the list.{RESET}")
        time.sleep(2)
        return None
    return cmds[choice - 1]


def edit_cooldown():
    """Change a command's cooldown permanently — updates the JSON config
    and shifts the running countdown by the difference."""
    prompt_header("Edit a cooldown  (saved to config)")

    cmd = pick_command(show="cooldown")
    if not cmd:
        return

    with lock:
        old_secs = COMMANDS[cmd]
    old_mins = old_secs / 60

    raw = input(f"  New cooldown for {cmd} in minutes (currently {old_mins:g}m): ").strip()
    if not raw:
        return
    try:
        new_mins = float(raw)
        if new_mins <= 0:
            raise ValueError
    except ValueError:
        print(f"  {RED}Enter a number greater than 0, e.g. 3.5{RESET}")
        time.sleep(2)
        return

    new_secs = int(round(new_mins * 60))
    delta    = new_secs - old_secs

    with lock:
        COMMANDS[cmd] = new_secs
        # shift the in-flight countdown by the difference, same as pressing C
        if cmd in next_run:
            now = datetime.now()
            next_run[cmd] = max(now, next_run[cmd] + timedelta(seconds=delta))
            left = format_countdown((next_run[cmd] - now).total_seconds())
        else:
            left = None

    try:
        save_config()
    except OSError as e:
        print(f"\n  {RED}Couldn't save config: {e}{RESET}")
        time.sleep(3)
        return

    beeped_for.discard(cmd)
    print(f"\n  {GREEN}{cmd}: {old_mins:g}m → {new_mins:g}m ({new_secs}s), saved to config.{RESET}")
    if left:
        print(f"  {GREEN}Running countdown adjusted — now {left} remaining.{RESET}")
    log(f"{cmd} cooldown changed to {new_mins:g}m and saved", CYAN)
    time.sleep(2.5)


def adjust_timer():
    """One-off nudge to a running countdown. Doesn't touch the config —
    the cooldown is unchanged, only the next scheduled run moves."""
    prompt_header("Adjust a running timer  (one-off — config is not changed)")

    cmd = pick_command(show="remaining")
    if not cmd:
        return

    raw = input(f"  Adjust {cmd} by how many minutes? (e.g. +5 or -5): ").strip()
    if not raw:
        return
    try:
        mins = float(raw.lstrip("+"))
    except ValueError:
        print(f"  {RED}Enter a number like +5 or -5.{RESET}")
        time.sleep(2)
        return

    with lock:
        run_at = next_run.get(cmd)
        if not run_at:
            print(f"  {YELLOW}{cmd} isn't currently scheduled.{RESET}")
            time.sleep(2)
            return
        now      = datetime.now()
        adjusted = run_at + timedelta(seconds=mins * 60)
        clamped  = adjusted < now
        next_run[cmd] = max(now, adjusted)
        left = format_countdown((next_run[cmd] - now).total_seconds())

    beeped_for.discard(cmd)  # let it warn again against the new time
    sign = "+" if mins >= 0 else ""
    if clamped:
        print(f"\n  {YELLOW}{cmd} {sign}{mins:g}m — that's past due, so it will fire shortly.{RESET}")
    else:
        print(f"\n  {GREEN}{cmd} {sign}{mins:g}m — now {left} remaining.{RESET}")
    log(f"{cmd} timer adjusted by {sign}{mins:g}m (one-off)", CYAN)
    time.sleep(2)


def key_listener():
    global paused, calibrating, beeps_enabled, adjusting, sleepy_mode
    global lazy_mode, lazy_break_until, lazy_next_break
    while True:
        if msvcrt.kbhit():
            key = msvcrt.getwch().lower()
            if key == 'p':
                paused = not paused
            elif key == 'b':
                beeps_enabled = not beeps_enabled
            elif key == 'l':
                lazy_mode = not lazy_mode
                if not lazy_mode and lazy_break_until:
                    lazy_break_until = None   # switching off ends a break now
                    restagger_overdue("Lazy mode off")
                lazy_next_break = None        # cycle restarts either way
                try:
                    save_config()
                except OSError:
                    log("Lazy mode toggled but couldn't save config.", YELLOW)
            elif key == 's':
                sleepy_mode = not sleepy_mode
                try:
                    save_config()   # remembered next launch — the whole point
                except OSError:
                    log("Sleepy mode toggled but couldn't save config.", YELLOW)
            elif key in ('t', 'e') and not calibrating and not adjusting:
                adjusting = True
                try:
                    adjust_timer() if key == 't' else edit_cooldown()
                finally:
                    adjusting = False
                    while msvcrt.kbhit():   # drop anything typed at the prompt
                        msvcrt.getwch()
                    flush_pending_logs()
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
        if calibrating or adjusting:
            time.sleep(1)
            continue

        os.system("cls")

        discord_open = check_discord_open()

        if not discord_open:
            status = f"{RED}DISCORD CLOSED — waiting for Discord to open{RESET}"
        elif paused:
            status = f"{YELLOW}PAUSED{RESET}"
        elif sleepy_mode and in_sleep_window():
            wake = sleep_until()
            left = format_countdown((wake - datetime.now()).total_seconds())
            status = f"{CYAN}SLEEPING — resumes at {wake.strftime('%H:%M')} (in {left}){RESET}"
        elif lazy_break_until:
            left = format_countdown((lazy_break_until - datetime.now()).total_seconds())
            status = f"{CYAN}LAZY BREAK — resumes at {lazy_break_until.strftime('%H:%M')} (in {left}){RESET}"
        else:
            status = f"{GREEN}RUNNING{RESET}"

        # Size the name column to the longest command so long ones like
        # "/buy upgrade:All Boosts" don't shunt the other columns out of line
        with lock:
            name_w = max([len("Command")] + [len(c) for c in COMMANDS])
        table_w = 2 + 3 + name_w + 1 + 8 + 3 + 10   # indent + index + cols + gaps
        rule_w  = max(74, table_w)                  # 74 = width of the hotkey bar

        print(f"{BOLD}{CYAN}{'─'*rule_w}")
        print(f"  TacoShack Auto-Commander  |  Close window to stop")
        print(f"{'─'*rule_w}{RESET}")
        print(f"  {status}")
        print(f"  Uptime: {format_uptime()}")
        print()
        print(f"  {'':<3}{'Command':<{name_w}} {'Next in':>8}   {'Last sent':<10}")
        print(f"  {'':<3}{'─'*name_w} {'─'*8}   {'─'*10}")

        now = datetime.now()
        with lock:
            for idx, cmd in enumerate(COMMANDS, 1):
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
                            if uptime > 45 and beeps_enabled:
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
                print(f"  {str(idx)+'.':<3}{colour}{cmd:<{name_w}}{RESET} {countdown:>8}   {sent_str:<10}")

        with lock:
            parts = [f"{cmd.lstrip('/')} ×{run_counts.get(cmd, 0)}" for cmd in COMMANDS]

        # Wrap at entry boundaries so a long name never gets split across
        # lines; continuation rows indent to sit under the first entry
        label   = "  Sent:   "
        indent  = " " * len(label)
        sep     = "  |  "
        lines, current = [], ""
        for part in parts:
            candidate = part if not current else current + sep + part
            if current and len(label) + len(candidate) > rule_w:
                lines.append(current)
                current = part
            else:
                current = candidate
        if current:
            lines.append(current)

        print()
        for i, line in enumerate(lines):
            print(f"{label if i == 0 else indent}{line}")

        # Hotkey bar
        beep_state  = f"{GREEN}on{RESET}" if beeps_enabled else f"{YELLOW}off{RESET}"
        sleep_win   = f"{SLEEP_START[0]:02d}:{SLEEP_START[1]:02d}-{SLEEP_END[0]:02d}:{SLEEP_END[1]:02d}"
        if SLEEP_JITTER:
            sleep_win += f" ±{SLEEP_JITTER:g}m"
        sleep_state = f"{GREEN}on{RESET} {sleep_win}" if sleepy_mode else f"{YELLOW}off{RESET}"
        if lazy_mode and lazy_next_break and not lazy_break_until:
            lazy_state = f"{GREEN}on{RESET} (break at {lazy_next_break.strftime('%H:%M')})"
        elif lazy_mode:
            lazy_state = f"{GREEN}on{RESET}"
        else:
            lazy_state = f"{YELLOW}off{RESET}"
        pause_lbl   = "resume" if paused else "pause"
        print(f"\n{CYAN}{'─'*rule_w}{RESET}")
        print(f"  {BOLD}P{RESET} {pause_lbl}   {BOLD}T{RESET} adjust timer   "
              f"{BOLD}E{RESET} edit cooldown   {BOLD}C{RESET} recalibrate")
        print(f"  {BOLD}B{RESET} beeps: {beep_state}   {BOLD}S{RESET} sleepy: {sleep_state}   "
              f"{BOLD}L{RESET} lazy: {lazy_state}")
        print()
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