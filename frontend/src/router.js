import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from './pages/Dashboard.vue'
import Domains from './pages/Domains.vue'
import LayerPaste from './pages/LayerPaste.vue'
import LayerDetail from './pages/LayerDetail.vue'
import LayerSummary from './pages/LayerSummary.vue'
import Jobs from './pages/Jobs.vue'
import Reconcile from './pages/Reconcile.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Dashboard },
    { path: '/domains', component: Domains },
    { path: '/paste', component: LayerPaste },
    { path: '/detail', component: LayerDetail },
    { path: '/summary', component: LayerSummary },
    { path: '/jobs', component: Jobs },
    { path: '/reconcile', component: Reconcile },
  ],
})
