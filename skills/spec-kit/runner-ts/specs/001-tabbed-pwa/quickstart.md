# Quickstart — tabrunner

Get tabrunner running and paired with your phone in under 10 minutes.

## Prerequisites

- Linux x86_64 host
- Nix with flakes enabled
- Tailscale installed and running (`tailscale status` returns OK)
- bubblewrap (`bwrap --version`) — usually in your base distro
- A target project directory you want to drive Claude Code in (e.g. `~/git/your-repo`)

## 1. Clone and enter the devshell

```bash
git clone <agent-framework-repo> ~/git/agent-framework
cd ~/git/agent-framework/skills/spec-kit/runner-ts
nix develop
```

The first `nix develop` builds the dev environment (~2 min cold). Subsequent entries are instant. The shell hook starts a `code-review-graph` watcher in the background and verifies tooling versions.

## 2. Install Node dependencies

```bash
npm install --ignore-scripts
npm rebuild better-sqlite3 node-pty
npm run build
```

`--ignore-scripts` blocks postinstall scripts (supply chain hardening). `npm rebuild` runs only the native-binding builds we actually need.

## 3. Initialize tabrunner

```bash
tabrunner init
```

Interactive prompts:
- **Watched project path**: absolute path to the project Claude will work on (e.g. `/home/max/git/your-repo`)
- Press Enter to accept defaults for `port` (8443), `data_dir` (`~/.local/share/tabrunner`)

This creates:
- `~/.config/tabrunner/config.toml`
- `~/.local/share/tabrunner/` with `ca.pem`, `ca-key.pem` (chmod 600), `server-cert.pem`, `server-key.pem`, `tabrunner.db`

Init is idempotent — re-running with everything in place prints the current state and exits 0.

## 4. Start the server

Foreground (for first run):

```bash
tabrunner serve
```

You should see:

```
[info] tabrunner listening on https://100.x.y.z:8443
[info] tailscale_ip=100.x.y.z port=8443 project=/home/max/git/your-repo
[info] FTS initial scan complete (0 sessions indexed)
```

Note the URL — that's the only address that accepts connections (Tailscale-only per Constitution I).

If you see `error: no config at ...` or `error: tailscale not running`, follow the printed instructions.

## 5. Pair your first device

In another terminal on the same host:

```bash
tabrunner pair
```

You'll get a QR code printed to the terminal plus a URL like:

```
https://100.x.y.z:8443/pair/3p_e8KW...x2
```

Scan the QR on a phone/laptop that's on the same Tailnet. Browser opens, generates an ECDSA P-256 keypair via WebCrypto, posts a CSR, receives a signed client cert + the CA cert.

Install the returned cert when prompted (the device's OS cert store). On iOS/Android Chrome, this is a one-tap confirm. On desktop Chrome/Firefox, it's a system cert dialog.

The pairing URL is valid for **5 minutes** OR until first successful use, whichever first.

## 6. Open the PWA

The pairing page redirects to `/` after cert install. You'll see:

- An empty tab bar with the pinned **Meta** tab on the left
- A "New Tab" button
- An "About" footer showing the Tailscale IP/port

Click **New Tab** → a session spawns inside bwrap. Type "hello" in the composer → Enter to send.

## 7. Try the meta agent

Click the **Meta** tab. Type:

> Show me the last 30 lines of stdout from any running session.

The meta agent calls `list_running()` then `tail_live(session_id, 30)` and shows the result. You can see the tool calls collapsed in the chat (click to expand).

## 8. Make it boot at login (optional)

Install the systemd user unit:

```bash
mkdir -p ~/.config/systemd/user
cp etc/systemd/tabrunner.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tabrunner
journalctl --user -u tabrunner -f      # follow logs
```

The unit restarts on failure and waits for `tailscaled.service`. Logs go to your user journal.

## Common admin commands

```bash
tabrunner sessions list                    # see all sessions, current PIDs
tabrunner sessions kill <session_id>       # graceful term, 10s grace
tabrunner clients list                     # see paired devices
tabrunner clients revoke <fingerprint>     # immediate revoke
tabrunner pair                             # add another device
```

## Recovery cheat sheet

| Symptom | Fix |
|---------|-----|
| PWA can't connect from device | `tailscale status` on device. If OK, `journalctl --user -u tabrunner -f` for TLS errors. |
| "Device not paired" on a previously-paired device | Cert expired (1 year) or revoked. Run `tabrunner pair` again. |
| `tabrunner serve` exits with code 78 | Read stderr. Usually missing config / data dir / CA → run `tabrunner init`. Or claude version drift → check `flake.nix` pin. |
| Session stuck mid-response | `tabrunner sessions kill <id>` then reopen from History. |
| DB locked | Restart server. SQLite WAL recovers automatically. |
| Want to start completely fresh | Stop server, `rm -rf ~/.local/share/tabrunner ~/.config/tabrunner`, then `tabrunner init` again. |

## What's next

- Read [spec.md](./spec.md) for the full feature requirements.
- Read [plan.md](./plan.md) for architecture and module structure.
- Read [data-model.md](./data-model.md) for the SQLite schema.
- Read [contracts/](./contracts/) for HTTP, WS, MCP, and internal interface contracts.
