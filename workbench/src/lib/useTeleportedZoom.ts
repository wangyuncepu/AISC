/**
 * W2: the shared zoom answer for body-teleported surfaces. ToastHost,
 * CommandPalette, FloatingPane each re-applied ui.font_scale by hand after
 * the SAME bug ("teleport escapes App's zoom scope → the surface ignores
 * the UI 字号 setting") bit three times (手测 P2-1 r2 / P2-4 r1 / W1 r1#2).
 * One composable, one source — new teleports (menus, dialogs) start here.
 */
import { computed } from "vue";
import { useSettingsStore } from "../stores/settings";

export function useTeleportedZoom() {
  const settings = useSettingsStore();
  /** Same source App.vue's uiScale reads (G-01: immediate-effect). */
  const uiScale = computed(() => settings.doc?.ui.font_scale ?? 1);
  return { uiScale, zoomStyle: computed(() => ({ zoom: uiScale.value })) };
}
