# Codex · Independent Android Environment

Private build project for a Termux-derived Android application named **Codex**, application ID **`io.cdxbox`**.

This is not an official OpenAI Android app. It does not reuse or overwrite `com.termux` or `com.dsharnessmobile.shell`.

## Build contract

- Pin official upstream revisions in `source-lock.json`.
- Compile aarch64 native programs for `/data/data/io.cdxbox/files/usr`; do not rename prebuilt `com.termux` binaries.
- Preserve the upstream Android 7+ / target-SDK-28 execution model until device compatibility is verified.
- Use a dedicated signing key, separate from the existing Termux and DSH applications.
- Never put GitHub tokens, API keys, signing passwords or private keys in source or APK assets.
- Bootstrap native APT sources are disabled: only matching native package artifacts may be installed. Ordinary `com.termux` repositories cannot be used with this package ID.
- Codex CLI, its Linux/runtime requirements and a phone graphical interface are subsequent validation steps; compiling this APK alone does not prove them working.

## Current status

Source preparation and CI setup. No APK has yet been declared usable; final reports must distinguish static checks from actual Android installation/runtime tests.

## Official sources

- https://github.com/termux/termux-app#forking
- https://github.com/termux/termux-packages/wiki/Building-packages
- https://github.com/termux/termux-packages/wiki/For-maintainers#build-bootstrap-archives

The pinned upstream `build-bootstraps.sh` is used with small audited script repairs, not an unreviewed draft fork. Android classes retain their upstream Java namespace while the installation identity and private paths are independently retargeted.
