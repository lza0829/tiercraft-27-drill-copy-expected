<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/layers/汇总')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>
<template>
  <div>
    <h2>汇总层</h2>
    <p class="lead">按业务日与门店编码聚合后的汇总表。</p>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>编号</th><th>主题域</th><th>业务日</th><th>门店编码</th>
            <th>金额合计</th><th>件数合计</th><th>明细行数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.domain_id }}</td>
            <td>{{ r.biz_day }}</td>
            <td>{{ r.store_code }}</td>
            <td>{{ r.amount_sum }}</td>
            <td>{{ r.qty_sum }}</td>
            <td>{{ r.line_count }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="muted">汇总层为空，请先跑明细到汇总。</p>
    </div>
  </div>
</template>
