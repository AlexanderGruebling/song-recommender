<script setup>
import { ref, onMounted } from "vue";
import { api } from "../api";
import { formatDate } from "../format";

const charts = ref([]);
const loading = ref(true);
const error = ref(null);
const refreshing = ref(false);
const refreshResult = ref(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    charts.value = await api.charts();
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  refreshing.value = true;
  refreshResult.value = null;
  try {
    refreshResult.value = await api.refreshCharts();
    await load();
  } catch (err) {
    error.value = err.message;
  } finally {
    refreshing.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="row">
      <h1>FM4 Top 40 Charts</h1>
      <div class="spacer"></div>
      <button class="btn primary small" :disabled="refreshing" @click="refresh">
        {{ refreshing ? "Refreshing…" : "Refresh charts" }}
      </button>
    </div>
    <p class="subtitle">Discovered FM4 Top 40 charts, newest first.</p>

    <div v-if="refreshResult" class="msg success">
      Refresh: {{ refreshResult.imported }} new, {{ refreshResult.skipped }} already known,
      {{ refreshResult.errors }} failed.
    </div>
    <div v-if="error" class="msg error">{{ error }}</div>
    <div v-if="loading" class="empty-state"><span class="spinner"></span> Loading…</div>

    <ul v-else-if="charts.length" class="chart-list">
      <li v-for="chart in charts" :key="chart.id">
        <router-link :to="`/charts/${chart.id}`" class="chart-card">
          <div class="date">{{ formatDate(chart.chart_date) }}</div>
          <div class="chart-title">{{ chart.title }}</div>
          <div class="meta">
            <span>{{ chart.entry_count }} songs</span>
            <span>{{ chart.downloads_completed }} downloaded</span>
          </div>
        </router-link>
      </li>
    </ul>
    <div v-else class="empty-state">
      No charts yet. Click “Refresh charts” to import the latest FM4 Top 40.
    </div>
  </div>
</template>