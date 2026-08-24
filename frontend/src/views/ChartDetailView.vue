<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";
import { formatDate } from "../format";
import StatusBadge from "../components/StatusBadge.vue";

const route = useRoute();
const chart = ref(null);
const error = ref(null);
const loading = ref(true);
let timer = null;

async function load() {
  try {
    chart.value = await api.chart(route.params.id);
    syncPolling();
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}

// Only poll while something is actually downloading; stop once settled.
function syncPolling() {
  const active =
    chart.value?.entries.some(
      (e) => e.download_status === "queued" || e.download_status === "downloading",
    ) ?? false;
  if (active && timer === null) {
    timer = setInterval(load, 3000);
  } else if (!active && timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

onMounted(load);
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer);
});
</script>

<template>
  <div>
    <nav class="breadcrumbs"><router-link to="/">Charts</router-link> · Chart</nav>
    <div v-if="loading" class="empty-state"><span class="spinner"></span> Loading…</div>
    <div v-else-if="error" class="msg error">{{ error }}</div>
    <div v-else-if="chart">
      <h1>{{ formatDate(chart.chart_date) }}</h1>
      <p class="subtitle">
        {{ chart.title }} — {{ chart.entry_count }} songs,
        {{ chart.downloads_completed }} downloaded
      </p>
      <div class="table-wrap">
        <table class="chart">
          <thead>
            <tr>
              <th>Rank</th>
              <th></th>
              <th>Artist</th>
              <th>Song</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in chart.entries" :key="entry.id">
              <td class="rank" :class="{ 'rank-1': entry.rank === 1 }">{{ entry.rank }}</td>
              <td>
                <span v-if="entry.movement" class="movement" :class="entry.movement">
                  {{
                    entry.movement === "new" ? "NEW" :
                    entry.movement === "up" ? "↑" :
                    entry.movement === "down" ? "↓" : "–"
                  }}
                </span>
              </td>
              <td class="song-artist">{{ entry.artist }}</td>
              <td>
                <router-link :to="`/songs/${entry.id}`" class="song-link">
                  <span class="song-title">{{ entry.title }}</span>
                </router-link>
              </td>
              <td>
                <StatusBadge :status="entry.download_status" :progress="entry.download_progress" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>