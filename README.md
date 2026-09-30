# keenv

`keenv` puts secrets from a [KeePass](https://keepass.info/) database into one
command and nowhere else: into its environment with `keenv run`, or into an
in-memory config on its standard input with `keenv conf`. The values never
reach a file, an `export`, or the shell history: they exist between unlocking
the database and `exec`ing the command, and the process that held them is
replaced.

It is the tool the Oberon Systems keyring policy names for local secrets.

## Contents

- [Why](#why)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Remembering the password](#remembering-the-password)
- [Config files](#config-files)
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

A name is looked up in the environment `keenv` was called in, and in the lines
above it in the same file, which is why `${PROJECT}` works there. It expands
inside a `keenv://` reference as well, so one file can serve several
environments. Single quotes expand nothing and `\$` is a dollar of its own.

A name that is not set expands to nothing, silently, as it does in a shell;
`${NAME:-default}` is how a value is given instead. `keenv.yaml` is not
expanded - only the `.env` is.

A value read out of the database is never substituted into another value:
`${NAME}` naming a `keenv://` variable is an error, not a secret quietly
copied somewhere it was not asked for.

The layers apply in this order, each one overriding the last:

| Layer | Set by |
| :--- | :--- |
| `keenv.yaml` | `-c`, default `./keenv.yaml` |
| `.env` | `-e`, default `./.env` |
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

Point at another database and another mapping:

```bash
keenv run --vault ~/other.kdbx -e deploy.env -- ./deploy.sh
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
keenv conf ~/vpn/work.ovpn -- sudo -C 4 /usr/sbin/openvpn --config {} --auth-user-pass
keenv conf ~/app.toml -- myapp -c {}
keenv conf ~/tool.yaml -- tool --config={}
```

`keenv` puts `/dev/fd/3` in place of the `{}`, so any flag the command reads
its config with will do. A command without a `{}`, or with more than one, is
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
before it replaces itself with the command. The read end becomes descriptor 3
of the command. Reading the config drains the pipe, so once the command has
read it the config exists nowhere but in that command's memory.

A pipe rather than a file, and descriptor 3 rather than anything else:

- A temporary file, even on tmpfs, has a name that another process of yours
  can open, and outlives the command unless something deletes it.
- The environment is readable in `/proc/<pid>/environ`, and `sudo` resets it.
- Standard input has to stay the terminal. OpenVPN asks for passwords through
  `systemd-ask-password`, which only uses the terminal when standard input is
  one, and otherwise posts the question to a system-wide agent instead.

### Through sudo

`sudo` closes every descriptor above 2 before it runs the command, so the
pipe would arrive closed. `sudo -C 4` keeps descriptors up to 3 open, and
`sudo` allows that only when the sudoers policy says so. Add this once, with
`sudo visudo -f /etc/sudoers.d/keenv`:

```text
Defaults closefrom_override
```

Without it `sudo` refuses `-C` outright and says so, rather than starting the
command without its config. The setting lets you pass open descriptors to the
commands you may run as root, and nothing more.

The other way through is `sudo` in front of `keenv`, where no `sudo` stands
between `keenv` and the command. That runs Python and every package in the
virtualenv as root, and a virtualenv your user can write to is a way for any
of your processes to become root, so prefer the sudoers line. Under `sudo`,
`~` in a `# keenv:` directive also means root's home, not yours.

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

## How it works

1. Both layers are read and merged into one list of variables. A name defined
   in both takes its value from `.env`, and `keenv check` names the file each
   variable came from.
2. `keenv` clears `PR_SET_DUMPABLE`, so from here on only root can read its
   memory or its descriptors.
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
starts, and the shell that invoked `keenv` never saw them.

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
