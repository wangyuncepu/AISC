import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { i18n } from "./i18n";
import { applyTheme } from "./theme";
import { logUiEvent } from "./lib/ipc";
import "./styles.css";

// G-04 (A-G04-2): resolve the SYSTEM preference synchronously before mount so
// the first frame is themed (the index.html inline script already painted the
// cached fixed mode). The settings watcher in App.vue applies the persisted
// mode once the settings file loads.
applyTheme(undefined);

const app = createApp(App);

// Manual-test fix #1 hardening (2026-09-06): a render-function throw aborts
// the Vue patch mid-way and leaves the vdom permanently broken (the settings
// GROUP_KEY bug froze the whole UI this way). Surface every unhandled error on
// the shared aisc.log timeline so the next one is diagnosable from logs alone.
app.config.errorHandler = (err, _instance, info) => {
  const detail = (err instanceof Error ? `${err.name}: ${err.message}` : String(err)).slice(0, 200);
  void logUiEvent(`vue_error[${info}]`, "error", detail).catch(() => undefined);
};

app.use(createPinia()).use(i18n).mount("#app");
