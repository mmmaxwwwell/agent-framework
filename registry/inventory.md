# Scout registry

The cross-project inventory read by the `scout` skill (`skills/scout/SKILL.md`).
- One row per repo or skill. Refresh with `bash skills/scout/scout-stale.sh`.
- Git worktrees are skipped; they belong to their parent's row.
- `rev`: repo HEAD for repos. For skills, the last commit touching the skill dir (`h:` means a content hash of uncommitted files).
- Rows are data written by agents from READMEs. Verify before relying on a claim.

## Repos

| name | kind | path | rev | what | tags | notes |
|---|---|---|---|---|---|---|
| 2040-ams-host | app | ~/git/2040-ams-host | 1544b27 | RP2040 firmware bridging Bambu AMS bus to Klipper as a Happy Hare MMU | rp2040, firmware, klipper, 3d-print, bambu, rs485, atopile, hardware | 2026-09-08 active; PIO 9-bit UART driver for AMS protocol |
| 2ndMonitor | prior-art | ~/git/2ndMonitor | nogit | Shell scripts to add a virtual second monitor via adb+xrandr+tailscale | xrandr, adb, tailscale, shell, monitor, linux | nogit; small one-off exploration scripts, abandoned |
| 3d-gallery | app | ~/git/3d-gallery | 417e596 | Browser-based OpenSCAD model gallery/viewer/slicer published to GitHub Pages | openscad, three-js, 3d-print, slicer, vite, typescript, github-pages, mcp-server | 2026-09-28 active; dev server also provides an orca-bridge MCP endpoint |
| agent-framework | skill | ~/git/agent-framework | b2bbdc3 | Collection of reusable Claude Code skills packaged as Nix flake outputs | claude-code, skills, nix-flake, agent-tooling, automation, prompts | 2026-06-01 dormant |
| agent-runner | app | ~/git/agent-runner | 936afba | Server + PWA (WebSocket/push) for running agent-framework projects remotely | typescript, nodejs, websocket, pwa, agent-tooling, push-notifications, preact | 2026-03-24 dormant; spec-kit style docs, may be superseded by newer agent-framework tooling |
| ariel | app | ~/git/ariel | 9dc0f56 | Household real-time transcription, speaker-ID and sound classification service | stt, audio, speaker-id, sound-classification, nixos-module, uses-mcp, agent-tooling | 2026-09-30 active; deployed as a NixOS module via homelab |
| astro-edge-pwa | template | ~/git/astro-edge-pwa | f701b94 | Static-first Astro PWA template deploying to Cloudflare Pages, zero SSR | astro, pwa, cloudflare-pages, typescript, template, static-site, turso, nix-flake | 2026-07-06 active |
| bambu-klipper-proxy | app | ~/git/bambu-klipper-proxy | nogit | Exposes a Bambu X1C (LAN mode) as a Moonraker/Klipper API for Mobileraker | bambu, klipper, moonraker, python, 3d-printer, proxy, lan-mode | nogit; early-stage scaffold, status unclear from code alone |
| battery-bank | app | ~/git/battery-bank | 8a30ebd | Hot-swappable modular 21700-cell UPS/power bank hardware + firmware project | battery, ups, firmware, hardware, atopile, 21700, power-bank, uses-mcp | 2026-09-23 active; spec-kit style hardware/firmware project |
| bcmu370-dual-filament-feeder | app | ~/git/bcmu370-dual-filament-feeder | nogit | Firmware turning one BCMU370 4-channel feeder into two auto-switching dual-spool feeders | firmware, 3d-print, filament-feeder, risc-v, ch32v203, klipper, hardware | nogit; early-stage firmware/hardware harness scaffold |
| blog | app | ~/git/blog | 1a9221c | Personal tech blog (electronics, 3D printing, OpenSCAD, software) built with Astro | astro, blog, mdx, tailwind, github-pages, typescript | 2026-03-29 dormant; straightforward static blog, low maintenance risk |
| boblov | app | ~/git/boblov | nogit | Clone/backup and reflash SD cards for Boblov body cameras | sd-card, backup, bash, body-camera, sfdisk, rsync, nix-flake | nogit; small standalone utility, last touched ~Mar 2026 |
| claude-code-voice-vscode | app | ~/git/claude-code-voice-vscode | 1a9c35e | VS Code extension adding voice control/dictation to Claude Code | vscode, typescript, voice, speech-to-text, python, agent-tooling, extension, nix-flake | 2026-03-25 dormant; has Python sidecar + VSIX build, no README |
| claude-runner | infra | ~/git/claude-runner | b739527 | Long-lived Claude Code agents in per-NixOS-container, controlled via PWA | nixos, agent-tooling, pwa, containers, claude-code, nixos-module, uses-mcp, kanidm | 2026-09-28 active; ships nixosModules.default consumed by homelab, pairs with manager+pwa |
| cn60-pihole | prior-art | ~/git/cn60-pihole | 79b1cdf | Terraform scripts to deploy NixOS pihole configs to remote hosts | terraform, nixos, pihole, deployment, infra-as-code, dns | 2022-10-31 abandoned; superseded by later homelab/colmena deploy tooling |
| cpiped | prior-art | ~/git/cpiped | 3abe3cc | C daemon piping line-in audio to a FIFO with silence detection | c, audio, daapd, linein, pipe, silence-detection, daemon | 2017-03-23 abandoned; small single-purpose C utility, reusable as-is if needed |
| deploy-nixos-terraform-laptop | prior-art | ~/git/deploy-nixos-terraform-laptop | 729d075 | Terraform scripts to deploy a NixOS laptop config over SSH | terraform, nixos, laptop, deployment, ssh, infra-as-code | 2022-09-26 abandoned; near-duplicate of cn60-pihole's terraform approach, superseded |
| docker-flutter | prior-art | ~/git/docker-flutter | 3cd6be2 | Docker image bundling Flutter/Android SDK + emulator for dev/CI | docker, flutter, android, emulator, devcontainer, ci | 2021-06-22 abandoned; appears to be a vendored/forked third-party image (matsp/docker-flutter) |
| enceladus | infra | ~/git/enceladus | cf0cb20 | Standalone NixOS flake config for the enceladus workstation laptop | nixos, nix-flake, workstation, configuration-management, hyprland | 2026-08-04 active; decoupled from homelab repo after its nixcfg tree was dropped |
| etchspec | app | ~/git/etchspec | 0a3e706 | Spec-kit design for a laser-engraving platform; no implementation code yet | laser-engraving, openscad, spec-kit, agent-tooling, planned-mcp, uses-mcp, typescript | 2026-06-01 dormant; spec/plan stage only, planned to ship two MCP servers once built |
| example_flutter_app | template | ~/git/example_flutter_app | 3704c35 | Flutter starter template with Nix-based Android SDK dev shell | flutter, android, nix-flake, template, mobile, dart | 2023-09-09 abandoned; generic Flutter scaffold, superseded by flutter-builder |
| flake2 | infra | ~/git/flake2 | 70c1b8d | NixOS flake config for host "hobbes" with home-manager and agenix | nixos, nix-flake, home-manager, agenix, nixos-config | 2025-01-17 dormant; single-host personal config, likely superseded by enceladus/homelab |
| flutter-adventure | app | ~/git/flutter-adventure | de197b7 | Generic Flutter "adminclient" starter app, unmodified scaffold | flutter, dart, mobile, admin-client, scaffold | 2021-01-18 abandoned; default Flutter template content, nothing custom built out |
| flutter-builder | app | ~/git/flutter-builder | fa799ed | Flutter "homelabmobile" app with Nix/Android SDK build + signing setup | flutter, android, nix-flake, android-sdk, keystore, mobile, apk-signing | 2025-01-21 dormant; has keystore.p12 and android-nixpkgs build pipeline for release signing |
| food-mountain | app | ~/git/food-mountain | 37cfd95 | Self-written static site generator for recipes from JSON data | nodejs, static-site-generator, recipes, templating, javascript | 2023-12-24 abandoned; small standalone templating engine, no framework deps |
| foster-card-generator | app | ~/git/foster-card-generator | 51cdf96 | Electron desktop app generating printable foster-animal adoption cards/flyers | electron, sqlite, puppeteer, sharp, handlebars, preact, desktop-app | 2026-04-24 dormant; well-documented, uses OpenAI optionally, QR codes, printer calibration |
| fwdy.net | infra | ~/git/fwdy.net | 72409b6 | URL shortener on Cloudflare Workers with per-org SSO and analytics | typescript, cloudflare-workers, url-shortener, oidc, d1, wrangler, ci-cd | 2026-09-26 active; enterprise eng-standards preset, CI/CD-only deploy |
| gdtscad | app | ~/git/gdtscad | d9e00d0 | GD&T-style DSL that compiles declarative specs to OpenSCAD with auto-generated drawings | openscad, dsl, 3d-print, python, cli, uses-mcp | 2026-05-25 dormant; design-only/pre-implementation, uses code-review-graph via .mcp.json |
| halow-esp32-mesh-bridge | infra | ~/git/halow-esp32-mesh-bridge | 5d5d6cb | Self-healing multi-hop Wi-Fi HaLow mesh firmware for ESP32-S3 Heltec boards | esp32, wifi-halow, mesh-network, firmware, esp-idf, nix-flake | 2026-09-30 active; POC with OTA update + rollback support, roaming 2.4GHz AP bridge |
| homelab-fdroid-repo | infra | ~/git/homelab-fdroid-repo | b0a4eb4 | F-Droid app repository hosting/signing config for distributing homelab Android APKs | fdroid, android, apk-signing, app-distribution, fdroidserver | 2025-01-18 dormant; no NixOS module outputs, fdroidserver repo data + a stale flutter flake.nix |
| homelab-mobile | app | ~/git/homelab-mobile | ce9b212 | Flutter mobile app for the homelab, built with android-nixpkgs toolchain | flutter, dart, android, mobile-app, nix-flake | 2025-01-21 dormant; Flutter app (lib/, pubspec.yaml, android/ios/web dirs), not an Android ROM builder |
| homelab | nixmod | ~/git/homelab | 43e1d73 | NixOS + nix-darwin homelab fleet infra managed via Colmena and deploy scripts | nixos, colmena, nix-darwin, fleet-management, infra-as-code, nix-flake | 2026-09-30 active; core multi-node fleet repo (carme/beacon/titan/enceladus/mac-mini) |
| homelab-secrets | infra | ~/git/homelab-secrets | 331dd31 | Age-encrypted secrets and per-host bundles for the homelab fleet, signed/tagged | age-encryption, secrets-management, yubikey, ssh-signing, git-tags | 2026-09-28 active; no flake.nix, pure data/trust repo consumed by homelab-platform |
| homelab-settings-staging | nixmod | ~/git/homelab-settings-staging | 3a4952c | Network-admin-owned NixOS options schema and values for the homelab fleet | nixos-options, configuration-schema, age-encryption, signed-tags | 2026-09-30 active; defines the typed options.nix schema consumed by homelab-platform |
| iot-framework | infra | ~/git/iot-framework | ec2de27 | Minimal flash/devShell scaffold plus a prebuilt ESPHome firmware and enclosure STL | esp32, esphome, rp2040, picotool, flash-script, nix-flake | 2025-02-15 abandoned; mostly binary blobs, only real content is a 6-line flash.sh |
| kanix | app | ~/git/kanix | a3c14c5 | Modular 3D-printed belt-mount system for dog handlers plus commerce site/admin/API | 3d-print, openscad, ecommerce, dog-handling, hardware, uses-mcp | 2026-09-11 active; hardware + Next-style commerce platform, not an Android Kotlin dev MCP |
| kiauh | prior-art | ~/git/kiauh | a8a7324 | Upstream dw-0/kiauh — Klipper Installation And Update Helper shell/python installer | klipper, 3d-printer, installer, bash, raspberry-pi | 2024-09-26 abandoned; external upstream clone, no local commits since 2024 |
| klipper-mcp | mcp | ~/git/klipper-mcp | 5901163 | Greenfield MCP server exposing a Klipper 3D printer via Moonraker's API | klipper, 3d-printer, mcp-server, moonraker, python, agent-tooling, uses-mcp | 2026-09-02 active; greenfield, built per spec-kit SDD workflow |
| klipper | prior-art | ~/git/klipper | 8f361a15b | Upstream Klipper3d/klipper — 3D printer firmware combining host + microcontroller | klipper, 3d-printer, firmware, c, python, microcontroller | 2024-09-30 abandoned; external upstream clone, no local commits since 2024 |
| mcp-toolbelt | mcp | ~/git/mcp-toolbelt | 0fe8d7c | Collection of MCP servers replacing Claude Code's built-in tools with structured ops | mcp-server, agent-tooling, nix-flake, typescript, python, rust-ast, tool-replacement | 2026-09-21 active; no nixosModules/homeManagerModules outputs, composes multiple MCP server packages |
| nix-key | app | ~/git/nix-key | 5532f35 | SSH agent delegating signing to an Android phone over Tailscale/mTLS | ssh, android, tailscale, mtls, grpc, go, nixos-module | 2026-04-17 dormant; Go SSH agent + Android app, phone hardware-keystore backed, ships a nixosModule |
| nix-mcp-debugkit | mcp | ~/git/nix-mcp-debugkit | 7e0aa25 | Nix-packaged MCP debug servers wrapping Android/Browser/iOS automation tools | mcp, android, ios, browser-automation, nix-flake, agent-tooling, debugging | 2026-04-26 dormant; packages/provides MCP servers for agents to screenshot/tap/read a11y trees |
| nix-mcp-proxy | mcp | ~/git/nix-mcp-proxy | 3c6483a | Typed MCP proxy enforcing tool/field whitelists between agents and upstream MCP servers | mcp, typescript, proxy, validation, nix-flake, agent-tooling, security, uses-mcp | 2026-05-28 dormant; npm-published, has own code-review-graph MCP devshell integration |
| NixNet | infra | ~/git/NixNet | 9636b42 | Terraform+NixOS deploy scripts for personal VPS hosts (beacon, titan, velo) | terraform, nixos, vultr, deploy, wireguard, infra | 2024-02-15 dormant; sibling of nixos-terraform-deploy/nixos-vultr-terraform, likely superseded by nyx |
| nixos-dad-laptop | infra | ~/git/nixos-dad-laptop | 8ac76f5 | Terraform deploy of a NixOS laptop config for a family member | terraform, nixos, laptop, deploy, infra | 2022-10-13 abandoned; one-off personal deploy, likely superseded by nyx |
| nixos-eve-kiosk | infra | ~/git/nixos-eve-kiosk | ca2df2c | Terraform deploy of a NixOS kiosk machine | terraform, nixos, kiosk, deploy, infra | 2022-09-11 abandoned; one-off personal deploy, likely superseded by nyx |
| nixos-generators | prior-art | ~/git/nixos-generators | f4631de | Vendored clone of upstream nix-community/nixos-generators image builder | nixos, image-builder, iso, nix-flake, upstream-clone, prior-art | 2024-02-22 dormant; git remote is nix-community/nixos-generators, a reference checkout |
| nixos-iso-generator | app | ~/git/nixos-iso-generator | 119546d | Builds a NixOS installer ISO that wipes a disk and auto-installs via SSH/Tailscale | nixos, iso, disk-wipe, tailscale, yubikey, ventoy, bootstrap | 2025-01-29 dormant; destructive installer scripts, has YubiKey+Ventoy flashing support |
| nixos-terraform-deploy | infra | ~/git/nixos-terraform-deploy | 12f29e6 | Terraform deploy scripts for personal NixOS VPS hosts (moon1, satellite1, terminal1) | terraform, nixos, vps, wireguard, deploy, infra | 2022-04-10 abandoned; same family as NixNet/nixos-vultr-terraform, superseded by nyx |
| nixos-vultr-terraform | infra | ~/git/nixos-vultr-terraform | 4a4a275 | Terraform deploy of custom NixOS ISOs on Vultr with Gandi DNS | terraform, nixos, vultr, dns, iso, deploy, infra | 2023-08-09 abandoned; superseded by nyx/NixNet |
| NixOS-WSL | prior-art | ~/git/NixOS-WSL | 4dbad73 | Personal fork of nix-community/NixOS-WSL, modules for NixOS on WSL | nixos, wsl, windows, nixos-module, prior-art, fork | 2024-05-07 dormant; fork of nix-community/NixOS-WSL kept for reference |
| nixpkgs | prior-art | ~/git/nixpkgs | 2d5b60ee9cec | Full upstream NixOS/nixpkgs checkout kept for reference | nixpkgs, nix, package-manager, upstream-clone, prior-art | 2025-01-30 dormant; plain clone of NixOS/nixpkgs, reference only |
| nyx | infra | ~/git/nyx | d8510bf1 | Personal multi-host NixOS flake monorepo (desktops, laptops, servers) | nixos, nix-flake, home-manager, multi-host, dotfiles, infra | 2024-05-10 abandoned; large multi-host personal flake, likely superseded by current homelab repo |
| openscad-web-generator | app | ~/git/openscad-web-generator | bc2ab837 | Browser-based OpenSCAD parameter editor, 3D preview, slicer, Android APK for Klipper | openscad, react, typescript, three-js, wasm, 3d-print, slicer, klipper, android | 2026-03-22 active; client-side WASM PrusaSlicer, has Android app for cleartext HTTP to printers |
| OvenSpace | prior-art | ~/git/OvenSpace | 88b171a | Upstream clone: web video conferencing frontend for OvenMediaEngine | webrtc, streaming, video-conferencing, python, flask, oven-media-engine, prior-art | 2022-10-14 abandoned; unmodified upstream clone (AirenSoft/OvenSpace), kept for reference only |
| pmbootstrap | prior-art | ~/git/pmbootstrap | acb94bea | Upstream clone: postmarketOS chroot/build/flash bootstrap tool | postmarketos, python, chroot, packaging, mobile-linux, cli, prior-art | 2023-05-15 abandoned; unmodified upstream clone (sr.ht postmarketos), kept for reference only |
| printer-kiosk | app | ~/git/printer-kiosk | 094d2dd | CLI/Node tool to extract slicer configs and compile reproducible 3D-print manifests into 3MFs | 3d-print, slicer, bambu-studio, orcaslicer, nodejs, nixos-module, uses-mcp, agent-tooling | 2026-05-16 active; npm package + NixOS module + kiosk app, has .mcp.json (uses-mcp, not an MCP provider) |
| printers | app | ~/git/printers | bebf3a9 | Knowledge base and CLI/tooling for a 4-machine 3D printer fleet config and models | 3d-print, klipper, nix-flake, fleet-management, cli, knowledge-base | 2026-09-13 active; Nix-first repo, tested like sibling homelab repo |
| prl-resources | app | ~/git/prl-resources | c49862d | Script that renders a foster-puppy guide markdown doc to PDF via Puppeteer | nodejs, puppeteer, pdf, markdown, personal-doc | 2026-08-04 active; tiny single-purpose PDF render script, minimal reusable code |
| qr-code-replacer | app | ~/git/qr-code-replacer | nogit | Node script that replaces/rickrolls QR codes in a JPEG while preserving placement and EXIF | nodejs, qr-code, image-processing, exif, jimp, prank-tool | nogit; small novelty script, has reusable QR-detect/redraw logic |
| rexops | lib | ~/git/rexops | ea0b27d | Rex (Perl) based devops bootstrap/deployment scripts for server provisioning | perl, rex, devops, provisioning, automation, bootstrap | 2021-09-06 abandoned; keybase-hosted remote, predates nix-based homelab tooling, likely superseded |
| secure-unlocker | app | ~/git/secure-unlocker | e63d259 | NixOS module + PWA/API for remotely unlocking LUKS-encrypted devices via Ed25519 auth | nixos-module, luks, encryption, ed25519, pwa, rate-limiting, systemd | 2026-01-15 active; has integration tests (tests.nix), likely precursor to homelab internal-disk recovery |
| terraform-nixos | lib | ~/git/terraform-nixos | 813ad13 | Terraform module that deploys and configures NixOS onto a target host | terraform, nixos, infrastructure-as-code, deployment, provisioning | 2023-12-25 dormant; small reusable terraform module, self-hosted gitea remote, still usable |
| toots-therapy-card-generator | app | ~/git/toots-therapy-card-generator | 49ec05e | Puppeteer script generating a pet therapy-dog business card with QR code | nodejs, puppeteer, qr-code, business-card, image-generation, personal-project | 2026-02-08 active; small single-purpose generator, has reusable Puppeteer-to-print QR card code |
| virtual-display-linux | prior-art | ~/git/virtual-display-linux | dcba99c | Upstream clone: bash script creating virtual/fake display monitors for VNC/TeamViewer | bash, virtual-display, vnc, teamviewer, x11, prior-art | 2022-02-28 abandoned; unmodified upstream clone (github.com/dianariyanto), kept for reference only |
| WebApp2 | prior-art | ~/git/WebApp2 | 5986f42 | Upstream clone: .NET MAUI expense-management demo app with shared web backend | dotnet, maui, csharp, android, expense-management, demo, prior-art | 2023-08-24 abandoned; unmodified upstream clone (github.com/davoscode), has Kotlin/C# mobile + web example code |

## Skills

| name | kind | path | rev | what | tags | notes |
|---|---|---|---|---|---|---|
| skill:agent-framework:code-review-node | skill | ~/git/agent-framework/skills/code-review-node | h:1d53b0c | Node.js-specific code review. | skill, agent-framework | |
| skill:agent-framework:code-review-react | skill | ~/git/agent-framework/skills/code-review-react | h:c9a0737 | React-specific code review. | skill, agent-framework | |
| skill:agent-framework:code-review | skill | ~/git/agent-framework/skills/code-review | h:96b0d7a | Review code changes for bugs, security issues, performance problems, and quality concerns. | skill, agent-framework | |
| skill:agent-framework:eng-standards | skill | ~/git/agent-framework/skills/eng-standards | h:dbc02ba | A standards library — engineering rigor baselines (presets) plus a tag-indexed set of reference standards | skill, agent-framework | |
| skill:agent-framework:execute-milestone | skill | ~/git/agent-framework/skills/execute-milestone | h:c68b0b1 | Execute one milestone of a <name>-TASKS.md (three-file funnel) with fresh-context subagents — one implementer per | skill, agent-framework | |
| skill:agent-framework:handoff | skill | ~/git/agent-framework/skills/handoff | h:246503e | Regenerate a project's <name>-megaprompt.md — the self-contained paste-into-a-fresh-session resume prompt of the three-file funnel — | skill, agent-framework | |
| skill:agent-framework:plan-feature | skill | ~/git/agent-framework/skills/plan-feature | h:d52dd66 | Turn an idea into the three-file funnel — <name>-plan.md (design + LOCKED decisions L1..Ln + | skill, agent-framework | |
| skill:agent-framework:scout | skill | ~/git/agent-framework/skills/scout | h:020986a | Find what we already have before building it. | skill, agent-framework | |
| skill:agent-framework:spec-kit | skill | ~/git/agent-framework/skills/spec-kit | h:2195d68 | Initialize and drive a spec-kit (Specification-Driven Development) project using the `specify` CLI. | skill, agent-framework | |
| skill:agent-framework:toolbelt-setup | skill | ~/git/agent-framework/skills/toolbelt-setup | h:069c751 | Set up mcp-toolbelt in a project: add flake input, configure mkDevShell, generate .mcp.json, update CLAUDE.md | skill, agent-framework | |
| skill:agent-framework:toolbelt | skill | ~/git/agent-framework/skills/toolbelt | h:82ba022 | Behavioral skill for agents running with mcp-toolbelt MCP servers. | skill, agent-framework | |
| skill:agent-framework:ux-review | skill | ~/git/agent-framework/skills/ux-review | h:a65cc04 | Review React app screenshots and code for accessibility, layout, and UX issues using structured heuristic | skill, agent-framework | |
| skill:fwdy.net:db-migration | skill | ~/git/fwdy.net/.claude/skills/db-migration | h:2cbe09a | Change the D1 schema safely — new numbered migration files, backwards-compatible rollout, local verification, and | skill, fwdy.net | |
| skill:fwdy.net:debug-remote | skill | ~/git/fwdy.net/.claude/skills/debug-remote | 72409b6 | Investigate production (fwdy.net / app.fwdy.net) safely — live logs, read-only SQL, smoke tests, error correlation. | skill, fwdy.net | |
| skill:fwdy.net:deploy | skill | ~/git/fwdy.net/.claude/skills/deploy | h:632bbd6 | Ship fwdy to Cloudflare — how CI/CD-only deploys work (merge to main → CI gate | skill, fwdy.net | |
| skill:fwdy.net:local-stack | skill | ~/git/fwdy.net/.claude/skills/local-stack | 72409b6 | Bring up, inspect, and reset the isolated local fwdy stack (workerd + local D1/KV/Queues + | skill, fwdy.net | |
| skill:fwdy.net:privacy-review | skill | ~/git/fwdy.net/.claude/skills/privacy-review | 72409b6 | Mandatory checklist when a change touches what personal data fwdy collects, stores, shows, shares, or | skill, fwdy.net | |
| skill:fwdy.net:security-triage | skill | ~/git/fwdy.net/.claude/skills/security-triage | h:92d127e | Triage and fix findings from fwdy's security gates — `just security` (Trivy, Grype, OSV, npm | skill, fwdy.net | |
| skill:fwdy.net:test-and-debug | skill | ~/git/fwdy.net/.claude/skills/test-and-debug | 72409b6 | Run fwdy's test tiers and diagnose failures from structured logs. | skill, fwdy.net | |
| skill:homelab:bump-nixpkgs | skill | ~/git/homelab/.claude/skills/bump-nixpkgs | 88ede09 | Bump the pinned nixpkgs input and drive the whole post-update chain — flake update → | skill, homelab | |
| skill:homelab:carme-audit | skill | ~/git/homelab/.claude/skills/carme-audit | 88ede09 | Drive the exhaustive carme hardening audit (packages.carme-audit-vm — Lynis, sysctl, sshd, systemd sandboxes, nginx, admin | skill, homelab | |
| skill:homelab:carme-backup | skill | ~/git/homelab/.claude/skills/carme-backup | 7e09c4e | Run and verify an encrypted carme disaster-recovery backup via ops/backup.sh. | skill, homelab | |
| skill:homelab:carme-cve-analyze | skill | ~/git/homelab/.claude/skills/carme-cve-analyze | 88ede09 | Advisory CVE triage for the carme closure — refresh the committed CycloneDX SBOM if flake.lock | skill, homelab | |
| skill:homelab:carme-cve-fix | skill | ~/git/homelab/.claude/skills/carme-cve-fix | 88ede09 | Act on the CVE triage produced by /carme-cve-analyze — bump nixpkgs to clear FIXED_IN_UNSTABLE_MAYBE findings, | skill, homelab | |
| skill:homelab:carme-postdeploy-verify | skill | ~/git/homelab/.claude/skills/carme-postdeploy-verify | a592f94 | Read-only post-deploy verifier for carme (or any fleet node). | skill, homelab | |
| skill:homelab:carme-restore | skill | ~/git/homelab/.claude/skills/carme-restore | 7e09c4e | Drive ops/restore.sh to decrypt a carme backup bundle with a connected YubiKey and restore selected | skill, homelab | |
| skill:homelab:carme-unlock | skill | ~/git/homelab/.claude/skills/carme-unlock | 37bdd77 | Drive and verify carme's warm state-disk unlock after a reboot. | skill, homelab | |
| skill:homelab:deploy | skill | ~/git/homelab/.claude/skills/deploy | 4f6d812 | Safe-deploy a config change to a NixOS node the fail-safe way — drive scripts/deploy.sh through | skill, homelab | |
| skill:homelab:env-create | skill | ~/git/homelab/.claude/skills/env-create | 9b04511 | Stand up an ephemeral or project ENVIRONMENT from a {platform-ref, settings-ref} triple — mint its | skill, homelab | |
| skill:homelab:internal-recovery-rotate-recipients | skill | ~/git/homelab/.claude/skills/internal-recovery-rotate-recipients | ad15e62 | Add or remove an admin YubiKey from the /internal recovery escrow's recipient set — the | skill, homelab | |
| skill:homelab:internal-recovery-setup | skill | ~/git/homelab/.claude/skills/internal-recovery-setup | ad15e62 | Arm the YubiKey-escrowed /internal recovery slot on a node with homelab.internalDisk.enable = true. | skill, homelab | |
| skill:homelab:internal-recovery-use | skill | ~/git/homelab/.claude/skills/internal-recovery-use | ad15e62 | NON-DESTRUCTIVE recovery for a lost/forgotten /internal passphrase on a node where /internal-recovery-setup has been run | skill, homelab | |
| skill:homelab:node-onboard | skill | ~/git/homelab/.claude/skills/node-onboard | d2c3e89 | Onboard a new NixOS node to the fleet — add its schema entry to settings/values.nix | skill, homelab | |
| skill:homelab:node-pave | skill | ~/git/homelab/.claude/skills/node-pave | cb41fd6 | Pave a bare machine into a new NixOS fleet node with disko — hardware survey | skill, homelab | |
| skill:homelab:pi-onboard | skill | ~/git/homelab/.claude/skills/pi-onboard | e32c730 | Add a Raspberry Pi (Pi 4 on microSD or USB, Pi Zero 2 W) to | skill, homelab | |
| skill:homelab:pwa-verify | skill | ~/git/homelab/.claude/skills/pwa-verify | a592f94 | Fast-iteration browser check for a PWA-touching change — boot the local `nix run .#control-plane-dev` harness | skill, homelab | |
| skill:homelab:reinit-state-disk | skill | ~/git/homelab/.claude/skills/reinit-state-disk | c708f28 | Recovery for a lost/forgotten state-disk passphrase on any fleet node with homelab.internalDisk.enable = true (today: | skill, homelab | |
| skill:homelab:secureboot-maintain | skill | ~/git/homelab/.claude/skills/secureboot-maintain | 37bdd77 | Re-seal carme's root-disk TPM2 unlock to Secure Boot PCR 7 after a firmware/Secure-Boot change, and | skill, homelab | |
| skill:homelab:session-close | skill | ~/git/homelab/.claude/skills/session-close | a592f94 | End-of-session hygiene for a homelab-repo agent — tree check, .comms/ status update, memory candidates review, | skill, homelab | |
| skill:homelab:titan-storage-cutover | skill | ~/git/homelab/.claude/skills/titan-storage-cutover | 81952fb | Co-drive the titan-storage M5 owner ceremony (live-hardware LUKS + btrfs shuffle-in-place migration, ~1-day risk window, | skill, homelab | |
| skill:mcp-toolbelt:graph-edit | skill | ~/git/mcp-toolbelt/.claude/skills/graph-edit | 744b218 | Use for any source-code change in a graph-edit-supported language (TypeScript v1; Python + Rust planned). | skill, mcp-toolbelt | |
| skill:nix-mcp-proxy:nix-mcp-proxy-consumer | skill | ~/git/nix-mcp-proxy/.claude/skills/nix-mcp-proxy-consumer | h:564e522 | Operate as an agent whose MCP tools are fronted by nix-mcp-proxy. | skill, nix-mcp-proxy | |

## Ignored

- 3d@2f267da — IGNORE: 3D-print model repo
- android-slicer-plan@65bd410 — IGNORE: only a README market-analysis doc for a hypothetical app, no code
- breezehome-workorders@2b048ad — IGNORE: single personal work-order doc (dad's house painting), no code
- cloudflare-pages-static-site-template@nogit — IGNORE: personal archive
- dadflash@nogit — IGNORE: personal archive
- dadstuff@nogit — IGNORE: personal document archive (HTML/MD/PDF notes), no code, not a git repo
- design@29b0157 — IGNORE: 3D model repository
- dog-id-tags@nogit — IGNORE: 3D model repository
- EXAMPLE_API@19a697f — IGNORE: trivial "Hello World" Express tutorial app, no reusable value
- flutter-windows-on-linux-docker@a6e15e1 — IGNORE: minimal content
- house-search@nogit — IGNORE: not a git repo
- kanix-parts-costs-private@nogit — IGNORE: not a git repo
- kobo-reader-mods@nogit — IGNORE: not a git repo
- nixos-reverse-proxy@nogit — IGNORE: empty template repo, only LICENSE and .gitignore, no actual code
- massive_games.servers-nixos@nogit — IGNORE: git repo initialized but has no commits (keybase remote, nixos terraform for a private game server)
- playground@nogit — IGNORE: test/sandbox directory, no active development
- printer@b341204 — IGNORE: 3D model repository (STL files only)
- reversesauce@6d6f2d0 — IGNORE: unmodified upstream terraform fork
- space-engineers-dedicated-docker-linux@99fb070 — IGNORE: unmodified upstream game server fork
- tag-case-generator2@nogit — IGNORE: empty directory
- tag-case-generator@nogit — IGNORE: empty directory
- test2@nogit — IGNORE: test directory
- test3@nogit — IGNORE: test directory
- test@nogit — IGNORE: test directory
- TradRack@3fcc668 — IGNORE: 3D printer design model (CAD files)
- Voron-Trident@45922db — IGNORE: 3D printer design model (CAD files)
- VzBoT-Vz330@18f38d3 — IGNORE: 3D printer design model (CAD files)
- Vz-Printhead-Printed@d4329fd — IGNORE: 3D printer design model (CAD files)
- wlroots@0855cdac — IGNORE: unmodified upstream Wayland library fork (migrated to gitlab)
