window.__MAPA_APP_BOOTED__ = true;

const CONFIG = {
  apiBase: "",
  politicalMapUrl: "/api/map/departments",
  conflictStart: { year: 2026, month: 5, day: 1 },
  refreshMs: 3600000
};

const STATUS = {
  2: { label: "Precaución", color: "#FDC715", rank: 5, code: "B" },
  3: { label: "Desvío", color: "#59C3EC", rank: 4, code: "C" },
  4: { label: "Cerrado", color: "#E62F58", rank: 1, code: "D" },
  5: { label: "Conflicto", color: "#6E61A7", rank: 2, code: "E" },
  7: { label: "Restricción", color: "#008F58", rank: 3, code: "G" },
  8: { label: "Restricción especial", color: "#59C3EC", rank: 3, code: "H" },
  9: { label: "Interrupción", color: "#E62F58", rank: 1, code: "I" }
};

const DEPARTMENTS = [
  { id: "LA PAZ", label: "La Paz", short: "La Paz", badgeDx: -66, badgeDy: 8 },
  { id: "COCHABAMBA", label: "Cochabamba", short: "Cbba.", badgeDx: 62, badgeDy: 52 },
  { id: "SANTA CRUZ", label: "Santa Cruz", short: "Sta. Cruz", badgeDx: 84, badgeDy: 18 },
  { id: "ORURO", label: "Oruro", short: "Oruro", badgeDx: -62, badgeDy: 38 },
  { id: "CHUQUISACA", label: "Chuquisaca", short: "Chuqui.", badgeDx: 74, badgeDy: 42 },
  { id: "BENI", label: "Beni", short: "Beni", badgeDx: 70, badgeDy: -8 },
  { id: "POTOSI", label: "Potos\u00ed", short: "Potos\u00ed", badgeDx: -62, badgeDy: 56 },
  { id: "TARIJA", label: "Tarija", short: "Tarija", badgeDx: 66, badgeDy: 50 },
  { id: "PANDO", label: "Pando", short: "Pando", badgeDx: 54, badgeDy: -26 }
];

const els = {
  clock: document.getElementById("clock"),
  updatedAt: document.getElementById("updatedAt"),
  mapStatus: document.getElementById("mapStatus"),
  map: document.getElementById("map"),
  totalCount: document.getElementById("totalCount"),
  closedCount: document.getElementById("closedCount"),
  conflictCount: document.getElementById("conflictCount"),
  cautionCount: document.getElementById("cautionCount"),
  selectedDepartmentFlag: document.getElementById("selectedDepartmentFlag"),
  selectedDepartmentEyebrow: document.getElementById("selectedDepartmentEyebrow"),
  selectedDepartmentTitle: document.getElementById("selectedDepartmentTitle"),
  historyList: document.getElementById("historyList"),
  departmentNav: document.getElementById("departmentNav"),
  selectedDepartmentName: document.getElementById("selectedDepartmentName"),
  selectedDepartmentCount: document.getElementById("selectedDepartmentCount"),
  departmentPointList: document.getElementById("departmentPointList"),
  tickerTrack: document.getElementById("tickerTrack")
};

let lastData = [];
let selectedDepartment = null;
let politicalMap = null;
let mapTransition = "";

function tickClock() {
  const now = new Date();
  els.clock.textContent = now.toLocaleTimeString("es-BO", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

async function fetchJson(path) {
  const response = await fetch(`${CONFIG.apiBase}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadTransitability() {
  els.mapStatus.textContent = "Consultando datos oficiales ABC...";
  try {
    const data = await fetchJson("/api/v1/data");
    lastData = normalizeItems(extractDataItems(data));

    try {
      politicalMap = await fetchPoliticalMap();
      enrichItemsWithDepartments(lastData, politicalMap);
    } catch (mapError) {
      console.error(mapError);
      els.mapStatus.textContent = "Datos ABC cargados; mapa base no disponible";
    }

    const usingCachedData = lastData.some((item) => item.__cached);
    render(lastData);
    if (politicalMap) {
      els.mapStatus.textContent = usingCachedData
        ? "Fuente: historial local / ABC no disponible"
        : "Fuente: ABC / transitabilidad.abc.gob.bo";
    }
    els.updatedAt.textContent = `Actualizado ${formatDateTime(new Date())}`;
  } catch (error) {
    els.mapStatus.textContent = `No se pudo actualizar ABC: ${error.message}`;
    els.updatedAt.textContent = "Reintentando conexi\u00f3n";
    if (lastData.length) render(lastData);
    console.error(error);
  }
}

async function fetchPoliticalMap() {
  if (politicalMap) return politicalMap;
  const response = await fetch(CONFIG.politicalMapUrl, { cache: "force-cache" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadHistory() {
  if (!els.historyList) return;
  try {
    await fetch("/api/today-summary", { cache: "no-store" });
    const response = await fetch("/api/history", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    renderHistory(Array.isArray(payload.history) ? payload.history : []);
  } catch (error) {
    els.historyList.innerHTML = '<span class="history-empty">Sin historial local</span>';
    console.error(error);
  }
}

function renderHistory(history) {
  const sorted = history
    .filter((item) => item?.date)
    .slice()
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const current = sorted[0];
  const yesterdayKey = previousDateString(current?.date);
  const yesterday = sorted.find((item) => item.date === yesterdayKey);
  const visible = sorted.slice(0, 7).reverse();
  if (!current) {
    els.historyList.innerHTML = '<span class="history-empty">Sin datos guardados</span>';
    return;
  }

  const currentConflicts = Number(current.conflicts) || 0;
  const yesterdayConflicts = yesterday ? Number(yesterday.conflicts) || 0 : null;
  const delta = yesterday ? currentConflicts - yesterdayConflicts : null;
  const trendClass = delta === null ? "trend-missing" : delta > 0 ? "trend-up" : delta < 0 ? "trend-down" : "trend-flat";
  const trendLabel = delta === null ? "Sin dato ayer" : delta > 0 ? "Subieron" : delta < 0 ? "Bajaron" : "Sin cambio";
  const trendValue = delta === null ? "--" : delta > 0 ? `+${delta}` : String(delta);

  const maxConflicts = Math.max(1, ...visible.map((item) => Number(item.conflicts) || 0));
  const rows = visible.map((item) => {
    const conflicts = Number(item.conflicts) || 0;
    const width = Math.max(8, Math.round((conflicts / maxConflicts) * 100));
    return `
      <article class="history-row">
        <span>${formatHistoryDate(item.date)}</span>
        <div class="history-bar"><i style="width:${width}%"></i></div>
        <strong>${conflicts}</strong>
      </article>
    `;
  }).join("");

  els.historyList.innerHTML = `
    <section class="history-compare ${trendClass}" aria-label="Comparacion con el dia anterior">
      <div class="history-day">
        <span>Hoy</span>
        <strong>${currentConflicts}</strong>
        <small>${formatHistoryDate(current.date)}</small>
      </div>
      <div class="history-trend">
        <span>${trendLabel}</span>
        <strong>${trendValue}</strong>
        <small>vs ayer</small>
      </div>
      <div class="history-day">
        <span>Ayer</span>
        <strong>${yesterdayConflicts === null ? "--" : yesterdayConflicts}</strong>
        <small>${yesterday ? formatHistoryDate(yesterday.date) : formatHistoryDate(yesterdayKey)}</small>
      </div>
    </section>
    ${rows}
  `;
}

function normalizeItems(data) {
  return data
    .filter((item) => STATUS[item.id_estado])
    .map((item, index) => ({ ...item, __viewId: `${item.id_registro || "r"}-${item.id_seccion || "s"}-${index}` }));
}

function enrichItemsWithDepartments(items, geojson) {
  if (!geojson?.features?.length) return;
  items.forEach((item) => {
    if (normalizeDepartment(item.departamento)) return;
    if (!hasCoordinates(item)) return;
    const department = findDepartmentByPoint(Number(item.longitud_inicio_seccion), Number(item.latitud_inicio_seccion), geojson);
    if (department) item.departamento = department;
  });
}

function findDepartmentByPoint(lon, lat, geojson) {
  const feature = geojson.features.find((candidate) => geometryContainsPoint(candidate.geometry, [lon, lat]));
  if (!feature) return "";
  return normalizeDepartment(feature.properties?.Departamento || feature.properties?.NOM_DEP);
}

function geometryContainsPoint(geometry, point) {
  if (!geometry) return false;
  const polygons = geometry.type === "MultiPolygon" ? geometry.coordinates : [geometry.coordinates];
  return polygons.some((polygon) => polygon.length && pointInRing(point, polygon[0]));
}

function pointInRing(point, ring) {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = Number(ring[i][0]);
    const yi = Number(ring[i][1]);
    const xj = Number(ring[j][0]);
    const yj = Number(ring[j][1]);
    const intersects = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-9) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
}

function extractDataItems(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.data)) return data.data;
  if (Array.isArray(data?.value)) return data.value;
  return [];
}

function render(items) {
  const totals = departmentTotals(items);
  if (!selectedDepartment) selectedDepartment = "BOLIVIA";

  const activeItems = selectedDepartment === "BOLIVIA"
    ? items
    : items.filter((item) => normalizeDepartment(item.departamento) === selectedDepartment);
  const activeCounts = countStatuses(activeItems);
  const activeCritical = getProblemItems(activeItems);

  els.totalCount.textContent = activeItems.length;
  els.closedCount.textContent = lastData.filter((item) => Number(item.id_estado) === 5).length;
  els.conflictCount.textContent = activeCounts[5] || 0;
  els.cautionCount.textContent = activeCounts[2] || 0;
  els.selectedDepartmentFlag.className = `selected-flag flag-${departmentFlagClass(selectedDepartment)}`;
  els.selectedDepartmentEyebrow.textContent = selectedDepartment === "BOLIVIA"
    ? "Resumen nacional"
    : "Departamento seleccionado";
  els.selectedDepartmentTitle.textContent = departmentLabel(selectedDepartment);
  els.selectedDepartmentName.textContent = departmentLabel(selectedDepartment);
  els.selectedDepartmentCount.textContent = selectedDepartment === "BOLIVIA"
    ? `${activeItems.length} alertas`
    : `${activeItems.length} alertas`;

  renderProblemMap(totals);
  renderDepartmentNav(totals);
  renderPointList(activeCritical.concat(activeItems.filter((item) => !isCritical(item))));
  renderTicker(activeCritical.length ? activeCritical : activeItems);
}

function renderProblemMap(totals) {
  if (!politicalMap?.features?.length) {
    renderFallbackMap(totals);
    return;
  }

  if (selectedDepartment !== "BOLIVIA") {
    renderDepartmentZoom(totals);
    return;
  }

  const countryConflictBlocks = lastData.filter((item) => Number(item.id_estado) === 5).length;
  const projection = createProjection(politicalMap);
  const mapLayers = politicalMap.features.reduce((acc, feature) => {
    const id = normalizeDepartment(feature.properties?.Departamento || feature.properties?.NOM_DEP);
    const department = DEPARTMENTS.find((item) => item.id === id);
    const conflicts = totals[id]?.conflicts || 0;
    const level = conflicts > 0 ? "danger" : "quiet";
    const center = geometryCenter(feature.geometry, projection);
    const badgeX = Number(center.x) + (department?.badgeDx || 48);
    const badgeY = Number(center.y) + (department?.badgeDy || 40);
    const badgeRadius = 31;
    acc.shapes.push(`
      <path
        class="department-shape level-${level} ${id === selectedDepartment ? "is-active" : ""}"
        data-department="${id}"
        d="${geometryToPath(feature.geometry, projection)}"
      />
    `);
    acc.labels.push(`
      <text class="department-name" x="${center.x}" y="${center.y}">${escapeHtml(department?.short || department?.label || id)}</text>
    `);
    acc.badges.push(`
      <g class="department-badge ${id === selectedDepartment ? "is-active" : ""}" data-department="${id}" transform="translate(${badgeX.toFixed(1)}, ${badgeY.toFixed(1)})">
        <circle r="${badgeRadius}"></circle>
        <text class="badge-total" y="9">${conflicts}</text>
      </g>
    `);
    return acc;
  }, { shapes: [], labels: [], badges: [] });

  els.map.innerHTML = `
    <button class="map-title ${selectedDepartment === "BOLIVIA" ? "is-active" : ""}" type="button" data-country="BOLIVIA" aria-label="Ver total nacional sin transitabilidad">
      <span>Bolivia</span>
      <strong>${countryConflictBlocks}</strong>
      <small>bloqueos sociales</small>
    </button>
    <svg class="political-map" viewBox="0 0 1000 760" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Mapa pol\u00edtico de Bolivia por departamentos">
      <g class="department-layer">${mapLayers.shapes.join("")}</g>
      <g class="department-label-layer">${mapLayers.labels.join("")}</g>
      <g class="department-badge-layer">${mapLayers.badges.join("")}</g>
    </svg>
    <aside class="blockade-days">
      <span>Conflicto pa\u00eds</span>
      <strong>${countryConflictBlocks}</strong>
      <small>bloqueos por conflictos sociales</small>
      <b>${getConflictDays()} d\u00edas de conflicto</b>
    </aside>
    <aside class="map-insight">
      <span>Conflicto pa\u00eds</span>
      <strong>${countryConflictBlocks}</strong>
      <small>todo el bloqueo</small>
    </aside>
  `;
  applyMapTransition();
}

function renderDepartmentZoom(totals) {
  const selectedFeature = politicalMap.features.find((feature) => {
    const id = normalizeDepartment(feature.properties?.Departamento || feature.properties?.NOM_DEP);
    return id === selectedDepartment;
  });

  if (!selectedFeature) {
    selectedDepartment = "BOLIVIA";
    renderProblemMap(totals);
    return;
  }

  const department = DEPARTMENTS.find((item) => item.id === selectedDepartment);
  const projection = createProjection({ features: [selectedFeature] }, 92);
  const departmentItems = lastData.filter((item) => normalizeDepartment(item.departamento) === selectedDepartment);
  const allBlockadeItems = departmentItems.filter((item) => Number(item.id_estado) === 5);
  const blockadeItems = allBlockadeItems.filter((item) => hasCoordinates(item));
  const syntheticBlockadeItems = allBlockadeItems.filter((item) => !hasCoordinates(item));
  const totalBlockades = departmentItems.filter((item) => Number(item.id_estado) === 5).length;
  const missingCoordinates = totalBlockades - blockadeItems.length;
  const pinPositions = arrangeBlockadePins(blockadeItems, projection)
    .concat(arrangeSyntheticPins(syntheticBlockadeItems, selectedFeature.geometry, projection));
  const pins = pinPositions.map(({ item, x, y }, index) => {
    const reason = reasonInfo(item);
    return `
      <g class="blockade-pin" data-point-id="${item.__viewId}" transform="translate(${x.toFixed(1)}, ${y.toFixed(1)})">
        <path d="M0 -24 C13 -24 23 -14 23 -2 C23 15 0 30 0 30 C0 30 -23 15 -23 -2 C-23 -14 -13 -24 0 -24 Z"></path>
        <circle r="11"></circle>
        <text y="5">${index + 1}</text>
        <title>${escapeHtml(reason.label)} - ${escapeHtml(routeTitle(item))}</title>
      </g>
    `;
  }).join("");

  els.map.innerHTML = `
    <button class="map-title map-title-compact" type="button" data-country="BOLIVIA" aria-label="Volver al mapa nacional">
      <span>Bolivia</span>
      <strong>${departmentLabel(selectedDepartment)}</strong>
      <small>volver al mapa nacional</small>
    </button>
    <svg class="political-map is-zoomed" viewBox="0 0 1000 760" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${escapeHtml(department?.label || selectedDepartment)} ampliado con bloqueos">
      <g class="department-layer">
        <path
          class="department-shape level-danger is-active is-zoom-shape"
          data-department="${selectedDepartment}"
          d="${geometryToPath(selectedFeature.geometry, projection)}"
        />
      </g>
      <g class="blockade-pin-layer">${pins}</g>
    </svg>
    <aside class="zoom-summary">
      <span>${escapeHtml(department?.label || selectedDepartment)}</span>
      <strong>${totalBlockades}</strong>
      <small>${missingCoordinates ? `${missingCoordinates} desde cache sin coordenadas` : "puntos de bloqueo"}</small>
    </aside>
    <aside class="blockade-days">
      <span>Conflicto pa\u00eds</span>
      <strong>${lastData.filter((item) => Number(item.id_estado) === 5).length}</strong>
      <small>bloqueos por conflictos sociales</small>
      <b>${getConflictDays()} d\u00edas de conflicto</b>
    </aside>
  `;
  applyMapTransition();
}

function renderFallbackMap(totals) {
  const countryConflictBlocks = lastData.filter((item) => Number(item.id_estado) === 5).length;
  const cards = DEPARTMENTS.map((department) => {
    const conflicts = totals[department.id]?.conflicts || 0;
    return `
      <button class="fallback-dept ${conflicts ? "has-conflict" : ""}" type="button" data-department="${department.id}">
        <span>${escapeHtml(department.label)}</span>
        <strong>${conflicts}</strong>
      </button>
    `;
  }).join("");

  els.map.innerHTML = `
    <button class="map-title is-active" type="button" data-country="BOLIVIA" aria-label="Ver total nacional">
      <span>Bolivia</span>
      <strong>${countryConflictBlocks}</strong>
      <small>bloqueos sociales</small>
    </button>
    <div class="fallback-map">
      ${cards}
    </div>
  `;
}

function renderDepartmentNav(totals) {
  els.departmentNav.innerHTML = "";
  const fragment = document.createDocumentFragment();

  DEPARTMENTS.forEach((department) => {
    const total = totals[department.id]?.total || 0;
    const critical = totals[department.id]?.critical || 0;
    const button = document.createElement("button");
    button.type = "button";
    button.className = [
      "dept-button",
      department.id === selectedDepartment ? "is-active" : "",
      critical > 0 ? "has-critical" : ""
    ].filter(Boolean).join(" ");
    button.dataset.department = department.id;
    button.innerHTML = `
      <span>
        <strong>${escapeHtml(department.label)}</strong>
        <span>${total} lugares</span>
      </span>
      <div class="dept-count" aria-label="${total} lugares">${total}</div>
    `;
    fragment.appendChild(button);
  });

  els.departmentNav.appendChild(fragment);
}

function renderPointList(items) {
  const visible = items.slice(0, 24);
  els.departmentPointList.innerHTML = "";

  if (!visible.length) {
    els.departmentPointList.innerHTML = '<li class="empty">Este departamento no tiene lugares con problemas en el reporte actual.</li>';
    return;
  }

  const fragment = document.createDocumentFragment();
  visible.forEach((item) => {
    const status = STATUS[item.id_estado];
    const reason = reasonInfo(item);
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "point-item";
    button.dataset.pointId = item.__viewId;
    button.style.borderLeft = `5px solid ${status.color}`;
    button.innerHTML = `
      <span class="reason-icon" style="background:${reason.color}">${escapeHtml(reason.code)}</span>
      <span class="point-copy">
        <strong>${escapeHtml(routeTitle(item))}</strong>
        <span>${escapeHtml(placeLine(item))}</span>
        <small>
          <span class="chip" style="background:${status.color}">${escapeHtml(status.label)}</span>
          <span class="chip" style="background:${reason.color}">${escapeHtml(reason.label)}</span>
        </small>
      </span>
    `;
    button.addEventListener("click", () => highlightPoint(button));
    li.appendChild(button);
    fragment.appendChild(li);
  });

  els.departmentPointList.appendChild(fragment);
}

function renderTicker(items) {
  const feed = items.slice(0, 12).map((item) => {
    const reason = reasonInfo(item).label;
    return `${departmentLabel(normalizeDepartment(item.departamento))}: ${reason} en ${routeTitle(item)}`;
  });

  els.tickerTrack.textContent = feed.length
    ? feed.join("     /     ")
    : "No se registran problemas en la fuente actual de transitabilidad.";
}

function bindControls() {
  document.addEventListener("click", (event) => {
    const countryButton = event.target.closest("[data-country]");
    if (countryButton) {
      if (selectedDepartment === "BOLIVIA") return;
      mapTransition = "zoom-out";
      selectedDepartment = "BOLIVIA";
      render(lastData);
      return;
    }

    const departmentButton = event.target.closest("[data-department]");
    if (!departmentButton) return;
    if (departmentButton.dataset.department === selectedDepartment) return;
    mapTransition = selectedDepartment === "BOLIVIA" ? "zoom-in" : "zoom-switch";
    selectedDepartment = departmentButton.dataset.department;
    render(lastData);
  });
}

function applyMapTransition() {
  if (!mapTransition) return;
  els.map.classList.remove("is-zooming-in", "is-zooming-out", "is-zoom-switching");
  void els.map.offsetWidth;
  const className = mapTransition === "zoom-in"
    ? "is-zooming-in"
    : mapTransition === "zoom-out"
      ? "is-zooming-out"
      : "is-zoom-switching";
  els.map.classList.add(className);
  window.setTimeout(() => els.map.classList.remove(className), 760);
  mapTransition = "";
}

function highlightPoint(button) {
  document.querySelectorAll(".point-item.is-active").forEach((item) => item.classList.remove("is-active"));
  button.classList.add("is-active");
}

function departmentTotals(items) {
  return DEPARTMENTS.reduce((acc, department) => {
    const departmentItems = items.filter((item) => normalizeDepartment(item.departamento) === department.id);
    acc[department.id] = {
      total: departmentItems.length,
      critical: departmentItems.filter(isCritical).length,
      conflicts: departmentItems.filter((item) => Number(item.id_estado) === 5).length
    };
    return acc;
  }, {});
}

function createProjection(geojson, pad = 42) {
  const coords = [];
  geojson.features.forEach((feature) => collectCoordinates(feature.geometry, coords));
  const minLon = Math.min(...coords.map((coord) => coord[0]));
  const maxLon = Math.max(...coords.map((coord) => coord[0]));
  const minLat = Math.min(...coords.map((coord) => coord[1]));
  const maxLat = Math.max(...coords.map((coord) => coord[1]));
  const targetWidth = 1000 - pad * 2;
  const targetHeight = 760 - pad * 2;
  const sourceWidth = maxLon - minLon;
  const sourceHeight = maxLat - minLat;
  const scale = Math.min(targetWidth / sourceWidth, targetHeight / sourceHeight);
  const drawnWidth = sourceWidth * scale;
  const drawnHeight = sourceHeight * scale;
  const offsetX = pad + (targetWidth - drawnWidth) / 2;
  const offsetY = pad + (targetHeight - drawnHeight) / 2;

  return {
    point(coord) {
      const x = offsetX + (coord[0] - minLon) * scale;
      const y = offsetY + (maxLat - coord[1]) * scale;
      return [x, y];
    }
  };
}

function hasCoordinates(item) {
  return Number.isFinite(Number(item.latitud_inicio_seccion)) && Number.isFinite(Number(item.longitud_inicio_seccion));
}

function arrangeBlockadePins(items, projection) {
  const pins = items.map((item) => {
    const [x, y] = projection.point([Number(item.longitud_inicio_seccion), Number(item.latitud_inicio_seccion)]);
    return { item, x, y };
  });
  const groups = [];
  const threshold = 70;

  pins.forEach((pin) => {
    const group = groups.find((candidate) => Math.hypot(pin.x - candidate.x, pin.y - candidate.y) < threshold);
    if (group) {
      group.items.push(pin);
      group.x = group.items.reduce((sum, item) => sum + item.x, 0) / group.items.length;
      group.y = group.items.reduce((sum, item) => sum + item.y, 0) / group.items.length;
    } else {
      groups.push({ x: pin.x, y: pin.y, items: [pin] });
    }
  });

  return groups.flatMap((group) => {
    if (group.items.length === 1) return group.items;
    const columns = Math.ceil(Math.sqrt(group.items.length));
    const rows = Math.ceil(group.items.length / columns);
    const spacing = 58;
    return group.items
      .sort((a, b) => a.y - b.y || a.x - b.x)
      .map((pin, index) => {
        const column = index % columns;
        const row = Math.floor(index / columns);
        const offsetX = (column - (columns - 1) / 2) * spacing;
        const offsetY = (row - (rows - 1) / 2) * spacing;
        return {
          item: pin.item,
          x: clamp(group.x + offsetX, 48, 952),
          y: clamp(group.y + offsetY, 48, 712)
        };
      });
  });
}

function arrangeSyntheticPins(items, geometry, projection) {
  if (!items.length) return [];
  const box = geometryBox(geometry, projection);
  const columns = Math.ceil(Math.sqrt(items.length));
  const rows = Math.ceil(items.length / columns);
  const cellWidth = box.width / Math.max(1, columns + 1);
  const cellHeight = box.height / Math.max(1, rows + 1);

  return items.map((item, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const wave = row % 2 ? 0.18 : -0.18;
    return {
      item,
      x: clamp(box.minX + cellWidth * (column + 1 + wave), 54, 946),
      y: clamp(box.minY + cellHeight * (row + 1), 54, 706)
    };
  });
}

function geometryBox(geometry, projection) {
  const coords = [];
  collectCoordinates(geometry, coords);
  const projected = coords.map((coord) => projection.point(coord));
  const minX = Math.min(...projected.map((coord) => coord[0]));
  const maxX = Math.max(...projected.map((coord) => coord[0]));
  const minY = Math.min(...projected.map((coord) => coord[1]));
  const maxY = Math.max(...projected.map((coord) => coord[1]));
  return {
    minX,
    maxX,
    minY,
    maxY,
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY)
  };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function collectCoordinates(geometry, coords) {
  if (!geometry) return;
  if (geometry.type === "Polygon") {
    geometry.coordinates.flat(1).forEach((coord) => coords.push(coord));
  }
  if (geometry.type === "MultiPolygon") {
    geometry.coordinates.flat(2).forEach((coord) => coords.push(coord));
  }
}

function geometryToPath(geometry, projection) {
  if (!geometry) return "";
  const polygons = geometry.type === "MultiPolygon" ? geometry.coordinates : [geometry.coordinates];
  return polygons.map((polygon) => polygon.map((ring) => {
    const projected = ring.map((coord) => projection.point(coord));
    return projected.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ") + " Z";
  }).join(" ")).join(" ");
}

function geometryCenter(geometry, projection) {
  const coords = [];
  collectCoordinates(geometry, coords);
  const projected = coords.map((coord) => projection.point(coord));
  const minX = Math.min(...projected.map((coord) => coord[0]));
  const maxX = Math.max(...projected.map((coord) => coord[0]));
  const minY = Math.min(...projected.map((coord) => coord[1]));
  const maxY = Math.max(...projected.map((coord) => coord[1]));
  return { x: ((minX + maxX) / 2).toFixed(1), y: ((minY + maxY) / 2).toFixed(1) };
}

function departmentWithMostProblems(totals) {
  return [...DEPARTMENTS]
    .sort((a, b) => {
      const criticalDiff = (totals[b.id]?.critical || 0) - (totals[a.id]?.critical || 0);
      if (criticalDiff !== 0) return criticalDiff;
      return (totals[b.id]?.total || 0) - (totals[a.id]?.total || 0);
    })[0]?.id || DEPARTMENTS[0].id;
}

function countStatuses(items) {
  return items.reduce((acc, item) => {
    acc[item.id_estado] = (acc[item.id_estado] || 0) + 1;
    return acc;
  }, {});
}

function getConflictDays() {
  const today = getBoliviaDateParts();
  const start = Date.UTC(CONFIG.conflictStart.year, CONFIG.conflictStart.month - 1, CONFIG.conflictStart.day);
  const current = Date.UTC(today.year, today.month - 1, today.day);
  const diffDays = Math.floor((current - start) / 86400000);
  return Math.max(1, diffDays + 1);
}

function getBoliviaDateParts() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/La_Paz",
    year: "numeric",
    month: "numeric",
    day: "numeric"
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, Number(part.value)]));
  return { year: values.year, month: values.month, day: values.day };
}

function getProblemItems(items) {
  return [...items].filter(isCritical).sort((a, b) => {
    const rankA = STATUS[a.id_estado]?.rank || 99;
    const rankB = STATUS[b.id_estado]?.rank || 99;
    if (rankA !== rankB) return rankA - rankB;
    return String(b.fecha_registro_hora || "").localeCompare(String(a.fecha_registro_hora || ""));
  });
}

function isCritical(item) {
  return [3, 4, 5, 7, 8].includes(Number(item.id_estado));
}

function routeTitle(item) {
  const route = item.ruta ? `RVF ${item.ruta}` : "Ruta";
  const section = item.tramo ? ` \u00b7 ${item.tramo}` : "";
  const sector = item.descr_sector ? ` \u00b7 ${stripHtml(item.descr_sector)}` : "";
  return `${route}${section}${sector}`;
}

function placeLine(item) {
  const start = item.inicio_seccion || "Origen no especificado";
  const end = item.fin_seccion || "Destino no especificado";
  return `${start} - ${end}`;
}

function departmentLabel(id) {
  if (id === "BOLIVIA") return "Bolivia";
  return DEPARTMENTS.find((department) => department.id === id)?.label || "Bolivia";
}

function departmentFlagClass(id) {
  return normalizeDepartment(id).toLowerCase().replace(/\s+/g, "-");
}

function reasonInfo(item) {
  const event = normalizeDepartment(item.evento?.descripcion_evento || item.descripcion_evento || item.descr_sector);
  if (event.includes("BLOQUEO") || item.id_estado === 5) return { label: "Conflicto social", code: "CS", color: "#6E61A7" };
  if (event.includes("DERRUMBE")) return { label: "Derrumbe", code: "DR", color: "#E62F58" };
  if (event.includes("PUENTE")) return { label: "Puente afectado", code: "PT", color: "#FDC715" };
  if (event.includes("CONSTRUCCION") || event.includes("REHABILITACION")) return { label: "Obras en v\u00eda", code: "OB", color: "#008F58" };
  if (event.includes("BARRO") || event.includes("RIADA") || event.includes("INUNDACION")) return { label: "Evento natural", code: "EN", color: "#59C3EC" };
  if (item.id_estado === 7 || item.id_estado === 8) return { label: "Restricci\u00f3n", code: "RV", color: "#008F58" };
  if (item.id_estado === 3) return { label: "Desv\u00edo", code: "DV", color: "#59C3EC" };
  return { label: item.evento?.descripcion_evento || "Precauci\u00f3n", code: STATUS[item.id_estado]?.code || "P", color: STATUS[item.id_estado]?.color || "#6b7280" };
}

function normalizeDepartment(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase();
}

function stripHtml(value) {
  const div = document.createElement("div");
  div.innerHTML = String(value || "");
  return div.textContent.replace(/\s+/g, " ").trim();
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatDateTime(date) {
  return date.toLocaleString("es-BO", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function formatHistoryDate(value) {
  const [year, month, day] = String(value || "").split("-");
  if (!year || !month || !day) return value || "--";
  return `${day}/${month}`;
}

function previousDateString(value) {
  const [year, month, day] = String(value || "").split("-").map(Number);
  if (!year || !month || !day) return "";
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

bindControls();
tickClock();
els.mapStatus.textContent = "JavaScript iniciado. Conectando con datos ABC...";
loadTransitability();
loadHistory();
setInterval(tickClock, 1000);
setInterval(loadTransitability, CONFIG.refreshMs);
setInterval(loadHistory, 600000);
