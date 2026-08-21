# SREs Design System

## Direction

Editorial clarity for a premium incident-response product. The interface feels like an impeccably edited technical report—light, spacious, and exact—rather than a dense developer console. Abstract artwork appears only at high-level moments such as the empty workspace, a report cover, or a decision frame; it is never wallpaper.

## Color

Use a restrained light palette in OKLCH.

- Canvas: a true off-white, nearly neutral—not cream or beige.
- Ink: deep blue-black for headings, data, and primary reading text.
- Surfaces: white and a subtly cool pale-gray layer for navigation, tables, and grouped evidence.
- Primary: a confident cobalt for deliberate action, current selection, and links.
- Accent: a quiet mineral blue for live/system context; use it sparingly.
- Semantic colors: green, amber, red, and blue remain reserved for explicit state and always pair with text and an icon/marker.

Avoid decorative gradients. When a screen benefits from atmosphere, use `frontend/public/art/sres-atmosphere.png`: a quiet, long-exposure landscape texture in mineral gray, moss, and muted earth. Treat it like Plane treats environmental photography—as a restrained frame for the product surface, never the subject itself.

## Typography

Use one high-quality sans-serif family for the interface, with a compact fixed type scale and confident, editorial weight contrast. Use a mono companion only for IDs, timestamps, queries, and raw evidence. Give page titles and report headings room to breathe; keep controls and metadata sober and compact.

## Layout

Use a light app shell with a quiet, cool-tinted navigation rail and a focused reading canvas. Establish hierarchy through alignment, section rhythm, typographic contrast, and disciplined rules—not card grids. Investigation work can be dense, but each page should have a clear lead question, a small number of anchored actions, and a logical evidence sequence.

At narrow widths, navigation becomes a concise horizontal strip; multi-column evidence becomes a readable single narrative. Tables retain their semantic structure and scroll horizontally only when necessary.

## Components

Components are precise and familiar: modest 8–12px radii, fine cool-gray rules, solid fills, and minimal shadows. Primary actions are cobalt; secondary actions are quiet outline or tonal controls. Panels use borders rather than decorative elevation. Status pills include a label and marker. Empty states teach the next action and may use the abstract art asset as a restrained editorial plate.

## Motion

Motion is brief (150–220ms) and communicates selection, streaming updates, or confirmation only. No entrance choreography or decorative ambient movement. Reduced-motion users receive instant state changes.
