<script setup>
</script>
<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand-block">
        <div class="brand">筑层</div>
        <div class="brand-sub">数仓分层建设台</div>
      </div>
      <nav class="topnav">
        <router-link to="/">总览</router-link>
        <router-link to="/domains">主题域</router-link>
        <router-link to="/paste">贴源层</router-link>
        <router-link to="/detail">明细层</router-link>
        <router-link to="/summary">汇总层</router-link>
        <router-link to="/jobs">分层任务</router-link>
        <router-link to="/reconcile">层间对账</router-link>
      </nav>
    </header>
    <div class="stratum" aria-hidden="true">
      <span class="s1">贴源</span>
      <span class="s2">明细</span>
      <span class="s3">汇总</span>
    </div>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>
