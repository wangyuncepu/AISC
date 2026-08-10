import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { i18n } from "./i18n";
import { applyTheme } from "./theme";
import "./styles.css";

// G-04 (A-G04-2): resolve the SYSTEM preference synchronously before mount so
// the first frame is themed (the index.html inline script already painted the
// cached fixed mode). The settings watcher in App.vue applies the persisted
// mode once the settings file loads.
applyTheme(undefined);

createApp(App).use(createPinia()).use(i18n).mount("#app");
