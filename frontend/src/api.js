async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  charts: () => request("/api/charts"),
  chart: (id) => request(`/api/charts/${id}`),
  refreshCharts: () => request("/api/charts/refresh", { method: "POST" }),
  song: (id) => request(`/api/songs/${id}`),
  youtube: (id) => request(`/api/songs/${id}/youtube`),
  searchYoutube: (id) => request(`/api/songs/${id}/youtube/search`, { method: "POST" }),
  download: (id, youtubeResultId) =>
    request(`/api/songs/${id}/download`, {
      method: "POST",
      body: JSON.stringify({ youtube_result_id: youtubeResultId }),
    }),
  downloads: () => request("/api/downloads"),
  getDownload: (id) => request(`/api/downloads/${id}`),
};