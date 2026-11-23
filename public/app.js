// The browser side. HTML alone can't react to clicks, so a little JavaScript
// is unavoidable. It only fetches data from the Python API, draws it, and
// sends button presses back. All the real rules live in src/server.py.

"use strict";

const state = {
  days: [],         // from /api/days
  current: null,    // the running session, or null
  settings: { course_name: "100 Days of Code", course_start_date: "", min_session_minutes: 20, theme: "system" },
  clockOffset: 0,   // server time minus this device's time, in ms
  openDay: null,    // day number shown in the panel, or null
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// talking to the API
// ---------------------------------------------------------------------------

async function api(path, { method = "GET", body } = {}) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `Something went wrong (${response.status})`;
    throw new Error(detail);
  }
  return data;
}

function showError(error) {
  for (const id of ["message", "panel-message"]) {
    $(id).textContent = error.message;
    $(id).hidden = false;
  }
  setTimeout(clearError, 8000);
}

function clearError() {
  for (const id of ["message", "panel-message"]) {
    $(id).hidden = true;
  }
}

// Run an action; show any error the API sends back; refresh everything after.
async function act(action) {
  clearError();
  try {
    await action();
  } catch (error) {
    showError(error);
  }
  await refresh();
}

// A button that asks "sure?" on the first click, without a browser pop-up.
function confirmClick(button, sureLabel, action) {
  const original = button.textContent;
  let armed = false;
  let timer = null;
  button.addEventListener("click", () => {
    if (!armed) {
      armed = true;
      button.textContent = sureLabel;
      timer = setTimeout(() => { armed = false; button.textContent = original; }, 4000);
      return;
    }
    clearTimeout(timer);
    armed = false;
    button.textContent = original;
    action();
  });
}

// ---------------------------------------------------------------------------
// themes and settings
// ---------------------------------------------------------------------------

// "system" means: no data-theme, so the CSS follows Windows light/dark.
function applyTheme(theme) {
  if (!theme || theme === "system") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = theme;
  }
}

function applySettings(settings) {
  state.settings = settings;
  applyTheme(settings.theme);
  $("title").textContent = settings.course_name;
  document.title = settings.course_name + " tracker";
}

async function loadSettings() {
  applySettings(await api("/api/settings"));
}

async function openSettings() {
  const settings = state.settings;
  $("set-name").value = settings.course_name;
  $("set-start").value = settings.course_start_date;
  $("set-start").max = new Date().toLocaleDateString("en-CA");  // today, as YYYY-MM-DD
  $("set-min").value = settings.min_session_minutes;
  $("set-theme").value = settings.theme;
  $("settings-message").hidden = true;
  $("settings-saved").hidden = true;
  $("reset-confirm").value = "";
  $("btn-reset").disabled = true;
  const about = await api("/api/about");
  $("data-folder").textContent = about.data_folder;
  $("settings").showModal();
}

$("btn-settings").addEventListener("click", () => openSettings().catch(showError));
$("settings-close").addEventListener("click", () => $("settings").close());
// Closing without saving puts the saved theme back (the picker only previews).
$("settings").addEventListener("close", () => applyTheme(state.settings.theme));
$("set-theme").addEventListener("change", () => applyTheme($("set-theme").value));

$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("settings-message").hidden = true;
  $("settings-saved").hidden = true;
  try {
    const saved = await api("/api/settings", {
      method: "PUT",
      body: {
        course_name: $("set-name").value,
        course_start_date: $("set-start").value,
        min_session_minutes: Number($("set-min").value),
        theme: $("set-theme").value,
      },
    });
    applySettings(saved);
    $("settings-saved").hidden = false;
    await refresh();
  } catch (error) {
    $("settings-message").textContent = error.message;
    $("settings-message").hidden = false;
  }
});

$("reset-confirm").addEventListener("input", () => {
  $("btn-reset").disabled = $("reset-confirm").value !== "RESET";
});
$("btn-reset").addEventListener("click", async () => {
  try {
    await api("/api/reset", { method: "POST", body: { confirm: "RESET" } });
    $("settings").close();
    await refresh();
  } catch (error) {
    $("settings-message").textContent = error.message;
    $("settings-message").hidden = false;
  }
});

// ---------------------------------------------------------------------------
// help
// ---------------------------------------------------------------------------

$("btn-help").addEventListener("click", async () => {
  try {
    const about = await api("/api/about");
    $("help-db").textContent = about.database;
    $("help-version").textContent = "v" + about.version;
    $("help-course").textContent = about.course_title;
    $("help-course").href = about.course_url;
  } catch (error) {
    // the help text still works without the extras
  }
  $("help").showModal();
});
$("help-close").addEventListener("click", () => $("help").close());

// ---------------------------------------------------------------------------
// loading
// ---------------------------------------------------------------------------

async function refresh() {
  const [days, current] = await Promise.all([api("/api/days"), api("/api/sessions/current")]);
  state.days = days;
  state.current = current.session;
  state.clockOffset = Date.parse(current.server_now) - Date.now();
  drawGrid();
  drawBanner();
  drawSummary();
  if (state.openDay !== null) {
    await drawPanel(state.openDay);
  }
  loadStats();
}

const STAT_LABELS = {
  start_date: "Started",
  days_elapsed: "Days since start",
  days_complete: "Course days complete",
  percent_complete: "Percent complete",
  total_hours: "Hours logged",
  avg_minutes_per_completed_day: "Avg minutes per finished day",
  avg_real_days_per_course_day: "Real days per course day",
  projected_finish_date: "Projected finish",
  current_streak: "Current streak (days)",
  longest_streak: "Longest streak (days)",
  hardest_day: "Most time-consuming day",
};

function formatStat(name, value) {
  if (value === null) return "-";
  if (name === "percent_complete") return `${value}%`;
  if (name === "hardest_day") return `Day ${value}`;
  if (name === "start_date" || name === "projected_finish_date") {
    return new Date(value + "T12:00:00").toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
  }
  return String(value);
}

async function loadStats() {
  try {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const stats = await api(`/api/stats?tz=${encodeURIComponent(timezone)}`);
    const list = $("stats-list");
    list.replaceChildren();
    for (const [name, value] of Object.entries(stats)) {
      const term = document.createElement("dt");
      term.textContent = STAT_LABELS[name] || name.replaceAll("_", " ");
      const detail = document.createElement("dd");
      detail.textContent = formatStat(name, value);
      list.append(term, detail);
    }
    $("stats").hidden = false;
  } catch (error) {
    $("stats").hidden = true;
  }
}

// ---------------------------------------------------------------------------
// the poster grid
// ---------------------------------------------------------------------------

function drawGrid() {
  const squares = state.days.map((day) => {
    const square = document.createElement("button");
    square.type = "button";
    square.className = "day";
    square.dataset.day = day.day_number;
    square.setAttribute("aria-label", `Day ${day.day_number}${day.is_complete ? ", complete" : ""}`);
    if (day.is_complete) square.classList.add("done");
    else if (day.session_count > 0) square.classList.add("progress");
    if (state.current && state.current.day_number === day.day_number) square.classList.add("running");

    const number = document.createElement("span");
    number.textContent = day.day_number;
    square.append(number);
    if (day.is_complete) {
      const check = document.createElement("span");
      check.className = "check";
      check.textContent = "✓";
      square.append(check);
    }
    square.addEventListener("click", () => openDay(day.day_number));
    return square;
  });
  $("grid").replaceChildren(...squares);
}

function drawSummary() {
  const done = state.days.filter((day) => day.is_complete).length;
  const minutes = state.days.reduce((sum, day) => sum + day.total_minutes, 0);
  $("summary").textContent = `${done} of 100 complete · ${formatMinutes(minutes)} logged`;
}

// ---------------------------------------------------------------------------
// the running-session banner
// ---------------------------------------------------------------------------

function activeMs(session) {
  const now = Date.now() + state.clockOffset;
  let ms = now - Date.parse(session.started_at);
  for (const pause of session.pauses) {
    const end = pause.resumed_at ? Date.parse(pause.resumed_at) : now;
    ms -= end - Date.parse(pause.paused_at);
  }
  return Math.max(ms, 0);
}

function drawBanner() {
  const session = state.current;
  $("banner").hidden = session === null;
  if (session === null) return;
  $("banner-day").textContent = `Day ${session.day_number}`;
  $("btn-pause").hidden = session.paused;
  $("btn-resume").hidden = !session.paused;
  tick();
}

// Called every second to keep the timer moving without asking the server.
function tick() {
  const session = state.current;
  if (session === null) return;
  const minimum = state.settings.min_session_minutes;
  const ms = activeMs(session);
  $("banner-timer").textContent = formatClock(ms);
  const counts = ms >= minimum * 60000;
  const status = session.paused ? "Paused · " : "";
  $("banner-note").textContent = status + (counts ? `✓ counts (${minimum}+ min)` : `counts at ${minimum} min`);
}

// ---------------------------------------------------------------------------
// the day panel
// ---------------------------------------------------------------------------

async function openDay(dayNumber) {
  clearError();
  state.openDay = dayNumber;
  await drawPanel(dayNumber);
  if (!$("panel").open) $("panel").showModal();
}

async function drawPanel(dayNumber) {
  const day = await api(`/api/days/${dayNumber}`);
  $("panel-title").textContent = `Day ${day.day_number}`;
  $("panel-status").textContent = day.is_complete
    ? `Complete${day.completed_at ? " · " + formatWhen(day.completed_at) : ""}`
    : day.session_count > 0 ? "In progress" : "Not started";
  const totals = [];
  if (day.session_count > 0) {
    totals.push(`${day.session_count} session${day.session_count === 1 ? "" : "s"}`);
  }
  totals.push(day.total_minutes > 0 ? `${formatMinutes(day.total_minutes)} total` : "No time logged yet");
  $("panel-totals").textContent = totals.join(" · ");

  const items = day.sessions.map((session) => {
    const item = document.createElement("li");
    const when = document.createElement("span");
    when.className = "when";
    when.textContent = session.ended_at
      ? `${formatWhen(session.started_at)} → ${formatTime(session.ended_at)}`
      : `${formatWhen(session.started_at)} → running`;
    const detail = document.createElement("span");
    detail.className = "detail";
    if (session.ended_at) {
      const pauses = session.pause_count > 0
        ? ` · ${session.pause_count} pause${session.pause_count === 1 ? "" : "s"} (${formatMinutes(session.paused_minutes)})`
        : "";
      detail.textContent = `${formatMinutes(session.active_minutes)} active${pauses}`;
    } else {
      detail.textContent = "in progress";
    }
    item.append(when, detail);
    return item;
  });
  $("panel-sessions").replaceChildren(...items);

  $("btn-start").hidden = Boolean(day.is_complete) || state.current !== null;
  $("btn-complete").textContent = day.is_complete ? "Reopen this day" : "Mark complete";
  $("btn-complete").dataset.day = day.day_number;
}

// ---------------------------------------------------------------------------
// formatting
// ---------------------------------------------------------------------------

function formatClock(ms) {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

function formatMinutes(minutes) {
  const whole = Math.round(minutes);
  if (whole < 60) return `${whole} min`;
  return `${Math.floor(whole / 60)} h ${whole % 60} min`;
}

function formatWhen(iso) {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// ---------------------------------------------------------------------------
// buttons
// ---------------------------------------------------------------------------

$("btn-start").addEventListener("click", () =>
  act(() => api("/api/sessions/start", { method: "POST", body: { day_number: state.openDay } }))
);
$("btn-pause").addEventListener("click", () => act(() => api("/api/sessions/pause", { method: "POST", body: {} })));
$("btn-resume").addEventListener("click", () => act(() => api("/api/sessions/resume", { method: "POST", body: {} })));
$("btn-stop").addEventListener("click", () => act(() => api("/api/sessions/stop", { method: "POST", body: {} })));
confirmClick($("btn-discard"), "Really discard?", () =>
  act(() => api("/api/sessions/discard", { method: "POST", body: {} }))
);
$("btn-complete").addEventListener("click", () =>
  act(() => api(`/api/days/${state.openDay}/toggle-complete`, { method: "POST", body: {} }))
);
$("panel-close").addEventListener("click", () => {
  state.openDay = null;
  $("panel").close();
});
$("panel").addEventListener("close", () => {
  state.openDay = null;
});

$("past-form").addEventListener("submit", (event) => {
  event.preventDefault();
  // datetime-local gives local time with no timezone; Date turns it into UTC.
  const body = {
    day_number: state.openDay,
    started_at: new Date($("past-start").value).toISOString(),
    ended_at: new Date($("past-end").value).toISOString(),
    paused_minutes: Number($("past-paused").value || 0),
  };
  act(async () => {
    await api("/api/sessions", { method: "POST", body });
    $("past-form").reset();
  });
});

// ---------------------------------------------------------------------------
// go
// ---------------------------------------------------------------------------

loadSettings()
  .then(refresh)
  .catch(showError);
setInterval(tick, 1000);
