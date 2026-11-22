# Design System

The visual language of the TrustUp frontend. It is derived from the reference design the product owner chose (light canvas, white rounded cards, black primary actions, sparing lime highlights, oversized light type) and documents what is **actually implemented** in `frontend/`.

> **Source of truth:** tokens live in `frontend/src/app/globals.css`; components live in `frontend/src/components/`. If this document and the code disagree, the code wins. Update this file in the same change.

---

## 1. Principles

1. **Calm canvas, clear cards.** A soft grey page with white, borderless, very rounded cards. Separation comes from colour, not lines or shadows.
2. **Black acts, lime highlights.** Black is the colour of action (primary buttons, the selected nav pill, the send button). Lime is used sparingly to draw the eye: AI insights, the current question, progress tips, unread dots.
3. **Big, light numbers.** Key figures are large and light (weight 300) with small, quiet units and labels.
4. **Minimal friction.** One clear primary action per area. Secondary options stay out of sight until they are relevant (e.g. manual rating only appears when needed).
5. **AI is visible but never decides alone.** AI output is marked (lime sparkle, "AI suggestion") and always has a human confirmation step.
6. **Honest visuals.** Charts show real data or nothing. No decorative "data-looking" graphics.

---

## 2. Brand

**Name:** TrustUp (written "TrustUp" in text; the wordmark is lower case "trustup").

**Mark:** two chain links joined on an upward diagonal, drawn as rounded outlines (64×64 grid, links 32×18 with radius 9, stroke 5.5, rotated −45°). **Wordmark:** Space Grotesk Bold, letter-spacing −0.04em, converted to outlines so it renders identically everywhere. Lock-up: mark height = 1.2× text size, gap = 0.2× text size.

| Variant | Colours (app palette) | Use |
|---|---|---|
| Light (`trustup-logo-light.svg`) | Links ink `#0F0F0F` + lime `#6BEF75`; "trust" ink; "up" brand-strong `#1B7E2A` | White / light backgrounds |
| Dark (`trustup-logo-dark.svg`) | Links off-white `#F2F2F2` + lime; "trust" off-white; "up" lime | Ink / dark backgrounds |
| Lime (`trustup-logo-lime.svg`) | Links ink + off-white; wordmark all ink | Lime backgrounds |
| Mark only (`trustup-mark-{light,dark,lime}.svg`) | As above | Tight spaces, avatars |
| App icon (`trustup-app-icon.svg`, `-small.svg`) | Ink rounded square (radius 23/100), off-white + lime links; small version uses stroke 7 | App icon, favicon (`src/app/icon.svg`) |

- In the app use the `Logo` / `LogoMark` components (`components/app/logo.tsx`); `tone="auto"` follows the theme tokens (light/dark automatically), `tone="lime"` is for lime surfaces. Size by height (`h-7` top bar, `h-9` auth pages).
- Static files: `frontend/public/brand/`. Regenerate with `frontend/scripts/build_brand.py` (keeps SVGs, component paths and palette in sync).
- Don't recolour the links individually, stretch the logo, or place the light version on dark backgrounds. Keep clear space of at least the mark's width/4 around it.

## 3. Colour

Colours are defined as OKLCH CSS variables and exposed to Tailwind as `bg-*`, `text-*`, `border-*` utilities (e.g. `--brand` → `bg-brand`). Hex values are approximate, for reference.

### 3.1 Core tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `background` | `#F0F0EF` | `#090909` | Page canvas |
| `card` / `popover` | `#FFFFFF` | `#151515` | Cards, panels, menus, dialogs |
| `foreground` | `#0F0F0F` | `#F2F2F2` | Body text |
| `primary` | `#0F0F0F` (black) | `#F2F2F2` (white) | Primary buttons, selected pills, user chat bubbles |
| `primary-foreground` | white | near-black | Text on `primary` |
| `brand` | `#6BEF75` (lime) | `#6BEF75` | Highlights, AI accents, logo, progress tips, unread dots |
| `brand-foreground` | near-black | near-black | Text on `brand` (always dark) |
| `brand-strong` | `#1B7E2A` (dark green) | `#6BEF75` (lime) | Green that must read on the current background: the logo's "up", green text on white |
| `muted` | `#F2F2F1` | `#1F1F1F` | Input fills, AI chat bubbles, quiet surfaces inside cards |
| `muted-foreground` | `#72726E` | `#989898` | Labels, secondary text, hints |
| `accent` | `#DBF8DA` (pale lime) | `#133716` | Selected list items, active outline item, AI-suggested rating cards |
| `accent-foreground` | `#0B3E12` | `#A1F7A3` | Text on `accent` |
| `border` / `input` | `#E3E3E1` | white 9% / 12% | Hairline dividers inside cards, outline buttons |
| `ring` | `#6FDA75` | same | Focus rings (lime) |

### 3.2 Status tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `success` | `#20A04E` | `#55C975` | Published, completed, verified, approved |
| `warning` | `#EFA831` (text `#3F2903`) | lighter amber | Drafts, in review, deprecated-version notices |
| `destructive` | `#DF2225` | `#FF6367` | Errors, changes requested, destructive actions (used as tinted backgrounds, e.g. `bg-destructive/10`) |

### 3.3 Data colours

**Maturity ratings** (`MaturityBadge`, `components/runs/badges.tsx`):

| Rating | Colour family | Label |
|---|---|---|
| 0 | red | Non-existent |
| 1 | orange | Initial |
| 2 | amber | Defined |
| 3 | emerald | Managed |
| 4 | teal | Optimized |
| N/A | muted grey | Not applicable |

**Scores** (`scoreTone`): `< 1.5` red · `< 2.5` amber · otherwise emerald.

**Risk score** (likelihood × impact): `≥ 15` solid red · `≥ 10` solid orange · `≥ 5` amber · below 5 pale emerald.

**Action priority**: critical red · high orange · medium amber · low grey (tinted badge backgrounds).

### 3.4 Colour rules

- **Do** use black (`primary`) for the single most important action in an area.
- **Do** use lime for emphasis and AI moments, in small doses.
- **Don't** put lime text on white or on light grey (insufficient contrast). Lime is a background or a fill; text on lime is always black.
- **Don't** introduce new hues. Add a token in `globals.css` if a new semantic colour is genuinely needed.

---

## 4. Typography

| Role | Font | Notes |
|---|---|---|
| UI and headings | **Outfit** (Google Fonts, via `next/font`) → `--font-sans` | Geometric sans, matching the reference |
| Codes and IDs | **Geist Mono** → `font-mono` | Control codes (`AC-02`), requirement keys (`R7`), clause refs (`A.5.15`) |

Font features: `"ss01"` and `"tnum"` (tabular numbers) are on globally.

### 4.1 Type scale

| Style | Classes | Where |
|---|---|---|
| Page title | `.display text-4xl sm:text-5xl` | `PageHeader` title |
| Hero / auth headline | `.display text-6xl` | Login/signup left side |
| Big number (stat) | `BigNumber` with `text-5xl` (overview), `text-7xl` (results), `text-3xl` (inline) | Stats, scores, coverage % |
| Section heading | `text-xl font-medium tracking-tight` | "Continue where you left off" |
| Card title / panel label | `text-[15px] text-muted-foreground` with an icon | `PanelTitle` |
| Body | `text-sm` (14px), longer reading `text-[15px]` | Default |
| Small / meta | `text-xs` (12px) `text-muted-foreground` | Hints, timestamps |
| Eyebrow | `text-sm text-muted-foreground` above a title | `PageHeader eyebrow` |

`.display` (in `globals.css`): weight 300, letter-spacing −0.03em, line-height 1.02. Use it for titles and big numbers only.

**Casing:** sentence case everywhere ("Create new version", not "Create New Version"). No all-caps labels except tiny markers in the reference style.

---

## 5. Layout and spacing

- **Container:** `max-w-[87.5rem] mx-auto px-4 lg:px-8`, top padding `pt-6`, bottom `pb-16` (set in `AppShell`).
- **Top bar:** sticky, height `h-18` (72px), translucent canvas (`bg-background/85 backdrop-blur-md`).
- **Grids:** `gap-4` between cards; overview stat rows are `sm:grid-cols-2 xl:grid-cols-4`.
- **Card padding:** `p-6` for stat and content panels, `p-5` for list rows and compact cards; shadcn `Card` uses `--card-spacing: 20px`.
- **Vertical rhythm:** sections separated by `mt-10`; page header has `mb-8`.
- **Full-bleed screens:** the assessment workspace (`/app/runs/[id]/domains/[domainId]`) uses the full width with `p-3 gap-3` between panels and a viewport-height layout.
- **Breakpoints:** Tailwind defaults. Top nav collapses into a slide-out menu below `lg` (1024px); the workspace collapses its three panels into tabs below `lg`, and the outline panel appears from `xl`.

---

## 6. Shape

> **Gotcha:** the theme radius is `--radius: 1rem`, and Tailwind's named radii scale from it: `rounded-sm` ≈ 10px, `rounded-md` ≈ 13px, `rounded-lg` = 16px, `rounded-xl` ≈ 22px, `rounded-2xl` ≈ 29px, `rounded-3xl` ≈ 35px. Named radii on small controls therefore look like pills. **Use explicit pixel radii for small rectangular controls.**

| Element | Radius |
|---|---|
| Cards, panels, dialogs, empty states | `rounded-3xl` (~35px) |
| Auth panels | `rounded-[2rem]` |
| Nested surfaces inside cards (rating cards, chat bubbles, outline items) | `rounded-2xl` / `rounded-3xl` |
| **Buttons, tabs, nav pills, badges** | `rounded-full` (pill) |
| **Text inputs** | **`rounded-[10px]`**, like select fields: form fields are rounded rectangles, never pills |
| **Text areas** | **`rounded-[12px]`** |
| Textareas | `rounded-2xl` (composer: `rounded-3xl`) |
| **Dropdowns (select fields)** | **`rounded-[10px]`** — rounded rectangle, never a pill |
| **Dropdown lists and menus** (select content, `⋯` menus, command pickers) | **`rounded-[12px]`** |
| **Options / menu items** | **`rounded-[6px]`** |
| Picker search box | `rounded-[8px]` |

---

## 7. Elevation

- **No shadows on cards.** White on grey provides separation.
- **Overlays** (menus, popovers, select lists) use the shadcn defaults: `shadow-md` + `ring-1 ring-foreground/10`.
- **Hover on clickable cards:** `hover:ring-2 hover:ring-brand/60` (lime ring), never a lift shadow. The lime insight card may lift slightly (`hover:-translate-y-0.5`).
- **Frosted lime surface:** `.glass-brand` (radial + linear lime gradient with an inner highlight). Reserved for AI insight cards, the overall maturity card, and the current question.

---

## 7a. Motion

One easing family and a few durations, defined once in `globals.css` (`@theme`). Pure CSS, no animation library.

| Token / class | Value | Use |
|---|---|---|
| `ease-smooth` (default for every `transition`) | `cubic-bezier(0.22, 1, 0.36, 1)` | Entering, expanding, hover: starts quickly, settles gently |
| `ease-smooth-in` | `cubic-bezier(0.55, 0, 0.75, 0.3)` | Elements leaving (overlay close) |
| default `transition` duration | 220ms | Hover, focus, colour changes |
| Popovers, menus, selects, dialogs | 200ms in / 150ms out | Exits are faster than entrances |
| Side sheets, requirements rail width | 350ms | Larger movement gets more time |
| Intake card stack | 450ms | |
| Progress bars | 500ms | Width animates to the new value |

Rules:
- Animate only `transform`, `opacity`, and (for panels that resize their neighbours) `width`. Never animate shadows or blur.
- Never swap content in one frame while its container changes size: layer both states and cross-fade (the rail fades its old view out in 150ms, the new one in after a 100–150ms delay, while the width transitions).
- New content (chat messages, question cards) fades and rises 4–8px.
- `prefers-reduced-motion: reduce` turns all transitions and animations off globally.

## 8. Components

All paths are relative to `frontend/src/components/`.

### 8.1 Buttons — `ui/button.tsx`

Pill-shaped (`rounded-full`).

| Variant | Look | Use |
|---|---|---|
| `default` | Black, white text | The primary action in an area |
| `brand` | Lime, black text | Rare celebratory/AI action |
| `outline` | White with hairline border | Secondary actions next to a primary |
| `secondary` | Light grey fill | Low-emphasis actions |
| `ghost` | Transparent, grey on hover | Toolbar/icon actions, menu triggers |
| `destructive` | Red tint | Destructive actions (always behind confirmation) |
| `link` | Underline on hover | Inline links |

| Size | Height | Notes |
|---|---|---|
| `xs` | 28px | Inline actions (Confirm, Adjust, Rate) |
| `sm` | 32px | Card-level actions |
| `default` | 36px | Standard |
| `lg` | 44px | Auth forms |
| `icon-xs` / `icon-sm` / `icon` / `icon-lg` | 28 / 32 / 36 / 44px | Round icon buttons; chat send is `icon-lg` black |

Icons: `lucide-react`, 16px by default. Icon-only buttons **must** have `aria-label`.

### 8.2 Inputs

| Component | Style |
|---|---|
| `ui/input.tsx` | `h-10 rounded-[10px]`, grey fill (`bg-muted`), no border; on focus: white fill + lime ring |
| `ui/textarea.tsx` | `rounded-[12px]`, grey fill, same focus treatment |
| `ui/select.tsx` | Field `h-10 rounded-[10px]` grey fill; list `rounded-[12px]`; options `rounded-[6px]`, highlighted in pale lime |
| `app/password-input.tsx` | `Input` + eye toggle (`Show password` / `Hide password`, `aria-pressed`). Use for **every** password field |
| `app/field.tsx` | Label + control + optional hint (`text-xs text-muted-foreground`) |

### 8.3 Tabs and navigation

- **Tabs** (`ui/tabs.tsx`): white pill track; the selected tab is a **black pill with white text**. Hover darkens only unselected tabs (`not-data-active:hover:…`) so selected text never becomes unreadable.
- **Top navigation** (`app/shell.tsx`): logo, horizontal pill links (selected = black pill), tenant name chip, round notification button with lime unread dot, avatar + name + role. Below `lg` the links move into a slide-out `Sheet`.

### 8.4 Badges — `ui/badge.tsx`, `app/status.tsx`, `runs/badges.tsx`

Small pills (`h-5`, `text-xs`). Status badges use tinted backgrounds of the status colour.

| Badge | States |
|---|---|
| `VersionBadge` | `vN Published` (success), `Draft` (warning), `Deprecated` (muted) |
| `RunStatusBadge` | Getting started, In progress, Preparing results (pale lime) · In review (warning) · Changes requested (destructive) · Approved (success) |
| `DomainStatusBadge` | Not started · In progress · Completed · Changes requested |
| `MaturityBadge` | Rating number + label in the maturity colour (§3.3) |
| `FrameworkBadge` | Short framework name (`ISO 27001`, `NIST CSF`) on secondary grey |

### 8.5 Cards and page structure — `app/page.tsx`

| Component | Purpose |
|---|---|
| `PageHeader` | Optional back pill, eyebrow, oversized title, description, meta row, actions |
| `Panel` / `PanelTitle` | White `rounded-3xl` card; title row = icon + grey label + optional action |
| `Stat` | Panel with label, `BigNumber`, hint and optional visual; becomes a link card with `href` |
| `BigNumber` | `.display` number with a small top-aligned unit (`/4`, `%`) |
| `EmptyState` | Lime round icon, title, text, optional action, on a white card |
| `ListSkeleton` | Rounded skeleton rows while loading |
| `ui/card.tsx` | shadcn Card restyled: `rounded-3xl`, no ring, 20px spacing |

### 8.6 Data visuals

| Component | Description | Rule |
|---|---|---|
| `SegmentBar` (`app/page.tsx`) | 24px bar: black fill, lime tip, hatched remainder | Progress toward a target (maturity /4, %) |
| `Bar` (`runs/badges.tsx`) | 6px thin bar: black fill with lime tip | Inline progress in rows and cards |
| `TickChart` (`app/page.tsx`) | Thin vertical "barcode" ticks; tall ticks black, highlights lime | Only with real values; omit if data is uniform or meaningless |
| Risk heat map (`app/app/risks/page.tsx`) | 5×5 grid, cell colour by score | Counts per likelihood × impact |

### 8.7 AI and conversation — `runs/chat.tsx`, `runs/ratings.tsx`, `runs/rich-text.tsx`

- **Question card:** current question = `.glass-brand` card with black text, a sparkle label ("Question" / "Follow-up"), help text as a bullet list, and a white-tinted "Doesn't apply to us" chip. Past questions = grey.
- **Bubbles:** user = black, right-aligned, `rounded-3xl rounded-br-lg`, initials avatar; AI = grey (`bg-muted`), left-aligned, `rounded-bl-lg`, lime round avatar with a sparkle.
- **Streaming:** the AI bubble grows as text arrives with a lime blinking cursor; while working, three bouncing dots + a status line ("Suggesting ratings…").
- **Events:** small centred grey lines ("Answer saved", "We've moved on…"); domain finished = black card with a lime icon.
- **Composer:** round outline attach button + pill textarea + black round send button; file chips are grey pills with a spinner while evidence is read.
- **Requirements rail** (`runs/requirements.tsx`): collapsed by default to a 64px rail (confirmed count + one dot per requirement: hollow = not rated, pulsing lime = AI rating it, lime = AI suggestion, black = confirmed); expands to 22rem compact cards. The choice is remembered per browser.
- **Requirement detail sheet:** right-side sheet with the statement, "what good evidence looks like", framework clause chips, the current rating with rationale and cited evidence, then **Your answer**, **Rating** (0–4 / N/A as 10px rounded segments; none selected = let the AI rate) and **Evidence** (upload or choose uploaded). Sticky primary action: "Save rating" or "Ask AI to rate"; "Confirm AI rating" appears on unchanged AI suggestions.
- **RichText:** renders the AI's paragraphs, `-` and `1.` lists, `**bold**` and `*italic*`. Never render raw Markdown.

### 8.8 Overlays — `ui/dialog.tsx`, `ui/alert-dialog.tsx`, `ui/popover.tsx`, `ui/dropdown-menu.tsx`

- Dialogs: `rounded-3xl`, `p-6`. Footer actions right-aligned: outline "Cancel" then the primary action.
- Destructive or irreversible actions (discard draft, delete) always go through `AlertDialog` with a plain explanation of the consequence.
- Menus: `rounded-[12px]` with `rounded-[6px]` items; destructive items use the `destructive` item variant.
- Toasts: `sonner`, top-right, rich colours; success for completed actions, error for failures.

---

## 9. Patterns

| Pattern | Recipe |
|---|---|
| **Overview page** | Eyebrow + "Overview" title on the left, lime insight card on the right (one sentence pointing to the next best action), then a 4-up `Stat` row, then lists |
| **List of records** | Stack of standalone white row cards (`rounded-3xl`, `space-y-2`), each a link with a trailing `↗` and a lime ring on hover; or rows inside one card separated by hairline borders for dense admin lists |
| **Detail page** | `PageHeader` with back pill + meta badges, content left, sticky side panel right (`lg:grid-cols-[1fr_19rem]`) |
| **Stacked-card modal** (pre-assessment intake, `runs/intake.tsx`) | Centred non-dismissable dialog on a darker backdrop (`overlayClassName="bg-black/45 …"`); one question card on top, up to 3 cards peeking below (scaled from the bottom, faded, content hidden); Next/Enter slides the top card away, Back brings it back; "Question n of N" + dot progress; a quiet skip link below the stack; AI working states render inside the same dialog |
| **Progressive disclosure** | Hide secondary actions until relevant (e.g. manual "Rate" only when no open question covers a requirement or AI is paused) |
| **Loading** | Skeletons for lists; a centred "Working" card (lime icon + pulse) for AI jobs, polling in the background |
| **Empty** | `EmptyState` with one clear next action |
| **Errors** | Inline `Alert` for page-level problems (with a retry where possible); toast for failed actions |
| **Notices** | Neutral notices on white cards; version/deprecation notices in warning tint |

---

## 10. Content and voice

- **Plain English.** Write for an IT manager or founder, not an auditor. Avoid jargon; explain when needed.
- **Sentence case** for every label, title and button.
- **Buttons say what happens:** "Save draft", "Publish v2", "Mark not applicable", not "Submit" or "OK".
- **Be specific in feedback:** "3 requirement(s) have no question yet", not "Invalid state".
- **AI copy** is short, friendly and never claims certainty it doesn't have; ratings say what they rely on.
- **No exclamation marks** except in genuinely celebratory moments.

---

## 11. Accessibility

- **Contrast:** body text on white/grey meets WCAG AA; never lime text on light backgrounds; text on lime and on glass cards is black.
- **Selected states keep their contrast on hover** (selected black pills keep white text).
- **Focus:** every interactive element shows a lime focus ring (`focus-visible:ring-3 ring-ring/40–50`).
- **Labels:** icon-only buttons have `aria-label`; toggles use `aria-pressed`; form fields have associated `<Label>`s.
- **Keyboard:** dialogs trap focus (Radix); Enter sends a chat message, Shift+Enter adds a line; menus and selects are fully keyboard-operable.
- **Motion:** animations are small (pulse, bounce dots, 0.5px lift); no essential information is conveyed by motion alone.

---

## 12. Dark mode

Driven by `next-themes` (`class="dark"`), user-selectable in the account menu (Light / Dark / System).

- Canvas near-black, cards one step lighter, `primary` flips to white (so primary buttons become white with dark text).
- Lime stays the same; pale-lime `accent` becomes deep green with light-green text.
- Status colours lighten for contrast. `.glass-brand` fades from lime into the dark card colour.
- Always check new screens in both themes.

---

## 13. Do and don't

| Do | Don't |
|---|---|
| Use one black primary action per area | Put several black buttons side by side |
| Keep dropdowns as rounded rectangles (`10px` / `12px` / `6px`) | Make selects, menus or options pill-shaped |
| Use `not-data-active:hover:` for hover styles on pill selectors | Let hover change text colour on a selected black pill |
| Use pixel radii for small rectangular controls | Use `rounded-lg`/`rounded-xl` on small controls (they render as pills, §6) |
| Use lime for highlights and AI moments | Use lime for body text or large areas |
| Show real data in charts, or no chart | Add decorative charts that look like data |
| Reuse `PageHeader`, `Panel`, `Stat`, `PasswordInput` | Rebuild headers, cards or password fields ad hoc |
| Separate with colour (white on grey) | Add borders or shadows to cards |

---

## 14. Where things live

| What | File |
|---|---|
| Tokens, fonts mapping, `.display`, `.glass-brand` | `frontend/src/app/globals.css` |
| Font loading | `frontend/src/app/layout.tsx` |
| shadcn primitives (restyled) | `frontend/src/components/ui/*` |
| App shell, logo, page primitives, field, password input | `frontend/src/components/app/*` |
| Status and version badges | `frontend/src/components/app/status.tsx`, `frontend/src/components/runs/badges.tsx` |
| Assessment workspace (chat, ratings, rich text) | `frontend/src/components/runs/*` |
| App name | `frontend/src/lib/format.ts` (`APP_NAME`) |

**Adding a token:** define it in `:root` and `.dark` in `globals.css`, expose it in the `@theme inline` block as `--color-<name>`, then document it in §3.

**Adding a component:** prefer composing existing primitives; if a new primitive is needed, put it in `components/app/`, follow the shape and colour rules above, and add it to §8.
