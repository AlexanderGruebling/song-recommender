import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount, flushPromises, RouterLinkStub } from "@vue/test-utils";
import SongView from "../src/views/SongView.vue";

const song = { id: 10, chart_id: 7, artist: "Nia Archives", title: "There Goes Ma Head" };

const candidates = [
  {
    id: 100, rank: 1, video_id: "abc", video_title: "Nia Archives - There Goes Ma Head (Official)",
    channel: "Nia Archives", thumbnail_url: "https://img/t1",
    duration_seconds: 225, video_url: "https://www.youtube.com/watch?v=abc",
  },
  {
    id: 101, rank: 2, video_id: "def", video_title: "There Goes Ma Head (Lyrics)",
    channel: "Lyrics", thumbnail_url: null,
    duration_seconds: 226, video_url: "https://www.youtube.com/watch?v=def",
  },
];

vi.mock("../src/api.js", () => ({
  api: {
    song: vi.fn(),
    youtube: vi.fn(),
    searchYoutube: vi.fn(),
    download: vi.fn(),
    getDownload: vi.fn(),
  },
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "10" } }),
}));

import { api } from "../src/api.js";

function mountView() {
  return mount(SongView, {
    global: { stubs: { "router-link": RouterLinkStub } },
  });
}

describe("SongView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  it("renders the song heading", async () => {
    api.song.mockResolvedValue(song);
    api.youtube.mockResolvedValue([]);
    api.searchYoutube.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find("h1").text()).toBe("There Goes Ma Head");
    expect(wrapper.text()).toContain("Nia Archives");
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("displays ranked YouTube candidates", async () => {
    api.song.mockResolvedValue(song);
    api.youtube.mockResolvedValue(candidates);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.findAll(".candidate")).toHaveLength(2);
    expect(wrapper.text()).toContain("Nia Archives - There Goes Ma Head (Official)");
    expect(wrapper.text()).toContain("3:45");
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("selects a candidate and starts a download", async () => {
    api.song.mockResolvedValue(song);
    api.youtube.mockResolvedValue(candidates);
    api.download.mockResolvedValue({ id: 900, status: "queued", progress: 0 });
    const wrapper = mountView();
    await flushPromises();

    await wrapper.findAll(".candidate")[1].trigger("click");
    const buttons = wrapper.findAll(".c-download button");
    expect(buttons[1].element.disabled).toBe(false);

    await buttons[1].trigger("click");
    await flushPromises();
    expect(api.download).toHaveBeenCalledWith("10", 101);
    expect(wrapper.text()).toContain("Queued for download");
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("runs a manual search when no candidates are cached", async () => {
    api.song.mockResolvedValue(song);
    api.youtube.mockResolvedValue([]);
    api.searchYoutube.mockResolvedValue(candidates);
    const wrapper = mountView();
    await flushPromises();
    expect(api.searchYoutube).toHaveBeenCalledWith("10");
    expect(wrapper.findAll(".candidate")).toHaveLength(2);
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("shows a failure message when the download fails", async () => {
    api.song.mockResolvedValue(song);
    api.youtube.mockResolvedValue(candidates);
    api.download.mockRejectedValue(new Error("quota exhausted"));
    const wrapper = mountView();
    await flushPromises();

    await wrapper.findAll(".candidate")[0].trigger("click");
    await wrapper.find(".c-download button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("quota exhausted");
    wrapper.unmount();
    vi.useRealTimers();
  });
});