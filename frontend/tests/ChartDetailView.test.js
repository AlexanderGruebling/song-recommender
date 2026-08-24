import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises, RouterLinkStub } from "@vue/test-utils";
import ChartDetailView from "../src/views/ChartDetailView.vue";

const chart = {
  id: 7,
  chart_date: "2026-07-25",
  title: "FM4 Top 40 vom 25.7.2026",
  entry_count: 40,
  downloads_completed: 5,
  entries: [
    { id: 10, rank: 1, artist: "Nia Archives", title: "There Goes Ma Head", movement: "up", download_status: "completed", download_progress: 100 },
    { id: 11, rank: 2, artist: "Some Artist", title: "Some Song", movement: "new", download_status: null, download_progress: 0 },
  ],
};

vi.mock("../src/api.js", () => ({
  api: { chart: vi.fn() },
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "7" } }),
}));

import { api } from "../src/api.js";

function mountView() {
  return mount(ChartDetailView, {
    global: { stubs: { "router-link": RouterLinkStub } },
  });
}

describe("ChartDetailView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  it("renders the chart header and every entry", async () => {
    api.chart.mockResolvedValue(chart);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find("h1").text()).toMatch(/2026/);
    expect(wrapper.findAll("tbody tr")).toHaveLength(2);
    expect(wrapper.text()).toContain("There Goes Ma Head");
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("marks new and up-movements", async () => {
    api.chart.mockResolvedValue(chart);
    const wrapper = mountView();
    await flushPromises();
    const movements = wrapper.findAll(".movement").map((n) => n.text().trim());
    expect(movements).toEqual(["↑", "NEW"]);
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("shows an error message when the chart cannot be loaded", async () => {
    api.chart.mockRejectedValue(new Error("not found"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.text()).toContain("not found");
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("does not poll while no download is active", async () => {
    api.chart.mockResolvedValue(chart);
    const wrapper = mountView();
    await flushPromises();
    vi.advanceTimersByTime(9000);
    await flushPromises();
    expect(api.chart).toHaveBeenCalledTimes(1);
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("polls while a download is active and stops when settled", async () => {
    const activeChart = {
      ...chart,
      entries: [
        { id: 10, rank: 1, artist: "A", title: "T", movement: null, download_status: "downloading", download_progress: 40 },
      ],
    };
    api.chart
      .mockResolvedValueOnce(activeChart)
      .mockResolvedValue(chart);
    const wrapper = mountView();
    await flushPromises();

    vi.advanceTimersByTime(3000);
    await flushPromises();
    expect(api.chart).toHaveBeenCalledTimes(2);

    // Settled chart returned on the second poll -> polling stops.
    vi.advanceTimersByTime(9000);
    await flushPromises();
    expect(api.chart).toHaveBeenCalledTimes(2);
    wrapper.unmount();
    vi.useRealTimers();
  });
});