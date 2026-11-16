<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/domains')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>
<template>
  <div>
    <h2>主题域</h2>
    <p class="lead">每个主题域对应一套贴源夹具与业务键，分层建设围绕主题域推进。</p>
    <p v-if="err" class="err">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr><th>编号</th><th>名称</th><th>业务键</th><th>夹具文件</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="d in rows" :key="d.id">
            <td>{{ d.id }}</td>
            <td>{{ d.name }}</td>
            <td>{{ d.biz_key }}</td>
            <td>{{ d.fixture_file }}</td>
            <td>{{ d.description }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
