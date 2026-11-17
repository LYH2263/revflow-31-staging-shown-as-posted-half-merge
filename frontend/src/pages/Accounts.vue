<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/accounts')
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

function yuan(cents) {
  return (Number(cents || 0) / 100).toFixed(2)
}
</script>

<template>
  <div>
    <h1>账户</h1>
    <p class="lead">
      同一账户两套余额分列：顶部「账户余额」取合计对外展示；分列数字仅供参考。
    </p>
    <p v-if="err" class="msg">{{ err }}</p>

    <div class="stats">
      <div class="stat">
        <div class="k">账户余额（元）</div>
        <div class="v">{{ yuan(totals.total) }}</div>
      </div>
      <div class="stat">
        <div class="k">配平暂存（元）</div>
        <div class="v">{{ yuan(totals.staging) }}</div>
      </div>
      <div class="stat">
        <div class="k">合计（元）· 待合并 {{ stagedCount }} 户</div>
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
            <th>合计（元）</th>
            <th>最近归并</th>
            <th>最近合并</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in rows" :key="a.id">
            <td>{{ a.code }}</td>
            <td>{{ a.name }}</td>
            <td>{{ a.currency }}</td>
            <td><span class="amount-cell posted">{{ yuan(Number(a.posted_cents||0)+Number(a.staging_cents||0)) }}</span></td>
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

    <p class="note-strip">
      账户页展示账户余额合计；合并由归并台触发。
    </p>
  </div>
</template>
