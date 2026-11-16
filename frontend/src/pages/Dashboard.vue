<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson } from '../api'

const data = ref(null)
const err = ref('')

onMounted(async () => {
  try {
    data.value = await getJson('/api/dashboard')
  } catch (e) {
    err.value = String(e.message || e)
  }
})

const meter = computed(() => {
  if (!data.value) return []
  const c = data.value.分层计数
  const max = Math.max(c.贴源层, c.明细层, c.汇总层, 1)
  return [
    { name: '贴源层', n: c.贴源层, pct: Math.round((c.贴源层 / max) * 100) },
    { name: '明细层', n: c.明细层, pct: Math.round((c.明细层 / max) * 100) },
    { name: '汇总层', n: c.汇总层, pct: Math.round((c.汇总层 / max) * 100) },
  ]
})
</script>
<template>
  <div>
    <p v-if="err" class="err">{{ err }}</p>
    <template v-if="data">
      <section class="hero">
        <div class="hero-copy">
          <div class="kicker">分层主链</div>
          <h2>筑层</h2>
          <p class="lead">贴源入仓，明细清洗，汇总落表，再做层间对账。三层条带对应建设进度，不和检道、变流同一套侧栏台面。</p>
        </div>
        <div class="layer-meter">
          <div class="row" v-for="m in meter" :key="m.name">
            <span>{{ m.name }}</span>
            <div class="bar"><i :style="{ width: m.pct + '%' }"></i></div>
            <span class="num">{{ m.n }}</span>
          </div>
        </div>
      </section>

      <div class="stat-strip">
        <div class="item"><div class="label">主题域</div><div class="value">{{ data.主题域数 }}</div></div>
        <div class="item"><div class="label">贴源层</div><div class="value">{{ data.分层计数.贴源层 }}</div></div>
        <div class="item"><div class="label">明细层</div><div class="value">{{ data.分层计数.明细层 }}</div></div>
        <div class="item"><div class="label">汇总层</div><div class="value">{{ data.分层计数.汇总层 }}</div></div>
      </div>

      <div class="panel">
        <h3>最近分层任务</h3>
        <table v-if="data.最近任务.length">
          <thead><tr><th>编号</th><th>步骤</th><th>状态</th><th>写入</th><th>剔除</th></tr></thead>
          <tbody>
            <tr v-for="j in data.最近任务" :key="j.编号">
              <td>{{ j.编号 }}</td><td>{{ j.步骤 }}</td><td>{{ j.状态 }}</td><td>{{ j.写入 }}</td><td>{{ j.剔除 }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">暂无任务，请到「分层任务」跑贴源到明细。</p>
      </div>

      <div class="panel">
        <h3>最近层间对账</h3>
        <table v-if="data.最近对账.length">
          <thead><tr><th>编号</th><th>状态</th><th>明细行数</th><th>汇总行数合计</th><th>差异键数</th></tr></thead>
          <tbody>
            <tr v-for="r in data.最近对账" :key="r.编号">
              <td>{{ r.编号 }}</td>
              <td :class="r.状态 === '一致' ? 'ok' : 'warn'">{{ r.状态 }}</td>
              <td>{{ r.明细行数 }}</td><td>{{ r.汇总行数合计 }}</td><td>{{ r.差异键数 }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">暂无对账报告。</p>
      </div>
    </template>
  </div>
</template>
