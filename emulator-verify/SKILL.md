---
name: emulator-verify
description: Verify a running Android emulator's UI state by capturing screenshots via adb and reading them back as images. Use any time you want to visually confirm an emulator render after a Flutter (or native Android) code change — checking a banner state, a chip color, a layout, an error overlay, or any "did this draw correctly?" question — instead of asking the user to look at their screen. Prefer this over driving the app via adb input tap (which is fragile) unless you need to interact with the UI, not just observe it.
---

# Verifying an Android emulator's UI

The Android emulator runs as a separate window on the user's machine. You can't see it directly, but you can pull screenshots over adb and read the PNG with your multimodal vision tools. One screencap takes ~2 seconds and is the fastest way to confirm a UI state.

## Preconditions

- The emulator is running. Confirm with `flutter devices` — you should see an `emulator-5554` entry (or similar). If not, boot one via `flutter emulators --launch <avd-name>`.
- `adb` is on PATH (installed with the Android SDK; typically under `<android-sdk>/platform-tools/`).
- A `flutter run -d emulator-5554` session is alive against the emulator. Without it, you'll be screenshotting an empty app launcher.

## Take a screenshot

```bash
adb exec-out screencap -p > /tmp/screen.png
```

`screencap -p` writes a PNG to stdout; `exec-out` is the adb variant that doesn't wrap stdout in line-ending translation (essential — without `exec-out`, the PNG comes back corrupt on Windows). Redirect to any writable temp path.

Then `Read` the PNG to see it:

```
Read('/tmp/screen.png')
```

The image renders as an inline visual in tool output. You can see fonts, colors, brand assets, layout — anything that's drawn.

## Patterns

**One-shot sanity check.** After a code change, screenshot once and look at the result. Did the banner change color? Is the new chip there? Did navigation work?

**Multi-step flow verification.** Ask the user to tap through a sequence (sign in → open a screen → tap a control → confirm), screenshotting after each step yourself. Beats them describing the screen.

**Regression spot-check before commits.** Before claiming a feature is done, screenshot the affected screen and the home screen. Confirm nothing visibly broke.

## When not to use this

- **You need to interact with the UI**, not just observe. `adb shell input tap X Y` sends taps at pixel coordinates, but coordinates are fragile and a tiny layout change breaks them. For real interaction, lean on semantic Flutter tooling (the `dart` / `flutter_driver` MCP tools — widget tree, hot reload) that reason about widgets, not pixels.
- **The user just wants to know if something works** and they're already at the keyboard with the answer one tap away. Use this when *you* need to verify something between turns, or when scripting a multi-step sequence.

## Common diagnostics

- **`No devices/emulators found`** → boot the AVD first (`flutter emulators --launch <avd-name>`).
- **Screenshot is blank/black** → the emulator is off or in a lock-screen state; unlock and retry.
- **Screenshot shows the system launcher, not your app** → no `flutter run` session is active; launch it.
- **PNG is corrupt / `Read` can't decode** → you used `adb shell screencap -p` instead of `adb exec-out screencap -p`. Re-run with `exec-out`.
