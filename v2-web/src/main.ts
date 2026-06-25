import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { installElementPlus } from './plugins/element-plus'
import router from './router'
import './styles/index.css'

const app = createApp(App)
app.use(createPinia()).use(router)
installElementPlus(app)
app.mount('#app')
