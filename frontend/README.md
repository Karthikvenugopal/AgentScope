# AgentScope research dashboard

React + TypeScript + Vite, React Router, TanStack Query, generated OpenAPI
contracts, Vitest, and React Testing Library. Requires Node 22.12+.

```sh
npm ci
npm run dev
```

Vite proxies the API at `http://127.0.0.1:8000`; override with `API_PROXY_TARGET`.
The complete Docker workflow is `make dev` from the repository root after `.env`
configuration.

```sh
npm run generate-api  # installed backend required; PYTHON selects interpreter
npm run check-api
npm run typecheck
npm run lint
npm test
npm run build
```

Do not edit `src/api/generated/` manually. Static production assets go to `dist/`;
the Compose frontend uses Vite development mode for hot reload.
See [Phase 5](../docs/phase5.md) for architecture, real screenshots, browser demo
instructions, socket security, and limitations.
