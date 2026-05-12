# Myah

Myah is an AI agent workstation platform built on top of [Hermes Agent](https://github.com/nousresearch/hermes-agent) by NousResearch and [Open WebUI](https://github.com/open-webui/open-webui).

## Architecture

- `platform/` — SvelteKit frontend + FastAPI backend
- `agent/` — Hermes agent configuration and runtime (git submodule)
- `docs/` — Design specs and implementation plans

## Quickstart

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/T3-Venture-Labs-Limited/myah

# Install frontend deps
cd platform && npm install

# Start backend
npm run dev:backend

# Start frontend (separate terminal)
npm run dev
```

## Contributing

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for contribution guidelines.

## License

See [LICENSE](LICENSE) for details.
