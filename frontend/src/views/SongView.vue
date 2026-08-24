<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";
import { formatDuration } from "../format";

const route = useRoute();
const song = ref(null);
const candidates = ref([]);
const loading = ref(true);
const candidatesLoading = ref(true);
const searching = ref(false);
const downloading = ref(false);
const error = ref(null);
const download = ref(null);
let timer = null;

const hasCandidates = computed(() => candidates.value.length > 0);

function buttonLabel(candidate) {
  if (downloading.value) return "Starting…";
  if (candidate.download_status === "completed") return "Downloaded ✓";
  return "Download";
}

function buttonDisabled(candidate) {
  return downloading.value || candidate.download_status === "completed";
}

async function loadSong() {
  try {
    song.value = await api.song(route.params.id);
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}

async function loadCandidates() {
  try {
    candidates.value = await api.youtube(route.params.id);
    if (!hasCandidates.value) await runSearch();
  } catch (err) {
    /* non-fatal */
  } finally {
    candidatesLoading.value = false;
  }
}

async function runSearch() {
  searching.value = true;
  error.value = null;
  try {
    candidates.value = await api.searchYoutube(route.params.id);
  } catch (err) {
    error.value = `YouTube search failed: ${err.message}`;
  } finally {
    searching.value = false;
  }
}

async function startDownload(resultId) {
  downloading.value = true;
  error.value = null;
  try {
    download.value = await api.download(route.params.id, resultId);
    const candidate = candidates.value.find((c) => c.id === resultId);
    if (candidate && download.value.status !== "failed") {
      candidate.download_status = download.value.status;
    }
  } catch (err) {
    error.value = err.message;
  } finally {
    downloading.value = false;
  }
}

// Pick up a download that was started earlier (e.g. before navigating away)
// so its progress keeps showing on this page.
async function resumeActiveDownload() {
  if (download.value && !["queued", "downloading"].includes(download.value.status)) return;
  try {
    const all = await api.downloads();
    const latest = all.find((d) => d.entry_id === Number(route.params.id));
    if (
      latest &&
      (!download.value || ["queued", "downloading"].includes(latest.status))
    ) {
      download.value = latest;
    }
  } catch {
    /* non-fatal */
  }
}

async function pollDownload() {
  if (!download.value) return;
  if (["queued", "downloading"].includes(download.value.status)) {
    try {
      download.value = await api.getDownload(download.value.id);
      if (download.value.status === "completed") {
        for (const candidate of candidates.value) {
          if (candidate.video_id === download.value.video_id) {
            candidate.download_status = "completed";
          }
        }
      }
    } catch {
      /* ignore */
    }
  }
}

onMounted(async () => {
  timer = setInterval(pollDownload, 2000);
  await Promise.all([loadSong(), loadCandidates(), resumeActiveDownload()]);
});
onBeforeUnmount(() => clearInterval(timer));
</script>

<template>
  <div>
    <nav class="breadcrumbs">
      <router-link :to="`/charts/${song?.chart_id}`">Chart</router-link> · Song
    </nav>
    <div v-if="loading" class="empty-state"><span class="spinner"></span> Loading…</div>
    <div v-else-if="song">
      <div class="song-heading">
        <h1>{{ song.title }}</h1>
        <p class="subtitle artist">{{ song.artist }}</p>
      </div>

      <div v-if="error" class="msg error">{{ error }}</div>
      <div v-if="download" class="msg" :class="download.status">
        <template v-if="download.status === 'completed'">
          Downloaded to <code>{{ download.output_path }}</code>
        </template>
        <template v-else-if="download.status === 'failed'">
          Download failed: {{ download.error }}
        </template>
        <template v-else-if="download.status === 'downloading'">
          Downloading… {{ Math.round(download.progress) }}%
          <div class="progress" style="margin-top: 6px">
            <div class="progress-fill" :style="{ width: download.progress + '%' }"></div>
          </div>
        </template>
        <template v-else>Queued for download…</template>
      </div>

      <div class="row" style="margin-bottom: 16px">
        <h2>YouTube candidates</h2>
        <div class="spacer"></div>
        <button class="btn small" :disabled="searching" @click="runSearch">
          {{ searching ? "Searching…" : "Refresh search" }}
        </button>
      </div>

      <div v-if="candidatesLoading || searching" class="empty-state">
        <span class="spinner"></span> Searching YouTube…
      </div>
      <div v-else-if="!hasCandidates" class="empty-state">
        No candidates found. Try “Refresh search”.
      </div>
      <div v-else class="candidates">
        <div
          v-for="candidate in candidates"
          :key="candidate.id"
          class="candidate"
          :class="{ completed: candidate.download_status === 'completed' }"
        >
          <img
            v-if="candidate.thumbnail_url"
            class="thumb"
            :src="candidate.thumbnail_url"
            alt=""
            loading="lazy"
          />
          <div class="c-rank">{{ candidate.rank }}</div>
          <div class="c-info">
            <div class="c-title">{{ candidate.video_title }}</div>
            <div class="c-channel">{{ candidate.channel }}</div>
            <div class="c-meta">
              <span v-if="candidate.duration_seconds">{{ formatDuration(candidate.duration_seconds) }}</span>
              <a :href="candidate.video_url" target="_blank" rel="noopener">Open on YouTube</a>
            </div>
          </div>
          <div class="c-download">
            <span
              v-if="candidate.download_status && candidate.download_status !== 'completed'"
              class="badge small-badge"
              :class="candidate.download_status"
            >
              {{ candidate.download_status }}
            </span>
            <button
              class="btn primary small"
              :disabled="buttonDisabled(candidate)"
              @click.stop="startDownload(candidate.id)"
            >
              {{ buttonLabel(candidate) }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
