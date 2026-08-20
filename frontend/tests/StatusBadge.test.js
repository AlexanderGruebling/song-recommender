import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import StatusBadge from "../src/components/StatusBadge.vue";

describe("StatusBadge", () => {
  it("renders 'Not downloaded' when there is no status", () => {
    const wrapper = mount(StatusBadge, { props: { status: null } });
    expect(wrapper.text()).toContain("Not downloaded");
  });

  it("labels each download status", () => {
    const cases = [
      ["queued", "Queued"],
      ["downloading", "Downloading"],
      ["completed", "Downloaded"],
      ["failed", "Failed"],
    ];
    for (const [status, label] of cases) {
      const wrapper = mount(StatusBadge, { props: { status, progress: 42 } });
      expect(wrapper.text()).toContain(label);
      expect(wrapper.find(".badge").classes()).toContain(status);
    }
  });

  it("shows progress percentage while downloading", () => {
    const wrapper = mount(StatusBadge, { props: { status: "downloading", progress: 42.3 } });
    expect(wrapper.text()).toContain("42%");
  });
});