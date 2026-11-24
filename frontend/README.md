# TrustUp frontend

The web app: Next.js 16 (App Router), Tailwind CSS v4, shadcn/ui and TanStack Query. It holds no
secrets and talks only to `/api`.

It runs as the `frontend` service of the Compose stack, not on its own: see
[../SETUP.md](../SETUP.md). The look and the components are described in
[../DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md).

```bash
npm ci
npx tsc --noEmit      # types
npx eslint src        # lint
npm run build         # production build
```

- `src/app/` pages: `(auth)/` sign-in and sign-up, `admin/` the super admin, `app/` a company's workspace.
- `src/components/` shared components (`ui/` is shadcn).
- `scripts/build_brand.py` builds every logo file from `scripts/brand/trustup-logo-source.svg`.
- `AGENTS.md`: Next.js 16 differs from earlier versions; read it before using unfamiliar APIs.
