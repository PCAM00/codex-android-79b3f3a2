# Source and licensing

This project builds a separately installed, Termux-derived Android environment. The launcher name **Codex** is a user-requested local label, not a claim of being an official OpenAI Android application.

The app source is pinned in `source-lock.json` to the official [termux/termux-app](https://github.com/termux/termux-app) repository. Its license is **GPL-3.0-only**, with the exceptions documented by the upstream project:

- [Upstream license](https://github.com/termux/termux-app/blob/v0.118.3/LICENSE.md)
- [Shared-library exceptions](https://github.com/termux/termux-app/blob/v0.118.3/termux-shared/LICENSE.md)
- The terminal-view and terminal-emulator modules retain upstream Apache-2.0 code and notices.

Build recipes and local source adaptations in this repository are provided under GPL-3.0-only. Preserve upstream copyright and license notices. Native packages retain their individual upstream licenses and pinned source URLs/hashes in the selected termux-packages revision.

The APK build also publishes an archive of its modified app sources and recipes, excluding build outputs and signing keys. Native build recipes are traceable to the exact official termux-packages revision. No private signing identity or model credential is part of the corresponding source.
