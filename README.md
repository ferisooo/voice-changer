# Kawaii Voice Changer

Free, open-source **real-time voice changer** for Windows, Linux, and macOS —
speak into your mic and come out as a different voice in games, calls, and
streams. Runs **locally** on your machine (RVC models only).

> **Not my software.** I (**feris**) didn't build the voice-conversion engine.
> This is an easier-to-use build with quality-of-life features on top. Full
> credits below.

- 🔒 Privacy: feris collects **nothing** — [`PRIVACY.md`](./PRIVACY.md)
- 📜 Terms: [`TERMS.md`](./TERMS.md)
- 📖 Full manual (hardware, troubleshooting, building, two-PC setup): [`voice changer/README.md`](./voice%20changer/README.md)

## What this version adds

Comfort/stability features on top of the unchanged conversion engine:

- **Auto Pitch** (noise-robust) — keeps your voice in range automatically
- **Voice calibration** — ~45s once, saves a tiny pitch profile (no audio stored)
- **Pitch limits**, **Auto-smooth** (adaptive buffer), **noise cleanup**
- **Extra Controls panel** — all tweaks in one grid with tooltips
- **Two-PC launcher** — Windows `.bat` that auto-finds the host PC

## Setup

For games/Discord/OBS you'll want a virtual audio cable like
[VAC Lite](https://software.muzychenko.net/freeware/vac470lite.zip).
Needs ~6 GB disk + ~6 GB RAM. Other OSes and details are in the
[full manual](./voice%20changer/README.md).

## Credits

- **[w-okada/voice-changer](https://github.com/w-okada/voice-changer)** — original project (MIT).
- **[Deiteris/voice-changer](https://github.com/deiteris/voice-changer)** — optimized RVC fork this build is based on.
- **feris** — quality-of-life & stability features, this build.
- **Claude (Anthropic)** — helped implement those features and docs.

No affiliation with or endorsement by w-okada or Deiteris. Trademarks belong to
their respective owners.
