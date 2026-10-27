# Sudoku: design guide

Design rules for the shell and every later build workflow (W-5 to W-11). Follow the values below exactly. Items marked (assumption) are not set by the charter and may be changed by the Requester.

## Design standards

These come from the charter and apply to every choice below.

- Warm, friendly, uncluttered look and tone
- Large tap targets and readable numbers
- Phone-first layout that also works on desktop
- Plain HTML, CSS and JavaScript in one file, no build step
- Help never reveals the solution outright (hint styling only marks an area, never a digit)

Look and tone: cream background, soft rounded corners, one accent colour, no ads, no clutter, no timers. One light theme only (assumption).

## Palette

Define these as CSS custom properties on `:root` and use only these colours.

| Token | Hex | Use |
|---|---|---|
| --bg | #FBF6EE | page background (warm cream) |
| --surface | #FFFDF8 | grid cells, cards, how-to and stats panels |
| --ink | #3B2F2A | main text, given digits (bold) |
| --ink-soft | #6B5B52 | secondary text, notes digits |
| --grid-line | #D9CBB8 | thin lines between cells |
| --box-line | #7A5C45 | thick lines around the 3x3 boxes and the grid edge |
| --selected | #FFD98A | the selected cell |
| --hl | #FBEBCB | row, column and box of the selected cell (.hl) |
| --same | #BFE3D0 | cells with the same digit as the selected cell (.same) |
| --conflict-bg | #F9D3CF | background of a conflicting cell (.conflict) |
| --conflict-ink | #B3261E | digit colour of a conflicting cell |
| --given | #3B2F2A | given digits (fixed) |
| --player | #25607F | digits the player entered |
| --hint | #3F8A6E | hint outline, 3px dashed, on the cell, row, column or box to look at (.hint-target) |
| --accent | #C2553A | primary buttons, active level, active notes toggle (white text, contrast about 4.7:1) |
| --accent-ink | #FFFFFF | text on --accent |
| --btn | #F1E4D3 | secondary buttons (pad, undo, erase, hint) |
| --success-bg | #E6F4EA | congratulation panel (#congrats) |
| --success-ink | #1F5A3A | congratulation text |

Rules:
- Priority when several states apply to one cell: conflict, then selected, then same, then hl, then plain surface.
- A conflict is never shown by colour alone: also add a 2px inset border in --conflict-ink and an underline under the digit (matches the spec).
- A selected cell also gets a 2px inset border in --accent so it is clear without relying on colour.
- Text on every background keeps at least 4.5:1 contrast.

## Grid sizing

The one rule that keeps cells at least 40px at 360px with no horizontal overflow:

- `#grid` is a CSS grid: `display: grid; grid-template-columns: repeat(9, 1fr); width: min(100%, 504px); margin-inline: auto; aspect-ratio: 1 / 1;`
- At 360px wide, `#game` has no horizontal padding and the page body has margin 0, so `#grid` is 360px wide and every cell is exactly 40px wide and tall (360 / 9). On wider screens the grid grows up to 504px (56px cells) and stays centred. At 1280px it is 504px wide.
- Every `.cell` uses `box-sizing: border-box` (set `*, *::before, *::after { box-sizing: border-box; }`) and draws all its lines as borders inside the cell, so lines never add width. The thin line is 1px --grid-line. Cells in columns 3 and 6, and rows 3 and 6, get a 2px --box-line on the right or bottom. The outer edge of the grid is a 2px --box-line drawn on the edge cells.
- Never use `100vw` for widths (it includes the scrollbar and causes overflow). Use `100%`. Give grid and flex children `min-width: 0`.
- Under 400px wide, hide the page scrollbar so the full 360px is available: `@media (max-width: 400px) { html { scrollbar-width: none; } html::-webkit-scrollbar { display: none; } }`
- Below 360px the grid simply keeps shrinking with the screen (cells under 40px are outside the charter).
- Digits inside cells: `font-size: clamp(20px, 6.2vw, 30px)`; given digits weight 700 in --given, player digits weight 500 in --player; centre them with flex.
- Pencil notes (`.notes` inside a cell): a 3x3 grid of small digits, `font-size: 11px` at 40px cells (up to 13px on wide screens), colour --ink-soft, one digit per fixed position (1 top-left to 9 bottom-right).
- Cells are square, with `line-height: 1`, and never change size when a digit or notes appear.

## Controls

All buttons carry the class `.j2-btn` and share this base style: `border: 0; border-radius: 12px; min-height: 44px; min-width: 44px; font: inherit; font-weight: 600; color: var(--ink); background: var(--btn); cursor: pointer;`

- Level buttons (`.level-btn`, Easy, Medium, Hard): one row of three equal columns, `gap: 8px`, height 44px, at least 100px wide at 360px. The active level uses --accent with --accent-ink text.
- Number pad (`#pad`, nine `.pad-btn`): a grid of 5 columns, `gap: 8px`, digits 1 to 5 on the first row and 6 to 9 on the second row. Each button is at least 56px wide (about 62px at 360px) and 52px tall, with a 22px digit in weight 600. The empty fifth slot on the second row stays empty.
- Action row (`#undo`, `#erase`, `#notes-toggle`, `#hint`): one row of four equal columns, `gap: 8px`, each at least 44px tall, about 78px wide at 360px. Each has a short text label and may have a simple icon character. `#notes-toggle` shows its on state with --accent background and white text, plus a text label "Notes: on" or "Notes: off" so colour is not the only cue.
- Message area (`#msg`): one line of text above the pad, centred, 16px, in --ink-soft, with room for two lines so the layout does not jump (`min-height: 3em`). It holds encouragement and hint text.
- Congratulation panel (`#congrats`): hidden at start (`hidden` attribute), then a rounded card in --success-bg and --success-ink, 18px text, with a short message and a "New puzzle" prompt that uses a level button.
- Focus: visible `:focus-visible` outline, 3px solid --accent with 2px offset, on every button and cell.
- Hint styling only outlines an area (--hint dashed outline). It never writes a digit into a cell, a note or the message.
- Motion: gentle only (a 120ms colour transition on cells and buttons, a soft fade for #congrats). Wrap it in `@media (prefers-reduced-motion: no-preference)`.

## Layout

One calm column, centred, phone first.

- Font: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`; base size 16px, line-height 1.45. The page title (h1 "Sudoku") is 26px, weight 700, left aligned.
- Order from top: header with title and `.site-nav`, then `#game` (level buttons, `#grid`, `#msg`, action row, `#pad`, `#congrats`), then `#how-to-play`, then `#stats`.
- `#game` is at most 520px wide, centred, with no horizontal padding. Everything inside `#game` except `#grid` has `padding-inline: 12px`. The header, `#how-to-play` and `#stats` use `padding-inline: 12px` and `max-width: 520px; margin-inline: auto`.
- Vertical spacing: 12px between blocks inside `#game`, 24px between sections. On a 360 x 640 phone the grid, pad and action row should be reachable with little or no scrolling.
- `.site-nav`: a row of links to `#game`, `#how-to-play` and `#stats`, each a `.j2-btn` at least 44px tall and wide, wrapping with `flex-wrap: wrap; gap: 8px`.
- `#how-to-play` and `#stats` are panels: --surface background, 12px radius, 16px padding, 1px --grid-line border. `#stats` shows games completed (`#games-count`) and the streak (`#streak-count`) as two large friendly numbers (28px, weight 700) with small labels.
- Desktop (min-width 900px): the same single column, centred, with the grid capped at 504px. No extra columns, no side clutter.
- No horizontal overflow at 360px and 1280px. Images are not used. Long text wraps (`overflow-wrap: anywhere` on #msg and panels).

## Touch

- Large tap targets and readable numbers: grid cells 40px or more at 360px, every button 44px or more in both directions, gaps of at least 8px between buttons.
- Set `touch-action: manipulation` on `body`, `.cell`, and every `.j2-btn` so there is no double-tap zoom delay.
- No text selection on the board and controls: `user-select: none; -webkit-user-select: none;` on `.cell`, `#pad`, `.j2-btn` and `#grid`.
- Set `-webkit-tap-highlight-color: transparent` on cells and buttons (the selected style gives the feedback instead).
- Cells are `button` elements or elements with `role="button"` and `tabindex`, so they work with keyboard and touch. Give the grid `role="grid"` or an `aria-label` of "Sudoku board" (assumption).
- Viewport: `<meta name="viewport" content="width=device-width, initial-scale=1">`. Do not disable user zoom.
- Pressed state: buttons darken slightly on `:active`; no hover-only effects, because phones have no hover.
