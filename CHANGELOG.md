## 0.4.0 (2026-09-30)

### Features

- **unlock**: let an empty new PIN run without the agent
- **ovpn**: run sudo openvpn on a config rendered into memory only

### Build

- **deps**: Bump commitizen from 4.18.1 to 4.19.0 in the pip group
- **deps**: Bump https://github.com/commitizen-tools/commitizen
- **pre-commit**: pin markdownlint hook to node 24
- **deps**: group dependabot updates and prefix their commits
- **github**: let dependabot bump hook revs and actions
- **publish**: add the release workflow
- **deps**: keep commitizen, wyld-cz and the hook rev in step
- **github**: create dependabot.yml

## 0.3.1 (2026-09-06)

### Bug Fixes

- **cli**: show normal message on app quit

## 0.3.0 (2026-09-06)

### Features

- **config**: expand ${NAME} in a .env the way a shell would

### Refactor

- **tests**: hang the indent of a signature flake8 was rejecting

### Build

- **context**: removed local context settings

## 0.2.1 (2026-08-28)

### Bug Fixes

- **pin**: a wrong PIN is named as one, not as a codec error
- **agent**: drop an empty agent on every path and survive one that vanished
- **vault**: ask for a PIN again instead of giving up on the first one
- **agent**: never leave an empty agent behind

### Documentation

- **readme**: update readme

## 0.2.0 (2026-08-28)

### Features

- **agent**: remember the master password behind a PIN

## 0.1.2 (2026-08-26)

### Bug Fixes

- **entity**: fix wrong entity path resolve

### Build

- **pre-commit, markdown**: added exclude for changelog

## 0.1.1 (2026-08-26)

### Bug Fixes

- **vault**: no terminal to ask for the master password fixed

## 0.1.0 (2026-08-26)

### Features

- **code**: base functions added

### Bug Fixes

- **cz**: update wyld-cz

### Build

- **base**: additional repo initialization
