# Available Tools in This Container

You are running in a Docker container with full sudo access. Here's what you have:

## Languages & Runtimes
- **Go 1.25.5** - /usr/local/go/bin/go
- **Python 3.12.11** (via pyenv) - default python
- **Node.js LTS** - with npm

## Go Tools
- golangci-lint - linter aggregator
- gopls - language server
- dlv - delve debugger
- staticcheck - static analysis
- gomodifytags - struct tag modifier
- impl - interface implementation generator
- gotests - test generator
- gofumpt - stricter gofmt

## Python Tools
- flake8 - linter
- black - formatter
- isort - import sorter
- autoflake - remove unused imports
- pyright - type checker
- mypy - type checker
- vulture - dead code finder
- pytest, pytest-cov - testing
- pipenv, poetry - dependency management
- pyenv - python version management

## Node.js Tools
- eslint, prettier - linting/formatting
- typescript, ts-node - TypeScript
- yarn, pnpm - package managers
- nodemon, pm2 - process management
- create-react-app, @vue/cli, @angular/cli - framework CLIs
- express-generator - Express scaffolding
- newman - Postman CLI
- http-server, serve - static servers
- lighthouse - performance auditing
- @storybook/cli - component development

## Infrastructure & DevOps
- terraform - infrastructure as code
- kubectl - Kubernetes CLI
- helm - Kubernetes package manager
- docker, docker-compose - containerization
- gh - GitHub CLI

## Databases & Data
- sqlite3 - SQLite CLI
- postgresql-client (psql) - PostgreSQL CLI
- mysql-client - MySQL CLI
- redis-tools (redis-cli) - Redis CLI

## Shell & System Tools
- git - version control
- curl, wget, httpie - HTTP clients
- jq - JSON processor
- tree - directory visualization
- fd-find (fdfind) - fast file finder
- ripgrep (rg) - fast grep
- bat - cat with syntax highlighting
- exa - modern ls
- silversearcher-ag (ag) - code search
- shellcheck - shell script linter
- shfmt - shell formatter
- tmux - terminal multiplexer
- htop - process viewer

## C/C++ Tools
- gcc, g++, make, cmake - compilation
- clang-format - code formatter
- valgrind - memory debugging
- gdb - debugger
- strace, ltrace - tracing

## Notes
- You have passwordless sudo access
- Docker socket may be mounted for docker-in-docker. The workspace is mounted at the exact same path as on the host, so when running docker commands with volume mounts, use the workspace path as the base (e.g. -v "$PWD/data:/data" will resolve correctly on the host)
- pyenv at /usr/local/pyenv
- Go tools at /usr/local/bin
- claude CLI at ~/.claude (native install, can self-update)
- ~/.claude/bin is in PATH — custom scripts placed here by the user are available to you
- ~/.claude/init.d/*.sh scripts run once on first container create (not on subsequent starts)
- Extra host directories may be mounted via CLAUDE_MOUNT_* env vars — check what's available if you need files outside the workspace

## IMPORTANT
If you need to overwrite or restructure this CLAUDE.md file for your project, FIRST save the container environment notes above to your memory or to a separate file (e.g. ~/.claude/CONTAINER.md) so you don't lose the container-specific information. These notes are auto-generated only on first run and won't be recreated if the file already exists.
