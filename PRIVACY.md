# Privacy Policy

_Last updated: 2026-06-20_

This privacy policy applies to the **feris** version of the Voice Changer (an
updated fork of [w-okada/voice-changer](https://github.com/w-okada/voice-changer)
via [Deiteris/voice-changer](https://github.com/deiteris/voice-changer)). In this
document, "the software" or "the tool" means this application, and "feris" means
the maintainer of this fork.

## The short version

**feris does not collect anything from you.** There are no accounts, no sign-up,
no analytics, no telemetry, no tracking, and no "phone home." Your microphone
audio, your voice, your voice models, and your settings stay on **your own
device(s)**. feris never receives them and operates no server that your audio is
sent to.

## What data feris collects

**None.** Specifically, the software contains:

- **No analytics or telemetry** of any kind (verified — there are no analytics
  or tracking libraries in the codebase).
- **No user accounts, logins, or registration.**
- **No advertising or tracking cookies.**
- **No crash/usage reporting to feris.**

feris has no servers that receive your data and therefore stores nothing about
you.

## Where your data goes

- **Your microphone audio is processed on your own machine.** Real-time
  conversion runs locally on the computer running the server.
- **Two-PC ("host") mode:** if you run the server on one PC and connect from
  another, your audio travels **only over your own local network** between your
  two devices. It is not sent to feris or any third party.
- **Voice calibration:** the optional calibration feature measures your pitch
  and saves a small *profile of numbers* (e.g. your typical pitch in Hz). **No
  audio recording is stored** — only those numbers — and the file lives on your
  own machine.
- **Settings and logs** are written to local files on your machine only.
- **Your voice models** (the `.pth`/`.onnx`/index files you add) stay on your
  machine. Uploading a model in the UI copies it locally on the server machine;
  it is not sent anywhere external.

## Internet connections the software makes (full transparency)

The software is usable largely offline, but it does make a few **outbound
downloads** so it can run. These are downloads **to you** — no information about
you is uploaded beyond the normal technical details any web request includes
(such as your IP address, which is visible to the host you download from, as
with any download):

- **Pre-trained model files** (pitch detectors, embedders such as HuBERT/
  ContentVec, RMVPE, CREPE, FCPE) are downloaded on first run from public
  repositories on **Hugging Face** and **GitHub**.
- **Sample model lists/files**, if you choose to download a sample voice, come
  from public Hugging Face repositories.
- **Optional advanced noise suppression (Amazon Chime "VoiceFocus"):** only if
  you turn it on in Quality settings, the browser may download that model from
  Amazon's servers. The audio itself is still processed locally in your browser.
- The **"Background noise cleanup"** toggle added in this version uses your
  **browser's built-in** noise suppression and is fully local (no download).

These third-party hosts (Hugging Face, GitHub, Amazon) have their own privacy
policies, which feris does not control.

## Your voice and likeness

You are solely in control of the voice models you use and the audio you create.
That data never reaches feris. Please use the tool responsibly and with consent
(see [`TERMS.md`](./TERMS.md)).

## Children

The software does not knowingly collect any data from anyone, including
children, because it does not collect data at all.

## How you can verify this yourself

This software is open source. You can:

- inspect the code for any tracking (there is none),
- run it with a firewall and block outbound traffic after the model files have
  downloaded — voice conversion will keep working fully offline, and
- watch your network traffic to confirm audio is only sent to your own
  server/LAN.

## Changes to this policy

If this policy changes, the "Last updated" date above will change. Because no
data is collected, changes will generally only clarify wording.

## Contact

This is a free, community fork maintained by **feris**. There is no data to
request, correct, or delete on any feris server, because none is collected. Any
local files (settings, calibration profile, logs, models) are on your device and
fully under your control.
