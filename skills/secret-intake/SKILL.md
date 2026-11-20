---
name: secret-intake
description: Get a secret (API token, password, key) from the operator without it ever passing through chat, a terminal, a command line or a log. Opens a prefilled Cloudflare create-token form when that is the source, then a rofi password box; the value is checked, verified and handed straight to where it belongs (an age file, a CI secret, `wrangler secret put`, ...). Use whenever the operator must supply a secret.
---

# secret-intake

A secret the operator types or pastes goes into a rofi box on their screen
and from there straight to its destinations. The agent never sees it.

## Rules

- Never ask for a secret in chat, and never hand the operator a command to
  paste one into. Never print, echo, log or pass a secret on a command line
  (argv is visible in `ps`). Never read a file that holds one.
- Explain in plain words what the secret is for and where it will go,
  BEFORE the box opens.
- A secret the agent can generate itself (a random password, a key pair)
  is generated, not asked for: write it straight to its destinations the
  same way (stdin pipes, tmpfs, shred afterwards).

## Steps

1. **If it is a Cloudflare API token**, open the form prefilled:

       secret-intake cloudflare-url --name "<what it is for>" \
         --perm page:edit --perm dns:edit ... --account <account id> [--zone <zone id>]

   Known permission keys: `page` (Cloudflare Pages), `d1`, `workers_r2`,
   `workers_scripts`, `workers_kv_storage`, `workers_routes`, `dns`, `zone`,
   `zone_settings`, `ssl_and_certificates`, `cache`. Cloudflare drops an
   unknown key silently, so tell the operator which rows the form should
   show and to add a missing one by hand (Turnstile's key is unknown:
   "Account → Turnstile → Edit"). Type is `read` or `edit`. Ask for the
   least the job needs.

2. **Ask before the box opens** (AskUserQuestion): "Is the token showing?"
   Rofi grabs the keyboard, so opening it while the operator is still
   clicking through the form blocks them.

3. **Open the box and deliver**:

       secret-intake paste --prompt "Paste the <what> (<permissions>), then Enter" \
         --verify cloudflare \
         --recipients-file <age recipients> --to age:<encrypted copy> \
         --to exec:'<command that reads the value on stdin>'

   `--verify cloudflare` checks the token with Cloudflare first (a *user*
   token: `/user/tokens/verify`). Without it, `--pattern <regex>` checks the
   shape (default: no whitespace). Every `--to` gets the value on stdin; an
   `exec:` command must read stdin, e.g. `wrangler secret put NAME`.
   Escape = cancelled, nothing written.

4. Report the statuses it printed. Commit any encrypted copy in its repo
   (ciphertext only); pushing is the operator's call.

## Machine setup

The script needs `rofi` (on a Wayland/X session the operator is looking
at), `age`, `jq`, `curl` and `xdg-open`. Where the encrypted copies go and
which recipients to use is per machine: the machine's own instructions
(e.g. its user `CLAUDE.md`) say so.
