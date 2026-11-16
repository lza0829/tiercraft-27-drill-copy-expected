<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getJson, postJson } from '../api'

const domains = ref([])
const domainId = ref(1)
const reports = ref([])
const current = ref(null)
const active = ref(null)
const err = ref('')
const busy = ref(false)
const detailLoading = ref(false)
let ready = false

async function refresh() {
  reports.value = await getJson(`/api/reconcile?domain_id=${domainId.value}`)
  current.value = await getJson(`/api/reconcile/current?domain_id=${domainId.value}`)
  if (reports.value.length) {
    await openReport(reports.value[0].id)
  } else {
    active.value = null
  }
}

async function openReport(reportId) {
  detailLoading.value = true
  try {
    active.value = await getJson(`/api/reconcile/${reportId}`)
  } finally {
    detailLoading.value = false
  }
}

onMounted(async () => {
  try {
    domains.value = await getJson('/api/domains')
    if (domains.value.length) domainId.value = domains.value[0].id
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    ready = true
  }
})

watch(domainId, async () => {
  if (!ready) return
  err.value = ''
  try {
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function run() {
  busy.value = true
  err.value = ''
  try {
    const created = await postJson('/api/reconcile', { domain_id: domainId.value })
    await refresh()
    await openReport(created.report.id)
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function recompute() {
  const reportId = active.value?.report?.id
  if (!reportId) return
  busy.value = true
  err.value = ''
  try {
    await postJson(`/api/reconcile/${reportId}/recompute`, {})
    await refresh()
    await openReport(reportId)
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

const diffKeys = computed(() => active.value?.diff_list?.keys || [])
const runs = computed(() => active.value?.diff_list?.recompute_runs || [])
const hasDiff = computed(() => diffKeys.value.length > 0)

function runStatusClass(s) {
  return s === '成功' ? 'ok' : 'warn'
}
</script>

<template>
  <div>
    <h2>层间对账</h2>
    <p class="lead">
      按业务日与门店编码逐键核对明细与汇总，发现键不对齐或金额漂移时物化差异键清单；可按清单逐键重算，只改这些键的汇总。
    </p>

    <div class="toolbar">
      <label>
        主题域
        <select v-model.number="domainId">
          <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <button :disabled="busy" @click="run">生成对账报告</button>
    </div>

    <p v-if="err" class="err">{{ err }}</p>

    <div v-if="current" class="stat-strip">
      <div class="item">
        <div class="label">当前现场状态</div>
        <div class="value" :class="current.status === '一致' ? 'ok' : 'warn'">{{ current.status }}</div>
      </div>
      <div class="item">
        <div class="label">当前差异键</div>
        <div class="value">{{ current.diff_key_count }}</div>
      </div>
      <div class="item">
        <div class="label">仅明细有</div>
        <div class="value">{{ current.counts.detail_only_count }}</div>
      </div>
      <div class="item">
        <div class="label">仅汇总有</div>
        <div class="value">{{ current.counts.summary_only_count }}</div>
      </div>
    </div>

    <div class="panel">
      <h3>对账报告</h3>
      <table v-if="reports.length">
        <thead>
          <tr>
            <th>报告</th><th>状态</th><th>明细行数</th><th>汇总行数合计</th>
            <th>金额漂移</th><th>差异键数</th><th>生成时间</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in reports" :key="r.id" :class="{ selected: active?.report?.id === r.id }">
            <td>{{ r.id }}</td>
            <td :class="r.status === '一致' ? 'ok' : 'warn'">{{ r.status }}</td>
            <td>{{ r.detail.明细行数 }}</td>
            <td>{{ r.detail.汇总行数合计 }}</td>
            <td>{{ r.detail.金额漂移 }}</td>
            <td>{{ r.detail.差异键数 ?? 0 }}</td>
            <td>{{ r.created_at }}</td>
            <td>
              <button class="secondary small" :disabled="detailLoading" @click="openReport(r.id)">
                查看差异清单
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">暂无对账报告。</p>
    </div>

    <template v-if="active?.report">
      <div class="panel">
        <h3>
          报告 {{ active.report.id }} · 差异清单
          <span v-if="active.diff_list" class="muted">
            （清单 {{ active.diff_list.id }}，{{ active.diff_list.key_count }} 个键）
          </span>
        </h3>
        <table>
          <tbody>
            <tr><th>贴源行数</th><td>{{ active.report.detail.贴源行数 }}</td></tr>
            <tr><th>明细行数</th><td>{{ active.report.detail.明细行数 }}</td></tr>
            <tr><th>汇总行数合计</th><td>{{ active.report.detail.汇总行数合计 }}</td></tr>
            <tr><th>明细金额合计</th><td>{{ active.report.detail.明细金额合计 }}</td></tr>
            <tr><th>汇总金额合计</th><td>{{ active.report.detail.汇总金额合计 }}</td></tr>
            <tr><th>键对齐</th><td>{{ active.report.detail.键对齐 ? '是' : '否' }}</td></tr>
            <tr><th>金额漂移</th><td>{{ active.report.detail.金额漂移 }}</td></tr>
            <tr><th>差异键数</th><td>{{ active.report.detail.差异键数 ?? 0 }}</td></tr>
          </tbody>
        </table>

        <div v-if="active.diff_list" class="diff-meta">
          <span>仅明细有 {{ active.diff_list.detail_only_count }}</span>
          <span>仅汇总有 {{ active.diff_list.summary_only_count }}</span>
          <span>行数不符 {{ active.diff_list.count_mismatch_count }}</span>
          <span>金额漂移 {{ active.diff_list.amount_drift_count }}</span>
        </div>

        <table v-if="hasDiff">
          <thead>
            <tr>
              <th>业务日</th><th>门店编码</th><th>差异类型</th>
              <th>明细行数</th><th>明细金额</th>
              <th>汇总行数</th><th>汇总金额</th><th>金额差</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in diffKeys" :key="k.id">
              <td>{{ k.biz_day }}</td>
              <td>{{ k.store_code }}</td>
              <td class="warn">{{ k.diff_kind }}</td>
              <td>{{ k.detail_line_count }}</td>
              <td>{{ k.detail_amount }}</td>
              <td>{{ k.summary_line_count }}</td>
              <td>{{ k.summary_amount }}</td>
              <td>{{ k.amount_delta }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">该报告键与金额均对齐，无差异键可重算。</p>

        <div class="toolbar">
          <button :disabled="busy || !hasDiff" @click="recompute">按差异键重算</button>
          <span class="muted">
            逐键独立事务：只从明细重新聚合写回清单内这些键，其它键不动；某个键失败时只回滚该键，
            已成功的键保留，重算报告标记为「部分失败」并列出失败键。与「分层任务」里的全量明细到汇总分开。
          </span>
        </div>
      </div>

      <div class="panel" v-if="runs.length">
        <h3>按键重算记录</h3>
        <div v-for="run in runs" :key="run.id" class="run-block">
          <div class="run-head">
            <strong>重算 {{ run.id }}</strong>
            <span :class="runStatusClass(run.status)">{{ run.status }}</span>
            <span class="muted">
              关联差异清单 {{ run.diff_list_id }} · {{ run.scope }} · {{ run.commit_mode }} ·
              成功 {{ run.key_success }} / 失败 {{ run.key_failed }} / 共 {{ run.key_total }}
            </span>
          </div>
          <p class="muted">{{ run.message }}</p>
          <table>
            <thead>
              <tr>
                <th>业务日</th><th>门店编码</th><th>状态</th><th>动作</th>
                <th>重算前行数 / 金额</th><th>重算后行数 / 金额</th><th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in run.items" :key="it.id">
                <td>{{ it.biz_day }}</td>
                <td>{{ it.store_code }}</td>
                <td :class="it.status === '成功' ? 'ok' : 'warn'">{{ it.status }}</td>
                <td>{{ it.action }}</td>
                <td>
                  <template v-if="it.before_existed">
                    {{ it.before_line_count }} / {{ it.before_amount }}
                  </template>
                  <span v-else class="muted">无</span>
                </td>
                <td>
                  <template v-if="it.after_line_count !== null">
                    {{ it.after_line_count }} / {{ it.after_amount }}
                  </template>
                  <span v-else class="muted">无</span>
                </td>
                <td>{{ it.message }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <h3>现场状态</h3>
        <p v-if="active.current" class="muted">
          报告 {{ active.report.id }} 是生成时的快照；按当前明细与汇总现场派生的状态为
          <span :class="active.current.status === '一致' ? 'ok' : 'warn'">{{ active.current.status }}</span>，
          当前差异键 {{ active.current.diff_key_count }} 个。
        </p>
      </div>
    </template>
  </div>
</template>
