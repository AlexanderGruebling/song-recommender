import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/", name: "charts", component: () => import("./views/ChartsView.vue") },
  { path: "/charts/:id", name: "chart", component: () => import("./views/ChartDetailView.vue") },
  { path: "/songs/:id", name: "song", component: () => import("./views/SongView.vue") },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});