<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/layers/明细')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>
<template>
  <div>
    <h2>明细层</h2>
    <p class="lead">清洗标准化后的明细；门店名为空或金额为负的贴源行不会进入本层。</p>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>编号</th><th>主题域</th><th>业务日</th><th>门店编码</th><th>门店名称</th>
            <th>品类</th><th>金额</th><th>件数</th><th>清洗标记</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.domain_id }}</td>
            <td>{{ r.biz_day }}</td>
            <td>{{ r.store_code }}</td>
            <td>{{ r.store_name }}</td>
            <td>{{ r.category }}</td>
            <td>{{ r.amount }}</td>
            <td>{{ r.qty }}</td>
            <td>{{ r.clean_flag }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="muted">明细层为空，请先在「分层任务」执行贴源到明细。</p>
    </div>
  </div>
</template>
