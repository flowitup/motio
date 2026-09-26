// Mọi chuỗi giao diện nằm ở đây để sau này thêm FR / EN.
const vi = {
  appName: "Motio",
  nav: { trends: "Tin hot", projects: "Dự án", settings: "Cài đặt" },
  engine: {
    starting: "Đang khởi động engine…",
    error: "Engine không chạy",
    retry: "Thử lại",
    openSettings: "Mở cài đặt",
    local: "Engine trên máy",
    remote: "Engine từ xa",
    ready: "Engine sẵn sàng",
  },
  trends: {
    title: "Tin hot",
    refresh: "Cập nhật tin",
    refreshing: "Đang cập nhật…",
    allSources: "Tất cả nguồn",
    produce: "Làm video",
    used: "Đã làm",
    empty: "Chưa có tin. Bấm “Cập nhật tin”.",
    lastRefresh: "Cập nhật lần cuối",
    refreshError: "Lỗi cập nhật",
    newScored: (n: number) => `${n} tin mới`,
  },
  projects: {
    title: "Dự án",
    empty: "Chưa có dự án nào. Vào Tin hot và bấm “Làm video”.",
    back: "Dự án",
    log: "Nhật ký",
    post: "Nội dung bài đăng",
    copy: "Copy",
    copied: "Đã copy",
    rerender: "Dựng lại",
    openFolder: "Mở thư mục",
    source: "Tin gốc",
    noVideo: "Chưa có video",
    status: { queued: "Chờ", running: "Đang làm", done: "Xong", failed: "Lỗi" } as Record<string, string>,
  },
  settings: {
    title: "Cài đặt",
    save: "Lưu",
    saved: "Đã lưu",
    engine: "Engine",
    engineMode: "Chế độ",
    engineUrl: "URL engine",
    engineToken: "Token",
    applyEngine: "Áp dụng",
    llm: "Viết kịch bản (LLM)",
    provider: "Nhà cung cấp",
    model: "Model",
    keys: "API keys",
    keyPlaceholder: "Nhập key mới để thay",
    voice: "Giọng đọc (ElevenLabs)",
    voiceAuto: "Tự chọn giọng tiếng Pháp",
    voiceNeedKey: "Nhập ElevenLabs API key để chọn giọng.",
    ttsModel: "Model ElevenLabs",
    whisper: "Model Whisper",
    content: "Nội dung",
    creditOnVideo: "Ghi nguồn trên video",
    creditInPost: "Ghi nguồn trong bài đăng",
    maxPerDay: "Số video tối đa mỗi ngày (0 = không giới hạn)",
    newsSources: "Nguồn tin (phân cách bằng dấu phẩy)",
    health: "Tình trạng engine",
    version: "Phiên bản",
    platform: "Hệ điều hành",
    notFound: "không tìm thấy",
    none: "không có",
    quotaLeft: "Còn lại hôm nay",
    unlimited: "không giới hạn",
    fromEnv: ".env",
    fromSettings: "đã lưu",
  },
  notify: {
    done: (t: string) => `Video xong: ${t}`,
    failed: (t: string) => `Dự án lỗi: ${t}`,
  },
  common: { error: "Lỗi", loading: "Đang tải…" },
  age: (ts?: number | null) => {
    if (!ts) return "—";
    const m = Math.floor((Date.now() / 1000 - ts) / 60);
    if (m < 1) return "vừa xong";
    if (m < 60) return `${m} phút trước`;
    if (m < 60 * 24) return `${Math.floor(m / 60)} giờ trước`;
    return `${Math.floor(m / 1440)} ngày trước`;
  },
};

export const t = vi;
