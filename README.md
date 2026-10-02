# keenv

`keenv` puts secrets from a [KeePass](https://keepass.info/) database into one
command and nowhere else: into its environment with `keenv run`, or into an
in-memory config it reads through a pipe with `keenv conf`. The values never
reach a file, an `export`, or the shell history: they exist between unlocking
the database and `exec`ing the command, and the process that held them is
replaced. Windows has no `exec`, and a short-lived process stands in for it
there, as the [Windows](#windows) section shows.

It is the tool the Oberon Systems keyring policy names for local secrets.

## Contents

- [Why](#why)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Remembering the password](#remembering-the-password)
- [Config files](#config-files)
- [macOS](#macos)
- [Windows](#windows)
- [How it works](#how-it-works)
- [Development](#development)

## Why

The usual ways of getting a secret into a process all leave it somewhere:
`export` puts it in every child of the shell for the rest of the session, a
`.env` full of plaintext puts it on disk, and `eval $(something)` puts it in
the history file as well.

`keenv` reads the value out of the database at the moment it is needed, builds
the environment for exactly one command, and replaces itself with that command.
There is no `keenv export` and no `keenv eval`, on purpose.

## Installation

```bash
pip install keenv
```

The database itself is read in process through
[pykeepass](https://github.com/libkeepass/pykeepass), so KeePassXC does not
have to be installed.

`keenv` runs on Linux, macOS and Windows. The [macOS](#macos) section lists
what is weaker there and how `keenv conf` works with `sudo`. On Windows it is
a reduced client, described in the [Windows](#windows) section.

### Installing on Windows

`keenv` needs Python 3.10 or later. Install Python from
[python.org](https://www.python.org/downloads/windows/) or with
[winget](https://learn.microsoft.com/windows/package-manager/winget/), then
install `keenv` with [pipx](https://pipx.pypa.io/), which keeps it in its own
environment and puts it on `PATH`:

```powershell
winget install Python.Python.3.12
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install keenv
```

Open a new terminal after `ensurepath`, so that it reads the updated `PATH`.
Plain pip works as well:

```powershell
py -m pip install keenv
```

Check the install:

```powershell
keenv --help
```

Expected output starts with:

```text
usage: keenv [-h] {run,check,lock,conf} ...
```

If `keenv` is not found, the Python `Scripts` directory is not on `PATH`.
`py -m keenv` runs the same program without it:

```powershell
py -m keenv --help
```

For the agent and `keenv conf` on a Windows machine, install `keenv` inside
[WSL](https://learn.microsoft.com/windows/wsl/) instead, where it is the Linux
client with everything this README describes.

## Configuration

`keenv` reads two files, both optional. `keenv.yaml` names the database and
maps environment variables onto entries:

```yaml
vault: ~/Dropbox/oberon.kdbx
keyfile: ~/.keys/oberon.keyx

env:
  AWS_ACCESS_KEY_ID:
    entry: Oberon/R2/indech-state
    field: username
  AWS_SECRET_ACCESS_KEY:
    entry: Oberon/R2/indech-state
    field: password
```

`.env` is the same mapping in the shape people already write, where a value may
be a `keenv://` reference instead of a literal:

```dotenv
AWS_ACCESS_KEY_ID=keenv://Oberon/R2/indech-state/username
AWS_SECRET_ACCESS_KEY=keenv://Oberon/R2/indech-state/password
TF_LOG=INFO
```

A reference is `keenv://<entry path>/<field>`. The last segment is the field
and everything before it is the path to the entry, so a field whose name
contains a slash cannot be addressed. `username`, `password`, `url`, `notes`
and `title` are matched case-insensitively; any other name is looked up as a
custom attribute, with its spelling preserved.

The entry path starts at the top-level groups, one level below the root group
KeePass shows at the top of its tree, so `Oberon/R2/indech-state` and not
`Root/Oberon/R2/indech-state`. A path that does name the root group first is
accepted too, under either the group's real name or a plain `root`, so a path
copied straight out of KeePass works as it stands.

Values that are not references pass through literally. A `#` only starts a
comment at the beginning of a line, never in the middle of one, because a
secret may contain it.

Before anything else, `keenv` expands the `.env` the way a shell sourcing it
would, so a file that works under `source .env` works under `keenv run`:

```dotenv
PROJECT=balor
SUIL_BASE_DIR="${PWD}/${PROJECT}"
TF_LOG="${TF_LOG:-INFO}"
AGE_KEY=keenv://Oberon/vaults/${PROJECT}-age/password
LITERAL='no ${expansion} here'
PRICE="100\$"
```

A name is looked up in the environment `keenv` was called in, in the `.env`
files read before this one, and in the lines above it in the same file, which
is why `${PROJECT}` works there. It expands
inside a `keenv://` reference as well, so one file can serve several
environments. Single quotes expand nothing and `\$` is a dollar of its own.

A name that is not set expands to nothing, silently, as it does in a shell;
`${NAME:-default}` is how a value is given instead. `keenv.yaml` is not
expanded - only the `.env` is.

A value read out of the database is never substituted into another value:
`${NAME}` naming a `keenv://` variable is an error, not a secret quietly
copied somewhere it was not asked for.

More than one `.env` can be read. Repeat `-e`, or list the files under
`env_files:` in `keenv.yaml`:

```yaml
env_files:
  - .env
  - secrets.env
```

The files are read in the order given, and a later one overrides an earlier
one. `-e` replaces the list in `keenv.yaml` and does not add to it, and
either one replaces the default `./.env`. A path under `env_files:` may start
with `~` and is otherwise relative to the directory `keenv` is called in.

The layers apply in this order, each one overriding the last:

| Layer | Set by |
| :--- | :--- |
| `keenv.yaml` | `-c`, default `./keenv.yaml` |
| `.env` | `env_files:`, then `-e`, default `./.env` |
| the database path | `vault:`, then `KEENV_VAULT`, then `--vault` |
| the key file path | `keyfile:`, then `KEENV_KEYFILE`, then `--keyfile` |

A file that is not there is an empty layer, not an error. Having nothing to
resolve after both layers is an error.

`ttl:` is read from `keenv.yaml` and nowhere else. It has no flag and no
environment variable, so nothing outside the file you can see can start
remembering your master password.

`keenv.yaml` is validated against a
[pydantic](https://docs.pydantic.dev/) model that rejects keys it does not
know, so `vualt:` is reported as a mistake rather than quietly ignored.

## Usage

Run a command with the resolved environment:

```bash
keenv run -- tofu -chdir=circuits/live/ramnode/compute plan
```

Check that every reference still points at something, without printing any
value:

```bash
keenv check
```

Expected output:

```text
AWS_ACCESS_KEY_ID            keenv://Oberon/R2/indech-state/UserName               20 chars  keenv.yaml
AWS_SECRET_ACCESS_KEY        keenv://Oberon/R2/indech-state/Password               40 chars  keenv.yaml
TF_LOG                       literal                                                4 chars  .env
```

The last column is the file the variable came from, which is the quickest
way to see that a `.env` is overriding `keenv.yaml`. The table goes to stdout
and the count that closes it to stderr, so `keenv check > list` writes the
table and nothing else.

Point at another database and other mappings:

```bash
keenv run --vault ~/other.kdbx -e deploy.env -e secrets.env -- ./deploy.sh
```

Exit codes are `0` on success, `1` for anything `keenv` can explain, `2` for a
usage mistake, `127` when the command does not exist, and `130` when the run
was cancelled at a prompt. Otherwise the exit code is the command's own,
because the command replaces `keenv`.

Ctrl-C at the master password or the PIN ends the run on one line, not on a
traceback, and an agent that had been forked but never filled is dropped with
it.

### Colour

`keenv` colours what it says in [Solarized](https://ethanschoonover.com/solarized/)
dark: yellow for something worth knowing that it carried on past, green for a
thing that worked, red for the line a run ends on. A `keenv://` reference in
the `check` table is blue, and the file a variable came from is dimmed.

Colour is for terminals only. It goes away when the output is a pipe or a
file, when `NO_COLOR` is set to anything, when `TERM` is `dumb`, and when
`--no-color` is passed:

```bash
keenv check --no-color
```

## Remembering the password

By default `keenv` remembers nothing. Every run asks for the master password,
and none of it outlives the process. Stay in that mode unless typing the
password is genuinely in the way.

Setting `ttl:` turns on an agent that remembers it for a while, behind a PIN:

```yaml
vault: ~/Dropbox/oberon.kdbx
ttl: 5m
```

The first run after that asks for the password and for a new PIN. Later runs
ask only for the PIN:

```console
$ keenv run -- tofu plan
Master password for /home/you/oberon.kdbx:
New PIN (4 to 8 digits, Enter to skip):
Repeat the PIN:

$ keenv run -- tofu apply
PIN for /home/you/oberon.kdbx:
```

Pressing Enter at `New PIN` instead of typing one skips the agent for that
run. `keenv` says `running without the agent`, waits two seconds so that
Ctrl-C can still stop the run, and goes on with the database it has already
opened. Nothing is remembered, so the next run asks for the password again.

`keenv lock` forgets it at once, without waiting for the TTL. There is no
`keenv unlock` on purpose: the first run that needs the password is the
unlock, so there is no separate state to remember to set up.

A run whose password or PIN is turned down leaves no agent behind, and an
agent that is up but holds nothing is not an error either: the next `keenv
run` simply asks for the password and a new PIN again.

### What is kept, and where

The agent never holds the master password in the clear. The client seals it
before the agent ever sees it:

```text
keystream = argon2id(PIN, random salt, 128 bytes)
blob      = password padded to 128 bytes XOR keystream
```

The agent holds that salt and that blob, and nothing else. The PIN is not
stored, not even as a hash: it is checked by unsealing the blob and offering
the result to the database, so a wrong PIN yields rubbish and the database is
what turns it down. Rubbish that is not even text never came out of a seal,
and keenv names that a wrong PIN before it gets that far. The padding is what
keeps the blob from betraying how long the password is.

The agent is forked before the password is read, so the plaintext is never in
its address space, not even inherited across the fork. It runs with core dumps
disabled, with `PR_SET_DUMPABLE` cleared so no other process of yours can
attach to it or read its memory, and with its pages kept out of swap where the
limits allow.

Its socket and lock file sit in `$XDG_RUNTIME_DIR/keenv/`, named after a hash
of the database path. Each database therefore gets one agent, shared by every
project pointing at it. That directory is a tmpfs owned by you, so nothing
survives a reboot, and nothing cryptographic is written there in any case: the
lock file holds a pid, a socket path and a version.

macOS has neither `PR_SET_DUMPABLE` nor a runtime tmpfs. The
[macOS](#macos) section says what the agent does there instead.

### The limits, plainly

`ttl` takes `30s`, `5m` or a bare count of seconds, and must be more than zero
and no more than fifteen minutes. Anything longer is a configuration error
rather than a value quietly cut down to fit. The clock is idle-based: every
successful run puts it back.

Five failures inside five minutes and the agent wipes itself and exits. That
catches a typo and a stuck script. It is **not** a defence against a hostile
program: the agent never sees the PIN, so a program bent on guessing simply
would not report its failures. What actually prices an attack is the cost of
Argon2 and the length of the PIN.

| PIN | Guesses | Roughly |
| :--- | ---: | :--- |
| 4 digits | 10 thousand | hours |
| 6 digits | 1 million | weeks |
| 8 digits | 100 million | years |

Four digits are accepted, but `keenv` says what they cost and asks you to
confirm.

Two things this does not protect against, said outright:

- Anyone who can both dump the agent's memory and obtain a copy of the
  `.kdbx` can search for the PIN offline, at the price above. A database kept
  in a synced folder is well within reach of that.
- The client necessarily holds the password in the clear for as long as it
  takes to open the database. It is closed to your other processes with
  `PR_SET_DUMPABLE` meanwhile, and `execvpe` then replaces it, which is the
  same guarantee the default mode gives.

A key file is a different trade and needs none of this. It already opens the
database without a prompt, so `ttl` does nothing alongside one, and `keenv`
says so rather than starting an agent that would hold nothing.

## Config files

`keenv conf` renders a config file out of the database and runs a command on
the rendered copy, without that copy ever becoming a file. The command is
given in full after `--`, as with `keenv run`, and `{}` marks where it takes
the config:

```bash
keenv conf ~/vpn/work.ovpn -- sudo /usr/sbin/openvpn --config {} --auth-user-pass
keenv conf ~/app.toml -- myapp -c {}
keenv conf ~/tool.yaml -- tool --config={}
```

`keenv` puts `/proc/<pid>/fd/3` in place of the `{}`, so any flag the command
reads its config with will do. A command without a `{}`, or with more than one, is
refused: the config reaches the command once, on descriptor 3. Standard input,
output and error stay the terminal, so the command can still ask for a
password or a one-time code there.

The template is the config as the command reads it, where a line holding
nothing but a `keenv://` reference is replaced by the value of that field,
which may span several lines. For [OpenVPN](https://openvpn.net/) that fits
the inline blocks version 2.6 reads secrets from:

```text
# keenv: vault ~/Dropbox/oberon.kdbx
# keenv: keyfile ~/.keys/oberon.keyx
client
remote vpn.example.com 1194
<key>
keenv://Oberon/vpn/work/client-key
</key>
<auth-user-pass>
keenv://Oberon/vpn/work/username
keenv://Oberon/vpn/work/password
</auth-user-pass>
```

A reference in the middle of a line is left as it is, because an entry path
may contain spaces and could not be told apart from the rest of the line.
Nothing else in the template is expanded either, so a `$` stays a `$`.

The template carries its own settings. `# keenv: vault` and `# keenv: keyfile`
name the database and the key file, and are cut out of what the command gets.
`keenv.yaml` and `.env` are not read. `KEENV_VAULT`, `KEENV_KEYFILE`,
`--vault` and `--keyfile` override the template in the same order as they
override `keenv.yaml`. Any other `# keenv:` directive is an error.

There is no PIN and no agent here. A command such as a VPN is brought up once
for a long session, so `keenv conf` asks for the master password, or opens the
database with the key file, and remembers nothing. `# keenv: ttl` is refused.
The directives are `#` comments, so the format has to take `#` as a comment,
as OpenVPN, YAML and TOML do.

### Where the config lives

The rendered config is written into a pipe, whose write end `keenv` closes
before it replaces itself with the command. The read end stays open as
descriptor 3 of that process, whose pid `exec` leaves unchanged. Reading the
config drains the pipe, so once the command has read it the config exists
nowhere but in that command's memory.

A pipe rather than a file, and descriptor 3 rather than anything else:

- A temporary file, even on tmpfs, has a name that another process of yours
  can open, and outlives the command unless something deletes it.
- The environment is readable in `/proc/<pid>/environ`, and `sudo` resets it.
- Standard input has to stay the terminal. OpenVPN asks for passwords through
  `systemd-ask-password`, which only uses the terminal when standard input is
  one, and otherwise posts the question to a system-wide agent instead.

### Through sudo

`sudo` closes every descriptor above 2 in the command it starts, but not its
own, and `sudo` keeps running as the parent of that command. So the path is
`/proc/<pid>/fd/3` rather than `/dev/fd/3`: it names descriptor 3 of the
process `keenv` became, which is `sudo` itself, and the command, running as
root, opens it there. Nothing in sudoers has to change, and `sudo -C` is not
needed.

This relies on `sudo` staying the parent of the command, which it does
whenever it keeps a PAM session or a pseudo-terminal, as it does by default.
A `sudo` that replaced itself with the command would have closed the
descriptor, and the command then fails to open its config rather than
starting without it.

### What reaches the config, and when

Nothing is left for a process of your own to read at any point:

- `keenv conf` and `keenv run` close themselves to your other processes with
  `PR_SET_DUMPABLE` before they ask for the master password. From then on only
  root can read their memory or open their `/proc/<pid>/fd`.
- `sudo` is setuid, so the process stays closed through the `exec` and while
  `sudo` asks for its own password.
- The command reads the pipe as soon as it starts. Anyone reading it first
  drains it, and the command then fails on an empty config rather than coming
  up quietly with a stolen one.

Two limits, said outright:

- Root can read the config out of the command's memory at any time, as it can
  read anything.
- The config is read once. OpenVPN rereads its config on `SIGHUP` and finds
  the pipe empty, so restart it with `SIGUSR1`, which keeps the config it has.

## macOS

`keenv` runs on macOS as well as on Linux. Every difference is a separate
branch in the code, so nothing described above changes on Linux. What differs
on macOS:

- There is no `PR_SET_DUMPABLE`. `keenv` and its agent run open to your other
  processes, as far as the system's own debugging restrictions allow, so
  another process of yours may be able to read their memory.
- There is no `mlockall`, so nothing keeps the agent's pages out of swap. The
  swap on macOS is encrypted.
- Without `XDG_RUNTIME_DIR` the agent keeps its socket and lock file in
  `$TMPDIR/keenv/`. That directory is private to you but is not a tmpfs, and
  the agent's TTL, not a logout, is what clears it.
- `keenv conf` puts `/dev/fd/3` in place of the `{}`, since there is no
  `/proc`.

### Examples on macOS

Everything except `sudo` inside the `keenv conf` command works as on Linux:

```bash
keenv run -- tofu plan
keenv check
keenv lock
keenv conf ~/app.toml -- myapp -c {}
keenv conf ~/tool.yaml -- tool --config={}
```

With `ttl` set in `keenv.yaml` and no `XDG_RUNTIME_DIR`, the agent shows up
in `$TMPDIR` after the first run:

```bash
ls "$TMPDIR/keenv"
```

Expected output, one pair per database:

```text
<hash>.lock  <hash>.sock
```

### keenv conf with sudo on macOS

`/dev/fd/3` names descriptor 3 of the process that opens it, and `sudo` closes
that descriptor in the command it starts. A command that begins with `sudo` is
therefore refused on macOS, before the database is opened:

```bash
keenv conf ~/vpn/work.ovpn -- sudo openvpn --config {}
```

Expected output, with exit code 1:

```text
keenv: on macOS sudo closes the descriptor the config is on; run keenv itself under sudo: sudo keenv conf work.ovpn -- openvpn --config {}
```

Run `keenv` itself under `sudo` instead:

```bash
sudo keenv conf ~/vpn/work.ovpn -- openvpn --config {}
sudo keenv conf --vault /Users/me/Dropbox/oberon.kdbx ~/vpn/work.ovpn -- openvpn --config {}
```

`keenv` then runs as root, and the master password prompt is the same.
Whether a `~` in `# keenv: vault` means your home or root's depends on how
`sudo` treats `HOME`, so name the database by its absolute path there or pass
`--vault`.

## Windows

`keenv` on Windows is a reduced client: `run` and `check` work, `lock` has
nothing to drop, and `conf` is refused. Every difference is a separate branch
in the code, so nothing described for Linux or macOS changes. For the full
client, run `keenv` inside WSL, as [Installing on
Windows](#installing-on-windows) describes.

### What differs on Windows

- There is no agent. A `ttl` in `keenv.yaml` is ignored with a warning, so
  every run asks for the master password, or opens the database with its key
  file.
- `keenv lock` has no agent to drop, says so and exits with `0`.
- `keenv conf` is refused. Windows has no descriptor path a command can open
  its config through, and a temporary file is exactly what `conf` exists to
  avoid.
- The master password is read from the console itself, never from standard
  input, so a pipe into the command keeps its first line.
- There is no `PR_SET_DUMPABLE` and no `mlockall`, so nothing closes `keenv`
  to your other processes or keeps its pages out of the page file.
- Colour needs a console that takes escape sequences, as Windows Terminal and
  current Windows consoles do. Without one, `keenv` prints plain text.

### How keenv run works on Windows

Windows has no `exec`, so the process that opened the database cannot become
the command. A process that started the command and waited for it would keep
the whole decrypted database in its memory for as long as the command runs.
`keenv run` is therefore split in two:

```text
keenv run -- app              waiter: never reads a config or a secret
  +- python -m keenv run ...  resolver: prompt, database, values
       +- app                 the command, with the values in its environment
```

1. The waiter starts the resolver on the same arguments and then ignores
   Ctrl-C, which reaches the prompt or the command on the shared console.
2. The resolver reads `keenv.yaml` and `.env`, opens the database, resolves
   every reference and starts the command with the result.
3. The resolver hands the waiter a handle on the command and exits. Windows
   frees its memory, and the database and the values go with it.
4. The waiter waits on that handle and exits with the command's exit code.

A resolver that cannot hand the command over kills it and fails, rather than
waiting on it and keeping the database in memory for the command's lifetime.

### The limits on Windows, plainly

- For the seconds the resolver lives, another process running as you can read
  its memory, database included. Windows lets processes of one user open each
  other, and has no equivalent of `PR_SET_DUMPABLE`.
- The command holds the values in its environment for its whole life, as on
  every system, and a process running as you can read that environment.
- Without an agent there is no PIN. A key file saves typing the master
  password, at the price of a file that opens the database on its own.

### Examples on Windows

The examples are for `cmd.exe`. `check`, `lock` and `run` take the same flags
as on Linux:

```bat
keenv check
keenv lock
keenv run -- terraform plan
keenv run --vault C:\Users\me\oberon.kdbx -e deploy.env -- deploy.cmd
```

The command's exit code comes back through the waiter:

```bat
keenv run -- cmd /c "exit 3"
echo %ERRORLEVEL%
```

Expected output of the second line:

```text
3
```

`keenv lock` is expected to print:

```text
keenv: no agents on Windows, nothing to drop
```

A `ttl` in `keenv.yaml` is expected to print this before the password
prompt:

```text
keenv: ttl does nothing on Windows, which has no agent
```

`keenv conf` is refused with exit code `1`:

```bat
keenv conf work.ovpn -- openvpn --config {}
```

Expected output:

```text
keenv: keenv conf is not available on Windows: there is no way to hand a config over in memory only
```

## How it works

1. Both layers are read and merged into one list of variables. A name defined
   in both takes its value from `.env`, and `keenv check` names the file each
   variable came from.
2. `keenv` clears `PR_SET_DUMPABLE`, so from here on only root can read its
   memory or its descriptors. This step is Linux only, see [macOS](#macos).
3. If any of the variables is a `keenv://` reference, the database is opened
   once. The master password is asked for on `/dev/tty`, never on stdin, so a
   password prompt can never swallow the first line of a pipe. A key file
   replaces the prompt, and `ttl:` replaces it with a PIN for as long as the
   agent lives.
4. Every reference is resolved from that one open database.
5. The resolved variables are laid over a copy of the current environment and
   handed to `os.execvpe`.

Step 5 is what keeps the secrets contained: `execvpe` replaces the process
image, so nothing that held the values is still running once the command
starts, and the shell that invoked `keenv` never saw them. Windows has no
`execvpe`; the [Windows](#windows) section shows the two processes that stand
in for it there.

## Development

```bash
make init
make test
make lint
```

`make init` creates `.venv`, installs the package in editable mode and wires up
the [pre-commit](https://pre-commit.com/) hooks. The test suite builds its own
throwaway database in a temporary directory; no test opens a real vault.

Commits go through [commitizen](https://commitizen-tools.github.io/commitizen/):

```bash
.venv/bin/cz commit
```
