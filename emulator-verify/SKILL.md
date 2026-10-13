---
name: emulator-verify
description: Verify a running Android emulator's UI state by capturing screenshots via adb and reading them back as images, and optionally drive the app through a flow with adb input or deep links. Use any time you want to visually confirm an emulator render after a Flutter (or native Android) code change (checking a banner state, a chip color, a layout, an error overlay, or any "did this draw correctly?" question) instead of asking the user to look at their screen, and to capture a before/after set of every screen for a design or refactor pass.
---

# Verifying an Android emulator's UI

The Android emulator runs as a separate window on the user's machine. You can't see it directly, but you can pull screenshots over adb and read the PNG with your multimodal vision tools. One screencap takes ~2 seconds and is the fastest way to confirm a UI state.

## Preconditions

- The emulator is running. Confirm with `flutter devices` — you should see an `emulator-5554` entry (or similar). If not, boot one via `flutter emulators --launch <avd-name>`.
- `adb` is on PATH (installed with the Android SDK; typically under `<android-sdk>/platform-tools/`).
- A `flutter run -d emulator-5554` session is alive against the emulator. Without it, you'll be screenshotting an empty app launcher.
- Python with Pillow (`pip install pillow`), for the helper script below.

## Take a screenshot

**Never Read a full-size capture.** The default emulator phone is 1080×2400. Reading a 2400px-tall image has been seen to break image reading for the rest of the session (likely because the API caps image size lower once a conversation holds many images, and the big one stays in the history). Keep the full-size PNG for records and before/after, and Read only a downscaled copy, at most 2000px on its long edge. Half size (540×1200) is plenty to read text.

### With the helper

`scripts/shot.py` is in this skill's folder; call it by its full path from the project. It saves both files in one step:

```bash
python <skill>/scripts/shot.py capture .tmp-verify/home.png
# .tmp-verify/home.png        1080x2400  (keep; do not Read)
# .tmp-verify/home.small.png  540x1200   <- Read this one. Device px = small px x 2
```

It calls adb itself and keeps the bytes, so no shell redirect is involved and it works the same from PowerShell and bash. `shot.py shrink <png>` makes the small copy of a PNG you already have.

### By hand

**The right command depends on your shell.** Getting this wrong yields a file that looks plausible (tens of KB) but will not decode.

**PowerShell (and any Windows-default shell)**

```powershell
adb shell screencap -p /sdcard/s.png
adb pull /sdcard/s.png screen.png
adb shell rm /sdcard/s.png
```

Round-trip through the device's filesystem. It is the only reliable form here: **PowerShell's `>` re-encodes a native command's stdout as text**, so it corrupts binary no matter which adb mode produced it. `adb exec-out screencap -p > screen.png` fails in PowerShell for this reason — the redirection mangles the bytes after adb has already done its part correctly.

**bash / zsh / cmd**

```bash
adb exec-out screencap -p > screen.png
```

Here `>` is byte-safe, and `exec-out` is what you want: it's the adb variant that doesn't wrap stdout in line-ending translation. Plain `adb shell screencap -p > file` **does** come back corrupt in these shells, because adb's shell mode inserts CRLF.

So the two failure modes are opposites, and the fix is not the same one:

| Shell | Use | Why the other fails |
|---|---|---|
| PowerShell | `adb shell screencap` + `adb pull` | `>` re-encodes bytes as text |
| bash / zsh / cmd | `adb exec-out screencap -p >` | `adb shell` adds CRLF translation |

If you have a Bash tool available on Windows, the `exec-out` one-liner works there too — it is PowerShell's redirection that is the problem, not Windows.

Then shrink it before you Read it:

```bash
python -c "from PIL import Image; im = Image.open('C:/work/screen.png'); im.resize((im.width // 2, im.height // 2)).save('C:/work/screen.small.png')"
```

Windows-native Python can't open Git Bash's `/c/...` paths. Git Bash rewrites a path passed as its own argument, but not one inside a `python -c "..."` string, so write `C:/...` there (`cygpath -m /c/work` converts). No Pillow? `magick screen.png -resize 50% screen.small.png` or `ffmpeg -i screen.png -vf scale=iw/2:-1 screen.small.png` do the same, as does `sips -Z 1200` on a Mac.

### Read the small copy

```
Read('.tmp-verify/home.small.png')
```

The image renders as an inline visual in tool output. You can see fonts, colors, brand assets, layout — anything that's drawn.

**Crop with the coordinates of the image you crop.** To look closer at one strip, such as a snackbar at the bottom, crop the small copy in its own pixels: on a 540×1200 copy the bottom fifth is y 960 to 1200. Device coordinates (1920 to 2400) fall off the small image, and Pillow pads the crop with black instead of failing, so you get an all-black picture. Cropping the full-size file with device coordinates is fine too, as long as the crop itself stays under 2000px.

## Driving the app yourself

Screenshots answer "what does it look like"; taps get you to the screen worth looking at. For a multi-step flow you can drive the emulator directly rather than asking the user to tap:

```bash
adb shell input tap 540 2210          # x y, in device pixels
adb shell input swipe 540 1800 540 600 400   # x1 y1 x2 y2 duration_ms
adb shell input text "hello"
adb shell input keyevent KEYCODE_BACK
```

**Coordinates come from the small copy, scaled up.** Multiply what you read on it by the factor the helper printed (×2 for half size) to get device pixels: a button at (270, 1105) on a 540×1200 copy is `input tap 540 2210`. If the Read result says the image was shown smaller still, multiply that in too. Getting this backwards is the usual reason a tap lands on nothing.

Chain a whole sequence in one command with short sleeps between steps, then screenshot once at the end. A six-step flow (open a tab → open settings → scroll → tap a control → go back → open another tab) is entirely doable this way and much faster than a round trip per tap.

**Or skip the taps with a deep link.** If the app routes links, open a screen directly:

```bash
adb shell am start -a android.intent.action.VIEW -d "https://example.com/settings" -n com.example.app/.MainActivity
```

The explicit `-n <package>/<activity>` hands the URL straight to your running app, even for paths outside its declared App Links filters, as long as the app's own deep-link routing is on (Flutter with go_router: the `flutter_deeplinking_enabled` manifest flag, on by default since Flutter 3.27). Without `-n`, Android may open the browser instead. `adb shell cmd package resolve-activity --brief <package>` prints the activity on its last line. If the URL has `?` or `&`, quote it for the device shell too: `adb shell "am start ... -d 'https://example.com/a?b=1&c=2' ..."`.

**The caveat still stands:** pixel coordinates are fragile and a layout change silently breaks them. Re-screenshot whenever you're unsure rather than firing taps blind, and prefer semantic Flutter tooling (the `dart` / `flutter_driver` MCP tools — widget tree, hot reload) when you need robust interaction rather than a one-off walk.

## Patterns

**One-shot sanity check.** After a code change, screenshot once and look at the result. Did the banner change color? Is the new chip there? Did navigation work?

**Multi-step flow verification.** Drive the sequence with `input tap`, screenshotting after each meaningful step. Beats asking the user to describe the screen.

**Regression spot-check before commits.** Before claiming a feature is done, screenshot the affected screen and the home screen. Confirm nothing visibly broke.

**Before/after set for a design or refactor pass.** Capture every screen in a fixed list before you change anything, then the same list after, and compare. Write the list once, one `name route` per line, with `scroll` after the route to swipe a screen down first:

```text
01-home        /
02-settings    /settings
03-settings-2  /settings  scroll
```

```bash
python <skill>/scripts/shot.py set screens.txt .tmp-verify/v2-ui/before --component com.example.app/.MainActivity --base https://example.com
# make the change, then run the same list into .tmp-verify/v2-ui/after
python <skill>/scripts/shot.py sheet .tmp-verify/v2-ui/before .tmp-verify/v2-ui/after
```

`set` fires each deep link, waits, and saves `NN-name.png` at full size plus its small copy. `sheet` lays every screen out with its before beside its after, each page at most 2000px. Read the sheets rather than each image, then the small copy of any screen that looks off. Keep `.tmp-verify/` in the project's `.gitignore`; the captures hold real app data.

- **Wait generously.** A slow emulator needs a `--wait` above what feels enough, and the first hit on a route of a local dev server can compile for 10 to 20s. A "loading" or "server error" capture may be timing, so retake it before believing it.
- **A page that fits on one screen** makes its `scroll` capture a duplicate. Drop that line from the list.
- **Snackbars and toasts are gone in seconds.** Capture twice, about 1.5s apart, and keep the one that caught it.

## Common diagnostics

- **`No devices/emulators found`** → boot the AVD first (`flutter emulators --launch <avd-name>`).
- **Screenshot is blank/black** → the emulator is off or in a lock-screen state; unlock and retry.
- **Screenshot shows the system launcher, not your app** → no `flutter run` session is active; launch it.
- **PNG is corrupt / `Read` can't decode** → you used the wrong form for your shell. In PowerShell use `adb shell screencap` + `adb pull`; in bash/cmd use `adb exec-out ... >`. See the table above — the two shells fail in opposite directions, so "add `exec-out`" is not a universal fix. The helper avoids the question by never redirecting.
- **Image reads stop working partway through a session** → a full-size capture was Read. It may not recover in that session, so prevention is the fix: Read only small copies.
- **A crop comes back all black** → device coordinates were used on the small copy. Crop each image in its own pixels.
- **Install fails with `Requested internal only, but not enough space`** → the emulator's `/data` is full (check with `adb shell df -h /data`; the default AVD is only ~6 GB and old installs accumulate). Free it by uninstalling packages (`adb shell pm list packages -3`, then `adb uninstall <pkg>`), or factory-reset the AVD with `emulator -avd <name> -wipe-data -no-snapshot-load` (~70s to reboot). **Wiping destroys everything on the device — confirm with the user first.**
- **The app renders but sits on a spinner** → retake once after a longer wait, since a local dev server may still be compiling the route. If it still spins, that's a real finding, not a screenshot problem. A data source that throws inside an un-caught `initState` load leaves the screen in its loading state forever. Check `adb logcat -d -t 200` for the exception before assuming the capture failed.
- **A deep link opens the browser, or lands on the app's first screen** → add `-n <package>/<activity>`, and check the app's deep-link routing is on.
- **Results don't match the backend you just changed** → another dev server may hold the port. `next dev` and similar print "port 3000 in use, using 3001 instead" and carry on, so the device can be talking to an old server. Check what owns the port (`netstat -ano | findstr :3000` on Windows, `lsof -i :3000` elsewhere) and what the device maps (`adb reverse --list`) before trusting a result.
- **`adb root` fails with "adbd cannot run as root in production builds"** → you're on a Google Play system image. Use unrooted alternatives (`adb shell dumpsys diskstats`) or pick a non-Play AVD.
