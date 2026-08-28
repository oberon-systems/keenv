# keenv

`keenv` puts secrets from a [KeePass](https://keepass.info/) database into the
environment of one command and nowhere else. The values never reach a file, an
`export`, or the shell history: they exist between unlocking the database and
`exec`ing the command, and the process that held them is replaced.

It is the tool the Oberon Systems keyring policy names for local secrets.
## Contents

- [Why](#why)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Remembering the password](#remembering-the-password)
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
way to see that a `.env` is overriding `keenv.yaml`.

Point at another database and another mapping:

```bash
keenv run --vault ~/other.kdbx -e deploy.env -- ./deploy.sh
```

Exit codes are `0` on success, `1` for anything `keenv` can explain, `2` for a
usage mistake, and `127` when the command does not exist. Otherwise the exit
code is the command's own, because the command replaces `keenv`.

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
New PIN (4 to 8 digits):
Repeat the PIN:

$ keenv run -- tofu apply
PIN for /home/you/oberon.kdbx:
```

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
what turns it down. The padding is what keeps the blob from betraying how long
the password is.

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
  takes to open the database. `execvpe` then replaces the process, which is
  the same guarantee the default mode gives.

A key file is a different trade and needs none of this. It already opens the
database without a prompt, so `ttl` does nothing alongside one, and `keenv`
says so rather than starting an agent that would hold nothing.

## How it works

1. Both layers are read and merged into one list of variables. A name defined
   in both takes its value from `.env`, and `keenv check` names the file each
   variable came from.
2. If any of them is a `keenv://` reference, the database is opened once. The
   master password is asked for on `/dev/tty`, never on stdin, so a password
   prompt can never swallow the first line of a pipe. A key file replaces the
   prompt, and `ttl:` replaces it with a PIN for as long as the agent lives.
3. Every reference is resolved from that one open database.
4. The resolved variables are laid over a copy of the current environment and
   handed to `os.execvpe`.

Step 4 is what keeps the secrets contained: `execvpe` replaces the process
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
