<script setup lang="ts">
/**
 * Stage 11 (11d): VS Code-style file/folder type icon — locally controlled
 * SVG, currentColor only, fixed 16px box so row height never changes
 * (03 §7, D11-08). Purely decorative: aria-hidden, semantics live on the row
 * label / aria-expanded.
 */
import { computed } from "vue";
import { fileIconKind } from "./iconKind";

const props = defineProps<{
  name: string;
  dir: boolean;
  expanded?: boolean;
}>();

interface IconSpec {
  paths: string[];
  /** Small filled circles (knobs, image sun): [cx, cy, r]. */
  dots?: Array<[number, number, number]>;
  /** Two-letter language tag rendered inside the page (TS/JS/PY/RS). */
  text?: string;
}

const DIR_CLOSED: IconSpec = {
  paths: ["M1.5 3.5h4.5l1.5 2h7v7h-13z"],
};
const DIR_OPEN: IconSpec = {
  paths: ["M1.5 3.5h4.5l1.5 2h7l-1.6 7H1.5z", "M1.5 5.5h13"],
};

const FILE_KINDS: Record<string, IconSpec> = {
  "generic-file": { paths: ["M4 1.5h5l3 3v10H4z", "M9 1.5v3h3"] },
  typescript: { paths: ["M4 1.5h5l3 3v10H4z"], text: "TS" },
  javascript: { paths: ["M4 1.5h5l3 3v10H4z"], text: "JS" },
  python: { paths: ["M4 1.5h5l3 3v10H4z"], text: "PY" },
  rust: { paths: ["M4 1.5h5l3 3v10H4z"], text: "RS" },
  json: {
    paths: [
      "M6 3.5c-1.2 0-1.2 1-1.2 2v1c0 .8-.4 1.2-1.3 1.5.9.3 1.3.7 1.3 1.5v1c0 1 0 2 1.2 2",
      "M10 3.5c1.2 0 1.2 1 1.2 2v1c0 .8.4 1.2 1.3 1.5-.9.3-1.3.7-1.3 1.5v1c0 1 0 2-1.2 2",
    ],
  },
  markdown: {
    paths: ["M1.5 4h13v8h-13z", "M3.5 10V6l2 2.5L7.5 6v4", "M9.5 6l2.5 2.5V6", "M12 8.5V10"],
  },
  image: {
    paths: ["M1.5 3.5h13v9h-13z", "M3 11l3-3.5 2 2 2.5-3L13.5 11"],
    dots: [[5, 6, 0.9]],
  },
  archive: {
    paths: ["M2.5 6.5v8h11v-8", "M1.5 3.5h13v3h-13z", "M8 7.5v1", "M8 9.5v1", "M8 11.5v1.5"],
  },
  config: {
    paths: ["M2.5 4.5h11", "M2.5 8h11", "M2.5 11.5h11"],
    dots: [
      [5.5, 4.5, 1.2],
      [10.5, 8, 1.2],
      [7, 11.5, 1.2],
    ],
  },
};

const spec = computed<IconSpec>(() => {
  if (props.dir) return props.expanded ? DIR_OPEN : DIR_CLOSED;
  return FILE_KINDS[fileIconKind(props.name)] ?? FILE_KINDS["generic-file"];
});
</script>

<template>
  <svg
    class="type-icon"
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    stroke-width="1.2"
    stroke-linejoin="round"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path v-for="(d, i) in spec.paths" :key="i" :d="d" />
    <circle v-for="(dot, i) in spec.dots ?? []" :key="`d${i}`" :cx="dot[0]" :cy="dot[1]" :r="dot[2]" fill="currentColor" stroke="none" />
    <text v-if="spec.text" x="8" y="12.6" font-size="6" text-anchor="middle" fill="currentColor" stroke="none" style="font-family: var(--font-mono)">
      {{ spec.text }}
    </text>
  </svg>
</template>
