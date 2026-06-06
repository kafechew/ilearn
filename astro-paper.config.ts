import { defineAstroPaperConfig } from "./src/types/config";

export default defineAstroPaperConfig({
  site: {
    url: "https://www.kheai.com",
    title: "KheAi",
    description: "An engineering blueprint to reclaim your time, attention, and biology in a high-entropy world. Learn the system architecture of the Minimal Path to Freedom (MPF).",
    author: "Kai",
    profile: "https://www.linkedin.com/in/kheai/",
    ogImage: "kheai-mpf.png",
    lang: "en",
    timezone: "Asia/Kuala_Lumpur",
    dir: "ltr",
  },
  posts: {
    perPage: 4,
    perIndex: 4,
    scheduledPostMargin: 15 * 60 * 1000,
  },
  features: {
    lightAndDarkMode: true,
    dynamicOgImage: true,
    showArchives: true,
    showBackButton: true,
    editPost: {
      enabled: true,
      url: "https://github.com/kafechew/ilearn/edit/main/",
    },
    search: "pagefind",
  },
  socials: [
    { name: "github",   url: "https://github.com/kafechew/ilearn" },
    { name: "x",        url: "https://x.com/kafechew" },
    { name: "linkedin", url: "https://www.linkedin.com/in/kheai/" },
    { name: "mail",     url: "mailto:kheaichew@gmail.com" },
  ],
  shareLinks: [
    { name: "whatsapp", url: "https://wa.me/?text=" },
    { name: "facebook", url: "https://www.facebook.com/sharer.php?u=" },
    { name: "x",        url: "https://x.com/intent/post?url=" },
    { name: "telegram", url: "https://t.me/share/url?url=" },
    { name: "pinterest", url: "https://pinterest.com/pin/create/button/?url=" },
    { name: "mail",     url: "mailto:?subject=See%20this%20post&body=" },
  ],
});