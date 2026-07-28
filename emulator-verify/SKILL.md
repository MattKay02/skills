---
name: emulator-verify
description: Verify a running Android emulator's UI state by capturing screenshots via adb and reading them back as images, and optionally drive the app through a flow with adb input. Use any time you want to visually confirm an emulator render after a Flutter (or native Android) code change — checking a banner state, a chip color, a layout, an error overlay, or any "did this draw correctly?" question — instead of asking the user to look at their screen.
---

# Verifying an Android emulator's UI

The Android emulator runs as a separate window on the user's machine. You can't see it directly, but you can pull screenshots over adb and read the PNG with your multimodal vision tools. One screencap takes ~2 seconds and is the fastest way to confirm a UI state.

## Preconditions

- The emulator is running. Confirm with `flutter devices` — you should see an `emulator-5554` entry (or similar). If not, boot one via `flutter emulators --launch <avd-name>`.
- `adb` is on PATH (installed with the Android SDK; typically under `<android-sdk>/platform-tools/`).
- A `flutter run -d emulator-5554` session is alive against the emulator. Without it, you'll be screenshotting an empty app launcher.

## Take a screenshot

**The right command depends on your shell.** Getting this wrong yields a file that looks plausible (tens of KB) but will not decode.

### PowerShell (and any Windows-default shell)

```powershell
adb shell screencap -p /sdcard/s.png
adb pull /sdcard/s.png screen.png
adb shell rm /sdcard/s.png
```

Round-trip through the device's filesystem. It is the only reliable form here: **PowerShell's `>` re-encodes a native command's stdout as text**, so it corrupts binary no matter which adb mode produced it. `adb exec-out screencap -p > screen.png` fails in PowerShell for this reason — the redirection mangles the bytes after adb has already done its part correctly.

### bash / zsh / cmd

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

Then `Read` the PNG to see it:

```
Read('screen.png')
```

The image renders as an inline visual in tool output. You can see fonts, colors, brand assets, layout — anything that's drawn.

## Driving the app yourself

Screenshots answer "what does it look like"; taps get you to the screen worth looking at. For a multi-step flow you can drive the emulator directly rather than asking the user to tap:

```bash
adb shell input tap 540 2210          # x y, in device pixels
adb shell input swipe 540 1800 540 600 400   # x1 y1 x2 y2 duration_ms
adb shell input text "hello"
adb shell input keyevent KEYCODE_BACK
```

**Coordinates come from the screenshot you just read, scaled.** A screenshot read back is often displayed to you at a reduced size — multiply by the stated factor to get device pixels (e.g. a 1080×2400 screen shown at 900×2000 needs ×1.2). Getting this backwards is the usual reason a tap lands on nothing.

Chain a whole sequence in one command with short sleeps between steps, then screenshot once at the end. A six-step flow (open a tab → open settings → scroll → tap a control → go back → open another tab) is entirely doable this way and much faster than a round trip per tap.

**The caveat still stands:** pixel coordinates are fragile and a layout change silently breaks them. Re-screenshot whenever you're unsure rather than firing taps blind, and prefer semantic Flutter tooling (the `dart` / `flutter_driver` MCP tools — widget tree, hot reload) when you need robust interaction rather than a one-off walk.

## Patterns

**One-shot sanity check.** After a code change, screenshot once and look at the result. Did the banner change color? Is the new chip there? Did navigation work?

**Multi-step flow verification.** Drive the sequence with `input tap`, screenshotting after each meaningful step. Beats asking the user to describe the screen.

**Regression spot-check before commits.** Before claiming a feature is done, screenshot the affected screen and the home screen. Confirm nothing visibly broke.

## Common diagnostics

- **`No devices/emulators found`** → boot the AVD first (`flutter emulators --launch <avd-name>`).
- **Screenshot is blank/black** → the emulator is off or in a lock-screen state; unlock and retry.
- **Screenshot shows the system launcher, not your app** → no `flutter run` session is active; launch it.
- **PNG is corrupt / `Read` can't decode** → you used the wrong form for your shell. In PowerShell use `adb shell screencap` + `adb pull`; in bash/cmd use `adb exec-out ... >`. See the table above — the two shells fail in opposite directions, so "add `exec-out`" is not a universal fix.
- **Install fails with `Requested internal only, but not enough space`** → the emulator's `/data` is full (check with `adb shell df -h /data`; the default AVD is only ~6 GB and old installs accumulate). Free it by uninstalling packages (`adb shell pm list packages -3`, then `adb uninstall <pkg>`), or factory-reset the AVD with `emulator -avd <name> -wipe-data -no-snapshot-load` (~70s to reboot). **Wiping destroys everything on the device — confirm with the user first.**
- **The app renders but sits on a spinner** → that's a real finding, not a screenshot problem. A data source that throws inside an un-caught `initState` load leaves the screen in its loading state forever. Check `adb logcat -d -t 200` for the exception before assuming the capture failed.
- **`adb root` fails with "adbd cannot run as root in production builds"** → you're on a Google Play system image. Use unrooted alternatives (`adb shell dumpsys diskstats`) or pick a non-Play AVD.
