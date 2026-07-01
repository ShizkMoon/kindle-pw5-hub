# Kindle Paperwhite 5 Setup Guide

Practical setup and configuration for KPW5 (11th Gen), jailbroken with KOReader as primary reader. Kindle native system is retained as backup but is not the daily driver.

---

## Device Specifications

| Spec | KPW5 (11th Gen, 2021) |
|---|---|
| Display | 6.8" E Ink Carta 1200, 300 PPI |
| Front light | 17 LEDs (white + amber warm light) |
| Storage | 8 GB / 16 GB / 32 GB (Signature Edition) |
| Connectivity | USB-C, Wi-Fi 5 (802.11ac), Bluetooth 5.0 |
| Waterproof | IPX8 (2m fresh water, 60 min) |
| Battery | 1700 mAh |
| Dimensions | 174 x 125 x 8.1 mm, 205 g |
| Firmware target | Must be **< 5.18.1** for WinterBreak |

---

## Jailbreak

### Prerequisites

- Firmware version **below 5.18.1**
- USB-C cable and a PC
- ~30 minutes
- Reversible: does not brick, does not void hardware warranty

### Method: WinterBreak

WinterBreak is the recommended jailbreak for KPW5. Full step-by-step instructions at the [WinterBreak Wiki](https://github.com/KindleModding/WinterBreak).

**Key steps (checklist):**

1. Verify firmware version: `Settings -> Device Options -> Device Info`
2. If firmware >= 5.18.1, downgrade is required (follow WinterBreak downgrade path)
3. Download WinterBreak package for your firmware version
4. Enter demo mode on Kindle
5. Copy WinterBreak files to Kindle root via USB
6. Trigger the exploit through demo-mode menu
7. Confirm jailbreak success: `;log mrpi` search bar command should respond
8. Exit demo mode and return to normal mode

### Post-Jailbreak Must-Dos

After successful jailbreak, complete these immediately:

| Step | Command / Action | Purpose |
|---|---|---|
| Install hotfix | Copy `Update_hotfix_*.bin` to root, then `Settings -> Update Your Kindle` | Survives firmware updates |
| Disable OTA updates | Create empty folder `/update.bin.tmp.partial/` at Kindle root (or use renameotabin extension) | Prevents Amazon from patching the jailbreak |
| Block OTA via hosts | Add `0.0.0.0 softwareupdates.amazon.com` to hosts (if using KUAL+ helper) | Network-level block |
| Install KUAL | Copy KUAL booklet to `documents/` | Application launcher required for KOReader |
| Install MRPI | Copy MRPI extension folder | Package installer for extensions |

---

## KOReader Installation

### Install via KUAL + MRPI

1. Download latest KOReader release from [koreader.rocks](https://koreader.rocks)
2. Extract to Kindle root -- merges into `extensions/` and `koreader/` folders
3. Eject Kindle, open KUAL, select KOReader to launch

### Essential Plugins (KOReader)

Install via KOReader's built-in plugin manager: `Tools -> More tools -> Plugin management`.

| Plugin | Purpose | Configuration |
|---|---|---|
| **Syncery** | Multi-device sync via Syncthing | Needs KOSyncthing+ daemon running |
| **HighlightSync** | Export highlights/notes to WebDAV | Set WebDAV URL + credentials |
| **Cloud Storage** | Download books from WebDAV | Set WebDAV URL + credentials |
| **KOSyncthing+** | Background Syncthing daemon | Pair with Windows peer via QR/code |
| **ReadTimer** | Reading time tracking and statistics | Install, enable in menu |
| **Terminal** | Built-in SSH/telnet client | For advanced management |

---

## KOReader Configuration

### Style Tweaks

Enable via: `Bottom menu -> Gear (second tab) -> Style Tweaks`.

| Tweak | Enable? | Effect |
|---|---|---|
| `Ignore publisher font families` | **Yes** | Use KOReader font for all books, ignoring embedded fonts |
| `Ignore publisher font sizes` | Optional | Only if source EPUB has erratic/messy font sizing |
| `Enforce steady line heights` | **Yes** | Prevent superscript/subscript from jittering line spacing |
| `Smaller sub- and superscript` | **Yes** | Reduce sub/superscript to 50% size for readability |
| `Hyphenation` | Optional | Enable hyphenation in body text |

### Font Setup

```
Path:  Kindle:/koreader/fonts/
Files: *.ttf, *.otf
```

KOReader auto-shares the Kindle native `fonts/` folder but has its own `koreader/fonts/` for fonts specific to KOReader. The `koreader/fonts/noto/` folder contains system fonts -- do not delete it.

**Recommended CJK fonts for KOReader:**

| Font | Style | Best For |
|---|---|---|
| Source Han Serif (思源宋体) | Serif | Long-form reading |
| Source Han Sans (思源黑体) | Sans-serif | UI and menus |
| LXGW WenKai (霞鹜文楷) | Kai-style | Literary/classical text |

**Recommended Latin fonts:**

| Font | Style | Best For |
|---|---|---|
| Bookerly | Serif | Kindle's native body font, optimized for E Ink |
| Literata | Serif | Google's e-reader font, high x-height |
| Atkinson Hyperlegible | Sans-serif | Maximum readability, Braille Institute |

### Cloud Storage -> WebDAV Setup

```
KOReader: Tools -> Cloud Storage -> Add WebDAV
  URL:      https://<server>:<port>/<path>
  Username: koreader
  Password: <webdav_password>
```

Books placed in the WebDAV directory appear in KOReader's Cloud Storage browser for download.

### Syncthing Pairing (Syncery)

1. Install KOSyncthing+ plugin on KOReader
2. Launch KOSyncthing+ -- it will show a Device ID
3. On Windows peer (Syncthing GUI: `http://127.0.0.1:8384`):
   - `Add Remote Device` -> enter KOReader's Device ID
   - Choose folders to share (e.g., KOReader's `settings/` and `highlights/`)
4. Confirm pairing on KOReader
5. Enable Syncery plugin -> it will now auto-sync via the KOSyncthing+ daemon

**Folders to sync:**

| Folder | Purpose | Direction |
|---|---|---|
| `koreader/settings/` | Reading progress, bookmarks, configuration | Bidirectional |
| `koreader/highlights/` | Highlight exports | KOReader -> PC |
| `koreader/news/` | RSS/news downloads | PC -> KOReader |

---

## Recommended Reading Settings

### Brightness and Warmth (KPW5 Hardware)

| Scenario | Brightness | Warmth | Notes |
|---|---|---|---|
| Daytime indoor | 8-10 | 0 | E Ink screen is reflective, front light is supplementary |
| Nighttime bedside | 6-8 | 15-18 | Pair with dark mode (white text on black) for zero-ambient reading |
| Outdoor sunlight | 0 | 0 | E Ink needs no front light in direct light |
| Max battery life | <= 10 | 0 | Brightness 20+ approximately halves battery life |

- **Disable auto-brightness**: the ambient light sensor drains battery continuously
- **Warmth schedule**: set automatic 19:00-07:00 or manual sunset-to-sunrise
- **Estimated battery**: brightness 10 + airplane mode = ~30h reading; brightness 24 + warmth = ~18h

### KOReader Display Settings

| Setting | Recommendation | Reason |
|---|---|---|
| E Ink refresh rate | Every page | Eliminates ghosting; KPW5 page-turn speed makes this imperceptible |
| Contrast | Default (1.0) | Adjust per book if text appears washed out |
| Font weight | Default (0) | Increase to +1 or +2 for thin CJK fonts |
| Gamma | Default (1.0) | Increase for darker text without increasing contrast |
| Screen DPI | 300 | Match KPW5 hardware |

---

## Quick Reference

### KOReader Gestures

| Gesture | Zone | Action |
|---|---|---|
| Tap | Left edge | Page back |
| Tap | Right/center | Page forward |
| Tap | Top edge | Toggle menu |
| Tap | Bottom edge | Toggle bottom menu |
| Swipe up | Left edge | Backlight brightness + |
| Swipe down | Left edge | Backlight brightness - |
| Swipe up | Right edge | Warmth + |
| Swipe down | Right edge | Warmth - |
| Long press | Word | Dictionary lookup + highlight |
| Long press | Page number (bottom) | Go to page |
| Pinch | Anywhere | Zoom (PDF/images) |
| Two-finger swipe | Anywhere | Pan (when zoomed) |

### Kindle Native Shortcuts

| Action | Method |
|---|---|
| Screenshot | Tap top-left + bottom-right corners simultaneously |
| Force restart | Hold power button 40 seconds |
| Quick brightness | Swipe down from top edge |
| Landscape mode | `Aa -> Layout -> Orientation -> Landscape` |
| Clock display | `Aa -> More -> Show Clock` |

### Common KOReader Operations

| Operation | Path |
|---|---|
| Open file browser | Top menu -> File browser |
| Switch book | Swipe down from top -> File browser, or tap book title in top menu |
| Add bookmark | Top menu -> Bookmark icon, or top-right corner tap |
| View bookmarks | Top menu -> Table of Contents -> Bookmarks tab |
| Dictionary lookup | Long-press word |
| Search in book | Top menu -> Search icon (magnifying glass) |
| Reading statistics | Top menu -> Hamburger menu -> Reading statistics |
| Cloud Storage | Top menu -> Hamburger menu -> Cloud Storage |
| Plugin management | Top menu -> Hamburger menu -> More tools -> Plugin management |
| Exit KOReader | Top menu -> Hamburger menu -> Exit -> Exit KOReader |

### Troubleshooting

| Problem | Fix |
|---|---|
| KOReader won't start | Reinstall via MRPI; check `extensions/koreader/` exists |
| Books not showing | Confirm format is EPUB; check path under `documents/` or KOReader's library scan |
| WebDAV connection fails | Verify server URL, credentials, and that server is reachable (test on phone first) |
| Syncthing not syncing | Confirm both peers online; check folder IDs match; verify no file conflicts |
| Battery drain unusually fast | Wait 24h after importing large batches (indexing); disable Wi-Fi when not needed; brightness <= 10 |
| Ghosting (residual text) | Enable "refresh every page" in KOReader; Kindle native: `Settings -> Reading Options -> Page Refresh -> On` |
| Plugins not appearing | Refresh plugin list: `Plugin management -> Reload`; confirm files are in `koreader/plugins/` |
| KOReader freeze | Exit via menu if possible; force restart Kindle if not |

### Important Notes

- **Do not connect USB while KOReader is running.** Exit KOReader first, then plug in USB. KOReader holds the filesystem and USB mass-storage mode can corrupt data.
- **Do not delete `koreader/fonts/noto/`.** These are system-level fonts that KOReader depends on.
- **KOReader and Kindle native share the `documents/` folder but maintain separate reading state.** Books read in KOReader will not show reading progress in Kindle native and vice versa.

---

## References

- [WinterBreak Jailbreak Wiki](https://github.com/KindleModding/WinterBreak)
- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [KOReader Plugin List](https://github.com/koreader/koreader/wiki/Plugins)
- [Syncthing Documentation](https://docs.syncthing.net/)
- [Bookfere Kindle 新手入门](https://bookfere.com/novice)
- [Bookfere Kindle 字典下载](https://bookfere.com/dict)
- [iFixit KPW5 Repair Guide](https://www.ifixit.com/Device/Kindle_Paperwhite_11th_Generation)
- [Standard Ebooks](https://standardebooks.org/)
