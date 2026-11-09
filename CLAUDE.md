# Project notes for Claude

## Design workflow

- Impeccable is the primary design authority for layout, typography, color and spacing.
- Use Emil Kowalski's skill (`emil-design-eng`) for animations, transitions and interaction polish.
- Use Taste Skill (`design-taste-frontend`) only as a secondary check against generic "AI slop" patterns. Where it conflicts with Impeccable, Impeccable wins.
- When I share a Figma link, use the Figma MCP to read the real design (tokens, spacing, components) instead of guessing.
- After any visual change, start the dev server, use Playwright to open the page, take screenshots at desktop (1440px) and mobile (390px) widths, review them against the skills, and fix issues before telling me it's done.

## Restoring the design skills

The skills aren't committed because of their size. On a fresh clone, run these from the repo root:

```bash
npx impeccable install -y --providers=claude --scope=project
npx skills experimental_install
```
