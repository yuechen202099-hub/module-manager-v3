import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { installElementPlus } from './plugins/element-plus'
import router from './router'
import './styles/index.css'

document.documentElement.dataset.moduleManagerBuildVersion =
  __MODULE_MANAGER_VUE_ENTRY_VERSION_MARKER__

const app = createApp(App)
app.use(createPinia()).use(router)
installElementPlus(app)
app.mount('#app')
