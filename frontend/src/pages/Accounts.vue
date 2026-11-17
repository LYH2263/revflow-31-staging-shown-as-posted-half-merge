<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const merges = ref([])
const proof = ref(null)
const err = ref('')
const busy = ref(false)

onMounted(async () => {
  try {
    const [accountRows, mergeRows] = await Promise.all([
      getJson('/api/accounts'),
      getJson('/api/balance-merges'),
    ])
    rows.value = accountRows
    merges.value = mergeRows
  } catch (e) {
    err.value = String(e.message || e)
  }
})

const totals = computed(() => {
  const posted = rows.value.reduce((s, a) => s + Number(a.posted_cents || 0), 0)
  const staging = rows.value.reduce((s, a) => s + Number(a.staging_cents || 0), 0)
  return { posted, staging, total: posted + staging }
})

const stagedCount = computed(() => rows.value.filter((a) => a.staging_cents !== 0).length)

async function openProof(id) {
  busy.value = true
  err.value = ''
  try {
    const m = await getJson(`/api/balance-merges/${id}`)
    proof.value = m.证明
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

function yuan(cents) {
  return (Number(cents || 0) / 100).toFixed(2)
}
</script>

<template>
  <div>
    <h1>账户</h1>
    <p class="lead">
      同一账户两套余额<strong>分列</strong>：对外口径只认「已对外余额」；
      配平暂存是归并净额的待合并缓冲，不冒充已对外；合计仅供内部核对。
    </p>
    <p v-if="err" class="msg">{{ err }}</p>

    <div class="stats">
      <div class="stat">
        <div class="k">已对外余额（元）· 对外口径</div>
        <div class="v">{{ yuan(totals.posted) }}</div>
      </div>
      <div class="stat">
        <div class="k">配平暂存（元）· 待合并 {{ stagedCount }} 户</div>
        <div class="v">{{ yuan(totals.staging) }}</div>
      </div>
      <div class="stat">
        <div class="k">内部合计（元）· 不对外</div>
        <div class="v">{{ yuan(totals.total) }}</div>
      </div>
    </div>

    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>编码</th>
            <th>名称</th>
            <th>币种</th>
            <th>已对外余额（元）</th>
            <th>配平暂存（元）</th>
            <th>内部合计（元）</th>
            <th>最近归并</th>
            <th>最近合并</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in rows" :key="a.id">
            <td>{{ a.code }}</td>
            <td>{{ a.name }}</td>
            <td>{{ a.currency }}</td>
            <td><span class="amount-cell posted">{{ yuan(a.posted_cents) }}</span></td>
            <td>
              <span class="amount-cell" :class="a.staging_cents ? 'staged' : 'zero'">
                {{ yuan(a.staging_cents) }}
              </span>
            </td>
            <td class="amount-cell muted">{{ yuan(a.total_cents) }}</td>
            <td>{{ a.last_settle_run_id || '—' }}</td>
            <td>{{ a.last_merge_id || '—' }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="8">尚无账户</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>合并证明</h2>
      <p class="note-strip">
        按合并批次查询的只读证明：记录每批「合并前已对外/暂存 → 合并后已对外/暂存」，
        与账户双列同源派生，合并后暂存恒为 0。
      </p>
      <table>
        <thead>
          <tr>
            <th>批次#</th><th>状态</th><th>合并前已对外（元）</th><th>合并前暂存（元）</th>
            <th>合并后已对外（元）</th><th>合并后暂存（元）</th><th>证明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in merges" :key="m.id">
            <td>{{ m.id }}</td>
            <td>{{ m.status }}</td>
            <td>{{ yuan(m.posted_before_cents) }}</td>
            <td>{{ yuan(m.staging_before_cents) }}</td>
            <td>{{ yuan(m.posted_after_cents) }}</td>
            <td>{{ yuan(m.staging_after_cents) }}</td>
            <td>
              <button class="btn secondary" :disabled="busy" @click="openProof(m.id)">查看证明</button>
            </td>
          </tr>
          <tr v-if="!merges.length"><td colspan="7">尚无合并批次</td></tr>
        </tbody>
      </table>

      <div v-if="proof" class="proof-box">
        <h3>批次 #{{ proof.合并批次id }} 合并证明 · 对外口径：{{ proof.对外口径 }}</h3>
        <p class="note-strip">
          合并前 已对外 ¥{{ yuan(proof.合并前已对外分) }} + 暂存 ¥{{ yuan(proof.合并前暂存分) }}
          → 合并后 已对外 ¥{{ yuan(proof.合并后已对外分) }}，暂存 ¥{{ yuan(proof.合并后暂存分) }}（清零）
        </p>
        <table>
          <thead>
            <tr>
              <th>账户</th><th>合并前已对外（元）</th><th>合并前暂存（元）</th>
              <th>合并后已对外（元）</th><th>合并后暂存（元）</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="line in proof.分户" :key="line.account_id">
              <td>{{ line.account_code }}</td>
              <td>{{ yuan(line.合并前已对外分) }}</td>
              <td>{{ yuan(line.合并前暂存分) }}</td>
              <td>{{ yuan(line.合并后已对外分) }}</td>
              <td><span class="amount-cell zero">{{ yuan(line.合并后暂存分) }}</span></td>
            </tr>
            <tr v-if="!proof.分户.length"><td colspan="5">本批无待合并暂存（空合并）</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <p class="note-strip">
      已对外与配平暂存分列展示、同源派生；显式合并由归并台触发，合并与清零同事务同成败。
    </p>
  </div>
</template>
