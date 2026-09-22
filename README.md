# TacoShack Auto-Commander

A Windows automation tool that automatically sends TacoShack slash commands in Discord at timed intervals, so you can carry on using your computer while it runs in the background.

> **Disclaimer:** Automating actions on a personal Discord account (selfbotting) is against Discord's Terms of Service. Use at your own risk.

---

## How It Works

TacoShack Auto-Commander runs in a command prompt window and fires `/tips`, `/work`, and `/overtime` into Discord at configurable intervals. When a command is due, it will briefly take over your mouse and keyboard to switch to Discord, clear the message box, and send the command - then return control to whatever you were doing. You can carry on using your computer normally in between.

Optional sleepy and lazy modes will pause it overnight and take random breaks through the day, so it isn't running flat out around the clock.

---

## Requirements

- **Windows only**
- **Python 3.12** - recommended. Python 3.14 has a known compatibility issue with PyInstaller if you plan to compile it
- The following Python packages (see installation below):
  - `pyautogui`
  - `pygetwindow`
  - `pyperclip`
  - `keyboard`

---

## Installation

1. Install Python 3.12 from [python.org](https://www.python.org). During installation, make sure to tick **"Add Python to PATH"**
2. Download or clone this repository
3. Open a command prompt in the folder and run:

```
pip install -r requirements.txt
```

---

## First Time Setup

Run the script by double-clicking `tacoshack.bat` (or `python discord_auto.py` in a command prompt).

On first launch with no config file, you'll be walked through a setup wizard:

**Step 1: Command cooldowns**

Enter how many minutes between each command. Press Enter to accept the defaults:

```
Minutes between /tips (default: 2m):
Minutes between /work (default: 6m):
Minutes between /overtime (default: 30m):
```

**Step 2: Calibration timer**

Enter how many seconds you'd like for each calibration countdown. 10 seconds is usually plenty:

```
Seconds to hover over taskbar icon during calibration (default: 10s):
Seconds to hover over message box during calibration (default: 10s):
```

**Step 3: Mouse calibration**

After setup, you'll be shown a clear explanation of what's about to happen and asked to press any key when ready. Then:

1. **Taskbar icon** - hover your mouse over the Discord icon in your taskbar and hold it there during the countdown
2. **Message box** - switch to Discord, navigate to your channel, hover over the message input box at the bottom and hold it there during the countdown

Everything is saved to `discord_auto_config.json` automatically. Next time you launch, setup is skipped entirely.

---

## Daily Use

Launch the script via `tacoshack.bat`. On startup there's a 10 second grace period before the first command fires (then the rest follow at 8 second intervals), and warning beeps are suppressed for the first 45 seconds - so a quiet window at launch is normal, not a hang. The main display shows:

```
──────────────────────────────────────────────────────────────────────────
  TacoShack Auto-Commander  |  Close window to stop
──────────────────────────────────────────────────────────────────────────
  RUNNING
  Uptime: 01:23:45

     Command      Next in   Last sent
     ─────────── ────────   ──────────
  1. /tips          01:47   15:32:01
  2. /work          04:12   15:29:45
  3. /overtime      22:08   15:10:02
  4. /daily      22:38:40   14:57:44

  Sent:   tips ×14  |  work ×6  |  overtime ×1  |  daily ×1

──────────────────────────────────────────────────────────────────────────
  P pause   T adjust timer   E edit cooldown   C recalibrate
  B beeps: on   S sleepy: on 00:00-07:30 ±20m   L lazy: on (break at 14:52)
```

The table sizes itself to your longest command name, so adding something like `/buy upgrade:All Boosts` keeps everything lined up. Countdowns over an hour are shown as `hh:mm:ss`. All available hotkeys are listed along the bar at the bottom, along with the current state of the beep, sleepy and lazy toggles.

**Colour coding:**
- 🟢 **Green** - more than 30 seconds until next run
- 🟡 **Yellow** - under 30 seconds
- 🔴 **Red** - under 10 seconds (you'll also hear a double beep as a heads-up)

**Keyboard shortcuts:**
- **P** - pause or resume all commands
- **B** - toggle warning beeps on/off (for unattended mode)
- **S** - toggle sleepy mode, which pauses overnight (see below)
- **L** - toggle lazy mode, which takes random breaks through the day (see below)
- **T** - adjust a running timer as a one-off (see below)
- **E** - change a command's cooldown and save it to the config (see below)
- **C** - pause and recalibrate mouse positions (useful if you've resized or moved Discord)
- **Close the window** - stops the script

---

## Sleepy and Lazy Modes

Two optional modes that stop the script running flat out around the clock. Both are toggled with a single keypress and both are **saved to the config**, so once you switch them on they stay on across restarts. The states are shown on the hotkey bar.

### S - sleepy mode (overnight pause)

Pauses everything between two times of day, so leaving the script running by mistake doesn't keep your computer awake all night.

- Default window is **00:00 to 07:30**, set by `sleep_start` and `sleep_end` in the config
- Windows that cross midnight work fine, e.g. `23:00` to `07:30`
- Both edges are randomly nudged by up to **±20 minutes** each night (`sleep_jitter` in the config), so it doesn't stop and start at the same time every day. One night it might sleep 23:45 to 07:38, the next 00:12 to 07:14. Set it to `0` for exact times
- Each night's times are picked once and stick for that night, so it won't flick in and out of sleep
- The status line shows `SLEEPING` with that night's actual resume time and a countdown
- If you launch the script shortly after the nominal end time, it may still be inside that night's window and sit for a few minutes before starting. The status line will say so

### L - lazy mode (random breaks)

Takes a break at random intervals through the day, freeing up your screen and breaking up the regular send pattern.

- Runs for a random **1 to 2 hours**, then breaks for a random **30 to 60 minutes**, then picks a fresh interval
- Ranges are set by `lazy_work_min` / `lazy_work_max` and `lazy_break_min` / `lazy_break_max` in the config, all in minutes
- The status line shows `LAZY BREAK` with the resume time; the hotkey bar shows when the next break is due
- Switching it off during a break resumes immediately rather than waiting the break out
- Expect to lose roughly a third of your daily sends with the default ranges. Narrow the break range if that's too much

**How they interact:** sleepy mode takes precedence. The lazy cycle is reset while sleeping, so you won't wake up at 07:30 straight into a break that was due at 3am - the first break of the day lands an hour or two after waking.

**Catching up on resume:** several commands will have gone overdue during any pause. Rather than firing them all in the same second, they're restaggered when the script picks back up: the first lands 10 to 40 seconds after resuming, and the rest follow at random 6 to 15 second gaps in a shuffled order.

---

## Adjusting Timers and Cooldowns

There are two ways to change when a command fires, depending on whether the problem is with *this run* or with the cooldown itself. Both show a numbered list matching the numbers in the main table, both take minutes (including decimals like `3.5`) and do the seconds conversion for you, and both cancel with nothing changed if you press Enter on its own.

### T - adjust a running timer (one-off)

If a command doesn't land - say `/overtime` misfires and you only notice five minutes later, then send it manually - the script's countdown is now out of step with the real cooldown. Press **T** to nudge it back into line.

```
  Adjust a running timer  (one-off - config is not changed)

    1. /tips        01:47 remaining
    2. /work        04:12 remaining
    3. /overtime    22:08 remaining

  Press Enter on its own at any point to cancel.

  Which command? (number): 3
  Adjust /overtime by how many minutes? (e.g. +5 or -5): +5
```

- Positive pushes the next run further away, negative brings it forward
- The change is a **one-off** - your config is untouched, so the run after that one goes back to normal
- Subtract more time than is remaining and the command is simply due immediately, firing shortly after you exit

### E - edit a cooldown (permanent)

If the cooldown itself is wrong, press **E**. This saves to `discord_auto_config.json` for you, so there's no need to edit the file by hand or work out how many seconds are in 3.5 minutes.

```
  Edit a cooldown  (saved to config)

    1. /tips       2m cooldown
    2. /work       6m cooldown
    3. /overtime   30m cooldown

  Press Enter on its own at any point to cancel.

  Which command? (number): 2
  New cooldown for /work in minutes (currently 6m): 3.5

  /work: 6m → 3.5m (210s), saved to config.
  Running countdown adjusted - now 00:23 remaining.
```

- The new value is written to the config immediately - no restart needed
- The countdown already running is shifted by the difference, so the change takes effect straight away rather than from the next cycle
- To **add or remove** commands rather than retime them, edit the `commands` section of the config and press **C**

While either prompt is open, commands are paused and nothing fires underneath you. If a command happens to be mid-send when you press the key, the prompt waits for it to finish first.

---

## Carry On Using Your Computer

The script is designed to run in the background while you work. When a command is due, it will:

1. Switch to Discord
2. Wait for a 2 second gap in your typing so it doesn't interrupt you mid-sentence
3. Clear the message box of anything that may have landed there
4. Paste and send the command
5. Return focus to whatever you were doing

You don't need to babysit it - just leave it running.

---

## Configuration

All settings are stored in `discord_auto_config.json` in the same folder as the script. You can edit this file directly with any text editor:

```json
{
  "random_extra_min": 10,
  "random_extra_max": 25,
  "taskbar_hover_time": 10,
  "msgbox_hover_time": 10,
  "commands": {
    "/tips": 120,
    "/work": 360,
    "/overtime": 1800
  },
  "taskbar": [165, 1053],
  "msgbox": [960, 1020],
  "sleepy_mode": false,
  "sleep_start": "00:00",
  "sleep_end": "07:30",
  "sleep_jitter": 20,
  "lazy_mode": false,
  "lazy_work_min": 60,
  "lazy_work_max": 120,
  "lazy_break_min": 30,
  "lazy_break_max": 60
}
```

| Key | Description |
|-----|-------------|
| `random_extra_min` | Minimum extra seconds added to each cooldown |
| `random_extra_max` | Maximum extra seconds added to each cooldown |
| `taskbar_hover_time` | Seconds allowed to hover over taskbar icon during calibration |
| `msgbox_hover_time` | Seconds allowed to hover over message box during calibration |
| `commands` | Command names and their cooldowns in seconds |
| `taskbar` | Recorded taskbar icon coordinates (set by calibration) |
| `msgbox` | Recorded message box coordinates (set by calibration) |
| `sleepy_mode` | Whether sleepy mode is on (toggled with **S**) |
| `sleep_start` | Start of the overnight pause, as `HH:MM` |
| `sleep_end` | End of the overnight pause, as `HH:MM` |
| `sleep_jitter` | Maximum minutes each night's start and end times are randomly moved by (`0` for exact times) |
| `lazy_mode` | Whether lazy mode is on (toggled with **L**) |
| `lazy_work_min` | Minimum minutes of running before a lazy break |
| `lazy_work_max` | Maximum minutes of running before a lazy break |
| `lazy_break_min` | Minimum length of a lazy break, in minutes |
| `lazy_break_max` | Maximum length of a lazy break, in minutes |

The `sleepy_mode` and `lazy_mode` values are written by the **S** and **L** hotkeys, so there's no need to edit them by hand. The time and range values are only settable in the config.

**Adding or removing a command:** edit the `commands` section, then press **C** in the script - new commands are picked up and scheduled with a full cooldown, and removed commands disappear from the display. No restart needed.

**Changing cooldowns:** easiest done with **E** in the script - it takes minutes, converts to seconds, saves the config and adjusts the running countdown for you. If you'd rather edit the JSON directly you still can: change the values, then press **C**, and any countdown currently running adjusts by the difference - e.g. if `/work` has 3 minutes left and you raise its cooldown from 360 to 540 seconds, the live countdown jumps to 6 minutes.

---

## Logging

The script keeps a running log in `logfile.txt` in the same folder:

```
29/07/2026 - tips:131 | work:62 | overtime:16
28/07/2026 - tips:201 | work:95 | overtime:17
```

- Counts are updated every time a command is successfully sent
- If you start a new session on the same day, counts continue from where they left off
- At midnight the counts reset and a new line is started for the new date
- Newest date is always at the top

---

## Troubleshooting

**Discord isn't being detected**
The script looks for a window titled "Discord". Make sure Discord is open and not minimised to the system tray. If Discord is in the tray the script will pause and wait until it's restored.

**Commands firing in the wrong channel**
The script has no way to check which channel or server Discord is currently showing. If you switch to another server, channel, or DMs while the script is running, commands will be sent there instead. Make sure Discord is left on the correct channel when commands are due to fire.

**Commands are firing in the wrong window**
Press **C** to recalibrate - your Discord window may have moved or been resized since the positions were last saved.

**The beep isn't working or sounds delayed**
If you're using Bluetooth headphones, the first beep of a session may be lost while the headphones wake up. A double beep is used to compensate for this. If you hear nothing at all, your system may not support `winsound.Beep` - this is cosmetic only and won't affect functionality.