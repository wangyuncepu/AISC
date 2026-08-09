import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { i18n } from "./i18n";
import "./styles.css";

createApp(App).use(createPinia()).use(i18n).mount("#app");
