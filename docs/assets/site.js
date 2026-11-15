const results = document.querySelector("[data-results]");
const loadDemo = document.querySelector("[data-load-demo]");
const frames = [...document.querySelectorAll("[data-frame]")];
const points = [...document.querySelectorAll("[data-point]")];
const historyDialog = document.querySelector("[data-history-dialog]");
const historyList = document.querySelector("[data-history-list]");
const historyKey = "spherex-static-history-v1";
let currentFrame = 0;
let timer = null;

function showFrame(index) {
  currentFrame = (index + frames.length) % frames.length;
  frames.forEach((frame, frameIndex) => frame.classList.toggle("active", frameIndex === currentFrame));
  points.forEach((point, pointIndex) => {
    point.classList.toggle("active", pointIndex === currentFrame);
    point.setAttribute("aria-current", pointIndex === currentFrame ? "true" : "false");
  });
}

function stopPlayback() {
  if (timer) window.clearInterval(timer);
  timer = null;
}

document.querySelector("[data-prev]").addEventListener("click", () => { stopPlayback(); showFrame(currentFrame - 1); });
document.querySelector("[data-next]").addEventListener("click", () => { stopPlayback(); showFrame(currentFrame + 1); });
document.querySelector("[data-play]").addEventListener("click", () => {
  stopPlayback();
  timer = window.setInterval(() => showFrame(currentFrame + 1), 950);
});
document.querySelector("[data-pause]").addEventListener("click", stopPlayback);
points.forEach((point) => point.addEventListener("click", () => { stopPlayback(); showFrame(Number(point.dataset.point)); }));

function readHistory() {
  try { return JSON.parse(window.localStorage.getItem(historyKey)) || []; }
  catch (error) { return []; }
}

function writeHistory(entries) {
  try { window.localStorage.setItem(historyKey, JSON.stringify(entries.slice(0, 50))); }
  catch (error) { /* Browser storage is optional. */ }
}

function addHistoryEntry() {
  const entries = readHistory();
  entries.unshift({
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    name: "Offline SPHEREx D5 comparison",
    createdAt: new Date().toISOString(),
  });
  writeHistory(entries);
}

function actionLink(label, href) {
  const link = document.createElement("a");
  link.className = "button quiet";
  link.textContent = label;
  link.href = href;
  link.download = "";
  return link;
}

function renderHistory() {
  const entries = readHistory();
  historyList.replaceChildren();
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.textContent = "No offline demo has been opened in this browser yet.";
    historyList.append(empty);
    return;
  }
  entries.forEach((entry) => {
    const article = document.createElement("article");
    article.className = "history-entry";
    const heading = document.createElement("div");
    heading.className = "history-heading";
    const name = document.createElement("strong");
    name.textContent = entry.name;
    const time = document.createElement("time");
    time.dateTime = entry.createdAt;
    time.textContent = new Intl.DateTimeFormat("el-GR", {dateStyle: "short", timeStyle: "medium"}).format(new Date(entry.createdAt));
    heading.append(name, time);
    const description = document.createElement("p");
    description.textContent = "RA 133.805° · Dec −8.770° · 06/05/2025 → 14/05/2026";
    const actions = document.createElement("div");
    actions.className = "history-actions";
    actions.append(
      actionLink("PDF", "assets/downloads/spherex-analysis-report.pdf"),
      actionLink("JSON", "assets/data/scientific-summary.json"),
      actionLink("GIF", "assets/downloads/spherex-timelapse.gif"),
    );
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "quiet";
    rename.textContent = "Rename";
    rename.addEventListener("click", () => {
      const nextName = window.prompt("Choose a name for this analysis:", entry.name)?.trim();
      if (!nextName) return;
      entry.name = nextName.slice(0, 80);
      writeHistory(entries);
      renderHistory();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "history-delete";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => {
      if (!window.confirm("Remove this entry from this browser's history?")) return;
      writeHistory(entries.filter((item) => item.id !== entry.id));
      renderHistory();
    });
    actions.append(rename, remove);
    article.append(heading, description, actions);
    historyList.append(article);
  });
}

loadDemo.addEventListener("click", () => {
  results.hidden = false;
  addHistoryEntry();
  showFrame(0);
  results.focus({preventScroll: true});
  results.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
});

document.querySelector("[data-history-open]").addEventListener("click", () => {
  renderHistory();
  historyDialog.showModal();
});
document.querySelector("[data-history-close]").addEventListener("click", () => historyDialog.close());
historyDialog.addEventListener("click", (event) => { if (event.target === historyDialog) historyDialog.close(); });

document.querySelector("[data-text-size]").addEventListener("click", (event) => {
  const enabled = document.body.classList.toggle("large-text");
  event.currentTarget.setAttribute("aria-pressed", String(enabled));
  event.currentTarget.textContent = enabled ? "Normal text" : "Larger text";
});

showFrame(0);
