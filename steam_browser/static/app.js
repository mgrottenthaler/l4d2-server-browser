(function () {
  "use strict";

  var STORAGE_KEY = "steamBrowser.filters.v1";
  var FAVORITES_KEY = "steamBrowser.favorites.v1";
  var COLUMN_WIDTHS_KEY = "steamBrowser.columnWidths.v1";

  var defaultFilters = {
    name: "",
    map: "",
    mode: "",
    campaign: "",
    ping: "",
    secure: "",
    notEmpty: false,
    notFull: false,
    noPassword: false,
    officialOnly: false,
    sortKey: "latency_ms",
    sortDir: "asc",
    filtersCollapsed: false,
    playersCollapsed: false,
    rulesCollapsed: true,
    technicalCollapsed: true,
    activeTab: "internet",
  };

  function favoriteKey(s) {
    return s.host + ":" + s.port;
  }

  function loadFavorites() {
    try {
      var raw = localStorage.getItem(FAVORITES_KEY);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch (e) {
      return new Set();
    }
  }

  function saveFavorites() {
    try {
      localStorage.setItem(FAVORITES_KEY, JSON.stringify(Array.from(state.favorites)));
    } catch (e) {
      /* localStorage unavailable (private mode / quota) - ignore */
    }
  }

  function loadColumnWidths() {
    try {
      var raw = localStorage.getItem(COLUMN_WIDTHS_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function saveColumnWidths(widths) {
    try {
      localStorage.setItem(COLUMN_WIDTHS_KEY, JSON.stringify(widths));
    } catch (e) {
      /* localStorage unavailable (private mode / quota) - ignore */
    }
  }

  function loadFilters() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return Object.assign({}, defaultFilters);
      var parsed = JSON.parse(raw);
      return Object.assign({}, defaultFilters, parsed);
    } catch (e) {
      return Object.assign({}, defaultFilters);
    }
  }

  function saveFilters() {
    var f = {
      name: els.name.value,
      map: els.map.value,
      mode: els.mode.value,
      campaign: els.campaign.value,
      ping: els.ping.value,
      secure: els.secure.value,
      notEmpty: els.notEmpty.checked,
      notFull: els.notFull.checked,
      noPassword: els.noPassword.checked,
      officialOnly: els.official.checked,
      sortKey: state.sortKey,
      sortDir: state.sortDir,
      filtersCollapsed: state.filtersCollapsed,
      playersCollapsed: state.playersCollapsed,
      rulesCollapsed: state.rulesCollapsed,
      technicalCollapsed: state.technicalCollapsed,
      activeTab: state.activeTab,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(f));
    } catch (e) {
      /* localStorage unavailable (private mode / quota) - ignore */
    }
  }

  var saved = loadFilters();

  var state = {
    servers: [],
    status: "idle",
    error: null,
    lastUpdated: null,
    candidateCount: 0,
    sortKey: saved.sortKey,
    sortDir: saved.sortDir,
    filtersCollapsed: saved.filtersCollapsed,
    playersCollapsed: saved.playersCollapsed,
    rulesCollapsed: saved.rulesCollapsed,
    technicalCollapsed: saved.technicalCollapsed,
    activeTab: saved.activeTab,
    favorites: loadFavorites(),
    favoriteServers: {}, // key ("host:port") -> direct-probe result, for favorites not in `servers`
    favoritesProbing: false,
    selected: null, // { host, port }
    playerQuery: null, // { key, loading, players, error }
    ruleQuery: null, // { key, loading, rules, error }
  };

  var els = {
    name: document.getElementById("f-name"),
    map: document.getElementById("f-map"),
    mode: document.getElementById("f-mode"),
    campaign: document.getElementById("f-campaign"),
    ping: document.getElementById("f-ping"),
    secure: document.getElementById("f-secure"),
    notEmpty: document.getElementById("f-not-empty"),
    notFull: document.getElementById("f-not-full"),
    noPassword: document.getElementById("f-no-password"),
    official: document.getElementById("f-official"),
    refreshBtn: document.getElementById("refresh-btn"),
    rows: document.getElementById("server-rows"),
    emptyState: document.getElementById("empty-state"),
    statusText: document.getElementById("status-text"),
    statusUpdated: document.getElementById("status-updated"),
    table: document.getElementById("server-table"),
    filterPanel: document.getElementById("filter-panel"),
    toggleFiltersBtn: document.getElementById("toggle-filters-btn"),
    filterSummary: document.getElementById("filter-summary"),
    tabInternet: document.getElementById("tab-internet"),
    tabFavorites: document.getElementById("tab-favorites"),
    sidebar: document.getElementById("server-sidebar"),
    sidebarTitle: document.getElementById("sidebar-title"),
    sidebarClose: document.getElementById("sidebar-close"),
    sidebarConnectLink: document.getElementById("sidebar-connect-link"),
    sidebarUri: document.getElementById("sidebar-uri"),
    sidebarCopy: document.getElementById("sidebar-copy"),
    sdStatus: document.getElementById("sd-status"),
    sdMode: document.getElementById("sd-mode"),
    sdCampaign: document.getElementById("sd-campaign"),
    sdMap: document.getElementById("sd-map"),
    sdPlayers: document.getElementById("sd-players"),
    sdBots: document.getElementById("sd-bots"),
    sdLatency: document.getElementById("sd-latency"),
    sdLocation: document.getElementById("sd-location"),
    sdIp: document.getElementById("sd-ip"),
    sdProtocol: document.getElementById("sd-protocol"),
    sdFolder: document.getElementById("sd-folder"),
    sdGame: document.getElementById("sd-game"),
    sidebarPlayers: document.getElementById("sidebar-players"),
    sidebarPlayersToggle: document.getElementById("sidebar-players-toggle"),
    sidebarPlayersRefresh: document.getElementById("sidebar-players-refresh"),
    sidebarPlayersCount: document.getElementById("sidebar-players-count"),
    sidebarPlayersTable: document.getElementById("sidebar-players-table"),
    sidebarPlayersRows: document.getElementById("sidebar-players-rows"),
    sidebarPlayersStatus: document.getElementById("sidebar-players-status"),
    sidebarRules: document.getElementById("sidebar-rules"),
    sidebarRulesToggle: document.getElementById("sidebar-rules-toggle"),
    sidebarRulesRefresh: document.getElementById("sidebar-rules-refresh"),
    sidebarRulesCount: document.getElementById("sidebar-rules-count"),
    sidebarRulesTable: document.getElementById("sidebar-rules-table"),
    sidebarRulesRows: document.getElementById("sidebar-rules-rows"),
    sidebarRulesStatus: document.getElementById("sidebar-rules-status"),
    sidebarTechnical: document.getElementById("sidebar-technical"),
    sidebarTechnicalToggle: document.getElementById("sidebar-technical-toggle"),
  };

  // Restore saved filter values into the form before first render.
  els.name.value = saved.name;
  els.map.value = saved.map;
  els.ping.value = saved.ping;
  // els.campaign is repopulated from live data once servers load, same as
  // els.mode; the saved value is re-applied inside populateCampaignOptions().
  els.secure.value = saved.secure;
  els.notEmpty.checked = saved.notEmpty;
  els.notFull.checked = saved.notFull;
  els.noPassword.checked = saved.noPassword;
  els.official.checked = saved.officialOnly;
  els.filterPanel.classList.toggle("collapsed", state.filtersCollapsed);
  els.sidebarPlayers.classList.toggle("collapsed", state.playersCollapsed);
  els.sidebarRules.classList.toggle("collapsed", state.rulesCollapsed);
  els.sidebarTechnical.classList.toggle("collapsed", state.technicalCollapsed);

  function applyActiveTabUI() {
    els.tabInternet.classList.toggle("active", state.activeTab === "internet");
    els.tabFavorites.classList.toggle("active", state.activeTab === "favorites");
  }
  applyActiveTabUI();
  // els.mode is repopulated from live data once servers load; the saved
  // value is re-applied inside populateModeOptions().

  var pollTimer = null;

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function pingClass(ms) {
    if (ms < 60) return "ping-good";
    if (ms < 120) return "ping-ok";
    return "ping-bad";
  }

  function playersClass(players, max) {
    if (players >= max) return "players-full";
    if (players === 0) return "players-empty";
    return "";
  }

  function formatDuration(seconds) {
    seconds = Math.max(0, Math.round(seconds || 0));
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = seconds % 60;
    var pad = function (n) { return n < 10 ? "0" + n : "" + n; };
    return h > 0 ? h + ":" + pad(m) + ":" + pad(s) : m + ":" + pad(s);
  }

  function countryFlag(countryCode) {
    if (!countryCode || countryCode.length !== 2) return "";
    var code = countryCode.toUpperCase();
    var base = 0x1F1E6; // regional indicator symbol letter A
    return String.fromCodePoint(base + (code.charCodeAt(0) - 65)) +
      String.fromCodePoint(base + (code.charCodeAt(1) - 65));
  }

  function populateModeOptions() {
    var modes = Array.from(new Set(state.servers.map(function (s) { return s.mode; })))
      .filter(function (m) { return m && m !== "-"; })
      .sort();
    var current = els.mode.value || saved.mode;
    els.mode.innerHTML = '<option value="">&lt;All&gt;</option>';
    modes.forEach(function (m) {
      var opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      els.mode.appendChild(opt);
    });
    if (modes.indexOf(current) !== -1) els.mode.value = current;
  }

  function populateCampaignOptions() {
    var campaigns = Array.from(new Set(state.servers.map(function (s) { return s.campaign; })))
      .filter(function (c) { return c && c !== "-"; })
      .sort();
    var current = els.campaign.value || saved.campaign;
    els.campaign.innerHTML = '<option value="">&lt;All&gt;</option>';
    campaigns.forEach(function (c) {
      var opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      els.campaign.appendChild(opt);
    });
    if (campaigns.indexOf(current) !== -1) els.campaign.value = current;
  }

  function buildFavoritesRows() {
    // The Favorites tab isn't just a filter over the last Internet-tab
    // refresh - a favorite can be offline, a listen server (excluded from
    // the background refresh), or simply not covered by the last refresh
    // at all. Prefer the fresher master-list-sourced entry when one exists;
    // otherwise fall back to the direct A2S probe kicked off by
    // probeFavorites() (see fetchServers()/tab-switch/refresh-button below).
    var seen = {};
    var rows = [];
    state.servers.forEach(function (s) {
      var key = favoriteKey(s);
      if (state.favorites.has(key)) {
        rows.push(s);
        seen[key] = true;
      }
    });
    state.favorites.forEach(function (key) {
      if (seen[key]) return;
      var probed = state.favoriteServers[key];
      if (probed) rows.push(probed);
    });
    return rows;
  }

  function getFiltered() {
    var nameQuery = els.name.value.trim().toLowerCase();
    var mapQuery = els.map.value.trim().toLowerCase();
    var mode = els.mode.value;
    var campaign = els.campaign.value;
    var maxPing = els.ping.value ? parseFloat(els.ping.value) : null;
    var secure = els.secure.value;
    var notEmpty = els.notEmpty.checked;
    var notFull = els.notFull.checked;
    var noPassword = els.noPassword.checked;
    var officialOnly = els.official.checked;
    var favoritesOnly = state.activeTab === "favorites";
    var source = favoritesOnly ? buildFavoritesRows() : state.servers;

    return source.filter(function (s) {
      // Offline favorites carry no server data to filter on - always show
      // them rather than have them silently vanish under an active filter.
      if (s.online === false) return true;
      if (nameQuery && s.name.toLowerCase().indexOf(nameQuery) === -1) return false;
      if (mapQuery &&
          s.map.toLowerCase().indexOf(mapQuery) === -1 &&
          s.stage.toLowerCase().indexOf(mapQuery) === -1 &&
          s.campaign.toLowerCase().indexOf(mapQuery) === -1) return false;
      if (mode && s.mode !== mode) return false;
      if (campaign && s.campaign !== campaign) return false;
      if (maxPing !== null && s.latency_ms > maxPing) return false;
      if (secure === "secure" && !s.secure) return false;
      if (secure === "insecure" && s.secure) return false;
      if (notEmpty && s.players === 0) return false;
      if (notFull && s.players >= s.max_players) return false;
      if (noPassword && s.password_protected) return false;
      if (officialOnly && s.name.toLowerCase().indexOf("valve") === -1) return false;
      return true;
    });
  }

  function sortValue(s, key) {
    if (key === "player_ratio") {
      return s.max_players > 0 ? s.players / s.max_players : 0;
    }
    return s[key];
  }

  function sortRows(rows) {
    var key = state.sortKey;
    var dir = state.sortDir === "asc" ? 1 : -1;
    rows.sort(function (a, b) {
      var va = sortValue(a, key);
      var vb = sortValue(b, key);
      if (typeof va === "string") {
        return va.localeCompare(vb) * dir;
      }
      return (va - vb) * dir;
    });
    return rows;
  }

  function isSelected(s) {
    return !!state.selected && state.selected.host === s.host && state.selected.port === s.port;
  }

  function findServer(selected) {
    if (!selected) return null;
    var match = state.servers.filter(function (s) {
      return s.host === selected.host && s.port === selected.port;
    })[0];
    if (match) return match;
    // Favorites that weren't in the last Internet refresh only exist as
    // direct-probe results in favoriteServers - without this fallback,
    // clicking such a row could never open the sidebar (and the poll loop
    // would drop its selection).
    var probed = state.favoriteServers[selected.host + ":" + selected.port];
    return probed && probed.online !== false ? probed : null;
  }

  function locationText(s) {
    var flag = countryFlag(s.country_code);
    if (s.country_name) return (flag ? flag + " " : "") + s.country_name;
    return flag || "Unknown";
  }

  function renderSidebar() {
    var s = findServer(state.selected);
    if (!s) {
      els.sidebar.hidden = true;
      return;
    }
    els.sidebar.hidden = false;
    els.sidebarTitle.textContent = s.name;
    els.sdStatus.textContent =
      (s.password_protected ? "Password protected" : "Open") +
      (s.secure ? " · VAC secured" : " · Not VAC secured");
    els.sdMode.textContent = s.mode;
    els.sdCampaign.textContent = s.campaign;
    els.sdMap.textContent = s.stage;
    els.sdPlayers.textContent = s.players + " / " + s.max_players;
    els.sdBots.textContent = s.bots || 0;
    els.sdLatency.textContent = Math.round(s.latency_ms) + " ms";
    els.sdLocation.textContent = locationText(s);
    els.sdIp.textContent = s.host + ":" + s.port;
    els.sdProtocol.textContent = s.protocol;
    els.sdFolder.textContent = s.folder;
    els.sdGame.textContent = s.game;

    var uri = "steam://connect/" + s.host + ":" + s.port;
    els.sidebarConnectLink.href = uri;
    els.sidebarUri.textContent = uri;

    renderPlayers();
    renderRules();
  }

  function patchPlayerCount(s) {
    // A live A2S_PLAYER query only refreshes one row's count, not the whole
    // list - running it through the normal render() would re-apply
    // getFiltered() (e.g. "not full"/"has users playing") using that one
    // fresher number and could yank the row the user just clicked right out
    // of view. Patch the DOM in place instead so the count updates without
    // re-filtering or re-sorting the rest of the table.
    if (isSelected(s)) {
      els.sdPlayers.textContent = s.players + " / " + s.max_players;
    }
    var row = els.rows.querySelector('tr[data-host="' + s.host + '"][data-port="' + s.port + '"]');
    if (row) {
      var cell = row.querySelector(".col-players");
      if (cell) {
        cell.textContent = s.players + "/" + s.max_players;
        cell.className = "col-players " + playersClass(s.players, s.max_players);
      }
    }
  }

  function patchServerInfo(s) {
    // Same reasoning as patchPlayerCount: patch the DOM in place rather than
    // going through render(), so a live A2S_INFO reading (map/mode/name
    // changed since the last full refresh) can't re-filter the just-clicked
    // row out of view.
    if (isSelected(s)) {
      els.sidebarTitle.textContent = s.name;
      els.sdStatus.textContent =
        (s.password_protected ? "Password protected" : "Open") +
        (s.secure ? " · VAC secured" : " · Not VAC secured");
      els.sdMode.textContent = s.mode;
      els.sdCampaign.textContent = s.campaign;
      els.sdMap.textContent = s.stage;
      els.sdBots.textContent = s.bots || 0;
      els.sdProtocol.textContent = s.protocol;
      els.sdFolder.textContent = s.folder;
      els.sdGame.textContent = s.game;
    }
    var row = els.rows.querySelector('tr[data-host="' + s.host + '"][data-port="' + s.port + '"]');
    if (row) {
      var nameCell = row.querySelector(".col-name");
      if (nameCell) nameCell.textContent = s.name;
      var modeCell = row.querySelector(".col-mode");
      if (modeCell) modeCell.textContent = s.mode;
      var campaignCell = row.querySelector(".col-campaign");
      if (campaignCell) campaignCell.textContent = s.campaign;
      var stageCell = row.querySelector(".col-stage");
      if (stageCell) stageCell.textContent = s.stage;
      var lockCell = row.querySelector(".col-lock");
      if (lockCell) lockCell.innerHTML = s.password_protected ? '<span class="lock-icon">&#128274;</span>' : "";
      var secureCell = row.querySelector(".col-secure");
      if (secureCell) secureCell.innerHTML = s.secure ? '<span class="secure-icon">&#10003;</span>' : "";
    }
    patchPlayerCount(s);
  }

  function fetchServerInfo(s) {
    var host = s.host, port = s.port;
    fetch("/api/servers/" + encodeURIComponent(host) + "/" + port + "/info")
      .then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      })
      .then(function (result) {
        if (!result.ok) return;
        if (!findServer({ host: host, port: port })) return; // stale, list moved on
        var info = result.data;
        s.name = info.name;
        s.map = info.map;
        s.campaign = info.campaign;
        s.stage = info.stage;
        s.players = info.players;
        s.max_players = info.max_players;
        s.bots = info.bots;
        s.protocol = info.protocol;
        s.folder = info.folder;
        s.game = info.game;
        s.password_protected = info.password_protected;
        s.secure = info.secure;
        s.mode = info.mode;
        patchServerInfo(s);
      })
      .catch(function () {});
  }

  function renderPlayers() {
    var q = state.playerQuery;
    if (!q) {
      els.sidebarPlayersTable.hidden = true;
      els.sidebarPlayersStatus.hidden = false;
      els.sidebarPlayersStatus.textContent = "";
      els.sidebarPlayersCount.textContent = "";
      return;
    }
    if (q.loading) {
      els.sidebarPlayersTable.hidden = true;
      els.sidebarPlayersStatus.hidden = false;
      els.sidebarPlayersStatus.textContent = "Loading…";
      els.sidebarPlayersCount.textContent = "";
      return;
    }
    if (q.error) {
      els.sidebarPlayersTable.hidden = true;
      els.sidebarPlayersStatus.hidden = false;
      els.sidebarPlayersStatus.textContent = "Couldn't load player list.";
      els.sidebarPlayersCount.textContent = "";
      return;
    }
    var players = (q.players || []).slice().sort(function (a, b) { return b.score - a.score; });
    els.sidebarPlayersCount.textContent = "(" + players.length + ")";
    if (players.length === 0) {
      els.sidebarPlayersTable.hidden = true;
      els.sidebarPlayersStatus.hidden = false;
      els.sidebarPlayersStatus.textContent = "No players connected.";
      return;
    }
    els.sidebarPlayersStatus.hidden = true;
    els.sidebarPlayersTable.hidden = false;
    els.sidebarPlayersRows.innerHTML = "";
    players.forEach(function (p) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + escapeHtml(p.name || "(unnamed)") + "</td>" +
        '<td class="col-score">' + p.score + "</td>" +
        '<td class="col-time">' + formatDuration(p.duration) + "</td>";
      els.sidebarPlayersRows.appendChild(tr);
    });
  }

  function fetchPlayers(s) {
    var key = s.host + ":" + s.port;
    state.playerQuery = { key: key, loading: true, players: null, error: null };
    renderPlayers();
    fetch("/api/servers/" + encodeURIComponent(s.host) + "/" + s.port + "/players")
      .then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      })
      .then(function (result) {
        if (!state.playerQuery || state.playerQuery.key !== key) return; // stale, selection moved on
        if (result.ok) {
          state.playerQuery = { key: key, loading: false, players: result.data.players, error: null };
          // The live A2S_PLAYER query is more current than the last full-list
          // probe, so reflect its count everywhere the player count is shown
          // (table row, sidebar summary) instead of waiting for the next poll.
          s.players = result.data.players.length;
          patchPlayerCount(s);
        } else {
          state.playerQuery = { key: key, loading: false, players: null, error: result.data.error || "Query failed" };
        }
        renderPlayers();
      })
      .catch(function () {
        if (!state.playerQuery || state.playerQuery.key !== key) return;
        state.playerQuery = { key: key, loading: false, players: null, error: "Query failed" };
        renderPlayers();
      });
  }

  function renderRules() {
    var q = state.ruleQuery;
    if (!q) {
      els.sidebarRulesTable.hidden = true;
      els.sidebarRulesStatus.hidden = false;
      els.sidebarRulesStatus.textContent = "Expand to load.";
      els.sidebarRulesCount.textContent = "";
      return;
    }
    if (q.loading) {
      els.sidebarRulesTable.hidden = true;
      els.sidebarRulesStatus.hidden = false;
      els.sidebarRulesStatus.textContent = "Loading…";
      els.sidebarRulesCount.textContent = "";
      return;
    }
    if (q.error) {
      els.sidebarRulesTable.hidden = true;
      els.sidebarRulesStatus.hidden = false;
      els.sidebarRulesStatus.textContent = "Couldn't load rules.";
      els.sidebarRulesCount.textContent = "";
      return;
    }
    var rules = (q.rules || []).slice().sort(function (a, b) {
      return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });
    els.sidebarRulesCount.textContent = "(" + rules.length + ")";
    if (rules.length === 0) {
      els.sidebarRulesTable.hidden = true;
      els.sidebarRulesStatus.hidden = false;
      els.sidebarRulesStatus.textContent = "No rules reported.";
      return;
    }
    els.sidebarRulesStatus.hidden = true;
    els.sidebarRulesTable.hidden = false;
    els.sidebarRulesRows.innerHTML = "";
    rules.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + escapeHtml(r.name) + "</td><td>" + escapeHtml(r.value) + "</td>";
      els.sidebarRulesRows.appendChild(tr);
    });
  }

  function fetchRules(s) {
    var key = s.host + ":" + s.port;
    state.ruleQuery = { key: key, loading: true, rules: null, error: null };
    renderRules();
    fetch("/api/servers/" + encodeURIComponent(s.host) + "/" + s.port + "/rules")
      .then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      })
      .then(function (result) {
        if (!state.ruleQuery || state.ruleQuery.key !== key) return; // stale, selection moved on
        if (result.ok) {
          state.ruleQuery = { key: key, loading: false, rules: result.data.rules, error: null };
        } else {
          state.ruleQuery = { key: key, loading: false, rules: null, error: result.data.error || "Query failed" };
        }
        renderRules();
      })
      .catch(function () {
        if (!state.ruleQuery || state.ruleQuery.key !== key) return;
        state.ruleQuery = { key: key, loading: false, rules: null, error: "Query failed" };
        renderRules();
      });
  }

  function renderFilterSummary() {
    var parts = [];
    if (els.name.value.trim()) parts.push('name contains "' + els.name.value.trim() + '"');
    if (els.map.value.trim()) parts.push('map contains "' + els.map.value.trim() + '"');
    if (els.mode.value) parts.push("mode = " + els.mode.value);
    if (els.campaign.value) parts.push("campaign = " + els.campaign.value);
    if (els.ping.value) parts.push("latency < " + els.ping.value);
    if (els.secure.value) parts.push(els.secure.value === "secure" ? "is secured" : "is not secured");
    if (els.notFull.checked) parts.push("is not full");
    if (els.notEmpty.checked) parts.push("is not empty");
    if (els.noPassword.checked) parts.push("has no password");
    if (els.official.checked) parts.push("is official");
    els.filterSummary.textContent = parts.length ? parts.join("; ") : "no filters applied";
  }

  function render() {
    populateModeOptions();
    populateCampaignOptions();
    var rows = sortRows(getFiltered());
    // Offline favorites carry no sortable data - keep them below whatever
    // the active sort produced instead of interleaving randomly. Array.sort
    // is spec-stable, so this doesn't disturb the primary sort order.
    rows.sort(function (a, b) {
      if (a.online === false && b.online !== false) return 1;
      if (b.online === false && a.online !== false) return -1;
      return 0;
    });

    els.rows.innerHTML = "";
    rows.forEach(function (s) {
      var tr = document.createElement("tr");
      tr.dataset.host = s.host;
      tr.dataset.port = s.port;
      if (isSelected(s)) tr.classList.add("selected");
      var favorited = state.favorites.has(favoriteKey(s));

      if (s.online === false) {
        tr.classList.add("offline");
        tr.innerHTML =
          '<td class="col-fav"><span class="fav-star favorited">&#9733;</span></td>' +
          '<td class="col-lock"></td>' +
          '<td class="col-secure"></td>' +
          '<td class="col-name">' + escapeHtml(s.host) + ":" + s.port + "</td>" +
          '<td class="col-mode">-</td>' +
          '<td class="col-campaign">-</td>' +
          '<td class="col-stage">-</td>' +
          '<td class="col-ip">' + escapeHtml(s.host) + ":" + s.port + "</td>" +
          '<td class="col-players">-</td>' +
          '<td class="col-ping offline-label">Offline</td>';
        tr.querySelector(".fav-star").addEventListener("click", function (e) {
          e.stopPropagation();
          state.favorites.delete(favoriteKey(s));
          delete state.favoriteServers[favoriteKey(s)];
          saveFavorites();
          render();
        });
        els.rows.appendChild(tr);
        return;
      }

      var flag = countryFlag(s.country_code);
      tr.innerHTML =
        '<td class="col-fav"><span class="fav-star' + (favorited ? " favorited" : "") + '">' +
          (favorited ? "★" : "☆") + "</span></td>" +
        '<td class="col-lock">' + (s.password_protected ? '<span class="lock-icon">&#128274;</span>' : "") + "</td>" +
        '<td class="col-secure">' + (s.secure ? '<span class="secure-icon">&#10003;</span>' : "") + "</td>" +
        '<td class="col-name">' + escapeHtml(s.name) + "</td>" +
        '<td class="col-mode">' + escapeHtml(s.mode) + "</td>" +
        '<td class="col-campaign">' + escapeHtml(s.campaign) + "</td>" +
        '<td class="col-stage">' + escapeHtml(s.stage) + "</td>" +
        '<td class="col-ip">' + (flag ? flag + " " : "") + escapeHtml(s.host) + ":" + s.port + "</td>" +
        '<td class="col-players ' + playersClass(s.players, s.max_players) + '">' + s.players + "/" + s.max_players + "</td>" +
        '<td class="col-ping ' + pingClass(s.latency_ms) + '">' + Math.round(s.latency_ms) + "</td>";
      tr.querySelector(".fav-star").addEventListener("click", function (e) {
        e.stopPropagation();
        var key = favoriteKey(s);
        if (state.favorites.has(key)) {
          state.favorites.delete(key);
          delete state.favoriteServers[key];
        } else {
          state.favorites.add(key);
        }
        saveFavorites();
        render();
      });
      tr.addEventListener("click", function () {
        state.selected = { host: s.host, port: s.port };
        fetchPlayers(s);
        fetchServerInfo(s);
        state.ruleQuery = null;
        if (!state.rulesCollapsed) fetchRules(s);
        render();
      });
      els.rows.appendChild(tr);
    });

    els.emptyState.hidden = rows.length !== 0;
    els.table.hidden = rows.length === 0;
    if (rows.length === 0) {
      if (state.activeTab === "favorites" && state.favorites.size === 0) {
        els.emptyState.textContent = "No favorites yet. Click the star next to a server to add it here.";
      } else if (state.activeTab === "favorites" && state.favoritesProbing) {
        els.emptyState.textContent = "Checking favorites…";
      } else if (state.activeTab === "internet" && state.status === "idle" && !state.lastUpdated) {
        els.emptyState.textContent = "Click refresh to load the server list.";
      } else {
        els.emptyState.textContent = "No servers match the current filters.";
      }
    }

    var headerCells = document.querySelectorAll("#server-table thead th");
    headerCells.forEach(function (th) {
      th.classList.remove("sorted-asc", "sorted-desc");
      if (th.dataset.key === state.sortKey) {
        th.classList.add(state.sortDir === "asc" ? "sorted-asc" : "sorted-desc");
      }
    });

    renderStatus(rows.length);
    renderFilterSummary();
    renderSidebar();
    saveFilters();
  }

  function renderStatus(shownCount) {
    var parts = [];
    if (state.activeTab === "favorites" && state.favoritesProbing) {
      parts.push("Checking favorites…");
    } else if (state.status === "refreshing") {
      parts.push(
        "Refreshing… " + state.servers.length +
        (state.candidateCount ? " of " + state.candidateCount : "") + " responded"
      );
    } else if (state.status === "error") {
      parts.push("Error: " + state.error);
    } else if (state.activeTab === "favorites") {
      parts.push("Showing " + shownCount + " favorite" + (shownCount === 1 ? "" : "s"));
    } else {
      parts.push(
        "Showing " + shownCount + " of " + state.servers.length + " responding servers" +
        (state.candidateCount ? " (" + state.candidateCount + " queried)" : "")
      );
    }
    els.statusText.textContent = parts.join(" ");
    els.statusUpdated.textContent = state.lastUpdated
      ? "Last refreshed " + new Date(state.lastUpdated * 1000).toLocaleTimeString()
      : "";

    var refreshing = state.status === "refreshing" || state.favoritesProbing;
    els.refreshBtn.classList.toggle("spinning", refreshing);
    els.refreshBtn.title = refreshing ? "Stop refreshing" : "Refresh server list";
  }

  function fetchServers() {
    return fetch("/api/servers")
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        state.servers = data.servers || [];
        state.status = data.status;
        state.error = data.error;
        state.lastUpdated = data.last_updated;
        state.candidateCount = data.candidate_count;

        // Drop the selection if that server is no longer known anywhere
        // (neither the refreshed list nor a probed favorite).
        if (state.selected && !findServer(state.selected)) {
          state.selected = null;
          state.playerQuery = null;
          state.ruleQuery = null;
        }

        render();

        if (state.status === "refreshing") {
          scheduleNextPoll();
        } else {
          clearTimeout(pollTimer);
        }
      });
  }

  function scheduleNextPoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(fetchServers, 1500);
  }

  function triggerRefresh() {
    // not_empty/not_full are the only filters Valve's master server list
    // honors server-side (secure and password filters are silently ignored
    // or broken there - see steam_api.build_filter), so pushing just these
    // two down cuts probing work dramatically without changing behavior for
    // the rest, which stay client-side and instant.
    fetch("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ not_empty: els.notEmpty.checked, not_full: els.notFull.checked }),
    }).then(function () {
      fetchServers();
    });
  }

  function probeFavorites(forceAll) {
    // Servers already present in `servers` came from the last Internet-tab
    // refresh and are at least as fresh as a direct probe would be, so by
    // default only chase down favorites that refresh didn't cover (offline,
    // a listen server, or just never queried this session). The Favorites
    // tab's own refresh button passes forceAll to re-check every favorite
    // regardless, same as clicking Refresh on the Internet tab does for it.
    var keys = Array.from(state.favorites);
    var targets = forceAll ? keys : keys.filter(function (key) {
      return !state.servers.some(function (s) { return favoriteKey(s) === key; });
    });
    if (targets.length === 0) {
      render();
      return;
    }
    state.favoritesProbing = true;
    render();
    fetch("/api/favorites/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ servers: targets }),
    })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        (data.servers || []).forEach(function (s) {
          state.favoriteServers[s.host + ":" + s.port] = s;
        });
      })
      .catch(function () { /* best-effort; leave prior favoriteServers as-is */ })
      .then(function () {
        state.favoritesProbing = false;
        render();
      });
  }

  function stopRefresh() {
    // The backend stops appending new results and flips status back to
    // idle on its own; the existing poll loop (scheduleNextPoll) picks that
    // up on its next tick, so whatever was already found stays on screen.
    fetch("/api/refresh/stop", { method: "POST" });
  }

  document.querySelectorAll("#server-table thead th[data-key]").forEach(function (th) {
    th.addEventListener("click", function () {
      if (suppressNextSortClick) {
        suppressNextSortClick = false;
        return;
      }
      var key = th.dataset.key;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = "asc";
      }
      render();
    });
  });

  // Resizable columns: a drag handle on each header's right edge adjusts
  // that <th>'s inline width; table-layout:fixed makes all cells in the
  // column follow it. The table itself is kept at width:auto (no % width)
  // and its pixel width is set explicitly here — if the table were left at
  // width:100%, the fixed-layout algorithm proportionally rescales *every*
  // column whenever one column's width changes, which is what made
  // dragging feel like it "jumped".
  var tableHeaders = document.querySelectorAll("#server-table thead th");

  function syncTableWidth() {
    var total = 0;
    tableHeaders.forEach(function (th) { total += th.offsetWidth; });
    els.table.style.width = total + "px";
  }

  function columnKey(th, index) {
    return th.dataset.key || th.className.split(" ")[0] || ("col" + index);
  }

  function persistColumnWidths() {
    var widths = {};
    tableHeaders.forEach(function (th, index) {
      widths[columnKey(th, index)] = th.offsetWidth;
    });
    saveColumnWidths(widths);
  }

  (function initColumnWidths() {
    // Bake each column's natural (CSS-declared) width in as an explicit
    // inline width so later resizes have a known starting point. Columns
    // are free to sum to less than the table-wrap's width — the table
    // simply doesn't stretch to fill it (no forced full-width scaling).
    // A previously saved width (from a resize or autofit) wins over the
    // CSS default so column sizing survives a page refresh.
    var savedWidths = loadColumnWidths();
    tableHeaders.forEach(function (th, index) {
      var saved = savedWidths[columnKey(th, index)];
      th.style.width = (saved || th.offsetWidth) + "px";
    });
    syncTableWidth();
  })();

  var resizeState = null;
  var suppressNextSortClick = false;
  var MIN_COLUMN_WIDTH = 30;

  var DRAG_THRESHOLD_PX = 3;

  function onResizeMove(e) {
    if (!resizeState) return;
    // Ignore tiny jitter so a real double-click (two clicks with a few px
    // of movement between them) doesn't get misread as a resize drag.
    if (Math.abs(e.clientX - resizeState.startX) < DRAG_THRESHOLD_PX) return;
    var newWidth = Math.max(MIN_COLUMN_WIDTH, resizeState.startWidth + (e.clientX - resizeState.startX));
    resizeState.th.style.width = newWidth + "px";
    syncTableWidth();
  }

  function onResizeEnd() {
    if (!resizeState) return;
    resizeState.handle.classList.remove("resizing");
    resizeState = null;
    suppressNextSortClick = true;
    document.removeEventListener("mousemove", onResizeMove);
    document.removeEventListener("mouseup", onResizeEnd);
    persistColumnWidths();
  }

  // scrollWidth only reveals a cell's true content width when that content
  // is currently overflowing; if the column is already wider than needed
  // (e.g. the default width, or after a previous resize), scrollWidth just
  // reports the column's own current width back, so "autofit" could never
  // shrink a too-wide column. Measure text width off-screen instead, which
  // is independent of the cell's current size in either direction.
  var measureEl = document.createElement("span");
  measureEl.style.position = "absolute";
  measureEl.style.visibility = "hidden";
  measureEl.style.whiteSpace = "nowrap";
  measureEl.style.top = "-9999px";
  document.body.appendChild(measureEl);

  function measureTextWidth(text, sampleEl) {
    measureEl.style.font = getComputedStyle(sampleEl).font;
    measureEl.textContent = text;
    return measureEl.getBoundingClientRect().width;
  }

  function autofitColumn(th) {
    var index = Array.prototype.indexOf.call(th.parentElement.children, th);
    var cs = getComputedStyle(th);
    var horizontalPadding = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
    var maxTextWidth = measureTextWidth(th.textContent, th);
    els.rows.querySelectorAll("tr").forEach(function (tr) {
      var cell = tr.children[index];
      if (cell) maxTextWidth = Math.max(maxTextWidth, measureTextWidth(cell.textContent, cell));
    });
    th.style.width = Math.max(MIN_COLUMN_WIDTH, Math.ceil(maxTextWidth + horizontalPadding) + 2) + "px";
    syncTableWidth();
    persistColumnWidths();
  }

  // Native "dblclick" pairs two "click" events using the browser's own
  // distance/timing tolerance, which our mousedown/mouseup drag-tracking
  // listeners on the same 9px handle seem to throw off in practice. Pair
  // clicks ourselves instead, purely by time, so a little pointer drift
  // between the two clicks never stops it from registering.
  var DOUBLE_CLICK_MS = 450;
  var lastClick = { handle: null, time: 0 };

  tableHeaders.forEach(function (th) {
    var handle = document.createElement("span");
    handle.className = "col-resizer";
    handle.addEventListener("mousedown", function (e) {
      e.preventDefault();
      e.stopPropagation();
      resizeState = { th: th, handle: handle, startX: e.clientX, startWidth: th.offsetWidth };
      handle.classList.add("resizing");
      document.addEventListener("mousemove", onResizeMove);
      document.addEventListener("mouseup", onResizeEnd);
    });
    handle.addEventListener("click", function (e) {
      var now = Date.now();
      if (lastClick.handle === handle && now - lastClick.time < DOUBLE_CLICK_MS) {
        e.preventDefault();
        e.stopPropagation();
        autofitColumn(th);
        suppressNextSortClick = true;
        lastClick = { handle: null, time: 0 };
      } else {
        lastClick = { handle: handle, time: now };
      }
    });
    th.appendChild(handle);
  });

  [els.name, els.map].forEach(function (el) {
    el.addEventListener("input", render);
  });
  // The saved.mode/saved.campaign fallbacks in populateModeOptions()/
  // populateCampaignOptions() exist only to restore a persisted selection
  // once options arrive from live data; drop them as soon as the user
  // touches the select (registered before the render listeners below so
  // the very render triggered by the change already ignores them) -
  // otherwise choosing <All> ("") falls through "value || saved" back to
  // the stale saved value and the filter snaps right back.
  els.mode.addEventListener("change", function () { saved.mode = ""; });
  els.campaign.addEventListener("change", function () { saved.campaign = ""; });
  [els.mode, els.campaign, els.ping, els.secure, els.noPassword, els.official].forEach(function (el) {
    el.addEventListener("change", render);
  });
  // These two are pushed to the Valve query itself (see triggerRefresh), so
  // toggling them needs a fresh fetch+probe cycle, not just a re-render.
  [els.notEmpty, els.notFull].forEach(function (el) {
    el.addEventListener("change", triggerRefresh);
  });

  document.querySelectorAll(".info-icon").forEach(function (el) {
    // Prevent the tooltip icon from also toggling its parent <label>'s checkbox.
    el.addEventListener("click", function (e) { e.preventDefault(); });
  });

  els.refreshBtn.addEventListener("click", function () {
    if (state.status === "refreshing") {
      stopRefresh();
    } else if (state.activeTab === "favorites") {
      probeFavorites(true);
    } else {
      triggerRefresh();
    }
  });

  [els.tabInternet, els.tabFavorites].forEach(function (tab) {
    tab.addEventListener("click", function () {
      state.activeTab = tab.dataset.tab;
      applyActiveTabUI();
      if (state.activeTab === "favorites") {
        probeFavorites(false);
      } else {
        render();
      }
    });
  });

  els.toggleFiltersBtn.addEventListener("click", function () {
    state.filtersCollapsed = !state.filtersCollapsed;
    els.filterPanel.classList.toggle("collapsed", state.filtersCollapsed);
    saveFilters();
  });

  els.sidebarClose.addEventListener("click", function () {
    state.selected = null;
    state.playerQuery = null;
    state.ruleQuery = null;
    render();
  });

  els.sidebarPlayersToggle.addEventListener("click", function () {
    state.playersCollapsed = !state.playersCollapsed;
    els.sidebarPlayers.classList.toggle("collapsed", state.playersCollapsed);
    saveFilters();
  });

  els.sidebarPlayersRefresh.addEventListener("click", function (e) {
    e.stopPropagation();
    var s = findServer(state.selected);
    if (s) fetchPlayers(s);
  });

  els.sidebarRulesToggle.addEventListener("click", function () {
    state.rulesCollapsed = !state.rulesCollapsed;
    els.sidebarRules.classList.toggle("collapsed", state.rulesCollapsed);
    saveFilters();
    if (!state.rulesCollapsed) {
      var s = findServer(state.selected);
      var key = s ? s.host + ":" + s.port : null;
      if (s && (!state.ruleQuery || state.ruleQuery.key !== key)) fetchRules(s);
    }
  });

  els.sidebarRulesRefresh.addEventListener("click", function (e) {
    e.stopPropagation();
    var s = findServer(state.selected);
    if (s) fetchRules(s);
  });

  els.sidebarTechnicalToggle.addEventListener("click", function () {
    state.technicalCollapsed = !state.technicalCollapsed;
    els.sidebarTechnical.classList.toggle("collapsed", state.technicalCollapsed);
    saveFilters();
  });

  els.sidebarCopy.addEventListener("click", function () {
    var uri = els.sidebarUri.textContent;
    if (uri && navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(uri);
    }
  });

  fetchServers();
  if (state.activeTab === "favorites") {
    probeFavorites(false);
  }
})();
