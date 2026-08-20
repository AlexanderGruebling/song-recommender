import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises, RouterLinkStub } from "@vue/test-utils";
import ChartsView from "../src/views/ChartsView.vue";

const charts = [
  { id: 1, chart_date: "2026-07-25", title: "FM4 Top 40 vom 25.7.2026", entry_count: 40, downloads_completed: 12 },
  { id: 2, chart_date: "2026-07-18", title: "FM4 Top 40 vom 18.7.2026", entry_count: 40, downloads_completed: 0 },
];

vi.mock("../src/api.js", () => ({
  api: {
    charts: vi.fn(),
    refreshCharts: vi.fn(),
  },
}));

import { api } from "../src/api.js";

function mountView() {
  return mount(ChartsView, {
    global: { stubs: { "router-link": RouterLinkStub } },
  });
}

describe("ChartsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading state before the request resolves", () => {
    api.charts.mockReturnValue(new Promise(() => {}));
    const wrapper = mountView();
    expect(wrapper.text()).toContain("Loading");
    wrapper.unmount();
  });

  it("renders discovered charts after loading", async () => {
    api.charts.mockResolvedValue(charts);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.findAll(".chart-card")).toHaveLength(2);
    expect(wrapper.text()).toContain("FM4 Top 40 vom 25.7.2026");
    expect(wrapper.text()).toContain("40 songs");
    expect(wrapper.text()).toContain("12 downloaded");
    wrapper.unmount();
  });

  it("shows an error message when loading fails", async () => {
    api.charts.mockRejectedValue(new Error("boom"));
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.text()).toContain("boom");
    wrapper.unmount();
  });

  it("shows the empty state when there are no charts", async () => {
    api.charts.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.text()).toContain("No charts yet");
    wrapper.unmount();
  });

  it("triggers a refresh and reloads the list", async () => {
    api.charts.mockResolvedValue([]);
    api.refreshCharts.mockResolvedValue({ imported: 3, skipped: 0, errors: 0 });
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find("button").trigger("click");
    await flushPromises();

    expect(api.refreshCharts).toHaveBeenCalledOnce();
    expect(api.charts).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("3 new");
    wrapper.unmount();
  });
});