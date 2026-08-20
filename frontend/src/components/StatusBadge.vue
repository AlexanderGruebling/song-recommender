<script setup>
const props = defineProps({
  status: { type: String, default: null },
  progress: { type: Number, default: 0 },
});

const labels = {
  queued: "Queued",
  downloading: "Downloading",
  completed: "Downloaded",
  failed: "Failed",
};
</script>

<template>
  <span v-if="status" class="badge" :class="status">
    <span v-if="status === 'downloading'" class="spinner"></span>
    {{ labels[status] || status }}
    <span v-if="status === 'downloading'">· {{ Math.round(progress) }}%</span>
  </span>
  <span v-else class="badge none">Not downloaded</span>
</template>