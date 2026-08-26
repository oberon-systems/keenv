# keenv

`keenv` puts secrets from a [KeePass](https://keepass.info/) database into the
environment of one command and nowhere else. The values never reach a file, an
`export`, or the shell history: they exist between unlocking the database and
`exec`ing the command, and the process that held them is replaced.

It is the tool the Oberon Systems keyring policy names for local secrets, and
the way [indech](https://github.com/oberon-systems/indech) hands the Cloudflare
R2 keys to OpenTofu.

## Contents

- [Why](#why)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
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
AWS_ACCESS_KEY_ID            keenv://Oberon/R2/indech-state/UserName    20 chars
AWS_SECRET_ACCESS_KEY        keenv://Oberon/R2/indech-state/Password    40 chars
```

Point at another database and another mapping:

```bash
keenv run --vault ~/other.kdbx -e deploy.env -- ./deploy.sh
```

Exit codes are `0` on success, `1` for anything `keenv` can explain, `2` for a
usage mistake, and `127` when the command does not exist. Otherwise the exit
code is the command's own, because the command replaces `keenv`.

## How it works

1. Both layers are read and merged into one list of variables.
2. If any of them is a `keenv://` reference, the database is opened once. The
   master password is asked for on `/dev/tty`, never on stdin, so a password
   prompt can never swallow the first line of a pipe. A key file replaces the
   prompt.
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
