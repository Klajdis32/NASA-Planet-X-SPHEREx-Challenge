const results = document.querySelector("[data-results]");
const loadDemo = document.querySelector("[data-load-demo]");
const frames = [...document.querySelectorAll("[data-frame]")];
const points = [...document.querySelectorAll("[data-point]")];
const historyDialog = document.querySelector("[data-history-dialog]");
const historyList = document.querySelector("[data-history-list]");
const historyKey = "spherex-static-history-v1";
const accessibilityMenu = document.querySelector("[data-accessibility-menu]");
let currentFrame = 0;
let timer = null;

if (accessibilityMenu) {
  const root = document.documentElement;
  const fontInputs = [...accessibilityMenu.querySelectorAll("[data-font-size]")];
  const contrastInput = accessibilityMenu.querySelector("[data-high-contrast]");
  const motionInput = accessibilityMenu.querySelector("[data-reduce-motion]");
  const spacingInput = accessibilityMenu.querySelector("[data-readable-spacing]");
  const resetButton = accessibilityMenu.querySelector("[data-accessibility-reset]");
  const status = accessibilityMenu.querySelector("[data-accessibility-status]");
  const storageKey = "spherex-static-accessibility";

  function readAccessibilityPreferences() {
    try { return JSON.parse(window.localStorage.getItem(storageKey)) || {}; }
    catch (error) { return {}; }
  }

  function applyAccessibilityPreferences(preferences, announce = false) {
    const fontSize = ["normal", "large", "xlarge"].includes(preferences.fontSize) ? preferences.fontSize : "normal";
    root.classList.toggle("a11y-font-large", fontSize === "large");
    root.classList.toggle("a11y-font-xlarge", fontSize === "xlarge");
    root.classList.toggle("a11y-high-contrast", Boolean(preferences.highContrast));
    root.classList.toggle("a11y-reduce-motion", Boolean(preferences.reduceMotion));
    root.classList.toggle("a11y-readable-spacing", Boolean(preferences.readableSpacing));
    fontInputs.forEach((input) => { input.checked = input.value === fontSize; });
    contrastInput.checked = Boolean(preferences.highContrast);
    motionInput.checked = Boolean(preferences.reduceMotion);
    spacingInput.checked = Boolean(preferences.readableSpacing);
    if (announce) status.textContent = "Accessibility settings updated.";
  }

  function updateAccessibilityPreferences() {
    const preferences = {
      fontSize: fontInputs.find((input) => input.checked)?.value || "normal",
      highContrast: contrastInput.checked,
      reduceMotion: motionInput.checked,
      readableSpacing: spacingInput.checked,
    };
    applyAccessibilityPreferences(preferences, true);
    try { window.localStorage.setItem(storageKey, JSON.stringify(preferences)); } catch (error) { /* Storage is optional. */ }
  }

  applyAccessibilityPreferences(readAccessibilityPreferences());
  fontInputs.forEach((input) => input.addEventListener("change", updateAccessibilityPreferences));
  [contrastInput, motionInput, spacingInput].forEach((input) => input.addEventListener("change", updateAccessibilityPreferences));
  resetButton.addEventListener("click", () => {
    const defaults = {fontSize: "normal", highContrast: false, reduceMotion: false, readableSpacing: false};
    applyAccessibilityPreferences(defaults, true);
    try { window.localStorage.setItem(storageKey, JSON.stringify(defaults)); } catch (error) { /* Storage is optional. */ }
  });
  accessibilityMenu.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && accessibilityMenu.open) {
      accessibilityMenu.open = false;
      accessibilityMenu.querySelector("summary").focus();
    }
  });
}

const skyViewport = document.querySelector("[data-sky-viewport]");
const skyLayer = document.querySelector("[data-sky-layer]");
const aladinElement = document.querySelector("[data-aladin-map]");
const mapLoading = document.querySelector("[data-map-loading]");
const mapHelp = document.querySelector("[data-map-help]");
const channelSelect = document.querySelector("[data-sky-channel]");
let mapScale = 1;
let mapX = 0;
let mapY = 0;
let mapDragging = false;
let mapPointerX = 0;
let mapPointerY = 0;
let atlasMode = false;
let aladin = null;
let hipsLayer = null;

function renderMap() {
  skyLayer.style.transform = `translate(${mapX}px, ${mapY}px) scale(${mapScale})`;
}

function zoomMap(factor, x = skyViewport.clientWidth / 2, y = skyViewport.clientHeight / 2) {
  const nextScale = Math.max(1, Math.min(8, mapScale * factor));
  const ratio = nextScale / mapScale;
  mapX = x - (x - mapX) * ratio;
  mapY = y - (y - mapY) * ratio;
  mapScale = nextScale;
  renderMap();
}

skyViewport.addEventListener("wheel", (event) => {
  if (!atlasMode) return;
  event.preventDefault();
  const rect = skyViewport.getBoundingClientRect();
  zoomMap(event.deltaY < 0 ? 1.2 : 1 / 1.2, event.clientX - rect.left, event.clientY - rect.top);
}, {passive: false});
skyViewport.addEventListener("pointerdown", (event) => {
  if (!atlasMode) return;
  mapDragging = true;
  mapPointerX = event.clientX;
  mapPointerY = event.clientY;
  skyViewport.classList.add("dragging");
  skyViewport.setPointerCapture(event.pointerId);
});
skyViewport.addEventListener("pointermove", (event) => {
  if (!atlasMode || !mapDragging || mapScale === 1) return;
  mapX += event.clientX - mapPointerX;
  mapY += event.clientY - mapPointerY;
  mapPointerX = event.clientX;
  mapPointerY = event.clientY;
  renderMap();
});
skyViewport.addEventListener("pointerup", () => {
  mapDragging = false;
  skyViewport.classList.remove("dragging");
});
document.querySelector("[data-zoom-in]").addEventListener("click", () => atlasMode ? zoomMap(1.25) : aladin?.increaseZoom?.());
document.querySelector("[data-zoom-out]").addEventListener("click", () => atlasMode ? zoomMap(1 / 1.25) : aladin?.decreaseZoom?.());
document.querySelector("[data-reset-map]").addEventListener("click", () => {
  if (atlasMode) {
    mapScale = 1;
    mapX = 0;
    mapY = 0;
    renderMap();
  } else {
    aladin?.gotoRaDec?.(180, 0);
    aladin?.setFoV?.(360);
  }
});

function useAtlasFallback(message = "Aladin unavailable · packaged sky overview") {
  atlasMode = true;
  aladinElement.hidden = true;
  skyLayer.hidden = false;
  mapLoading.hidden = true;
  mapHelp.textContent = message;
}

function showCubeChannel(channel) {
  if (!hipsLayer) return;
  const depth = 102;
  const speedOfLight = 299792458.0;
  const lowFrequency = speedOfLight / 5.009e-6;
  const highFrequency = speedOfLight / 7.43e-7;
  const frame = Number(channel) - 1;
  hipsLayer.setFrequency({
    value: lowFrequency + (frame + 0.5) / depth * (highFrequency - lowFrequency),
    unit: "Hz",
  });
  mapHelp.textContent = `Continuous Aitoff map · channel ${channel}/102`;
}

for (let channel = 2; channel <= 102; channel += 1) {
  const option = document.createElement("option");
  const detector = Math.ceil(channel / 17);
  const detectorChannel = ((channel - 1) % 17) + 1;
  option.value = String(channel);
  option.textContent = `Channel ${channel} · D${detector}/${detectorChannel}`;
  channelSelect.append(option);
}
channelSelect.addEventListener("change", () => showCubeChannel(channelSelect.value));

async function startAladin() {
  if (!window.A) {
    window.addEventListener("aladin-ready", startAladin, {once: true});
    window.setTimeout(() => { if (!window.A) useAtlasFallback(); }, 15000);
    return;
  }
  try {
    await window.A.init;
    aladin = window.A.aladin("#spherex-all-sky", {
      fov: 360,
      projection: "AIT",
      cooFrame: "equatorial",
      showCooGrid: true,
      showReticle: true,
      showZoomControl: false,
      showFullscreenControl: false,
      showLayersControl: false,
      showProjectionControl: false,
      showCooGridControl: false,
      showSettingsControl: false,
      showShareControl: false,
      showStatusBar: false,
      showContextMenu: false,
      showSimbadPointerControl: false,
    });
    hipsLayer = window.A.imageHiPS(document.querySelector("[data-hips-url]").dataset.hipsUrl, {
      successCallback: () => {
        showCubeChannel(channelSelect.value);
        mapLoading.hidden = true;
      },
      errorCallback: () => useAtlasFallback("SPHEREx HiPS unavailable · packaged sky overview"),
    });
    aladin.setBaseImageLayer(hipsLayer);
    aladin.setProjection?.("AIT");
    aladin.setFoV?.(360);
    aladin.gotoRaDec?.(180, 0);
    aladin.on("click", (position) => {
      if (!position || !Number.isFinite(position.ra) || !Number.isFinite(position.dec)) return;
      mapHelp.textContent = `Exploring RA ${position.ra.toFixed(3)}° · Dec ${position.dec.toFixed(3)}° · offline analysis remains locked`;
    });
  } catch (error) {
    useAtlasFallback();
  }
}
startAladin();

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

showFrame(0);
