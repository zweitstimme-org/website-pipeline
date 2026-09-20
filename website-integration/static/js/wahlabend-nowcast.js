(function () {
  'use strict';

  function siteBase() {
    if (window.pipelineData && typeof window.pipelineData.siteBase === 'function') {
      return window.pipelineData.siteBase();
    }
    if (window.pipelineData && window.pipelineData.SITE_BASE) {
      return String(window.pipelineData.SITE_BASE).replace(/\/?$/, '/');
    }
    var path = window.location.pathname || '/';
    // Do not use the literal '/preview/' — gh-pages path rewriting would
    // turn it into '/website-pipeline/preview/' and slice the base to '/'.
    var m = path.match(/^(.*?\/)preview(?:\/|$)/);
    if (m) return m[1];
    return '/';
  }

  function dataUrl(name) {
    return siteBase() + 'data/' + name;
  }

  function stampLogo(ctx, cssW, cssH) {
    if (typeof window.drawZweitstimmeWatermark !== 'function' || !ctx) return;
    window.drawZweitstimmeWatermark(ctx, {
      left: 0,
      top: 0,
      right: cssW,
      bottom: cssH
    }, {
      anchor: 'top-right',
      maxWidth: 156,
      maxHeight: 28,
      pad: 6,
      opacity: 0.55
    });
  }

  function allowedLands() {
    var root = $('wahlabend-root');
    var raw = root && root.getAttribute('data-wb-lands');
    if (raw) {
      return String(raw).split(',').map(function (s) {
        return s.trim().toLowerCase();
      }).filter(function (s) { return s === 'st' || s === 'be' || s === 'mv'; });
    }
    return ['st', 'be', 'mv'];
  }

  function defaultLand() {
    var root = $('wahlabend-root');
    var d = root && root.getAttribute('data-wb-default-land');
    if (d) d = String(d).toLowerCase();
    var allowed = allowedLands();
    if (d && allowed.indexOf(d) >= 0) return d;
    return allowed[0] || 'st';
  }

  function landFromQuery() {
    var root = $('wahlabend-root');
    var locked = root && root.getAttribute('data-wb-lock-land');
    if (locked) return String(locked).toLowerCase();
    var q = new URLSearchParams(window.location.search || '');
    var s = (q.get('state') || q.get('land') || '').toLowerCase();
    var allowed = allowedLands();
    if (s && allowed.indexOf(s) >= 0) return s;
    return defaultLand();
  }

  function isLivePage() {
    var root = $('wahlabend-root');
    return !!(root && root.getAttribute('data-wb-live') === '1');
  }

  function replayFileForLand(land) {
    if (isLivePage() && land === 'be') return 'wahlabend_nowcast_be_live.json';
    if (isLivePage() && land === 'mv') return 'wahlabend_nowcast_mv_live.json';
    if (isLivePage() && land === 'st') return 'wahlabend_nowcast_st_live.json';
    if (land === 'st') return 'wahlabend_nowcast_st.json';
    if (land === 'mv') return 'wahlabend_nowcast_mv.json';
    return 'wahlabend_nowcast_replay.json';
  }

  function fallbackFileForLand(land) {
    if (land === 'be') return 'wahlabend_nowcast_replay.json';
    if (land === 'mv') return 'wahlabend_nowcast_mv.json';
    return 'wahlabend_nowcast_st.json';
  }

  function applyPartyOrderFromData(data) {
    var from = (data && data.parties) || [];
    from.forEach(function (p) {
      if (PARTIES_ORDER.indexOf(p) < 0) {
        var i = PARTIES_ORDER.indexOf('others');
        if (i >= 0) PARTIES_ORDER.splice(i, 0, p);
        else PARTIES_ORDER.push(p);
      }
    });
  }

  var SCENARIO_LABELS = {
    actual_times: 'AfS-Zeiten (_W_ Datum/Zeit)',
    urne_first: 'Urne zuerst, dann Brief (Bias)',
    random: 'Zufällig (wenig Bias)',
    small_first: 'Kleine Bezirke zuerst',
    green_first: 'Grüne Hochburgen zuerst (Bias)',
    cdu_first: 'CDU-Hochburgen zuerst (Bias)'
  };

  var SCOPE_LABELS = {
    zweit: 'Zweitstimme',
    lage: 'Szenarien',
    land: 'Listen',
    wkr: 'Wahlkreise'
  };

  // Berlin 2026: nur CDU/SPD/Linke mit Bezirkslisten; Grüne/AfD/FDP/BSW = Landesliste.
  var BEZIRKSLISTE_PARTIES = ['spd', 'cdu', 'linke'];
  var BEZIRKSLISTE_LABEL = 'CDU/SPD/Linke';

  var PARTIES_ORDER = ['cdu', 'spd', 'gruene', 'linke', 'afd', 'fdp', 'bsw', 'others'];

  var state = {
    data: null,
    land: 'st',
    scenario: 'actual_times',
    scope: 'zweit',
    unit: 'BE',
    partyFocus: null,
    step: 10,
    openBezirk: {},
    openWkr: {},
    showZeroScenarios: false,
    wkrSearch: '',
    external: null
  };

  var PARTY_ALIAS = {
    cdu: 'cdu', spd: 'spd', afd: 'afd', fdp: 'fdp', bsw: 'bsw',
    gru: 'gruene', gruene: 'gruene', lin: 'linke', linke: 'linke',
    oth: 'others', others: 'others'
  };

  var PARTY_COLORS = {
    cdu: '#111111',
    spd: '#E3000F',
    gruene: '#64A12D',
    linke: '#BE3075',
    afd: '#009EE0',
    fdp: '#C4A000',
    bsw: '#7878C8',
    others: '#8a8a8a'
  };

  function $(id) { return document.getElementById(id); }

  function hasBezirkslisten() {
    var f = state.data && state.data.features;
    if (f && typeof f.bezirkslisten === 'boolean') return f.bezirkslisten;
    return state.land === 'be' &&
      ((state.data && state.data.geo_units && state.data.geo_units.bezirk) || []).length > 0;
  }

  function hasListenEinzug() {
    var f = state.data && state.data.features;
    if (f && typeof f.listen_einzug === 'boolean') return f.listen_einzug;
    return state.land === 'be';
  }

  function listenModeLabel() {
    var mode = state.data && state.data.listen_mode;
    if (mode === 'landes') return 'Landeslisten';
    if (mode === 'berlin_mixed') return 'Landes- und Bezirkslisten';
    return hasBezirkslisten() ? 'Landes- und Bezirkslisten' : 'Landeslisten';
  }

  /** German decimal: 1,2 instead of 1.2 */
  function fmtNum(x, digits) {
    if (x == null || !isFinite(x)) return '—';
    return Number(x).toFixed(digits).replace('.', ',');
  }

  function fmtPct(x) {
    if (x == null || !isFinite(x)) return '—';
    return fmtNum(x, 1) + '\u00a0%';
  }

  /** Official last-election turnout / size (amtliches Endergebnis). */
  function lastElectionRef() {
    var d = state.data || {};
    var fromJson = d.last_election;
    if (fromJson && (fromJson.turnout != null || fromJson.parliament_size != null || fromJson.size != null)) {
      return {
        year: fromJson.year,
        label: fromJson.label || String(fromJson.year || 'letzte Wahl'),
        turnout: fromJson.turnout,
        parliament_size: fromJson.parliament_size != null
          ? fromJson.parliament_size
          : fromJson.size
      };
    }
    var land = state.land;
    var el = String(d.election || '');
    var live = /2026/.test(el);
    if (live) {
      if (land === 'be') return { year: 2023, label: 'AGH 2023', turnout: 62.9, parliament_size: 159 };
      if (land === 'st') return { year: 2021, label: 'LTW 2021', turnout: 60.3, parliament_size: 97 };
      if (land === 'mv') return { year: 2021, label: 'LTW 2021', turnout: 70.8, parliament_size: 79 };
    }
    if (land === 'be' || el === 'AGH2023') {
      return { year: 2016, label: 'AGH 2016', turnout: 66.9, parliament_size: 160 };
    }
    if (land === 'st') {
      return { year: 2016, label: 'LTW 2016', turnout: 61.1, parliament_size: 87 };
    }
    if (land === 'mv') {
      return { year: 2016, label: 'LTW 2016', turnout: 61.6, parliament_size: 71 };
    }
    return null;
  }

  function lastElectionShort(ref) {
    if (!ref) return 'letzte Wahl';
    return ref.year != null ? String(ref.year) : (ref.label || 'letzte Wahl');
  }

  function uncLandNote(s) {
    var frac = (s && s.frac_reported) || 0;
    var fromJson = s && s.uncertainty_note && s.uncertainty_note.land;
    if (frac >= 0.999) return '± = 0: das Land ist ausgezählt.';
    if (fromJson && isLivePage()) {
      if (frac <= 0) {
        return fromJson + ' Gerade: noch 100 % Prognose, 0 % Live.';
      }
      return fromJson;
    }
    return '± = offener Stimmenanteil × Ausgangslage-Band. Kein formales Konfidenzintervall.';
  }

  function uncWkrNote(r) {
    var frac = (r && r.frac_reported) || 0;
    var st = steps();
    var s = st.length ? st[Math.min(state.step, st.length - 1)] : null;
    var fromJson = s && s.uncertainty_note && s.uncertainty_note.wkr;
    if (frac >= 0.999) return '± = 0: dieser Wahlkreis ist ausgezählt.';
    if (fromJson) {
      if (frac <= 0) {
        return fromJson + ' Noch keine Meldung in diesem Kreis — volle Regressionsunsicherheit.';
      }
      return fromJson;
    }
    return '± in diesem WK kommt aus der Wahlkreis-Prognose, nicht aus dem Landesband.';
  }

  function drawHRef(ctx, pad, w, yAt, value, text, color) {
    if (value == null || !isFinite(value)) return;
    var y = yAt(value);
    ctx.strokeStyle = color || '#8a6d3b';
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + w, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color || '#8a6d3b';
    ctx.font = '11px system-ui,sans-serif';
    ctx.fillText(text, pad.l + 6, y - 4);
  }

  /** Statewide list-vote threshold (Sperrklausel). Landtag / AGH: 5 %. */
  function drawHurdleLine(ctx, pad, w, yAt, yMin, yMax) {
    var h = 5;
    if (yMin != null && !(h > yMin)) return;
    if (yMax != null && !(h < yMax)) return;
    drawHRef(ctx, pad, w, yAt, h, '5%-Hürde', '#888');
  }

  /** German integer with thousands separator (1.234.567). */
  function fmtInt(x) {
    if (x == null || !isFinite(x)) return '—';
    return Math.round(x).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  function fmtPp(x) {
    if (x == null || !isFinite(x)) return '—';
    return (x >= 0 ? '+' : '') + fmtNum(x, 2) + '\u00a0PP';
  }

  var PARTY_SHORT = {
    cdu: 'CDU', spd: 'SPD', gruene: 'Grüne', linke: 'Linke',
    afd: 'AfD', fdp: 'FDP', bsw: 'BSW', others: 'Andere'
  };

  function partyShort(p) {
    if (!p) return '—';
    if (PARTY_SHORT[p]) return PARTY_SHORT[p];
    var labels = (state.data && state.data.party_labels) || {};
    return labels[p] || p;
  }

  /** P(Führung hält) als Anzeige: >99,9 % statt 100 %. */
  function fmtProb(x) {
    if (x == null || !isFinite(x)) return '—';
    if (x >= 0.9995) return '>99,9\u00a0%';
    if (x <= 0.0005) return '<0,1\u00a0%';
    return fmtNum(x * 100, 1) + '\u00a0%';
  }

  function fmtClockShort(clock) {
    if (!clock) return null;
    var m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(String(clock));
    if (!m) return String(clock);
    var hm = m[4] + ':' + m[5];
    // Wahlabend / früher Morgen: nur Uhrzeit; sonst Datum + Uhrzeit
    if (m[2] === '02' && (m[3] === '12' || m[3] === '13')) return hm;
    return m[3] + '.' + m[2] + '. ' + hm;
  }

  /** scope: 'land' | 'wkr' | null — makes “ausgezählt” unambiguous. */
  function fmtFracPct(frac, scope) {
    if (frac == null || !isFinite(frac)) return null;
    var pct = Math.round(frac * 100) + '\u00a0%';
    if (scope === 'land') return pct + ' Land ausgezählt';
    if (scope === 'wkr') return pct + ' WK ausgezählt';
    return pct + ' ausgezählt';
  }

  /** Primär Uhrzeit, sekundär Auszählungsstand. */
  function fmtWhen(clock, frac, src, scope) {
    var t = fmtClockShort(clock);
    var f = fmtFracPct(frac, scope);
    var sim = (src === 'simulated' && t) ? ' (sim.)' : '';
    if (t && f) return t + sim + ' · ' + f;
    if (t) return t + sim;
    return f || '—';
  }

  function stepWhen(s, scope) {
    if (!s) return '—';
    return fmtWhen(s.clock, s.frac_reported, s.clock_source, scope || 'land');
  }

  function callWhen(call) {
    if (!call) return null;
    // Call-Zeitpunkt am landesweiten Auszählungsstand verankert
    return fmtWhen(call.called_at_clock, call.called_at, call.called_at_clock_source, 'land');
  }

  function likelyWhen(call) {
    if (!call || call.likely_at == null) return null;
    return fmtWhen(call.likely_at_clock, call.likely_at, call.likely_at_clock_source, 'land');
  }

  /** Nur Uhrzeit (für „voll ausgezählt seit …“). */
  function clockOnly(clock, src) {
    var t = fmtClockShort(clock);
    if (!t) return null;
    return t + (src === 'simulated' ? ' (sim.)' : '');
  }

  function completeWhen(call) {
    if (!call || call.complete_at == null) return null;
    return clockOnly(call.complete_at_clock, call.complete_at_clock_source) ||
      fmtFracPct(call.complete_at);
  }

  function isCompleteNow(r, call, s) {
    if (r && (r.complete || (r.frac_reported != null && r.frac_reported >= 0.999))) {
      return true;
    }
    if (!call || call.complete_at == null || !s) return false;
    return call.complete_at <= (s.frac_reported || 0) + 1e-9;
  }

  /** Land voll ausgezählt — erst dann Endstände im Live-Dashboard zeigen. */
  function isLandComplete(s) {
    return !!(s && s.frac_reported != null && s.frac_reported >= 0.999);
  }

  function isWkrComplete(s, wkrId) {
    if (!s || !wkrId) return false;
    var r = (s.by_wkr && s.by_wkr[wkrId]) || {};
    return isCompleteNow(r, wkrCalls()[wkrId] || {}, s);
  }

  /** 'called' | 'likely' | 'open' — wahrscheinlich auch ohne lokale Auszählung. */
  function callTier(r) {
    if (!r) return 'open';
    if (r.called) return 'called';
    if (r.likely) return 'likely';
    var thr = (state.data && state.data.call_threshold) || 0.90;
    if ((r.p_lead || 0) >= thr) return 'likely';
    return 'open';
  }

  function wkrCalls() {
    var b = scenarioBundle();
    if (b && b.wkr_calls) return b.wkr_calls;
    return (state.data && state.data.wkr_calls) || {};
  }

  /** Anzeige der Generierungszeit (Europe/Berlin), Sekunden. */
  function formatBerlin(isoOrLocal) {
    if (!isoOrLocal) return '—';
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(isoOrLocal)) {
      return isoOrLocal + ' (Berlin)';
    }
    var d = new Date(isoOrLocal);
    if (isNaN(d.getTime())) return String(isoOrLocal);
    var parts = new Intl.DateTimeFormat('sv-SE', {
      timeZone: 'Europe/Berlin',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false
    }).formatToParts(d);
    var get = function (t) {
      var p = parts.find(function (x) { return x.type === t; });
      return p ? p.value : '';
    };
    return get('year') + '-' + get('month') + '-' + get('day') + ' ' +
      get('hour') + ':' + get('minute') + ':' + get('second') + ' (Berlin)';
  }

  function scenarioBundle() {
    if (!state.data) return null;
    return (state.data.scenarios || {})[state.scenario] || null;
  }

  function steps() {
    var b = scenarioBundle();
    var raw = (b && b.steps && b.steps.length)
      ? b.steps
      : ((state.data && state.data.steps) || []);
    return sanitizeNightSteps(raw);
  }

  /** Live x = counted share: a 0 % step after a counted one draws a second fan. */
  function sanitizeNightSteps(raw) {
    var list = (raw || []).filter(Boolean).slice();
    list.sort(function (a, b) {
      var fa = Number(a.frac_reported) || 0;
      var fb = Number(b.frac_reported) || 0;
      if (fa !== fb) return fa - fb;
      var na = Number(a.n_reported) || 0;
      var nb = Number(b.n_reported) || 0;
      if (na !== nb) return na - nb;
      return String(a.clock || '').localeCompare(String(b.clock || ''));
    });
    var keep = [];
    var bestF = -1;
    var bestN = -1;
    list.forEach(function (s) {
      var f = Number(s.frac_reported) || 0;
      var n = Number(s.n_reported) || 0;
      if (keep.length) {
        var last = keep[keep.length - 1];
        var lf = Number(last.frac_reported) || 0;
        var ln = Number(last.n_reported) || 0;
        if (Math.abs(lf - f) < 1e-6 && ln === n) {
          keep[keep.length - 1] = s;
          return;
        }
      }
      if (f < bestF - 1e-6 || (Math.abs(f - bestF) < 1e-6 && n < bestN)) return;
      keep.push(s);
      if (f > bestF + 1e-6 || n > bestN) {
        bestF = f;
        bestN = n;
      }
    });
    return keep;
  }

  function unitLabel(scope, unitId) {
    var catalog = (state.data && state.data.geo_units) || {};
    var list = catalog[scope] || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === unitId) return list[i].label;
    }
    return unitId;
  }

  /** Split "01 · Mitte" into code + name for Wahlkreis-tile group headers. */
  function bezirkHeadParts(bid) {
    if (!bid || bid === '?') return { code: '', name: 'Ohne Bezirk' };
    var label = String(unitLabel('bezirk', bid) || bid);
    var m = label.match(/^(\d{2})\s*[·.•\-–]\s*(.+)$/);
    if (m) return { code: m[1], name: m[2] };
    if (label !== bid) return { code: String(bid), name: label };
    return { code: String(bid), name: '' };
  }

  function viewForStep(s) {
    if (!s) return null;
    var staticRoot = (state.data && state.data.geo_static) || {};
    if (state.scope === 'bezirk' && s.by_bezirk && s.by_bezirk[state.unit]) {
      var zb = s.by_bezirk[state.unit];
      var sb = (staticRoot.bezirk || {})[state.unit] || {};
      return {
        frac_reported: zb.frac_reported,
        n_reported: zb.n_reported,
        n_total: sb.n_total,
        nowcast: zb.nowcast,
        naive: zb.naive,
        prior: sb.prior,
        truth: sb.truth,
        mae_nowcast: zb.mae_nowcast,
        mae_naive: zb.mae_naive,
        mae_prior: sb.mae_prior,
        uncertainty: zb.uncertainty || null,
        methodNote: null
      };
    }
    if (state.scope === 'wkr' && s.by_wkr && s.by_wkr[state.unit]) {
      var zw = s.by_wkr[state.unit];
      var sw = (staticRoot.wkr || {})[state.unit] || {};
      return {
        frac_reported: zw.frac_reported,
        n_reported: zw.n_reported,
        n_total: sw.n_total,
        nowcast: zw.nowcast,
        naive: zw.naive,
        prior: sw.prior,
        truth: sw.truth,
        mae_nowcast: zw.mae_nowcast,
        mae_naive: zw.mae_naive,
        mae_prior: sw.mae_prior,
        uncertainty: zw.uncertainty || null,
        methodNote: null
      };
    }
    var land = {
      frac_reported: s.frac_reported,
      n_reported: s.n_reported,
      n_total: s.n_total,
      nowcast: s.nowcast,
      naive: s.naive,
      prior: s.prior || s.baseline,
      truth: s.truth,
      mae_nowcast: s.mae_nowcast,
      mae_naive: s.mae_naive,
      mae_prior: s.mae_prior != null ? s.mae_prior : s.mae_baseline,
      uncertainty: s.uncertainty || null,
      methodNote: null
    };
    return land;
  }

  function ensureUnit() {
    if (!state.data) return;
    if (state.scope === 'land' && !hasListenEinzug()) {
      state.scope = 'zweit';
    }
    if (state.scope === 'zweit' || state.scope === 'lage' || state.scope === 'land') {
      state.unit = 'BE';
      return;
    }
    var list = ((state.data.geo_units || {})[state.scope]) || [];
    var ids = list.map(function (u) { return String(u.id); });
    var cur = state.unit != null ? String(state.unit) : '';
    if (state.scope === 'wkr') {
      // Kein Auto-Pick: erst Tiles/Hub, bis ein WK gewählt ist.
      if (cur && ids.indexOf(cur) < 0) state.unit = '';
      return;
    }
    if (ids.indexOf(cur) < 0) {
      state.unit = ids[0] || '';
    }
  }

  function renderScopeButtons() {
    var tabs = $('wb-scope-tabs');
    if (!tabs) return;
    tabs.querySelectorAll('[data-scope]').forEach(function (btn) {
      var scope = btn.getAttribute('data-scope');
      if (scope === 'land') btn.hidden = !hasListenEinzug();
      btn.classList.toggle('is-active', scope === state.scope);
    });
  }

  function renderSubnav() {
    var el = $('wb-subnav');
    if (!el || !state.data) return;

    if (state.scope === 'lage') {
      el.innerHTML =
        '<p class="wb-subnav-label">Politische Szenarien und Parlamentsgröße (landesweit)</p>';
      return;
    }

    if (state.scope === 'zweit' || state.scope === 'land') {
      var labels = state.data.party_labels || {};
      var chips = '<button type="button" class="wb-sub-btn' +
        (!state.partyFocus ? ' is-active' : '') +
        '" data-party="">Alle</button>' +
        PARTIES_ORDER.map(function (p) {
          var col = PARTY_COLORS[p] || '#888';
          var active = state.partyFocus === p;
          return '<button type="button" class="wb-sub-btn has-party' +
            (active ? ' is-active' : '') +
            '" data-party="' + p + '" style="border-left-color:' + col + ';">' +
            escapeHtml(labels[p] || partyShort(p)) + '</button>';
        }).join('');
      el.innerHTML =
        '<p class="wb-subnav-label">' +
          (state.scope === 'zweit' ? 'Partei (Chart-Fokus)' : 'Partei (Listenplätze)') +
        '</p>' +
        '<div class="wb-sub-chips">' + chips + '</div>';
      return;
    }

    // Wahlkreise: Tiles als Unterauswahl
    var st = steps();
    if (!st.length) {
      el.innerHTML = '<p class="wb-subnav-label">Wahlkreis wählen</p>';
      return;
    }
    var s = st[Math.min(state.step, st.length - 1)];
    var races = collectWkrRaces(s);
    if (!races.length) {
      el.innerHTML = '<p class="wb-meta">Keine Wahlkreisdaten.</p>';
      return;
    }
    var nCalled = 0, nLikely = 0, nOpen = 0;
    races.forEach(function (x) {
      if (x.called) nCalled++;
      else if (x.likely) nLikely++;
      else nOpen++;
    });
    var byBez = {};
    races.forEach(function (x) {
      var bid = x.bezirk || '?';
      if (!byBez[bid]) byBez[bid] = [];
      byBez[bid].push(x);
    });
    var bezirkIds = Object.keys(byBez).sort();
    var showBezirkGroups = bezirkIds.some(function (id) { return id && id !== '?'; });
    var tilesHtml = '';
    function appendTiles(list) {
      list.slice().sort(function (a, b) {
        return Number(a.id) - Number(b.id);
      }).forEach(function (x) {
        tilesHtml += wkrTileHtml(x);
      });
    }
    if (!showBezirkGroups) {
      appendTiles(races);
    } else {
      bezirkIds.forEach(function (bid) {
        var head = bezirkHeadParts(bid);
        var title = [head.code, head.name].filter(Boolean).join(' · ');
        tilesHtml += '<div class="wb-wkr-bez-group" data-bez="' + escapeHtml(bid) + '">' +
          '<span class="wb-wkr-bez-head" title="' + escapeHtml(title) + '">' +
            (head.code
              ? '<span class="wb-wkr-bez-code">' + escapeHtml(head.code) + '</span>'
              : '') +
            (head.name
              ? '<span class="wb-wkr-bez-name">' + escapeHtml(head.name) + '</span>'
              : '') +
          '</span>' +
          '<div class="wb-wkr-bez-tiles">';
        appendTiles(byBez[bid]);
        tilesHtml += '</div></div>';
      });
    }
    el.innerHTML =
      '<p class="wb-subnav-label">Wahlkreis' +
        (state.unit ? '' : ' — Tiles antippen') + '</p>' +
      '<div class="wb-wkr-search-row">' +
        '<input type="search" id="wb-wkr-search" class="wb-wkr-search" ' +
        'placeholder="WK-Nr., Bezirk, Name …" autocomplete="off" ' +
        'value="' + escapeHtml(state.wkrSearch || '') + '">' +
        '<span class="wb-wkr-search-hint wb-art" id="wb-wkr-search-hint"></span>' +
      '</div>' +
      '<div class="wb-wkr-tile-legend">' +
        '<span><i class="wb-wkr-tile-swatch is-called"></i> gecallt</span>' +
        '<span><i class="wb-wkr-tile-swatch is-likely"></i> wahrscheinlich</span>' +
        '<span><i class="wb-wkr-tile-swatch is-open"></i> offen</span>' +
        '<span class="wb-art">' + nCalled + ' Call · ' + nLikely +
          ' wahrsch. · ' + nOpen + ' offen</span>' +
      '</div>' +
      '<div class="wb-wkr-tiles' +
        (showBezirkGroups ? ' wb-wkr-tiles-grouped' : '') + '">' +
        tilesHtml + '</div>';
    bindWkrLinks(el);
    applyWkrSearchFilter();
  }

  function normSearch(s) {
    return String(s || '').toLowerCase()
      .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue')
      .replace(/ß/g, 'ss').trim();
  }

  function wkrSearchHaystack(x) {
    var bezLabel = unitLabel('bezirk', x.bezirk || '');
    var parts = shortWkrLabel(x.label, x.id);
    return normSearch([
      x.id,
      parts.num,
      parts.rest,
      x.label,
      x.bezirk,
      bezLabel,
      x.party ? partyShort(x.party) : ''
    ].join(' '));
  }

  function applyWkrSearchFilter() {
    var wrap = $('wb-subnav');
    if (!wrap || state.scope !== 'wkr') return;
    var q = normSearch(state.wkrSearch);
    var tiles = wrap.querySelectorAll('.wb-wkr-tile');
    var groups = wrap.querySelectorAll('.wb-wkr-bez-group');
    var n = 0;
    tiles.forEach(function (tile) {
      var hay = tile.getAttribute('data-search') || '';
      var show = !q || hay.indexOf(q) >= 0;
      tile.hidden = !show;
      if (show) n++;
    });
    groups.forEach(function (g) {
      var visible = false;
      g.querySelectorAll('.wb-wkr-tile').forEach(function (tile) {
        if (!tile.hidden) visible = true;
      });
      g.hidden = !!q && !visible;
    });
    var hint = $('wb-wkr-search-hint');
    if (hint) {
      if (!q) hint.textContent = '';
      else if (!n) hint.textContent = 'Keine Treffer';
      else hint.textContent = n + (n === 1 ? ' Treffer' : ' Treffer');
    }
  }

  function setScope(scope) {
    if (!scope || scope === state.scope) {
      renderScopeButtons();
      return;
    }
    if (scope !== 'wkr') state.wkrSearch = '';
    state.scope = scope;
    ensureUnit();
    renderScopeButtons();
    renderStep();
  }

  function drawLineChart(canvasId, seriesA, seriesB, opts) {
    opts = opts || {};
    var canvas = $(canvasId);
    if (!canvas || !state.data) return;
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 900;
    var cssH = 220;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    var n = seriesA.length;
    if (!n) return;
    var pad = { l: 36, r: 12, t: 16, b: 28 };
    var w = cssW - pad.l - pad.r;
    var h = cssH - pad.t - pad.b;
    var yMin = opts.yMin != null ? opts.yMin : 0;
    var yMax = opts.yMax != null ? opts.yMax : Math.max(1, Math.max.apply(null, seriesA.concat(seriesB)) * 1.15);
    if (yMax <= yMin) yMax = yMin + 1;

    function xAt(i) { return pad.l + (i / Math.max(1, n - 1)) * w; }
    function yAt(v) { return pad.t + (1 - (v - yMin) / (yMax - yMin)) * h; }

    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.stroke();

    ctx.fillStyle = '#888';
    ctx.font = '11px system-ui,sans-serif';
    ctx.fillText('0\u00a0%', pad.l, cssH - 8);
    ctx.fillText('100\u00a0%', pad.l + w - 28, cssH - 8);
    var topLabel = opts.pctAxis
      ? Math.round(yMax * 100) + '\u00a0%'
      : fmtNum(yMax, 1) + ' PP';
    ctx.fillText(topLabel, 4, pad.t + 10);

    function strokeSeries(arr, color) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      arr.forEach(function (v, i) {
        var x = xAt(i), y = yAt(v);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
    strokeSeries(seriesB, '#c45c26');
    strokeSeries(seriesA, '#1a1a1a');

    var i = Math.min(state.step, n - 1);
    ctx.strokeStyle = '#5b7cfa';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(xAt(i), pad.t);
    ctx.lineTo(xAt(i), pad.t + h);
    ctx.stroke();
    ctx.setLineDash([]);
    stampLogo(ctx, cssW, cssH);
  }

  function comparisonRows() {
    var rows = ((state.data && state.data.comparisons) || []).slice();
    var haveId = {};
    var haveKind = {};
    rows.forEach(function (r) {
      if (!r) return;
      if (r.id) haveId[r.id] = true;
      if (r.kind) haveKind[r.kind] = true;
    });
    synthesizeComparisons().forEach(function (s) {
      if (!s || !s.id || haveId[s.id]) return;
      if (s.kind === 'forecast' && haveKind.forecast) return;
      if (s.kind === 'prognose' || s.kind === 'exit_avg' ||
          s.kind === 'hochrechnung' || s.kind === 'forecast') {
        rows.push(s);
        haveId[s.id] = true;
        haveKind[s.kind] = true;
      }
    });
    return fillMissingComparisonUnc(rows);
  }

  function canonParty(p) {
    return PARTY_ALIAS[String(p || '').toLowerCase()] || null;
  }

  function sharesToPct(shares) {
    var out = {};
    var sum = 0;
    Object.keys(shares || {}).forEach(function (k) {
      var p = canonParty(k);
      var v = Number(shares[k]);
      if (!p || !isFinite(v)) return;
      out[p] = (out[p] || 0) + v;
      sum += v;
    });
    if (sum > 0 && sum <= 1.5) {
      Object.keys(out).forEach(function (p) {
        out[p] = Math.round(out[p] * 1000) / 10;
      });
    }
    return out;
  }

  function latestExternalPerPublisher(sources) {
    var by = {};
    (sources || []).forEach(function (s) {
      var pub = String((s && (s.publisher || s.institute)) || '').trim();
      if (!pub) return;
      var prev = by[pub];
      if (!prev || String(s.time || '') >= String(prev.time || '')) by[pub] = s;
    });
    return Object.keys(by).sort().map(function (k) { return by[k]; });
  }

  function synthesizeComparisons() {
    var land = String(state.land || '').toLowerCase();
    var block = (state.external && (state.external[land] || state.external[state.land])) || {};
    var sources = block.sources || [];
    var st = steps();
    var first = st.length ? st[0] : {};
    var last = st.length ? st[st.length - 1] : {};
    var rows = [];
    var prior = first.prior || last.prior || {};
    var priorPct = sharesToPct(prior);
    var t0 = first.turnout || last.turnout || {};
    var fcUnc = forecastUncMap();
    if (Object.keys(priorPct).length) {
      rows.push({
        id: 'forecast',
        kind: 'forecast',
        label: 'zweitstimme.org',
        short: 'zs.org',
        shares: priorPct,
        uncertainty: fcUnc,
        uncertainty_pp: fcUnc ? medianUncPp(fcUnc) : undefined,
        turnout: t0.prior != null ? t0.prior : undefined,
        turnout_unc: t0.prior != null ? 15 : undefined,
        axis: 'preamble'
      });
    }
    latestExternalPerPublisher(sources.filter(function (s) {
      return s && s.kind === 'prognose';
    })).forEach(function (s) {
      var pub = String(s.publisher || 'Exit');
      rows.push({
        id: 'prognose-' + pub.toLowerCase(),
        kind: 'prognose',
        label: 'Prognose ' + pub + (s.time ? ' ' + s.time : ''),
        short: pub,
        publisher: pub,
        time: s.time,
        shares: sharesToPct(s.shares),
        uncertainty_pp: s.uncertainty_pp,
        axis: 'preamble'
      });
    });
    latestExternalPerPublisher(sources.filter(function (s) {
      return s && s.kind === 'hochrechnung';
    })).forEach(function (s) {
      var pub = String(s.publisher || 'HR');
      var t = String(s.time || '').replace(':', '');
      rows.push({
        id: 'hochrechnung-' + pub.toLowerCase() + (t ? '-' + t : ''),
        kind: 'hochrechnung',
        label: 'Hochrechnung ' + pub + (s.time ? ' ' + s.time : ''),
        short: pub + ' HR',
        publisher: pub,
        time: s.time,
        shares: sharesToPct(s.shares),
        uncertainty_pp: s.uncertainty_pp,
        axis: 'preamble'
      });
    });
    return rows;
  }

  function forecastUncMap() {
    var raw = (state.data && state.data.prior_uncertainty_pp) || {};
    var out = {};
    var any = false;
    PARTIES_ORDER.forEach(function (p) {
      var v = Number(raw[p]);
      if (v > 0 && isFinite(v)) {
        out[p] = v;
        any = true;
      }
    });
    return any ? out : null;
  }

  function medianUncPp(unc) {
    var vals = Object.keys(unc || {}).map(function (p) { return Number(unc[p]); })
      .filter(function (v) { return v > 0 && isFinite(v); })
      .sort(function (a, b) { return a - b; });
    if (!vals.length) return 0;
    var mid = Math.floor(vals.length / 2);
    return vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
  }

  function tvUncMap(kind, shares) {
    var hr = kind === 'hochrechnung';
    var rmse = (hr ? 0.64 : 0.77) * 4.0;
    var floor = hr ? 2.5 : 3.5;
    var z = 1.37;
    var varRef = 0.20 * 0.80;
    var out = {};
    PARTIES_ORDER.forEach(function (p) {
      var share = Number((shares || {})[p] || 0);
      if (share > 1.5) share /= 100;
      share = Math.max(0, Math.min(0.99, share));
      var pEff = Math.max(share, 0.02);
      var scale = Math.sqrt(pEff * (1 - pEff) / varRef);
      out[p] = Math.round(Math.max(floor, z * rmse * scale) * 10) / 10;
    });
    return out;
  }

  function rowHasPartyUnc(row) {
    var u = row && row.uncertainty;
    if (!u) return false;
    return Object.keys(u).some(function (k) { return Number(u[k]) > 0; });
  }

  function liftPartyUnc(row, floorMap) {
    var u = Object.assign({}, row.uncertainty || {});
    PARTIES_ORDER.forEach(function (p) {
      var cur = Number(u[p]) || 0;
      var fl = Number((floorMap || {})[p]) || 0;
      if (fl > cur) u[p] = fl;
    });
    row.uncertainty = u;
    row.uncertainty_pp = Math.max(Number(row.uncertainty_pp) || 0, medianUncPp(u));
  }

  function fillMissingComparisonUnc(rows) {
    (rows || []).forEach(function (r) {
      if (!r) return;
      if (r.kind === 'forecast') {
        if (rowHasPartyUnc(r)) return;
        var u = forecastUncMap();
        if (!u) return;
        r.uncertainty = u;
        if (r.uncertainty_pp == null) r.uncertainty_pp = medianUncPp(u);
        return;
      }
      if (r.kind === 'prognose' || r.kind === 'exit_avg' || r.kind === 'hochrechnung') {
        liftPartyUnc(r, tvUncMap(r.kind, r.shares));
      }
    });
    return rows;
  }

  function shareUnc(row, party) {
    if (!row) return 0;
    var u = row.uncertainty || {};
    if (party && u[party] != null && isFinite(u[party])) return Number(u[party]);
    var s = row.uncertainty_pp;
    return (s != null && isFinite(s)) ? Number(s) : 0;
  }

  function drawVertSpan(ctx, x, yLoVal, yHiVal, yAt, color) {
    if (!(yHiVal > yLoVal)) return;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    var yHi = yAt(yHiVal);
    var yLo = yAt(yLoVal);
    ctx.beginPath();
    ctx.moveTo(x, yHi);
    ctx.lineTo(x, yLo);
    ctx.stroke();
    var cap = 3.2;
    ctx.beginPath();
    ctx.moveTo(x - cap, yHi);
    ctx.lineTo(x + cap, yHi);
    ctx.moveTo(x - cap, yLo);
    ctx.lineTo(x + cap, yLo);
    ctx.stroke();
    ctx.restore();
  }

  function drawVertCI(ctx, x, yMid, u, yAt, color) {
    if (!(u > 0)) return;
    drawVertSpan(ctx, x, Math.max(0, yMid - u), yMid + u, yAt, color);
  }

  function preambleMarkers() {
    if (!isLivePage()) return [];
    var rank = { forecast: 0, prognose: 1, exit_avg: 1, hochrechnung: 2 };
    var rows = comparisonRows().filter(function (r) {
      return r && r.shares && (r.axis === 'preamble' || rank[r.kind] != null);
    });
    return rows.slice().sort(function (a, b) {
      var da = (rank[a.kind] != null ? rank[a.kind] : 9) - (rank[b.kind] != null ? rank[b.kind] : 9);
      if (da) return da;
      return String(a.id || '').localeCompare(String(b.id || ''));
    });
  }

  function preambleSlotKind(kind) {
    if (kind === 'forecast') return 'forecast';
    if (kind === 'prognose' || kind === 'exit_avg') return 'prognose';
    if (kind === 'hochrechnung') return 'hochrechnung';
    return null;
  }

  function preamblePublisher(m) {
    var blob = String((m && (m.id || '')) + ' ' + (m.short || '') + ' ' + (m.label || '')).toLowerCase();
    if (blob.indexOf('zdf') >= 0) return 'ZDF';
    if (blob.indexOf('ard') >= 0) return 'ARD';
    return (m && m.short) || '';
  }

  /** Forecast | Exit (ARD+ZDF) | HR (ARD+ZDF) — one x-tick per kind. */
  function preambleSlots(markers) {
    var groups = { forecast: [], prognose: [], hochrechnung: [] };
    (markers || preambleMarkers()).forEach(function (r) {
      var k = preambleSlotKind(r.kind);
      if (k && groups[k]) groups[k].push(r);
    });
    var labels = { forecast: 'zs.org', prognose: 'Exit', hochrechnung: 'HR' };
    return ['forecast', 'prognose', 'hochrechnung'].filter(function (k) {
      return groups[k].length;
    }).map(function (k) {
      return { kind: k, label: labels[k], rows: groups[k] };
    });
  }

  /** Land-level Δ applied to a WK forecast: dest = base + (toLand − fromLand). */
  function swingShareMap(base, fromLand, toLand) {
    var out = {};
    var seen = {};
    [base, fromLand, toLand].forEach(function (m) {
      if (!m) return;
      Object.keys(m).forEach(function (k) { seen[k] = true; });
    });
    Object.keys(seen).forEach(function (p) {
      var v = (base[p] || 0) + (toLand[p] || 0) - (fromLand[p] || 0);
      out[p] = v < 0 ? 0 : v;
    });
    return out;
  }

  function wkrForecastRow(uid) {
    var fc = (state.data && state.data.wkr_forecast) || {};
    return fc[String(uid != null ? uid : state.unit)] || null;
  }

  function earliestWkrRegion() {
    var st = steps();
    var best = null;
    var bestF = 2;
    st.forEach(function (s) {
      var r = (s.by_wkr && s.by_wkr[state.unit]) || {};
      var f = r.frac_reported != null ? r.frac_reported : 1;
      if (f < bestF) {
        bestF = f;
        best = r;
      }
    });
    return best || {};
  }

  function erfApprox(x) {
    var sign = x < 0 ? -1 : 1;
    x = Math.abs(x);
    var t = 1 / (1 + 0.3275911 * x);
    var y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t -
      0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return sign * y;
  }

  /** Same Normal-approx as live wkr_races (margin pp vs mean ±). */
  function pLeadFromShares(shares, uncOf) {
    var parties = PARTIES_ORDER.filter(function (p) { return p !== 'others'; });
    var ranked = parties.slice().sort(function (a, b) {
      return (shares[b] || 0) - (shares[a] || 0);
    });
    if (!ranked.length) {
      return { leader: null, runner: null, margin: 0, p_lead: 0.5 };
    }
    if (ranked.length < 2) {
      return { leader: ranked[0], runner: null, margin: shares[ranked[0]] || 0, p_lead: 1 };
    }
    var a = ranked[0];
    var b = ranked[1];
    var margin = (shares[a] || 0) - (shares[b] || 0);
    var ua = uncOf ? uncOf(a) : 3;
    var ub = uncOf ? uncOf(b) : 3;
    if (!(ua > 0)) ua = 3;
    if (!(ub > 0)) ub = 3;
    var mu = 0.5 * (ua + ub);
    var z = margin / (mu + 0.5);
    var p = 0.5 * (1 + erfApprox(z / Math.SQRT2));
    if (p > 1) p = 1;
    if (p < 0) p = 0;
    return { leader: a, runner: b, margin: margin, p_lead: p };
  }

  function preambleSlotLabel(row) {
    if (!row) return '';
    if (row.kind === 'forecast') return 'zs.org';
    var pub = preamblePublisher(row);
    if (row.kind === 'prognose' || row.kind === 'exit_avg') {
      return pub ? ('Exit ' + pub) : 'Exit';
    }
    if (row.kind === 'hochrechnung') {
      return pub ? (pub + ' HR') : 'HR';
    }
    return row.short || row.label || '';
  }

  function wkrPreambleLeadRows() {
    var marks = wkrPreambleMarkers(wkrErst);
    var fc = wkrForecastRow();
    return marks.map(function (m) {
      return Object.assign({ row: m, label: preambleSlotLabel(m) }, preambleLeadOf(m, fc));
    });
  }

  function preambleLeadOf(m, fc) {
    var thr = (state.data && state.data.call_threshold) || 0.90;
    if (m && m.kind === 'forecast' && fc && fc.p_lead != null) {
      var p0 = Number(fc.p_lead);
      return {
        leader: fc.direct_pred || fc.leader_pred || null,
        runner: fc.runner_up || null,
        margin: fc.margin,
        p_lead: p0,
        likely: !!fc.likely || p0 >= thr
      };
    }
    var info = pLeadFromShares((m && m.shares) || {}, function (p) {
      return shareUnc(m, p);
    });
    info.likely = info.p_lead >= thr;
    return info;
  }

  /**
   * WK preamble: zs.org is the frozen district forecast.
   * Exit/HR = that forecast plus the land-level Δ vs zs.org.
   * Never swing zs.org off the latest HR — that flipped close races
   * (Mitte 7: Linke knapp voraus → Grüne klar voraus).
   */
  function wkrPreambleMarkers(shareOfRegion) {
    var land = preambleMarkers();
    if (!land.length || !state.unit) return [];
    var st = steps();
    if (!st.length) return [];
    var fc = wkrForecastRow();
    var base = fc ? shareOfRegion(fc) : shareOfRegion(earliestWkrRegion());
    if (!base || !Object.keys(base).length) return [];
    var zsLand = null;
    land.forEach(function (row) {
      if (row.kind === 'forecast') zsLand = row.shares || {};
    });
    var latest = land[land.length - 1];
    var fromOthers = zsLand && Object.keys(zsLand).length
      ? zsLand
      : ((latest && latest.shares) || {});
    return land.map(function (row) {
      if (row.kind === 'forecast') {
        return Object.assign({}, row, {
          shares: Object.assign({}, base),
          uncertainty: (fc && fc.uncertainty) || row.uncertainty
        });
      }
      return Object.assign({}, row, {
        shares: swingShareMap(base, fromOthers, row.shares || {})
      });
    });
  }

  function preambleWidthFrac(slots) {
    var n = (slots || preambleSlots()).length;
    if (!n) return 0;
    // Extra room so the zs.org party-jitter (wide CIs) does not sit on Exit.
    return Math.min(0.36, 0.11 + 0.08 * n);
  }

  function xAtPreamble(padL, plotW, k, slots) {
    slots = slots || preambleSlots();
    var n = slots.length;
    var pre = preambleWidthFrac(slots) * plotW;
    if (n <= 0) return padL;
    var slotW = pre / n;
    var x = padL + (k + 0.5) * slotW;
    if (slots[k] && slots[k].kind === 'forecast') {
      x -= Math.min(10, slotW * 0.22);
    }
    return x;
  }

  /** Fan overlapping dots a few px so CIs stay readable. */
  function partyJitterX(x, partyIndex, nParties, rowIndex, nRows) {
    if (nParties > 1) {
      var span = Math.min(20, 3.4 * nParties);
      x += (partyIndex - (nParties - 1) / 2) * (span / (nParties - 1));
    }
    if (nRows > 1) {
      x += ((rowIndex || 0) - (nRows - 1) / 2) * 6;
    }
    return x;
  }

  function preamblePointX(padL, plotW, slotIndex, rowIndex, partyIndex, nParties, slots) {
    slots = slots || preambleSlots();
    var slot = slots[slotIndex];
    var x = xAtPreamble(padL, plotW, slotIndex, slots);
    if (!slot) return x;
    return partyJitterX(x, partyIndex, nParties, rowIndex, slot.rows.length);
  }

  function drawPreambleDot(ctx, x, y, color, pub) {
    ctx.fillStyle = color;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    if (pub === 'ZDF') {
      ctx.beginPath();
      ctx.moveTo(x, y - 4.2);
      ctx.lineTo(x + 4.2, y);
      ctx.lineTo(x, y + 4.2);
      ctx.lineTo(x - 4.2, y);
      ctx.closePath();
      ctx.fill();
      return;
    }
    ctx.beginPath();
    ctx.arc(x, y, 3.4, 0, Math.PI * 2);
    ctx.fill();
  }

  function countAxisOrigin(padL, plotW, opt) {
    var pre = (opt && opt.preamble && isLivePage())
      ? preambleWidthFrac(opt.slots)
      : 0;
    return padL + pre * plotW;
  }

  /** Live: x = counted share (0–100 %). Replay: equal spacing by step.
      opt.preamble: leave a left strip for exit polls / Hochrechnung. */
  function xAlongNight(padL, plotW, st, i, opt) {
    var x0 = countAxisOrigin(padL, plotW, opt);
    var countW = padL + plotW - x0;
    if (isLivePage()) {
      var f = (st[i] && st[i].frac_reported) || 0;
      if (f < 0) f = 0;
      if (f > 1) f = 1;
      return x0 + f * countW;
    }
    return padL + (i / Math.max(1, st.length - 1)) * plotW;
  }

  function shadeRestOfNight(ctx, pad, plotW, h, st, ci, opt) {
    if (!isLivePage()) {
      if (ci < st.length - 1) {
        var xReplay = xAlongNight(pad.l, plotW, st, ci, opt);
        ctx.fillStyle = 'rgba(0,0,0,0.035)';
        ctx.fillRect(xReplay, pad.t, pad.l + plotW - xReplay, h);
      }
      return;
    }
    var x = xAlongNight(pad.l, plotW, st, ci, opt);
    ctx.fillStyle = 'rgba(0,0,0,0.035)';
    ctx.fillRect(x, pad.t, pad.l + plotW - x, h);
  }

  function drawPreambleAxis(ctx, pad, plotW, cssH, opt) {
    if (!(opt && opt.preamble && isLivePage())) return;
    var slots = opt.slots || preambleSlots();
    if (!slots.length) return;
    var x0 = countAxisOrigin(pad.l, plotW, opt);
    ctx.strokeStyle = 'rgba(0,0,0,0.22)';
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(x0, pad.t);
    ctx.lineTo(x0, pad.t + (cssH - pad.t - pad.b));
    ctx.stroke();
    ctx.fillStyle = '#666';
    ctx.font = '10px system-ui,sans-serif';
    slots.forEach(function (slot, k) {
      var x = xAtPreamble(pad.l, plotW, k, slots);
      var lab = slot.label;
      var tw = ctx.measureText(lab).width;
      ctx.fillText(lab, Math.max(pad.l, x - tw / 2), cssH - 8);
    });
  }

  function colorWithAlpha(hex, a) {
    var h = (hex || '#888').replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var r = parseInt(h.slice(0, 2), 16);
    var g = parseInt(h.slice(2, 4), 16);
    var b = parseInt(h.slice(4, 6), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  function marginUnc(r) {
    if (!r) return null;
    var u = r.uncertainty || {};
    var lead = r.direct_pred || r.leader_pred;
    var run = r.runner_up;
    if (!lead || !run) return null;
    var ul = u[lead];
    var ur = u[run];
    if (ul == null || ur == null) return null;
    return Math.sqrt(ul * ul + ur * ur);
  }

  function ensureCompareChartDom() {
    ['wb-compare-label', 'wb-compare-legend', 'wb-chart-compare', 'wb-compare-note'].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      el.style.display = 'none';
      if (el.parentNode && el.parentNode !== document.body && !el.parentNode.id) {
        el.parentNode.style.display = 'none';
      }
    });
  }

  /** zs.org | Exit (ARD+ZDF) | HR (ARD+ZDF) | Nowcast — Nowcast always last. */
  function compareSlots() {
    var groups = { forecast: [], prognose: [], hochrechnung: [], nowcast: [] };
    comparisonRows().forEach(function (r) {
      if (!r || !r.shares) return;
      var k = r.kind === 'nowcast' ? 'nowcast' : preambleSlotKind(r.kind);
      if (k && groups[k]) groups[k].push(r);
    });
    var labels = { forecast: 'zs.org', prognose: 'Exit', hochrechnung: 'HR', nowcast: 'Nowcast' };
    return ['forecast', 'prognose', 'hochrechnung', 'nowcast'].filter(function (k) {
      return groups[k].length;
    }).map(function (k) {
      return { kind: k, label: labels[k], rows: groups[k] };
    });
  }

  function drawCompareChart() {
    ensureCompareChartDom();
    return;
    var canvas = $('wb-chart-compare');
    var legend = $('wb-compare-legend');
    var label = $('wb-compare-label');
    var note = $('wb-compare-note');
    if (!canvas) return;
    var slots = compareSlots();
    var hide = slots.length < 2 || (state.scope && state.scope !== 'zweit');
    canvas.style.display = hide ? 'none' : '';
    if (legend) legend.style.display = hide ? 'none' : '';
    if (label) label.style.display = hide ? 'none' : '';
    if (note) note.style.display = hide ? 'none' : '';
    if (hide) return;

    var series = [];
    slots.forEach(function (slot) {
      slot.rows.forEach(function (r) { series.push(r); });
    });
    var parties = PARTIES_ORDER.filter(function (p) {
      return series.some(function (s) { return (s.shares[p] || 0) > 0.15; });
    });
    if (!parties.length) parties = PARTIES_ORDER.slice(0, 7);

    if (legend) {
      legend.innerHTML = parties.map(function (p) {
        var c = PARTY_COLORS[p] || '#888';
        return '<span><i style="background:' + c +
          ';display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:0.35rem;"></i>' +
          partyShort(p) + '</span>';
      }).join(' ') +
        ' <span class="wb-art">· ARD ● · ZDF ◆ · hohl = zs.org · Rand = HR · grau gestrichelt = 5%-Hürde</span>';
    }
    if (label) {
      label.textContent = 'Vergleich: Vorhersage, Exit-Polls' +
        (slots.some(function (s) { return s.kind === 'hochrechnung'; }) ? ', Hochrechnung' : '') +
        ', Nowcast';
    }
    if (note) {
      note.textContent = 'Punkte je Quelle leicht versetzt. Nowcast rechts. Kappen = ±.';
    }

    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 900;
    var cssH = 250;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    var pad = { l: 36, r: 16, t: 12, b: 32 };
    var w = cssW - pad.l - pad.r;
    var h = cssH - pad.t - pad.b;
    var yMax = 10;
    series.forEach(function (s) {
      parties.forEach(function (p) {
        yMax = Math.max(yMax, (s.shares[p] || 0) + shareUnc(s, p));
      });
    });
    yMax *= 1.12;
    function yAt(v) { return pad.t + (1 - v / yMax) * h; }
    function xAt(k) { return pad.l + (k + 0.5) * (w / slots.length); }

    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.stroke();
    ctx.fillStyle = '#888';
    ctx.font = '11px system-ui,sans-serif';
    ctx.fillText(fmtNum(yMax, 0) + '\u00a0%', 4, pad.t + 10);
    ctx.fillText('0', 4, pad.t + h);
    drawHurdleLine(ctx, pad, w, yAt, 0, yMax);

    slots.forEach(function (slot, k) {
      var x = xAt(k);
      ctx.strokeStyle = 'rgba(0,0,0,0.12)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, pad.t + h);
      ctx.stroke();
      ctx.fillStyle = '#444';
      ctx.font = '11px system-ui,sans-serif';
      var lab = slot.label;
      var tw = ctx.measureText(lab).width;
      ctx.fillText(lab, x - tw / 2, cssH - 8);

      slot.rows.forEach(function (s) {
        var pub = preamblePublisher(s);
        parties.forEach(function (p) {
          var val = s.shares[p] || 0;
          if (!(val > 0.05) && s.kind !== 'nowcast' && s.kind !== 'forecast') return;
          var col = PARTY_COLORS[p] || '#888';
          var px = partyJitterX(
            x, parties.indexOf(p), parties.length,
            slot.rows.indexOf(s), slot.rows.length
          );
          var u = shareUnc(s, p);
          if (u > 0) drawVertCI(ctx, px, val, u, yAt, 'rgba(20,20,20,0.55)');
          ctx.globalAlpha = s.kind === 'forecast' ? 0.55 : 1;
          if (s.kind === 'forecast') {
            ctx.strokeStyle = col;
            ctx.lineWidth = 1.4;
            ctx.beginPath();
            ctx.arc(px, yAt(val), 3.6, 0, Math.PI * 2);
            ctx.stroke();
          } else {
            drawPreambleDot(ctx, px, yAt(val), col, pub);
            if (s.kind === 'hochrechnung') {
              ctx.strokeStyle = '#111';
              ctx.lineWidth = 1.1;
              ctx.beginPath();
              if (pub === 'ZDF') {
                ctx.moveTo(px, yAt(val) - 4.2);
                ctx.lineTo(px + 4.2, yAt(val));
                ctx.lineTo(px, yAt(val) + 4.2);
                ctx.lineTo(px - 4.2, yAt(val));
                ctx.closePath();
              } else {
                ctx.arc(px, yAt(val), 3.4, 0, Math.PI * 2);
              }
              ctx.stroke();
            }
          }
          ctx.globalAlpha = 1;
        });
      });
    });
    stampLogo(ctx, cssW, cssH);
  }

  function drawShareChart() {
    var canvas = $('wb-chart-shares');
    var legend = $('wb-share-legend');
    var label = $('wb-share-chart-label');
    if (!canvas || !state.data) return;
    if (state.scope !== 'zweit' && !(state.scope === 'wkr' && state.unit)) return;
    var st = steps();
    if (!st.length) return;
    var ci = Math.min(state.step, st.length - 1);
    var showTruth = state.scope === 'wkr'
      ? isWkrComplete(st[ci], state.unit)
      : isLandComplete(st[ci]);
    var views = st.map(viewForStep);
    var parties = PARTIES_ORDER.filter(function (p) {
      return views.some(function (v) {
        return v && v.nowcast && v.nowcast[p] != null;
      });
    });
    if (state.scope === 'zweit' && state.partyFocus &&
        parties.indexOf(state.partyFocus) >= 0) {
      parties = [state.partyFocus];
    }
    // In WK: Bänder nur für die aktuell führenden Parteien (weniger Clutter)
    var bandParties = parties;
    if (state.scope === 'wkr') {
      var curV = views[Math.min(state.step, views.length - 1)];
      if (curV && curV.nowcast) {
        bandParties = parties.slice().sort(function (a, b) {
          return (curV.nowcast[b] || 0) - (curV.nowcast[a] || 0);
        }).slice(0, 4);
      }
    }
    if (label) {
      label.textContent = state.partyFocus
        ? partyShort(state.partyFocus) + ' — Zweitstimme über die Nacht (Nowcast ± Band)'
        : (isLivePage()
          ? (state.scope === 'wkr'
            ? 'Zweitstimme in diesem WK — zs.org (Wahlkreisprognose) / Exit / Hochrechnung, dann Nowcast 0–100\u00a0%'
            : 'Zweitstimme — Exit-Polls / Hochrechnung, dann Nowcast 0–100\u00a0%')
          : 'Zweitstimme — Partei-Anteile über die Nacht (Nowcast ± Band)');
    }
    if (legend) {
      legend.innerHTML = parties.map(function (p) {
        var c = PARTY_COLORS[p] || '#888';
        return '<span><i style="background:' + c +
          ';display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:0.35rem;"></i>' +
          partyShort(p) + '</span>';
      }).join(' ') +
        ' <span class="wb-art">· Fläche + gestrichelte Kanten = ± Band</span>' +
        ' <span class="wb-art">· grau gestrichelt = 5%-Hürde</span>' +
        (isLivePage() && preambleSlots().length
          ? ' <span class="wb-art">· links von 0&nbsp;% = zs.org, Exit ARD●/ZDF◆, HR (Punkte versetzt)</span>'
          : '');
    }

    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 900;
    var cssH = 280;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    var n = views.length;
    var preMarks = state.scope === 'wkr'
      ? wkrPreambleMarkers(function (r) { return (r && r.nowcast) || {}; })
      : preambleMarkers();
    var preSlots = preambleSlots(preMarks);
    var nightOpt = { preamble: isLivePage() && preSlots.length > 0, slots: preSlots };
    var pad = { l: 36, r: 12, t: 16, b: nightOpt.preamble ? 38 : 28 };
    var w = cssW - pad.l - pad.r;
    var h = cssH - pad.t - pad.b;
    var vals = [];
    parties.forEach(function (p) {
      views.forEach(function (v) {
        if (!v || !v.nowcast) return;
        var nc = v.nowcast[p] || 0;
        var u = (v.uncertainty && v.uncertainty[p]) || 0;
        vals.push(nc + u);
        if (showTruth && v.truth) vals.push(v.truth[p] || 0);
      });
      preMarks.forEach(function (m) {
        if (m.shares && m.shares[p] != null) {
          vals.push(m.shares[p] + shareUnc(m, p));
        }
      });
    });
    var yMin = 0;
    var yMax = Math.max(10, Math.max.apply(null, vals.concat([0])) * 1.08);

    function xAt(i) { return xAlongNight(pad.l, w, st, i, nightOpt); }
    function yAt(v) { return pad.t + (1 - (v - yMin) / (yMax - yMin)) * h; }

    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.stroke();
    ctx.fillStyle = '#888';
    ctx.font = '11px system-ui,sans-serif';
    var x0 = countAxisOrigin(pad.l, w, nightOpt);
    ctx.fillText('0\u00a0%', x0, cssH - 8);
    ctx.fillText('100\u00a0%', pad.l + w - 28, cssH - 8);
    ctx.fillText(fmtNum(yMax, 0) + '\u00a0%', 4, pad.t + 10);
    shadeRestOfNight(ctx, pad, w, h, st, ci, nightOpt);
    drawPreambleAxis(ctx, pad, w, cssH, nightOpt);

    // Uncertainty ribbons + dashed ± envelopes (draw before solid lines)
    bandParties.forEach(function (p) {
      var c = PARTY_COLORS[p] || '#888';
      var hi = [];
      var lo = [];
      views.forEach(function (v, i) {
        if (!v || !v.nowcast) return;
        var nc = v.nowcast[p] || 0;
        var u = (v.uncertainty && v.uncertainty[p]) || 0;
        hi.push({ i: i, y: nc + u });
        lo.push({ i: i, y: Math.max(0, nc - u) });
      });
      if (hi.length < 2) return;

      ctx.fillStyle = colorWithAlpha(c, 0.22);
      ctx.beginPath();
      hi.forEach(function (pt, k) {
        var x = xAt(pt.i), y = yAt(pt.y);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      for (var k = lo.length - 1; k >= 0; k--) {
        ctx.lineTo(xAt(lo[k].i), yAt(lo[k].y));
      }
      ctx.closePath();
      ctx.fill();

      // Dashed envelopes so ± reads even when fills overlap
      ctx.strokeStyle = colorWithAlpha(c, 0.55);
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      hi.forEach(function (pt, k) {
        var x = xAt(pt.i), y = yAt(pt.y);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.beginPath();
      lo.forEach(function (pt, k) {
        var x = xAt(pt.i), y = yAt(pt.y);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    });

    drawHurdleLine(ctx, pad, w, yAt, yMin, yMax);

    // Endstand nur wenn Land voll ausgezählt (nicht die ganze Nacht vorwegnehmen)
    var truth = showTruth && views[ci] && views[ci].truth;
    if (truth) {
      parties.forEach(function (p) {
        var tv = truth[p];
        if (tv == null) return;
        ctx.strokeStyle = PARTY_COLORS[p] || '#888';
        ctx.globalAlpha = 0.35;
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x0, yAt(tv));
        ctx.lineTo(pad.l + w, yAt(tv));
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      });
    }

    parties.forEach(function (p) {
      var col = PARTY_COLORS[p] || '#888';
      ctx.strokeStyle = col;
      ctx.lineWidth = 2;
      ctx.beginPath();
      var started = false;
      views.forEach(function (v, i) {
        var val = (v && v.nowcast) ? (v.nowcast[p] || 0) : 0;
        var x = xAt(i), y = yAt(val);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      var pi = parties.indexOf(p);
      preSlots.forEach(function (slot, k) {
        slot.rows.forEach(function (m, ri) {
          if (!m.shares || m.shares[p] == null) return;
          var x = preamblePointX(pad.l, w, k, ri, pi, parties.length, preSlots);
          var val = m.shares[p];
          drawVertCI(ctx, x, val, shareUnc(m, p), yAt, col);
          drawPreambleDot(ctx, x, yAt(val), col, preamblePublisher(m));
        });
      });
    });

    var i = Math.min(state.step, n - 1);
    ctx.strokeStyle = '#5b7cfa';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(xAt(i), pad.t);
    ctx.lineTo(xAt(i), pad.t + h);
    ctx.stroke();
    ctx.setLineDash([]);

    // Marker + error bar at current step
    parties.forEach(function (p) {
      var v = views[i];
      if (!v || !v.nowcast) return;
      var val = v.nowcast[p] || 0;
      var u = (v.uncertainty && v.uncertainty[p]) || 0;
      var x = partyJitterX(xAt(i), parties.indexOf(p), parties.length);
      ctx.strokeStyle = PARTY_COLORS[p] || '#888';
      ctx.lineWidth = 1.5;
      if (u > 0) {
        ctx.beginPath();
        ctx.moveTo(x, yAt(val + u));
        ctx.lineTo(x, yAt(Math.max(0, val - u)));
        ctx.stroke();
      }
      ctx.fillStyle = PARTY_COLORS[p] || '#888';
      ctx.beginPath();
      ctx.arc(x, yAt(val), 3.5, 0, Math.PI * 2);
      ctx.fill();
    });
    stampLogo(ctx, cssW, cssH);
  }

  function stepIndexNearFrac(fracList, fracTarget) {
    var bestI = 0;
    var bestD = 1e9;
    for (var i = 0; i < fracList.length; i++) {
      var d = Math.abs((fracList[i] || 0) - fracTarget);
      if (d < bestD) { bestD = d; bestI = i; }
    }
    return bestI;
  }

  function direktAtFrac(st, fracTarget, which) {
    if (!st || !st.length) return null;
    var fracs = st.map(function (s) { return s.frac_reported || 0; });
    var i = stepIndexNearFrac(fracs, fracTarget);
    var s = st[i];
    var root = s.eval && s.eval.institutions;
    var block = root && root[which || 'nowcast'];
    if (!block || !block.direkt) return null;
    return {
      n: block.direkt.n_hit,
      total: block.direkt.n_total,
      rate: block.direkt.hit_rate,
      frac: s.frac_reported
    };
  }

  /** Direkt-Treffer nur unter noch nicht voll ausgezählten WK (faire Mid-Night-Metrik). */
  function direktOpenAtFrac(st, fracTarget, which) {
    if (!st || !st.length) return null;
    var fracs = st.map(function (s) { return s.frac_reported || 0; });
    var i = stepIndexNearFrac(fracs, fracTarget);
    var s = st[i];
    var by = s.by_wkr || {};
    var MAIN = ['cdu', 'spd', 'gruene', 'linke', 'afd', 'fdp'];
    var n = 0;
    var hit = 0;
    Object.keys(by).forEach(function (uid) {
      var r = by[uid];
      if ((r.frac_reported || 0) >= 0.999) return;
      n++;
      var truth = r.leader_truth;
      var pred;
      if (which === 'naive') {
        var nv = r.naive || {};
        pred = MAIN.reduce(function (best, p) {
          return (nv[p] || 0) > (nv[best] || 0) ? p : best;
        }, MAIN[0]);
      } else {
        pred = r.direct_pred || r.leader_pred;
      }
      if (pred && truth && pred === truth) hit++;
    });
    if (!n) return { n: 0, total: 0, rate: 1, frac: s.frac_reported, open: true };
    return {
      n: hit,
      total: n,
      rate: hit / n,
      frac: s.frac_reported,
      open: true
    };
  }

  function renderDirektMilestones() {
    var table = $('wb-direkt-table');
    if (!table) return;
    var st = steps();
    if (!st.length) { table.innerHTML = ''; return; }
    var targets = [0.25, 0.5, 0.75, 1.0];
    var labels = ['@~25\u00a0%', '@~50\u00a0%', '@~75\u00a0%', 'Ende'];

    function cell(d) {
      if (!d) return '—';
      if (!d.total) return '—';
      return d.n + '/' + d.total +
        ' <span class="wb-art">(' + Math.round(d.rate * 100) + '\u00a0%)</span>';
    }

    var ncRow = '<tr><td>Nowcast (alle WK)</td>' + targets.map(function (t) {
      return '<td>' + cell(direktAtFrac(st, t, 'nowcast')) + '</td>';
    }).join('') + '</tr>';
    var nvRow = '<tr><td>Naiv (alle WK)</td>' + targets.map(function (t) {
      return '<td>' + cell(direktAtFrac(st, t, 'naive')) + '</td>';
    }).join('') + '</tr>';
    var ncOpen = '<tr><td>Nowcast (nur offen)</td>' + targets.map(function (t) {
      return '<td>' + cell(direktOpenAtFrac(st, t, 'nowcast')) + '</td>';
    }).join('') + '</tr>';
    var nvOpen = '<tr><td>Naiv (nur offen)</td>' + targets.map(function (t) {
      return '<td>' + cell(direktOpenAtFrac(st, t, 'naive')) + '</td>';
    }).join('') + '</tr>';

    table.innerHTML =
      '<table class="wb-cov-table"><thead><tr>' +
      '<th>Direktmandate</th>' +
      labels.map(function (h) { return '<th>' + h + '</th>'; }).join('') +
      '</tr></thead><tbody>' + ncRow + nvRow + ncOpen + nvOpen + '</tbody></table>' +
      '<p class="wb-coverage-meta">Erststimme-Führer je WK. <em>Alle WK</em> zählt fertige ' +
      'Wahlkreise mit (dort sind beide ≈ Wahrheit). <em>Nur offen</em> = noch nicht ' +
      '100 % ausgezählt — dort ist Naiv bei 0 % lokal = Prior; der Nowcast kann spät ' +
      'schlechter sein, wenn der gelernte Landestrend für die spät meldenden Gebiete ' +
      '(z. B. Osten) falsch liegt.</p>';
  }

  function drawChart() {
    var st = steps();
    if (!st.length) return;
    drawLineChart(
      'wb-chart-hit',
      st.map(function (s) {
        var d = institutionsOf(s.eval);
        return (d && d.direkt) ? d.direkt.hit_rate : 0;
      }),
      st.map(function (s) {
        var d = s.eval && s.eval.institutions && s.eval.institutions.naive;
        return (d && d.direkt) ? d.direkt.hit_rate : 0;
      }),
      { yMin: 0, yMax: 1, pctAxis: true }
    );
    renderDirektMilestones();
  }


  function candidateFor(wkrId, party) {
    var roster = (state.data && state.data.direkt_candidates_2026) || {};
    var cell = ((roster[String(wkrId)] || {})[party]) || null;
    if (cell) return cell;
    if (isLivePage()) return { name: 'kein Direktkandidat', missing: true };
    return {
      name: partyShort(party) + ' · WK ' + wkrId + ' · Platzhalter',
      is_placeholder: true
    };
  }

  function nameHtml(cell) {
    if (!cell) return '—';
    if (cell.missing) {
      return '<span class="wb-ph">kein Direktkandidat</span>';
    }
    if (cell.is_placeholder) {
      return '<span class="wb-ph">' + escapeHtml(cell.name) + '</span>';
    }
    return escapeHtml(cell.name);
  }

  function wkrErst(r) {
    if (r && r.erst) return r.erst;
    if (r && r.nowcast) return r.nowcast;
    return {};
  }

  function drawAxisFrame(ctx, pad, w, h, cssH, yMin, yMax, yFmt) {
    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.stroke();
    ctx.fillStyle = '#888';
    ctx.font = '11px system-ui,sans-serif';
    ctx.fillText('0\u00a0%', pad.l, cssH - 6);
    ctx.fillText('100\u00a0%', pad.l + w - 28, cssH - 6);
    ctx.fillText(yFmt(yMax), 4, pad.t + 10);
    if (yMin > 0) ctx.fillText(yFmt(yMin), 4, pad.t + h);
  }

  function drawWkrRaceCharts() {
    var raceCanvas = $('wb-chart-race');
    var probCanvas = $('wb-chart-prob');
    var legend = $('wb-race-legend');
    if (!raceCanvas || state.scope !== 'wkr' || !state.unit) return;
    var st = steps();
    if (!st.length) return;
    var regions = st.map(function (s) {
      return (s.by_wkr && s.by_wkr[state.unit]) || {};
    });
    var staticW = (((state.data.geo_static || {}).wkr) || {})[state.unit] || {};
    var truth = staticW.truth || {};
    var ci = Math.min(state.step, regions.length - 1);
    var sCur = st[ci];
    var showTruth = isWkrComplete(sCur, state.unit);
    var cur = regions[ci] || {};
    var erstCur = wkrErst(cur);
    var parties = PARTIES_ORDER.filter(function (p) { return p !== 'others'; })
      .sort(function (a, b) {
        return (erstCur[b] || 0) - (erstCur[a] || 0);
      });

    var preMarks = wkrPreambleMarkers(wkrErst);
    var preSlots = preambleSlots(preMarks);
    var nightOpt = { preamble: isLivePage() && preSlots.length > 0, slots: preSlots };
    var raceLabel = $('wb-race-chart-label');
    if (raceLabel) {
      raceLabel.textContent = nightOpt.preamble
        ? 'Erststimme — zs.org (Wahlkreisprognose) / Exit / Hochrechnung, dann Nowcast 0–100\u00a0%'
        : 'Erststimmen-Rennen über die Nacht';
    }
    if (legend) {
      legend.innerHTML = parties.slice(0, 6).map(function (p) {
        var c = PARTY_COLORS[p] || '#888';
        return '<span><i style="background:' + c +
          ';display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:0.35rem;"></i>' +
          partyShort(p) + '</span>';
      }).join(' ') +
        (showTruth
          ? ' <span class="wb-art">· Band = ± (Fläche + Kante) · gestrichelt horizontal = Endstand</span>'
          : ' <span class="wb-art">· Band = ± (Fläche + Kante)</span>') +
        (nightOpt.preamble
          ? ' <span class="wb-art">· links von 0&nbsp;% = zs.org-Wahlkreisprognose (nicht die Landes-Δ), dann Exit ARD●/ZDF◆, HR (Punkte versetzt)</span>'
          : '');
    }

    // --- Race share chart ---
    var ctx = raceCanvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var cssW = raceCanvas.clientWidth || 900;
    var cssH = 260;
    raceCanvas.width = Math.round(cssW * dpr);
    raceCanvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    var n = regions.length;
    var pad = { l: 40, r: 12, t: 14, b: nightOpt.preamble ? 38 : 26 };
    var w = cssW - pad.l - pad.r;
    var h = cssH - pad.t - pad.b;
    var vals = [];
    parties.forEach(function (p) {
      regions.forEach(function (r) {
        var nc = (wkrErst(r)[p]) || 0;
        var u = (r.uncertainty && r.uncertainty[p]) || 0;
        vals.push(nc + u);
      });
      if (showTruth && truth[p] != null) vals.push(truth[p]);
      preMarks.forEach(function (m) {
        if (m.shares && m.shares[p] != null) {
          vals.push(m.shares[p] + shareUnc(m, p));
        }
      });
    });
    var yMin = 0;
    var yMax = Math.max(15, Math.max.apply(null, vals.concat([0])) * 1.1);
    function xAt(i) { return xAlongNight(pad.l, w, st, i, nightOpt); }
    function yAt(v) { return pad.t + (1 - (v - yMin) / (yMax - yMin)) * h; }
    var x0 = countAxisOrigin(pad.l, w, nightOpt);
    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.stroke();
    ctx.fillStyle = '#888';
    ctx.font = '11px system-ui,sans-serif';
    ctx.fillText('0\u00a0%', x0, cssH - 8);
    ctx.fillText('100\u00a0%', pad.l + w - 28, cssH - 8);
    ctx.fillText(fmtNum(yMax, 0) + '\u00a0%', 4, pad.t + 10);
    shadeRestOfNight(ctx, pad, w, h, st, ci, nightOpt);
    drawPreambleAxis(ctx, pad, w, cssH, nightOpt);

    parties.forEach(function (p) {
      var c = PARTY_COLORS[p] || '#888';
      var hi = [];
      var lo = [];
      regions.forEach(function (r, i) {
        var nc = (wkrErst(r)[p]) || 0;
        var u = (r.uncertainty && r.uncertainty[p]) || 0;
        hi.push({ i: i, y: nc + u });
        lo.push({ i: i, y: Math.max(0, nc - u) });
      });
      if (hi.length < 2) return;
      ctx.fillStyle = colorWithAlpha(c, 0.24);
      ctx.beginPath();
      hi.forEach(function (pt, k) {
        var x = xAt(pt.i), y = yAt(pt.y);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      for (var k = lo.length - 1; k >= 0; k--) {
        ctx.lineTo(xAt(lo[k].i), yAt(lo[k].y));
      }
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = colorWithAlpha(c, 0.55);
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      hi.forEach(function (pt, k) {
        var x = xAt(pt.i), y = yAt(pt.y);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.beginPath();
      lo.forEach(function (pt, k) {
        var x = xAt(pt.i), y = yAt(pt.y);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    });

    if (showTruth) {
      parties.forEach(function (p) {
        if (truth[p] == null) return;
        ctx.strokeStyle = PARTY_COLORS[p] || '#888';
        ctx.globalAlpha = 0.4;
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x0, yAt(truth[p]));
        ctx.lineTo(pad.l + w, yAt(truth[p]));
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      });
    }

    parties.forEach(function (p) {
      ctx.strokeStyle = PARTY_COLORS[p] || '#888';
      ctx.lineWidth = 2.25;
      ctx.beginPath();
      regions.forEach(function (r, i) {
        var val = wkrErst(r)[p] || 0;
        var x = xAt(i), y = yAt(val);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      var pi = parties.indexOf(p);
      preSlots.forEach(function (slot, k) {
        slot.rows.forEach(function (m, ri) {
          if (!m.shares || m.shares[p] == null) return;
          var x = preamblePointX(pad.l, w, k, ri, pi, parties.length, preSlots);
          var val = m.shares[p];
          drawVertCI(ctx, x, val, shareUnc(m, p), yAt, PARTY_COLORS[p] || '#888');
          drawPreambleDot(ctx, x, yAt(val), PARTY_COLORS[p] || '#888', preamblePublisher(m));
        });
      });
    });

    ctx.strokeStyle = '#5b7cfa';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(xAt(ci), pad.t);
    ctx.lineTo(xAt(ci), pad.t + h);
    ctx.stroke();
    ctx.setLineDash([]);
    parties.forEach(function (p) {
      var r = regions[ci];
      var val = wkrErst(r)[p] || 0;
      var u = (r.uncertainty && r.uncertainty[p]) || 0;
      var x = partyJitterX(xAt(ci), parties.indexOf(p), parties.length);
      ctx.strokeStyle = PARTY_COLORS[p] || '#888';
      ctx.lineWidth = 1.5;
      if (u > 0) {
        ctx.beginPath();
        ctx.moveTo(x, yAt(val + u));
        ctx.lineTo(x, yAt(Math.max(0, val - u)));
        ctx.stroke();
      }
      ctx.fillStyle = PARTY_COLORS[p] || '#888';
      ctx.beginPath();
      ctx.arc(x, yAt(val), 4, 0, Math.PI * 2);
      ctx.fill();
    });
    stampLogo(ctx, cssW, cssH);

    // --- P(lead) chart ---
    if (!probCanvas) return;
    ctx = probCanvas.getContext('2d');
    cssW = probCanvas.clientWidth || 900;
    cssH = 160;
    probCanvas.width = Math.round(cssW * dpr);
    probCanvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    pad = { l: 40, r: 12, t: 12, b: nightOpt.preamble ? 36 : 24 };
    w = cssW - pad.l - pad.r;
    h = cssH - pad.t - pad.b;
    yMin = 0;
    yMax = 1;
    function yP(v) { return pad.t + (1 - (v - yMin) / (yMax - yMin)) * h; }
    var x0p = countAxisOrigin(pad.l, w, nightOpt);
    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.stroke();
    ctx.fillStyle = '#888';
    ctx.font = '11px system-ui,sans-serif';
    ctx.fillText('0\u00a0%', x0p, cssH - 6);
    ctx.fillText('100\u00a0%', pad.l + w - 28, cssH - 6);
    ctx.fillText('100\u00a0%', 4, pad.t + 10);
    shadeRestOfNight(ctx, pad, w, h, st, ci, nightOpt);
    drawPreambleAxis(ctx, pad, w, cssH, nightOpt);

    var thrLikely = (state.data && state.data.call_threshold) || 0.90;
    var thrCall = (state.data && state.data.hard_call_threshold) || 0.999;
    ctx.setLineDash([4, 3]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#5b7cfa';
    ctx.beginPath();
    ctx.moveTo(x0p, yP(thrLikely));
    ctx.lineTo(pad.l + w, yP(thrLikely));
    ctx.stroke();
    ctx.strokeStyle = '#2e7d32';
    ctx.beginPath();
    ctx.moveTo(x0p, yP(thrCall));
    ctx.lineTo(pad.l + w, yP(thrCall));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = '11px system-ui,sans-serif';
    ctx.fillStyle = '#5b7cfa';
    ctx.fillText('wahrsch. ' + fmtNum(thrLikely * 100, 0) + '\u00a0%', x0p + 4, yP(thrLikely) - 4);
    ctx.fillStyle = '#2e7d32';
    ctx.fillText('Call ' + fmtNum(thrCall * 100, 1) + '\u00a0%', x0p + 4, yP(thrCall) + 12);

    // shade: wahrscheinlich (blau) ab P≥thr, hart gecallt (grün) ab erster WK-Meldung
    var likelyStart = null;
    var callStart = null;
    regions.forEach(function (r, i) {
      if (callTier(r) !== 'open' && likelyStart == null) likelyStart = i;
      if (r.called && callStart == null) callStart = i;
    });
    if (likelyStart != null) {
      ctx.fillStyle = 'rgba(35,80,143,0.07)';
      ctx.fillRect(xAt(likelyStart), pad.t, xAt(n - 1) - xAt(likelyStart), h);
    }
    if (callStart != null) {
      ctx.fillStyle = 'rgba(27,94,32,0.10)';
      ctx.fillRect(xAt(callStart), pad.t, xAt(n - 1) - xAt(callStart), h);
    }

    ctx.strokeStyle = '#1a1a1a';
    ctx.lineWidth = 2;
    ctx.beginPath();
    regions.forEach(function (r, i) {
      var pLead = r.p_lead != null ? r.p_lead : 0;
      var x = xAt(i), y = yP(pLead);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    var fcLead = wkrForecastRow();
    preSlots.forEach(function (slot, k) {
      slot.rows.forEach(function (m, ri) {
        var info = preambleLeadOf(m, fcLead);
        if (info.p_lead == null || !isFinite(info.p_lead)) return;
        var xp = preamblePointX(pad.l, w, k, ri, 0, 1, preSlots);
        var col = info.likely ? '#23508f' : '#1a1a1a';
        if (info.leader && PARTY_COLORS[info.leader]) col = PARTY_COLORS[info.leader];
        drawPreambleDot(ctx, xp, yP(info.p_lead), col, preamblePublisher(m));
        ctx.fillStyle = col;
        ctx.font = '10px system-ui,sans-serif';
        var lab = fmtProb(info.p_lead);
        var tw = ctx.measureText(lab).width;
        ctx.fillText(lab, Math.max(pad.l, xp - tw / 2), Math.max(pad.t + 10, yP(info.p_lead) - 7));
      });
    });

    ctx.strokeStyle = '#5b7cfa';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(xAt(ci), pad.t);
    ctx.lineTo(xAt(ci), pad.t + h);
    ctx.stroke();
    ctx.setLineDash([]);
    var pNow = regions[ci].p_lead != null ? regions[ci].p_lead : 0;
    ctx.fillStyle = '#1a1a1a';
    ctx.beginPath();
    ctx.arc(xAt(ci), yP(pNow), 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = '12px system-ui,sans-serif';
    ctx.fillText(fmtProb(pNow), Math.min(xAt(ci) + 8, pad.l + w - 60), yP(pNow) - 6);
    stampLogo(ctx, cssW, cssH);
  }

  function renderWkrRace() {
    var el = $('wb-wkr-race');
    if (!el) return;
    if (state.scope !== 'wkr' || !state.unit) {
      el.hidden = true;
      el.innerHTML = '';
      return;
    }
    el.hidden = false;
    var st = steps();
    if (!st.length) { el.innerHTML = ''; return; }
    var staticW = (((state.data.geo_static || {}).wkr) || {})[state.unit] || {};
    var truthParty = staticW.erst_winner || null;
    var cur = st[Math.min(state.step, st.length - 1)];
    var region = (cur.by_wkr && cur.by_wkr[state.unit]) || {};
    var predParty = region.direct_pred || region.leader_pred || null;
    var predCand = predParty ? candidateFor(state.unit, predParty) : null;
    var call = wkrCalls()[state.unit] || {};
    var doneNow = isCompleteNow(region, call, cur);
    var uncNow = region.uncertainty || {};
    var erstNow = wkrErst(region);
    var leadShare = predParty ? erstNow[predParty] : null;
    var leadU = predParty ? uncNow[predParty] : null;
    var runP = region.runner_up;
    var runShare = runP ? erstNow[runP] : null;
    var runU = runP ? uncNow[runP] : null;
    var mU = marginUnc(region);
    var srcLeads = isLivePage() ? wkrPreambleLeadRows() : [];
    var srcLeadHtml = srcLeads.length
      ? '<div class="wb-wkr-plead-src">' + srcLeads.map(function (x) {
          var verdict = x.likely
            ? '<span class="wb-wkr-plead-likely">wahrscheinlich</span>'
            : '<span class="wb-art">offen</span>';
          var who = x.leader ? partyShort(x.leader) : '';
          return '<div class="wb-wkr-plead-row">' +
            '<span class="wb-wkr-plead-src-k">' + escapeHtml(x.label) +
              (who ? ' · ' + escapeHtml(who) : '') + '</span>' +
            '<span class="wb-wkr-plead-src-v">' + fmtProb(x.p_lead) + '</span>' +
            '<span class="wb-wkr-plead-src-t">' + verdict + '</span></div>';
        }).join('') + '</div>'
      : '';

    var roster = ((state.data && state.data.direkt_candidates_2026) || {})[String(state.unit)] || {};
    var extra = roster._extra || [];
    var topParties = PARTIES_ORDER.filter(function (p) { return p !== 'others'; })
      .sort(function (a, b) {
        return (erstNow[b] || 0) - (erstNow[a] || 0);
      });

    var chips = topParties.map(function (p) {
      var sh = erstNow[p];
      var u = uncNow[p];
      var c = candidateFor(state.unit, p);
      var win = (doneNow && p === truthParty)
        ? ' · <span class="wb-ok">Endstand</span>' : '';
      var lead = p === predParty ? ' · führt' : '';
      return '<span class="wb-wkr-chip" style="border-left:3px solid ' +
        (PARTY_COLORS[p] || '#888') + ';">' +
        '<strong>' + partyShort(p) + '</strong> ' + nameHtml(c) +
        (sh != null
          ? ' · <strong>' + fmtNum(sh, 1) + '%</strong>' +
            (u != null ? ' <span class="wb-range">±\u00a0' + fmtNum(u, 1) + '</span>' : '')
          : '') +
        lead + win + '</span>';
    }).join('') + extra.map(function (c) {
      return '<span class="wb-wkr-chip" style="border-left:3px solid #8a8a8a;">' +
        '<strong>' + escapeHtml(c.party_raw || 'Sonstige') + '</strong> ' +
        escapeHtml(c.name || '') + '</span>';
    }).join('');

    var tier = callTier(region);
    var callInfo;
    if (tier === 'called') {
      callInfo = '<span class="wb-ok">gecallt</span>' +
        (callWhen(call) ? ' seit <strong>' + callWhen(call) + '</strong>' : '');
    } else if (tier === 'likely') {
      callInfo = '<span style="color:#23508f;font-weight:600;">wahrscheinlich</span>' +
        (likelyWhen(call) ? ' seit <strong>' + likelyWhen(call) + '</strong>' : '');
    } else {
      callInfo = '<span class="wb-art">noch offen</span>';
    }
    var doneInfo = doneNow
      ? ('<span class="wb-ok">dieser WK vollständig</span>' +
        (completeWhen(call) ? ' seit <strong>' + completeWhen(call) + '</strong>' : ''))
      : ('<strong>' + Math.round((region.frac_reported || 0) * 100) +
        '\u00a0%</strong> in diesem WK · ' +
        (region.n_reported || 0) + ' WB');

    el.innerHTML =
      '<h3>Direktmandat · Erststimmen-Nowcast</h3>' +
      '<p class="wb-coverage-meta" style="margin:0 0 0.4rem;">' +
        'Führung und Zahlen hier sind <strong>Erststimme</strong> (Direktmandat). ' +
        'Die Zweitstimme in diesem WK steht im Chart darunter (gleiche Achse: zs.org, Exit, HR, dann 0–100&nbsp;%).' +
      '</p>' +
      '<div class="wb-wkr-hero">' +
        '<div class="wb-wkr-lead">' +
          (predParty ? partyShort(predParty) : '—') + ' — ' + nameHtml(predCand) +
        '</div>' +
        '<div class="wb-wkr-sub">' +
          (leadShare != null
            ? fmtNum(leadShare, 1) + '\u00a0%' +
              (leadU != null ? ' ±\u00a0' + fmtNum(leadU, 1) : '') +
              (runP && runShare != null
                ? ' vor ' + partyShort(runP) + ' ' + fmtNum(runShare, 1) + '\u00a0%' +
                  (runU != null ? ' ±\u00a0' + fmtNum(runU, 1) : '')
                : '')
            : '') +
          (region.margin != null
            ? ' · Marge ' + fmtNum(region.margin, 1) +
              (mU != null ? ' ±\u00a0' + fmtNum(mU, 1) : '') + '\u00a0PP'
            : '') +
        '</div>' +
        '<div class="wb-wkr-chips">' + chips + '</div>' +
        '<p class="wb-coverage-meta" id="wb-wkr-unc-note" style="margin:0.45rem 0 0;">' +
          escapeHtml(uncWkrNote(region)) + '</p>' +
        '<div class="wb-wkr-meta">' +
          '<div class="wb-wkr-plead">' +
            '<span class="wb-wkr-plead-k">P(Führung hält)</span>' +
            '<span class="wb-wkr-plead-v">' + fmtProb(region.p_lead) +
              '<span class="wb-wkr-plead-now">Nowcast</span></span>' +
            srcLeadHtml +
          '</div>' +
          '<dl>' +
          '<dt>Call</dt><dd>' + callInfo + '</dd>' +
          '<dt>Stand Land</dt><dd>' + stepWhen(cur, 'land') + '</dd>' +
          '<dt>Auszählung WK</dt><dd>' + doneInfo + '</dd>' +
        '</dl></div>' +
      '</div>' +
      '<p class="wb-chart-label" id="wb-race-chart-label">Erststimmen-Rennen über die Nacht</p>' +
      '<div class="wb-legend" id="wb-race-legend"></div>' +
      '<canvas id="wb-chart-race" class="wb-chart wb-chart-race" width="900" height="260"></canvas>' +
      '<p class="wb-chart-label">P(Führung hält) · Wahrscheinlich / Call</p>' +
      '<canvas id="wb-chart-prob" class="wb-chart wb-chart-prob" width="900" height="160"></canvas>' +
      '<p class="wb-meta" style="margin:0.25rem 0 0;">' +
        'Blau = Partei wahrscheinlich (auch ohne WK-Meldung); Grün = harter Call.' +
        (srcLeads.length
          ? ' Links von 0&nbsp;%: zs.org-Wahlkreisprognose, Exit, HR (P und Farbe = führende Partei).'
          : '') +
        (isLivePage() ? '' : ' Slider oben bewegt den Zeitpunkt (blaue Linie).') +
      '</p>';

    // Draw after layout so clientWidth is correct
    requestAnimationFrame(function () {
      drawWkrRaceCharts();
    });
  }


  function renderCallBanner() {
    var el = $('wb-call-banner');
    if (!el) return;
    if (state.scope !== 'wkr' || !state.unit) {
      el.innerHTML = '';
      return;
    }
    var st = steps();
    if (!st.length) { el.innerHTML = ''; return; }
    var s = st[Math.min(state.step, st.length - 1)];
    var r = (s.by_wkr && s.by_wkr[state.unit]) || {};
    var call = wkrCalls()[state.unit] || {};
    var p = r.direct_pred || r.leader_pred;
    var cand = p ? candidateFor(state.unit, p) : null;
    var thrLikelyPct = fmtNum(((state.data && state.data.call_threshold) || 0.90) * 100, 0);
    var thrCallPct = fmtNum(((state.data && state.data.hard_call_threshold) || 0.999) * 100, 1);
    var doneBit = '';
    if (isCompleteNow(r, call, s)) {
      var cwhen = completeWhen(call);
      doneBit = ' · <span class="wb-ok">dieser WK voll ausgezählt</span>' +
        (cwhen ? ' seit <strong>' + cwhen + '</strong>' : '');
    }
    var tier = callTier(r);
    if (tier === 'called') {
      var since = '';
      var when = callWhen(call);
      if (when && call.called_at != null && call.called_at <= s.frac_reported + 1e-9) {
        since = ' seit <strong>' + when + '</strong>';
      }
      var verdict = '';
      if (isCompleteNow(r, call, s) && call.truth_erst) {
        if (p === call.truth_erst) {
          verdict = ' · Endstand bestätigt (<strong>' + partyShort(call.truth_erst) + '</strong>)';
        } else {
          verdict = ' · <span class="wb-bad">FEHL-CALL — Endstand ' +
            partyShort(call.truth_erst) + '</span>';
        }
      }
      el.innerHTML =
        '<div class="wb-call-banner wb-called">✔ <strong>Gecallt für ' +
        partyShort(p) + '</strong> — ' + nameHtml(cand) + since +
        ' · P(Führung hält) ' + fmtProb(r.p_lead) + doneBit + verdict + '</div>';
    } else if (tier === 'likely') {
      var lsince = '';
      var lwhen = likelyWhen(call);
      if (lwhen && call.likely_at != null && call.likely_at <= s.frac_reported + 1e-9) {
        lsince = ' seit <strong>' + lwhen + '</strong>';
      }
      var localNote = (r.frac_reported || 0) <= 0
        ? ' <span class="wb-art">(noch keine Meldung im WK — aus Prior/Landestrend)</span>'
        : '';
      el.innerHTML =
        '<div class="wb-call-banner wb-likely">◐ <strong>Partei wahrscheinlich: ' +
        partyShort(p) + '</strong> — ' + nameHtml(cand) + lsince +
        ' · P(Führung hält) ' + fmtProb(r.p_lead) + doneBit + localNote +
        ' <span class="wb-art">(Call ab ' + thrCallPct +
        '\u00a0% und wenn Rest die Marge nicht mehr kippen kann)</span></div>';
    } else {
      el.innerHTML =
        '<div class="wb-call-banner wb-open">Noch offen — <strong>' +
        (p ? partyShort(p) : '—') + '</strong> führt mit ' +
        (r.margin != null ? fmtNum(r.margin, 1) + '\u00a0PP' : '—') +
        ' · P(Führung hält) ' + fmtProb(r.p_lead) + doneBit +
        ' <span class="wb-art">(Wahrscheinlich ab ' + thrLikelyPct +
        '\u00a0%; Call ab ' + thrCallPct + '\u00a0%)</span></div>';
    }
  }

  function renderWkrWhy() {
    var el = $('wb-wkr-why');
    if (!el) return;
    if (state.scope !== 'wkr' || !state.unit) {
      el.innerHTML = '';
      return;
    }
    var st = steps();
    if (!st.length) { el.innerHTML = ''; return; }
    var s = st[Math.min(state.step, st.length - 1)];
    var r = (s.by_wkr && s.by_wkr[state.unit]) || {};
    var reported = reportedSet(s);
    var plist = realPrecincts((state.data.precincts || []).filter(function (p) {
      return p.wkr === state.unit;
    }));
    var stats = { W: { n: 0, rep: 0 }, B: { n: 0, rep: 0 } };
    plist.forEach(function (p) {
      var k = p.art === 'B' ? 'B' : 'W';
      stats[k].n++;
      if (reported[p.id]) stats[k].rep++;
    });
    var nc = r.nowcast || {};
    var nv = r.naive || {};
    var diffs = PARTIES_ORDER.filter(function (p) { return p !== 'others'; })
      .map(function (p) {
        return { p: p, d: (nc[p] || 0) - (nv[p] || 0) };
      })
      .filter(function (x) { return Math.abs(x.d) >= 0.8; })
      .sort(function (a, b) { return Math.abs(b.d) - Math.abs(a.d); });
    var lastEl = lastElectionRef();
    var lastYear = lastEl && lastEl.year != null ? String(lastEl.year) : '2021';
    var nRep = stats.W.rep + stats.B.rep;
    var html;
    var liveWk = isLivePage() && plist.length === 0;
    if (liveWk) {
      nRep = r.n_reported || 0;
      var nTot = r.n_total || 0;
      var fracW = r.frac_reported || 0;
      if (fracW <= 0 && nRep <= 0) {
        html = 'Im Wahlkreis ist noch nichts gemeldet — die Anzeige ist die ' +
          '<strong>zweitstimme.org-Wahlkreisprognose</strong> auf Basis von <strong>LTW&nbsp;' +
          lastYear + '</strong> (Erststimme: WK-Regression ohne Kandidateneffekte). ' +
          'Andere bereits gezählte Kreise können den Landestrend noch leicht verschieben.';
      } else if (fracW >= 0.999 || (nTot > 0 && nRep >= nTot)) {
        html = 'Dieser Wahlkreis ist ausgezählt — Nowcast = gemeldetes Ergebnis.';
      } else {
        html = 'Gemeldet: <strong>' + nRep + (nTot ? '/' + nTot : '') +
          '</strong> Wahlbezirke in diesem WK. Der offene Rest bleibt die ' +
          lastYear + 'er Wahlkreisprognose plus Swing aus den gezählten Bezirken.';
      }
    } else if (!nRep) {
      html = 'Im Wahlkreis ist noch nichts gemeldet — die Anzeige ist die ' +
        '<strong>Ausgangslage</strong> (' + lastYear +
        ' plus Swing auf das Vorwahl-Ziel), ' +
        'korrigiert nur um das, was andere Gebiete bereits über den Landestrend verraten.';
    } else if (nRep >= plist.length) {
      var cwhenWhy = completeWhen(wkrCalls()[state.unit] || {});
      html = 'Alle ' + plist.length + ' Wahlbezirke in diesem WK sind ausgezählt' +
        (cwhenWhy ? ' <strong>seit ' + cwhenWhy + '</strong>' : '') +
        ' — Nowcast = Endstand im Wahlkreis.';
    } else {
      html = 'Gemeldet: <strong>' + nRep + '/' + plist.length + '</strong> Wahlbezirke ' +
        '(Urne ' + stats.W.rep + '/' + stats.W.n + ', Brief ' + stats.B.rep + '/' + stats.B.n + '). ' +
        'Der Nowcast überschreibt die offenen Wahlbezirke <em>nicht</em> mit dem bisherigen ' +
        'Rohstand, sondern lässt ihnen die Ausgangslage (' + lastYear +
        ' + Swing) plus die gelernte Korrektur. ';
      if (diffs.length) {
        html += 'Größte Abweichungen zum Rohstand: ' + diffs.slice(0, 3).map(function (x) {
          return partyShort(x.p) + ' <strong>' + fmtPp(x.d) + '</strong>';
        }).join(', ') + '.';
        if (stats.B.rep === 0 && stats.B.n > 0) {
          html += ' Briefwahl (' + stats.B.n + ' WB) fehlt noch komplett — die zählt oft anders als die Urne.';
        }
      } else {
        html += 'Nowcast und Rohstand liegen hier derzeit nah beieinander.';
      }
    }
    el.innerHTML = '<div class="wb-why"><strong>Warum weicht der Nowcast vom bisherigen Rohstand ab?</strong><br>' + html + '</div>';
  }

  function openWkr(uid) {
    state.scope = 'wkr';
    state.unit = String(uid);
    renderScopeButtons();
    renderStep();
    var root = $('wahlabend-root');
    if (root) root.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function collectWkrRaces(s) {
    var byW = (s && s.by_wkr) || {};
    var units = ((state.data.geo_units || {}).wkr) || [];
    var calls = wkrCalls();
    return units.map(function (u) {
      var r = byW[u.id] || {};
      var call = calls[u.id] || {};
      var p = r.direct_pred || r.leader_pred;
      var truthP = call.truth_erst;
      var calledNow = !!r.called;
      var likelyNow = callTier(r) === 'likely' || calledNow;
      var hitNow = !!(p && truthP && p === truthP);
      var pLead = r.p_lead != null ? r.p_lead : 1;
      var margin = r.margin != null ? r.margin : 99;
      return {
        id: u.id,
        label: u.label,
        bezirk: u.bezirk || '',
        party: p,
        cand: p ? candidateFor(u.id, p) : null,
        r: r,
        call: call,
        called: calledNow,
        likely: likelyNow,
        truthP: truthP,
        hitNow: hitNow,
        pLead: pLead,
        margin: margin,
        mu: marginUnc(r)
      };
    });
  }

  function bindWkrLinks(root) {
    if (!root) return;
    root.querySelectorAll('[data-wkr-link]').forEach(function (el) {
      el.addEventListener('click', function () {
        openWkr(el.getAttribute('data-wkr-link'));
      });
    });
  }

  function geoCandidates() {
    if (state.land === 'st') {
      return ['ltw_wahlkreise_st_simple.geojson', 'ltw_wahlkreise_st.geojson'];
    }
    if (state.land === 'mv') return ['ltw_wahlkreise_mv.geojson'];
    if (state.land === 'be') return ['ltw_wahlkreise_be.geojson'];
    return [];
  }

  function ensureGeo(cb) {
    if (state.geo) { cb(state.geo); return; }
    if (state.geo === false) { cb(null); return; }
    if (state._geoLoading) { state._geoWait = cb; return; }
    var files = geoCandidates();
    if (!files.length) { state.geo = false; cb(null); return; }
    state._geoLoading = true;
    var i = 0;
    function next() {
      if (i >= files.length) {
        state._geoLoading = false;
        state.geo = false;
        cb(null);
        return;
      }
      fetch(dataUrl(files[i])).then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      }).then(function (g) {
        state._geoLoading = false;
        state.geo = g;
        cb(g);
        if (state._geoWait) { var w = state._geoWait; state._geoWait = null; w(g); }
      }).catch(function () {
        i += 1;
        next();
      });
    }
    next();
  }

  function ringPath(ring, proj) {
    return ring.map(function (pt, i) {
      var xy = proj(pt[0], pt[1]);
      return (i === 0 ? 'M' : 'L') + xy[0].toFixed(1) + ' ' + xy[1].toFixed(1);
    }).join(' ') + ' Z';
  }

  function geomPath(geom, proj) {
    if (!geom) return '';
    if (geom.type === 'Polygon') {
      return (geom.coordinates || []).map(function (r) { return ringPath(r, proj); }).join(' ');
    }
    if (geom.type === 'MultiPolygon') {
      return (geom.coordinates || []).map(function (poly) {
        return (poly || []).map(function (r) { return ringPath(r, proj); }).join(' ');
      }).join(' ');
    }
    return '';
  }

  function geomCentroid(geom) {
    var ring = null;
    if (geom && geom.type === 'Polygon') ring = geom.coordinates && geom.coordinates[0];
    else if (geom && geom.type === 'MultiPolygon') {
      var best = null;
      var bestN = 0;
      (geom.coordinates || []).forEach(function (poly) {
        var r = poly && poly[0];
        if (r && r.length > bestN) { best = r; bestN = r.length; }
      });
      ring = best;
    }
    if (!ring || !ring.length) return null;
    var sx = 0, sy = 0, n = 0;
    ring.forEach(function (pt) {
      if (!pt || pt.length < 2) return;
      sx += pt[0]; sy += pt[1]; n += 1;
    });
    return n ? [sx / n, sy / n] : null;
  }

  function featWkrId(props) {
    if (!props) return '';
    var raw = props.wkr != null ? props.wkr : (props.WKR != null ? props.WKR : props.id);
    return String(raw == null ? '' : raw);
  }

  function renderMap() {
    var svg = $('wb-map');
    var cap = $('wb-map-caption');
    var block = $('wb-map-block');
    if (!svg || !block) return;
    var show = state.scope === 'wkr';
    if (!show) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    var st = steps();
    if (!st.length) return;
    var s = st[Math.min(state.step, st.length - 1)];
    var races = collectWkrRaces(s);
    var byId = {};
    races.forEach(function (x) { byId[String(x.id)] = x; });
    ensureGeo(function (geo) {
      if (!geo || !geo.features) {
        svg.innerHTML = '';
        if (cap) cap.textContent = 'Wahlkreis-GeoJSON nicht auf dem Preview (ltw_wahlkreise_' + state.land + '.geojson).';
        return;
      }
      var feats = geo.features;
      var minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
      function walk(c) {
        if (!c) return;
        if (typeof c[0] === 'number') {
          minLon = Math.min(minLon, c[0]); maxLon = Math.max(maxLon, c[0]);
          minLat = Math.min(minLat, c[1]); maxLat = Math.max(maxLat, c[1]);
          return;
        }
        c.forEach(walk);
      }
      feats.forEach(function (f) { walk(f.geometry && f.geometry.coordinates); });
      var meanLat = (minLat + maxLat) / 2;
      var kx = Math.cos(meanLat * Math.PI / 180);
      var pad = 18;
      var vbW = 640, vbH = 780;
      var dx = (maxLon - minLon) * kx;
      var dy = maxLat - minLat;
      var sxy = Math.min((vbW - 2 * pad) / Math.max(dx, 1e-6), (vbH - 2 * pad) / Math.max(dy, 1e-6));
      function proj(lon, lat) {
        return [
          pad + (lon - minLon) * kx * sxy,
          pad + (maxLat - lat) * sxy
        ];
      }
      var paths = [];
      var labels = [];
      feats.forEach(function (f) {
        var id = featWkrId(f.properties);
        var x = byId[id] || { id: id, label: unitLabel('wkr', id), party: null, called: false, likely: false, r: {} };
        var d = geomPath(f.geometry, proj);
        if (!d) return;
        var col = x.party ? (PARTY_COLORS[x.party] || '#888') : '#c8c8c8';
        var frac = (x.r && x.r.frac_reported) || 0;
        var fillOp = x.called ? 0.92 : (x.likely ? 0.55 : (0.18 + 0.55 * frac));
        var active = state.scope === 'wkr' && String(state.unit) === String(id);
        var parts = shortWkrLabel(x.label, id);
        var title = (parts.rest ? (parts.num + ' ' + parts.rest) : ('WK ' + parts.num)) +
          (x.party ? ' · ' + partyShort(x.party) : '') +
          (x.called ? ' · Call' : (x.likely ? ' · wahrscheinlich' : ' · offen'));
        paths.push('<path data-wkr-link="' + escapeHtml(id) + '" class="' +
          (active ? 'is-active' : '') + '" d="' + d + '" fill="' + col +
          '" fill-opacity="' + fillOp.toFixed(2) + '"><title>' + escapeHtml(title) + '</title></path>');
        var c = geomCentroid(f.geometry);
        if (c) {
          var xy = proj(c[0], c[1]);
          var fill = (x.called && x.party && x.party !== 'fdp') ? '#fff' : '#1a1a1a';
          labels.push('<text class="wb-map-label" x="' + xy[0].toFixed(1) + '" y="' +
            xy[1].toFixed(1) + '" fill="' + fill + '">' +
            escapeHtml(parts.num) + '</text>');
        }
      });
      svg.innerHTML = '<g>' + paths.join('') + '</g><g>' + labels.join('') + '</g>';
      bindWkrLinks(svg);
      if (cap) {
        var nCalled = races.filter(function (x) { return x.called; }).length;
        cap.textContent = nCalled + ' von ' + races.length +
          ' Wahlkreisen gecallt · Deckkraft = ausgezählte Wahlbezirke im Kreis.';
      }
    });
  }

  function hexToRgb(hex) {
    var h = String(hex || '').replace('#', '');
    if (h.length === 3) {
      h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    }
    if (h.length !== 6) return { r: 136, g: 136, b: 136 };
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16)
    };
  }

  function partyRgba(party, alpha) {
    var rgb = hexToRgb(PARTY_COLORS[party] || '#888888');
    return 'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',' + alpha + ')';
  }

  /** Dunkler Text auf hellen Parteifarben (FDP). */
  function partyOnColor(party) {
    return party === 'fdp' ? '#1a1a1a' : '#ffffff';
  }

  function shortWkrLabel(label, id) {
    var s = String(label || '').trim();
    var m = s.match(/^(?:WK\s*)?(\d+)\s*[·.•\-–]?\s*(.*)$/i);
    var num = m ? m[1] : String(id);
    var rest = (m && m[2] ? m[2] : '').trim();
    if (!rest || rest === num) rest = '';
    return { num: num, rest: rest };
  }

  function wkrTileHtml(x) {
    var tier = x.called ? 'called' : (x.likely ? 'likely' : 'open');
    var parts = shortWkrLabel(x.label, x.id);
    var style = '';
    if (tier === 'called' && x.party) {
      style = 'background:' + (PARTY_COLORS[x.party] || '#888') +
        ';border-color:' + (PARTY_COLORS[x.party] || '#888') +
        ';color:' + partyOnColor(x.party) + ';';
    } else if (tier === 'likely' && x.party) {
      style = 'background:' + partyRgba(x.party, 0.22) +
        ';border-color:' + (PARTY_COLORS[x.party] || '#888') + ';';
    }
    var tip = escapeHtml(x.label) +
      (x.party ? ' · ' + partyShort(x.party) : '') +
      (tier === 'called' ? ' · Call' : (tier === 'likely' ? ' · wahrscheinlich' : ' · offen'));
    var active = state.scope === 'wkr' && String(state.unit) === String(x.id);
    var nameHtml = parts.rest
      ? '<span class="wb-wkr-tile-name">' + escapeHtml(parts.rest) + '</span>'
      : '';
    return '<button type="button" class="wb-wkr-tile wb-wkr-tile-' + tier +
      (active ? ' is-active' : '') +
      '" data-wkr-link="' + x.id + '" data-search="' + escapeHtml(wkrSearchHaystack(x)) +
      '" style="' + style + '" title="' + tip + '">' +
      '<span class="wb-wkr-tile-num">' + escapeHtml(parts.num) + '</span>' +
      nameHtml +
      '</button>';
  }

  function comparisonSize(row) {
    if (!row) return null;
    var q = row.parliament_size;
    if (Array.isArray(q) && q.length >= 3) {
      return [Number(q[0]), Number(q[1]), Number(q[2])];
    }
    if (q != null && isFinite(q)) {
      var v = Number(q);
      return [v, v, v];
    }
    return null;
  }

  function drawSizeChart() {
    var canvas = $('wb-chart-size');
    if (!canvas || state.scope !== 'lage') return;
    var st = steps();
    if (!st.length) return;
    var ci = Math.min(state.step, st.length - 1);
    // Kurve nur bis jetzt; X-Achse = volle Nacht (leerer Rest = „kommt noch“)
    var qs = st.map(function (s, i) {
      if (i > ci) return null;
      return (s.entry_mc && s.entry_mc.size) || null;
    });
    if (!qs.some(function (q) { return q; })) return;
    var showTruth = isLandComplete(st[ci]);
    var inst = institutionsOf(st[ci].eval);
    var sizeTruth = showTruth && inst && inst.parliament ? inst.parliament.size_truth : null;
    var lastEl = lastElectionRef();
    var lastSize = lastEl && lastEl.parliament_size != null ? lastEl.parliament_size : null;
    var preMarks = preambleMarkers().filter(function (m) { return comparisonSize(m); });
    var preSlots = preambleSlots(preMarks);
    var nightOpt = { preamble: isLivePage() && preSlots.length > 0, slots: preSlots };

    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 900;
    var cssH = canvas.clientHeight || 220;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    var nFull = st.length;
    var pad = { l: 40, r: 12, t: 16, b: nightOpt.preamble ? 36 : 24 };
    var w = cssW - pad.l - pad.r;
    var h = cssH - pad.t - pad.b;
    var vals = [];
    qs.forEach(function (q) { if (q) { vals.push(q[0], q[2]); } });
    if (sizeTruth != null) vals.push(sizeTruth);
    if (lastSize != null) vals.push(lastSize);
    preMarks.forEach(function (m) {
      var sq = comparisonSize(m);
      if (sq) vals.push(sq[0], sq[2]);
    });
    var yMin = Math.min.apply(null, vals) - 4;
    var yMax = Math.max.apply(null, vals) + 4;

    function xAt(i) { return xAlongNight(pad.l, w, st, i, nightOpt); }
    function yAt(v) { return pad.t + (1 - (v - yMin) / (yMax - yMin)) * h; }

    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.stroke();

    shadeRestOfNight(ctx, pad, w, h, st, ci, nightOpt);
    drawPreambleAxis(ctx, pad, w, cssH, nightOpt);

    ctx.fillStyle = '#888';
    ctx.font = '11px system-ui,sans-serif';
    var x0live = countAxisOrigin(pad.l, w, nightOpt);
    var x0 = isLivePage() ? '0\u00a0%' : (clockOnly(st[0].clock, st[0].clock_source) ||
      (Math.round((st[0].frac_reported || 0) * 100) + '\u00a0%'));
    var xEnd = isLivePage() ? '100\u00a0%' : (clockOnly(st[nFull - 1].clock, st[nFull - 1].clock_source) ||
      (Math.round((st[nFull - 1].frac_reported || 0) * 100) + '\u00a0%'));
    ctx.fillText(x0, isLivePage() ? x0live : pad.l, cssH - 6);
    var xEndW = ctx.measureText(xEnd).width;
    ctx.fillText(xEnd, pad.l + w - xEndW, cssH - 6);
    ctx.fillText(String(Math.round(yMax)), 6, pad.t + 10);
    ctx.fillText(String(Math.round(yMin)), 6, pad.t + h);

    // p10–p90 band (nur bis jetzt)
    ctx.fillStyle = 'rgba(91,124,250,0.16)';
    ctx.beginPath();
    var started = false;
    for (var i = 0; i <= ci; i++) {
      if (!qs[i]) continue;
      var x = xAt(i), y = yAt(qs[i][2]);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    for (var j = ci; j >= 0; j--) {
      if (!qs[j]) continue;
      ctx.lineTo(xAt(j), yAt(qs[j][0]));
    }
    if (started) {
      ctx.closePath();
      ctx.fill();
    }

    if (sizeTruth != null) {
      ctx.strokeStyle = '#888';
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(pad.l, yAt(sizeTruth));
      ctx.lineTo(pad.l + w, yAt(sizeTruth));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#666';
      ctx.fillText('Wahr ' + sizeTruth, pad.l + 6, yAt(sizeTruth) - 4);
    }
    if (lastSize != null) {
      drawHRef(
        ctx, pad, w, yAt, lastSize,
        lastElectionShort(lastEl) + ': ' + lastSize,
        '#8a6d3b'
      );
    }

    ctx.strokeStyle = '#1a1a1a';
    ctx.lineWidth = 2;
    ctx.beginPath();
    var started2 = false;
    for (var k = 0; k <= ci; k++) {
      if (!qs[k]) continue;
      var xk = xAt(k), yk = yAt(qs[k][1]);
      if (!started2) { ctx.moveTo(xk, yk); started2 = true; } else ctx.lineTo(xk, yk);
    }
    ctx.stroke();
    preSlots.forEach(function (slot, pk) {
      slot.rows.forEach(function (m, ri) {
        var sq = comparisonSize(m);
        if (!sq) return;
        var xp = preamblePointX(pad.l, w, pk, ri, 0, 1, preSlots);
        drawVertSpan(ctx, xp, sq[0], sq[2], yAt, '#1a1a1a');
        drawPreambleDot(ctx, xp, yAt(sq[1]), '#1a1a1a', preamblePublisher(m));
      });
    });

    // Aktueller Stand (nicht am rechten Achsenrand, solange Nacht offen)
    if (qs[ci]) {
      var xc = xAt(ci);
      ctx.strokeStyle = 'rgba(0,0,0,0.18)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(xc, pad.t);
      ctx.lineTo(xc, pad.t + h);
      ctx.stroke();
      ctx.setLineDash([]);
      drawVertSpan(ctx, xc, qs[ci][0], qs[ci][2], yAt, '#1a1a1a');
      ctx.fillStyle = '#1a1a1a';
      ctx.beginPath();
      ctx.arc(xc, yAt(qs[ci][1]), 3.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = '12px system-ui,sans-serif';
      var label = qs[ci][1] + ' (p10 ' + qs[ci][0] + ' – p90 ' + qs[ci][2] + ')';
      var lw = ctx.measureText(label).width;
      ctx.fillText(
        label,
        Math.max(pad.l, Math.min(xc + 6, pad.l + w - lw)),
        yAt(qs[ci][1]) - 8
      );
    }
    stampLogo(ctx, cssW, cssH);
  }

  function drawTurnoutChart() {
    var canvas = $('wb-chart-turnout');
    if (!canvas || state.scope !== 'lage') return;
    var st = steps();
    if (!st.length) return;
    var ci = Math.min(state.step, st.length - 1);
    var showTruth = isLandComplete(st[ci]);
    var series = st.map(function (s, i) {
      if (i > ci) return null;
      return s.turnout || null;
    });
    if (!series.some(function (t) { return t && t.nowcast != null; })) return;

    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 900;
    var cssH = canvas.clientHeight || 220;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    var nFull = st.length;
    var preMarks = preambleMarkers();
    var preSlots = preambleSlots();
    var nightOpt = { preamble: isLivePage() && preSlots.length > 0, slots: preSlots };
    var pad = { l: 40, r: 12, t: 16, b: nightOpt.preamble ? 36 : 24 };
    var w = cssW - pad.l - pad.r;
    var h = cssH - pad.t - pad.b;
    var vals = [];
    series.forEach(function (t) {
      if (!t || t.nowcast == null) return;
      var u = t.uncertainty != null ? t.uncertainty : 0;
      vals.push(t.nowcast - u, t.nowcast + u);
      if (showTruth && t.truth != null) vals.push(t.truth);
    });
    var truth = showTruth && st[ci].turnout ? st[ci].turnout.truth : null;
    if (truth != null) vals.push(truth);
    var lastEl = lastElectionRef();
    var lastTo = lastEl && lastEl.turnout != null ? lastEl.turnout : null;
    if (lastTo != null) vals.push(lastTo);
    preMarks.forEach(function (m) {
      if (m.turnout == null) return;
      var tu = m.turnout_unc != null ? m.turnout_unc : 0;
      vals.push(m.turnout - tu, m.turnout + tu);
    });
    var yMin = Math.min.apply(null, vals) - 1;
    var yMax = Math.max.apply(null, vals) + 1;
    if (!(yMax > yMin)) { yMin = 50; yMax = 80; }

    function xAt(i) { return xAlongNight(pad.l, w, st, i, nightOpt); }
    function yAt(v) { return pad.t + (1 - (v - yMin) / (yMax - yMin)) * h; }

    ctx.strokeStyle = '#ddd';
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.stroke();

    shadeRestOfNight(ctx, pad, w, h, st, ci, nightOpt);
    drawPreambleAxis(ctx, pad, w, cssH, nightOpt);

    ctx.fillStyle = '#888';
    ctx.font = '11px system-ui,sans-serif';
    var x0live = countAxisOrigin(pad.l, w, nightOpt);
    var x0 = isLivePage() ? '0\u00a0%' : (clockOnly(st[0].clock, st[0].clock_source) ||
      (Math.round((st[0].frac_reported || 0) * 100) + '\u00a0%'));
    var xEnd = isLivePage() ? '100\u00a0%' : (clockOnly(st[nFull - 1].clock, st[nFull - 1].clock_source) ||
      (Math.round((st[nFull - 1].frac_reported || 0) * 100) + '\u00a0%'));
    ctx.fillText(x0, isLivePage() ? x0live : pad.l, cssH - 6);
    ctx.fillText(xEnd, pad.l + w - ctx.measureText(xEnd).width, cssH - 6);
    ctx.fillText(fmtNum(yMax, 0) + '\u00a0%', 4, pad.t + 10);
    ctx.fillText(fmtNum(yMin, 0) + '\u00a0%', 4, pad.t + h);

    // ± band
    ctx.fillStyle = 'rgba(91,124,250,0.16)';
    ctx.beginPath();
    var started = false;
    for (var i = 0; i <= ci; i++) {
      var t = series[i];
      if (!t || t.nowcast == null) continue;
      var uHi = t.nowcast + (t.uncertainty != null ? t.uncertainty : 0);
      var x = xAt(i), y = yAt(uHi);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    for (var j = ci; j >= 0; j--) {
      var tLo = series[j];
      if (!tLo || tLo.nowcast == null) continue;
      var uLo = tLo.nowcast - (tLo.uncertainty != null ? tLo.uncertainty : 0);
      ctx.lineTo(xAt(j), yAt(uLo));
    }
    if (started) { ctx.closePath(); ctx.fill(); }

    if (truth != null) {
      ctx.strokeStyle = '#888';
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(pad.l, yAt(truth));
      ctx.lineTo(pad.l + w, yAt(truth));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#666';
      ctx.fillText('Wahr ' + fmtNum(truth, 1) + '\u00a0%', pad.l + 6, yAt(truth) - 4);
    }
    if (lastTo != null) {
      drawHRef(
        ctx, pad, w, yAt, lastTo,
        lastElectionShort(lastEl) + ': ' + fmtNum(lastTo, 1) + '\u00a0%',
        '#8a6d3b'
      );
    }

    ctx.strokeStyle = '#1a1a1a';
    ctx.lineWidth = 2;
    ctx.beginPath();
    var started2 = false;
    for (var k = 0; k <= ci; k++) {
      var tk = series[k];
      if (!tk || tk.nowcast == null) continue;
      var xk = xAt(k), yk = yAt(tk.nowcast);
      if (!started2) { ctx.moveTo(xk, yk); started2 = true; }
      else ctx.lineTo(xk, yk);
    }
    ctx.stroke();
    preSlots.forEach(function (slot, pk) {
      slot.rows.forEach(function (m, ri) {
        if (m.turnout == null) return;
        var xp = preamblePointX(pad.l, w, pk, ri, 0, 1, preSlots);
        drawVertCI(ctx, xp, m.turnout, m.turnout_unc || 0, yAt, '#1a1a1a');
        drawPreambleDot(ctx, xp, yAt(m.turnout), '#1a1a1a', preamblePublisher(m));
      });
    });

    var cur = series[ci];
    if (cur && cur.nowcast != null) {
      var xc = xAt(ci);
      ctx.strokeStyle = 'rgba(0,0,0,0.18)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(xc, pad.t);
      ctx.lineTo(xc, pad.t + h);
      ctx.stroke();
      ctx.setLineDash([]);
      drawVertCI(ctx, xc, cur.nowcast, cur.uncertainty || 0, yAt, '#1a1a1a');
      ctx.fillStyle = '#1a1a1a';
      ctx.beginPath();
      ctx.arc(xc, yAt(cur.nowcast), 3.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = '12px system-ui,sans-serif';
      var label = fmtNum(cur.nowcast, 1) + '\u00a0%' +
        (cur.uncertainty != null && cur.uncertainty > 0
          ? ' ±\u00a0' + fmtNum(cur.uncertainty, 1)
          : '');
      var lw = ctx.measureText(label).width;
      ctx.fillText(
        label,
        Math.max(pad.l, Math.min(xc + 6, pad.l + w - lw)),
        yAt(cur.nowcast) - 8
      );
    }
    stampLogo(ctx, cssW, cssH);
  }

  function entryStatusHtml(rank, q) {
    if (!q) return '<span class="wb-entry-status">—</span>';
    if (rank <= q[0]) return '<span class="wb-entry-status wb-in">sicher</span>';
    if (rank <= q[2]) return '<span class="wb-entry-status wb-maybe">Wackelplatz</span>';
    return '<span class="wb-entry-status wb-out">draußen</span>';
  }

  function usesBezirkListe(slot, listQ) {
    if (listQ && !Array.isArray(listQ) && typeof listQ === 'object') return true;
    if (slot && slot.list_type === 'bezirk') return true;
    var hasBez = slot && slot.bezirk && Object.keys(slot.bezirk).length > 0;
    var hasLand = slot && slot.landes && slot.landes.length > 0;
    return !!(hasBez && !hasLand);
  }

  function bezirkListBody(slot, listQ, wonWkrs) {
    var bezIds = Object.keys((slot && slot.bezirk) || {}).sort();
    if (!bezIds.length) return '<p class="wb-meta">Keine Listendaten.</p>';
    var perBez = listQ && !Array.isArray(listQ) && typeof listQ === 'object';
    var body = bezIds.map(function (bid) {
      var q = perBez ? (listQ[bid] || [0, 0, 0]) : null;
      var seatTxt = q
        ? (' — Listensitze ' + q[1] + ' <span class="wb-art">(p10 ' + q[0] +
          ' – p90 ' + q[2] + ')</span>')
        : '';
      return '<details class="wb-cov-nest"><summary>' +
        escapeHtml(unitLabel('bezirk', bid)) + seatTxt + '</summary>' +
        entryListTable(slot.bezirk[bid], q, wonWkrs) + '</details>';
    }).join('');
    return '<p class="wb-coverage-meta">Bezirkslisten (keine Landesliste): Sitze ' +
      'per Hare/Niemeyer auf die Bezirke (vereinfachte Suballokation). ' +
      'Aufklappen für Listenplätze je Bezirk.</p>' + body;
  }

  function entryListTable(entries, q, wonWkrs) {
    if (!entries || !entries.length) return '<p class="wb-meta">Keine Listendaten.</p>';
    var hi = q ? q[2] : Math.min(entries.length, 8);
    var rank = 0;
    var shown = 0;
    var hidden = 0;
    var rows = [];
    entries.forEach(function (e) {
      var direct = e.wkr != null && wonWkrs['' + e.wkr];
      var cell;
      if (direct) {
        cell = '<span class="wb-entry-status wb-direct-tag">Direkt WK ' + e.wkr + '</span>';
      } else {
        rank++;
        cell = entryStatusHtml(rank, q);
      }
      var isVisible = direct ? (shown <= hi + 3) : (rank <= hi + 3);
      if (!isVisible) { hidden++; return; }
      shown++;
      // Replay (AGH 2023 / LTW 2021): no 2026 names. Live ST 2026: real Landesliste.
      var showName = isLivePage() && e.name && !e.ph;
      rows.push('<tr><td>' + e.pos + '</td><td>' +
        nameHtml(showName
          ? { name: e.name, is_placeholder: false }
          : { name: 'Listenplatz ' + e.pos, is_placeholder: true }) +
        '</td><td>' + cell + '</td></tr>');
    });
    var more = hidden ? '<p class="wb-art" style="margin:0.25rem 0 0;">… ' + hidden + ' weitere Plätze (draußen)</p>' : '';
    return '<table class="wb-cov-table"><thead><tr>' +
      '<th>Platz</th><th>Name</th><th>Status</th></tr></thead><tbody>' +
      rows.join('') + '</tbody></table>' + more;
  }

  function placeholderListEntries(n, party) {
    var out = [];
    for (var i = 1; i <= n; i++) {
      out.push({ pos: i, name: partyShort(party) + ' · Listenplatz ' + i, ph: true });
    }
    return out;
  }

  function renderEntry() {
    var el = $('wb-entry');
    if (!el) return;
    if (state.scope !== 'land') {
      el.innerHTML = '';
      return;
    }
    if (!hasListenEinzug()) {
      el.innerHTML = '';
      return;
    }
    var st = steps();
    if (!st.length) { el.innerHTML = ''; return; }
    var s = st[Math.min(state.step, st.length - 1)];
    var mc = s.entry_mc;
    var roster = (state.data && state.data.listen_roster_2026) || {};
    if (!mc || !Object.keys(roster).length) {
      el.innerHTML = '<p class="wb-meta">Listen-Einzug für dieses Land ist noch nicht verfügbar.</p>';
      return;
    }
    var wonByParty = {};
    Object.keys(s.by_wkr || {}).forEach(function (uid) {
      var r = s.by_wkr[uid];
      var p = r.direct_pred || r.leader_pred;
      if (!p) return;
      if (!wonByParty[p]) wonByParty[p] = {};
      wonByParty[p][uid] = true;
    });
    var order = ['cdu', 'spd', 'gruene', 'linke', 'afd', 'fdp', 'bsw'].filter(function (p) {
      return roster[p];
    });
    if (state.partyFocus && order.indexOf(state.partyFocus) >= 0) {
      order = [state.partyFocus];
    }
    var html = order.map(function (p) {
      var slot = roster[p];
      var seatsQ = (mc.seats || {})[p] || [0, 0, 0];
      var dCount = (mc.directs || {})[p] || 0;
      var listQ = (mc.list_seats || {})[p];
      var wonWkrs = wonByParty[p] || {};
      // Party-total Listensitze: use MC list quantiles when Landesliste;
      // else seats − Direkt (Direkt fixed across draws ⇒ quantile(s−d)=quantile(s)−d).
      var listLo;
      var listMid;
      var listHi;
      if (Array.isArray(listQ) && listQ.length >= 3) {
        listLo = listQ[0];
        listMid = listQ[1];
        listHi = listQ[2];
      } else {
        listLo = Math.max(0, seatsQ[0] - dCount);
        listMid = Math.max(0, seatsQ[1] - dCount);
        listHi = Math.max(0, seatsQ[2] - dCount);
      }
      var head = partyShort(p) + ' — Sitze ' + seatsQ[1] +
        ' <span class="wb-art">(p10 ' + seatsQ[0] + ' – p90 ' + seatsQ[2] +
        ') · Direkt ' + dCount +
        ' · Liste ' + listMid + ' (p10 ' + listLo + ' – p90 ' + listHi + ')</span>';
      var openAttr = state.partyFocus === p ? ' open' : '';
      if (seatsQ[1] === 0 && seatsQ[2] === 0) {
        return '<details class="wb-entry-party"' + openAttr + '><summary>' + head +
          ' <span class="wb-entry-status wb-out">kein Einzug</span></summary>' +
          '<p class="wb-meta">Unter 5\u00a0% und keine Direktmandate im aktuellen Nowcast.</p></details>';
      }
      var bodyHtml;
      if (!slot) {
        bodyHtml = '<p class="wb-meta">Keine Listendaten für ' + partyShort(p) + '.</p>';
      } else if (usesBezirkListe(slot, listQ)) {
        bodyHtml = bezirkListBody(slot, listQ, wonWkrs);
      } else if (Array.isArray(listQ) || (slot.landes && slot.landes.length)) {
        bodyHtml = entryListTable(slot.landes, listQ, wonWkrs);
      } else {
        bodyHtml = '<p class="wb-meta">Keine Listensitz-Quantile.</p>';
      }
      return '<details class="wb-entry-party"' + openAttr + '><summary>' + head +
        '</summary>' + bodyHtml + '</details>';
    }).join('');
    el.innerHTML = html +
      '<p class="wb-meta" style="margin:0.5rem 0 0;">' +
      escapeHtml(state.data.listen_roster_note || '') +
      ' Direktgewinner (aktueller Nowcast-Führer je WK) werden in der Liste übersprungen.' +
      (hasBezirkslisten()
        ? ''
        : ' Nur Landeslisten — keine Bezirkslisten wie in Berlin.') +
      '</p>';
  }

  function yesNo(ok) {
    return ok
      ? '<span class="wb-ok">richtig</span>'
      : '<span class="wb-bad">falsch</span>';
  }

  function hurdleHits(ln) {
    var ok = ln.hurdle_ok || {};
    var keys = Object.keys(ok);
    var n = 0;
    keys.forEach(function (p) { if (ok[p]) n++; });
    return { n: n, total: keys.length || 6 };
  }

  function scenarioIds() {
    return Object.keys((state.data && state.data.scenarios) || {});
  }

  /** Step in a scenario closest to the given statewide frac_reported. */
  function stepNearFrac(scSteps, frac) {
    if (!scSteps || !scSteps.length) return null;
    var bestI = 0;
    var bestD = 1e9;
    for (var i = 0; i < scSteps.length; i++) {
      var d = Math.abs((scSteps[i].frac_reported || 0) - frac);
      if (d < bestD) { bestD = d; bestI = i; }
    }
    return scSteps[bestI];
  }

  /**
   * Across all Melde-Szenarien at ~same Auszählungsstand: how many get
   * Hürde / Größe / Einzug / alle Direktmandate richtig?
   */
  function crossScenarioAt(frac) {
    var ids = scenarioIds();
    var out = {
      n: ids.length,
      hurdle: 0,
      size: 0,
      entry: 0,
      direkt: 0,
      details: []
    };
    ids.forEach(function (id) {
      var b = (state.data.scenarios || {})[id];
      var s = stepNearFrac((b && b.steps) || [], frac);
      if (!s || !s.eval || !s.eval.list) return;
      var ln = s.eval.list.nowcast;
      var inst = institutionsOf(s.eval);
      var hh = hurdleHits(ln);
      var hurdleOk = hh.total > 0 && hh.n === hh.total;
      var sizeOk = !!(inst && inst.parliament &&
        inst.parliament.size_pred === inst.parliament.size_truth);
      var entryOk = !!(inst && inst.entry &&
        inst.entry.n_ok === inst.entry.n_total);
      var direktOk = !!(inst && inst.direkt &&
        inst.direkt.n_hit === inst.direkt.n_total);
      if (hurdleOk) out.hurdle++;
      if (sizeOk) out.size++;
      if (entryOk) out.entry++;
      if (direktOk) out.direkt++;
      out.details.push({
        id: id,
        hurdleOk: hurdleOk,
        sizeOk: sizeOk,
        entryOk: entryOk,
        direktOk: direktOk,
        direktHit: inst && inst.direkt ? inst.direkt.n_hit : null,
        direktTot: inst && inst.direkt ? inst.direkt.n_total : null,
        sizePred: inst && inst.parliament ? inst.parliament.size_pred : null,
        sizeTruth: inst && inst.parliament ? inst.parliament.size_truth : null
      });
    });
    return out;
  }

  function fmtScen(k, n) {
    if (!n) return '—';
    var cls = k === n ? 'wb-ok' : (k === 0 ? 'wb-bad' : '');
    var html = k + '\u00a0/\u00a0' + n;
    return cls ? '<span class="' + cls + '">' + html + '</span>' : html;
  }

  function seatHits(ln) {
    var pred = ln.seats_pred || {};
    var truth = ln.seats_truth || {};
    var parties = Object.keys(truth).length ? Object.keys(truth) : Object.keys(pred);
    var exact = 0;
    var overlap = 0;
    var totalSeats = 0;
    parties.forEach(function (p) {
      var a = pred[p] || 0;
      var b = truth[p] || 0;
      if (a === b) exact++;
      overlap += Math.min(a, b);
      totalSeats += b;
    });
    return {
      exact: exact,
      nParties: parties.length,
      overlap: overlap,
      totalSeats: totalSeats || 130
    };
  }

  function institutionsOf(ev) {
    return (ev && ev.institutions && ev.institutions.nowcast) || null;
  }

  function meanBezirkMae(s, key) {
    var by = (s && s.by_bezirk) || {};
    var staticBez = ((state.data && state.data.geo_static) || {}).bezirk || {};
    var ids = Object.keys(by);
    if (!ids.length) return null;
    var predKey = key === 'mae_naive' ? 'naive' : 'nowcast';
    var sum = 0;
    var n = 0;
    ids.forEach(function (id) {
      var pred = by[id][predKey];
      var truth = (staticBez[id] && staticBez[id].truth) || null;
      if (!pred || !truth) return;
      var partySum = 0;
      BEZIRKSLISTE_PARTIES.forEach(function (p) {
        partySum += Math.abs((pred[p] || 0) - (truth[p] || 0));
      });
      sum += partySum / BEZIRKSLISTE_PARTIES.length;
      n++;
    });
    return n ? sum / n : null;
  }

  function directsFmt(d) {
    if (!d) return '—';
    return Object.keys(d).filter(function (p) { return d[p] > 0; })
      .map(function (p) { return partyShort(p) + '\u00a0' + d[p]; })
      .join(', ') || 'keine';
  }

  function scenarioProbsOf(s) {
    return (s && s.scenario_probs) || null;
  }

  var forecastPStart = {};
  var forecastPStartOfficial = false;

  function ingestScenarioPStart(src, official) {
    if (!src) return;
    var items = src.scenarios && src.scenarios.items;
    if (Array.isArray(items)) {
      items.forEach(function (it) {
        if (it && it.id != null && it.probability != null) {
          var p = Number(it.probability);
          if (isFinite(p)) forecastPStart[it.id] = p;
        }
      });
    }
    // Nowcast-computed scenario_p_start is often a washed-out MC around π₀
    // (e.g. 56 % vs published 73 % for Linke-led R2G). Only fill gaps, and
    // never overwrite values from forecast_state_*.json.
    var map = src.scenario_p_start;
    if (map && typeof map === 'object') {
      Object.keys(map).forEach(function (id) {
        var v = Number(map[id]);
        if (!isFinite(v)) return;
        if (official || forecastPStart[id] == null) forecastPStart[id] = v;
      });
    }
    if (official) forecastPStartOfficial = true;
  }

  function scenarioPStartOf(it) {
    if (it && it.id != null && forecastPStart[it.id] != null) return forecastPStart[it.id];
    if (it && it.p_start != null) return it.p_start;
    if (it && it.p_prior != null) return it.p_prior;
    return null;
  }

  function loadForecastScenarioBaseline() {
    if (!isLivePage() || !state.land) return;
    fetch(dataUrl('forecast_state_' + state.land + '.json'), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (fc) {
        if (!fc) return;
        ingestScenarioPStart(fc, true);
        renderScenarioProbs();
      })
      .catch(function () { /* keep stamped p_start */ });
  }

  /** Soft lean from P≥50% — not a hard "Call". */
  function scenarioLeanTxt(it) {
    return it.call ? 'tritt eher ein' : 'tritt eher nicht ein';
  }

  function scenarioLeanCls(it) {
    return it.call ? 'wb-lean-yes' : 'wb-lean-no';
  }

  function scenarioRowHtml(it) {
    var leanCls = scenarioLeanCls(it);
    var pStart = scenarioPStartOf(it);
    var line2 = '<span class="' + leanCls + '">' + scenarioLeanTxt(it) + '</span>';
    if (pStart != null) {
      line2 += ' · vor Auszählung ' + fmtNum(pStart, 0) + '\u00a0%';
    }
    return '<div class="wb-scen-item">' +
      '<div class="wb-scen-main">' +
        '<div class="wb-scen-label">' + escapeHtml(it.label_de) + '</div>' +
        '<div class="wb-scen-meta">' + line2 + '</div>' +
      '</div>' +
      '<div class="wb-scen-pct ' + leanCls + '">' + fmtNum(it.p, 0) + '\u00a0%</div>' +
      '</div>';
  }

  function isZeroScenario(it) {
    return Math.round(Number(it && it.p) || 0) === 0;
  }

  function renderScenarioProbs() {
    var el = $('wb-scenarios');
    if (!el) return;
    if (state.scope !== 'lage') {
      el.innerHTML = '';
      return;
    }
    var st = steps();
    if (!st.length) { el.innerHTML = ''; return; }
    var s = st[Math.min(state.step, st.length - 1)];
    var sp = scenarioProbsOf(s);
    if (!sp || !sp.items || !sp.items.length) {
      el.innerHTML = '<p class="wb-meta">Szenario-Wahrscheinlichkeiten fehlen (JSON neu generieren).</p>';
      return;
    }
    var nonzero = [];
    var zero = [];
    sp.items.forEach(function (it) {
      if (isZeroScenario(it)) zero.push(it);
      else nonzero.push(it);
    });
    var showZero = state.showZeroScenarios;
    var rows = nonzero.map(scenarioRowHtml).join('');
    if (showZero) rows += zero.map(scenarioRowHtml).join('');
    if (!nonzero.length && !showZero) {
      rows = '<p class="wb-meta">Keine Szenarien mit P&nbsp;&gt;&nbsp;0&nbsp;% am aktuellen Stand.</p>';
    }
    if (zero.length) {
      rows += '<button type="button" class="wb-scen-more" id="wb-scen-more">' +
        (showZero
          ? '0\u00a0%-Szenarien ausblenden'
          : zero.length + ' mit 0\u00a0% · mehr anzeigen') +
        '</button>';
    }
    el.innerHTML = rows;
    var more = $('wb-scen-more');
    if (more) {
      more.addEventListener('click', function () {
        state.showZeroScenarios = !state.showZeroScenarios;
        renderScenarioProbs();
      });
    }
    renderScenarioProbsEval(sp);
  }

  function renderScenarioProbsEval(sp) {
    var el = $('wb-scenarios-eval-body');
    if (!el) return;
    if (state.scope === 'wkr' || !sp || !sp.items) {
      el.innerHTML = '';
      return;
    }
    var rows = sp.items.map(function (it) {
      var leanCls = scenarioLeanCls(it);
      var verdict = it.correct
        ? '<span class="wb-ok">richtig</span>'
        : '<span class="wb-bad">falsch</span>';
      var truthTxt = it.truth ? 'tritt ein' : 'tritt nicht ein';
      var pStart = scenarioPStartOf(it);
      var line2 = '<span class="' + leanCls + '">' + scenarioLeanTxt(it) + '</span>' +
        ' · Wahr: ' + truthTxt;
      if (pStart != null) {
        line2 += ' · vor ' + fmtNum(pStart, 0) + '\u00a0%';
      }
      return '<div class="wb-scen-item">' +
        '<div class="wb-scen-main">' +
          '<div class="wb-scen-label">' + escapeHtml(it.label_de) + '</div>' +
          '<div class="wb-scen-meta">' + line2 + '</div>' +
        '</div>' +
        '<div class="wb-scen-pct ' + leanCls + '">' + fmtNum(it.p, 0) + '\u00a0%</div>' +
        '<div class="wb-scen-verdict">' + verdict + '</div>' +
        '</div>';
    }).join('');
    el.innerHTML =
      '<p class="wb-scen-score">Richtung richtig: <strong>' +
        sp.n_ok + '\u00a0/\u00a0' + sp.n_total +
        '</strong> <span class="wb-art">(P\u00a0≥\u00a050\u00a0%\u00a0=\u00a0eher ein)</span></p>' +
      rows;
  }

  function renderHitsStrip() {
    var el = $('wb-hits');
    if (!el) return;
    if (state.scope !== 'zweit') {
      el.innerHTML = '';
      return;
    }
    var st = steps();
    if (!st.length) { el.innerHTML = ''; return; }
    var s = st[Math.min(state.step, st.length - 1)];
    var ev = s.eval;
    if (!ev || !ev.list) { el.innerHTML = ''; return; }
    var ln = ev.list.nowcast;
    var inst = institutionsOf(ev);
    var parl = inst && inst.parliament;
    var dir = inst && inst.direkt;
    var ent = inst && inst.entry;
    var bzMae = meanBezirkMae(s, 'mae_nowcast');
    var hh = hurdleHits(ln);
    var sp = scenarioProbsOf(s);
    var sizeHtml = parl
      ? (parl.size_pred + ' <span class="wb-art">(Wahr ' + parl.size_truth +
          (parl.size_err ? ', Δ' + (parl.size_err > 0 ? '+' : '') + parl.size_err : '') +
          ')</span>')
      : '—';
    el.innerHTML =
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">Szenarien</span>' +
        '<div class="wb-hit-v">' +
          (sp ? (sp.n_ok + '\u00a0/\u00a0' + sp.n_total) : '—') + '</div>' +
        '<div class="wb-hit-s">eher ein/nicht vs. Wahrheit</div>' +
      '</div>' +
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">5-%-Hürde richtig</span>' +
        '<div class="wb-hit-v">' + hh.n + '\u00a0/\u00a0' + hh.total + '</div>' +
        '<div class="wb-hit-s">Parteien ≥5\u00a0% ja/nein</div>' +
      '</div>' +
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">Parlamentsgröße</span>' +
        '<div class="wb-hit-v">' + sizeHtml + '</div>' +
        '<div class="wb-hit-s">BE-Formel aus Nowcast</div>' +
      '</div>' +
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">Direktmandate</span>' +
        '<div class="wb-hit-v">' +
          (dir ? (dir.n_hit + '\u00a0/\u00a0' + dir.n_total) : '—') + '</div>' +
        '<div class="wb-hit-s">Erststimmen-Nowcast</div>' +
      '</div>' +
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">Einzug richtig</span>' +
        '<div class="wb-hit-v">' +
          (ent ? (ent.n_ok + '\u00a0/\u00a0' + ent.n_total) : '—') + '</div>' +
        '<div class="wb-hit-s">5\u00a0% oder Grundmandat</div>' +
      '</div>' +
      (hasBezirkslisten()
        ? ('<div class="wb-hit-card">' +
          '<span class="wb-hit-k">Bezirkslisten (' + BEZIRKSLISTE_LABEL + ')</span>' +
          '<div class="wb-hit-v">' +
            (bzMae != null ? fmtNum(bzMae, 2) + '\u00a0PP' : '—') + '</div>' +
          '<div class="wb-hit-s">mittlerer Anteilsfehler · 12 Bezirke</div>' +
        '</div>')
        : '');
  }

  function renderHitsTimeline() {
    var body = $('wb-hits-timeline-body');
    if (!body) return;
    if (state.scope === 'wkr') {
      body.innerHTML = '';
      return;
    }
    var st = steps();
    if (!st.length) { body.innerHTML = ''; return; }
    var rows = st.map(function (s, i) {
      var ev = s.eval;
      if (!ev || !ev.list) return '';
      var ln = ev.list.nowcast;
      var lv = ev.list.naive;
      var hh = hurdleHits(ln);
      var hhn = hurdleHits(lv);
      var inst = institutionsOf(ev);
      var parl = inst && inst.parliament;
      var dir = inst && inst.direkt;
      var ent = inst && inst.entry;
      var sp = scenarioProbsOf(s);
      var sizeCell = parl
        ? (parl.size_pred +
          (parl.size_pred === parl.size_truth
            ? ' <span class="wb-ok">=</span>'
            : ' <span class="wb-bad">≠' + parl.size_truth + '</span>'))
        : '—';
      var dirCell = dir ? (dir.n_hit + '/' + dir.n_total) : '—';
      var entCell = ent ? (ent.n_ok + '/' + ent.n_total) : '—';
      var scenCell = sp
        ? ('<span class="' + (sp.n_ok === sp.n_total ? 'wb-ok' : '') + '">' +
            sp.n_ok + '/' + sp.n_total + '</span>')
        : '—';
      var bzMae = meanBezirkMae(s, 'mae_nowcast');
      var bzMaeN = meanBezirkMae(s, 'mae_naive');
      var active = i === state.step ? ' class="wb-row-active"' : '';
      return '<tr' + active + ' data-step="' + i + '" style="cursor:pointer;">' +
        '<td>' + stepWhen(s) + '</td>' +
        '<td>' + scenCell + '</td>' +
        '<td>' + hh.n + '/' + hh.total +
          ' <span class="wb-art">naiv ' + hhn.n + '/' + hhn.total + '</span></td>' +
        '<td>' + sizeCell + '</td>' +
        '<td>' + dirCell + '</td>' +
        '<td>' + entCell + '</td>' +
        (hasBezirkslisten()
          ? ('<td>' + (bzMae != null ? fmtNum(bzMae, 2) : '—') +
            ' <span class="wb-art">naiv ' +
            (bzMaeN != null ? fmtNum(bzMaeN, 2) : '—') + '</span></td>')
          : '') +
        '</tr>';
    }).join('');
    body.innerHTML =
      '<table class="wb-cov-table"><thead><tr>' +
      '<th>Zeit / Auszählung</th>' +
      '<th>Szenarien</th>' +
      '<th>Hürde</th>' +
      '<th>Größe</th>' +
      '<th>Direkt</th>' +
      '<th>Einzug</th>' +
      (hasBezirkslisten() ? '<th>Bezirk-MAE*</th>' : '') +
      '</tr></thead><tbody>' + rows + '</tbody></table>' +
      (hasBezirkslisten()
        ? ('<p class="wb-coverage-meta">* Nur ' + BEZIRKSLISTE_LABEL +
          ' (Bezirkslisten). Szenarien = politische Ereignisse ' +
          '(Mehrheit / stärkste Kraft / Hürde): P\u00a0≥\u00a050\u00a0%\u00a0=\u00a0eher ein ' +
          'vs. Wahrheit.</p>')
        : ('<p class="wb-coverage-meta">Szenarien = politische Ereignisse ' +
          '(Mehrheit / stärkste Kraft / Hürde): P\u00a0≥\u00a050\u00a0%\u00a0=\u00a0eher ein ' +
          'vs. Wahrheit.</p>'));
    body.querySelectorAll('tr[data-step]').forEach(function (tr) {
      tr.addEventListener('click', function () {
        if (isLivePage()) return; // live: always the latest poll
        var i = Number(tr.getAttribute('data-step'));
        state.step = i;
        var slider = $('wb-slider');
        if (slider) slider.value = String(i);
        renderStep();
      });
    });
  }

  function syncScopePanels() {
    var isWkr = state.scope === 'wkr';
    var isLand = state.scope === 'land';
    var isZweit = state.scope === 'zweit';
    var isLage = state.scope === 'lage';
    document.querySelectorAll('[data-hide-wkr]').forEach(function (el) {
      el.hidden = isWkr;
    });
    document.querySelectorAll('[data-zweit-only]').forEach(function (el) {
      el.hidden = !isZweit;
    });
    document.querySelectorAll('[data-zweit-or-wkr]').forEach(function (el) {
      el.hidden = !(isZweit || (isWkr && state.unit));
    });
    document.querySelectorAll('[data-lage-only]').forEach(function (el) {
      el.hidden = !isLage;
    });
    document.querySelectorAll('[data-land-only]').forEach(function (el) {
      el.hidden = !isLand;
    });
    document.querySelectorAll('[data-bezirk-only]').forEach(function (el) {
      el.hidden = true;
    });
    document.querySelectorAll('[data-wkr-only]').forEach(function (el) {
      el.hidden = !isWkr;
    });
  }

  function renderEval() {
    var el = $('wb-eval');
    if (!el) return;
    if (state.scope !== 'zweit') {
      el.innerHTML = '';
      return;
    }
    var st = steps();
    if (!st.length) return;
    var s = st[Math.min(state.step, st.length - 1)];
    var ev = s.eval;
    if (!ev || !ev.list) {
      el.innerHTML = '';
      return;
    }
    var ln = ev.list.nowcast;
    var lv = ev.list.naive;
    var inst = institutionsOf(ev);
    var parl = inst && inst.parliament;
    var dir = inst && inst.direkt;
    var ent = inst && inst.entry;
    var sh = parl
      ? seatHits({ seats_pred: parl.seats_pred, seats_truth: parl.seats_truth })
      : seatHits(ln);
    var bzMae = meanBezirkMae(s, 'mae_nowcast');
    var bzMaeN = meanBezirkMae(s, 'mae_naive');
    var hh = hurdleHits(ln);
    var scenProbs = scenarioProbsOf(s);

    var unitNote = '';
    if (state.scope === 'bezirk' && s.by_bezirk && s.by_bezirk[state.unit]) {
      var ub = s.by_bezirk[state.unit];
      unitNote = '<p class="wb-meta" style="margin:0.5rem 0 0;">Dieser Bezirk: Anteilsfehler Nowcast <strong>' +
        fmtNum(ub.mae_nowcast, 2) + '\u00a0PP</strong> (alle Parteien). ' +
        'Für Listenplätze zählen die Bezirksanteile nur bei <strong>' +
        BEZIRKSLISTE_LABEL + '</strong>; Grüne/AfD/FDP haben eine Landesliste.</p>';
    } else if (state.scope === 'wkr' && s.by_wkr && s.by_wkr[state.unit]) {
      var uw = s.by_wkr[state.unit];
      unitNote = '<p class="wb-meta" style="margin:0.5rem 0 0;">Dieser Wahlkreis: stärkste Partei Nowcast <strong>' +
        partyShort(uw.leader_pred) + '</strong> gegenüber Wahr <strong>' +
        partyShort(uw.leader_truth) + '</strong> — ' + yesNo(uw.leader_ok) + '</p>';
    }

    var seatSrc = parl || ln;
    var hurdleRows = Object.keys(ln.hurdle_ok || {}).map(function (p) {
      var ok = ln.hurdle_ok[p];
      var pred = ln.above5_pred[p] ? '≥5%' : '<5%';
      var truth = ln.above5_truth[p] ? '≥5%' : '<5%';
      var sp = (seatSrc.seats_pred && seatSrc.seats_pred[p] != null) ? seatSrc.seats_pred[p] : '—';
      var stSeats = (seatSrc.seats_truth && seatSrc.seats_truth[p] != null) ? seatSrc.seats_truth[p] : '—';
      var seatOk = sp === stSeats;
      var dPred = dir && dir.directs_pred ? (dir.directs_pred[p] || 0) : '—';
      var dTruth = dir && dir.directs_truth ? (dir.directs_truth[p] || 0) : '—';
      var ePred = ent && ent.pred ? (ent.pred[p] ? 'ja' : 'nein') : '—';
      var eTruth = ent && ent.truth ? (ent.truth[p] ? 'ja' : 'nein') : '—';
      var eOk = ent && ent.pred && ent.truth ? yesNo(ent.pred[p] === ent.truth[p]) : '—';
      return '<tr><td>' + partyShort(p) + '</td><td>' + pred + '</td><td>' + truth +
        '</td><td>' + yesNo(ok) + '</td><td>' + dPred + '</td><td>' + dTruth +
        '</td><td>' + ePred + '/' + eTruth + ' ' + eOk +
        '</td><td>' + sp + '</td><td>' + stSeats +
        '</td><td>' + yesNo(seatOk) + '</td></tr>';
    }).join('');

    var instBlock = '';
    if (inst) {
      instBlock =
        '<h3 style="margin-top:1rem;">Direkt · Einzug · Parlamentsgröße</h3>' +
        '<div class="wb-eval-grid">' +
          '<div><dl>' +
            '<dt>Direktmandate</dt><dd><strong>' +
              dir.n_hit + '/' + dir.n_total + '</strong> WK richtig' +
              '<div class="wb-art">Erststimmen-Nowcast vs. Erst-Sieger</div>' +
              '<div>Nowcast: ' + directsFmt(dir.directs_pred) +
              ' · Wahr: ' + directsFmt(dir.directs_truth) + '</div></dd>' +
            '<dt>Einzug</dt><dd><strong>' + ent.n_ok + '/' + ent.n_total +
              '</strong> Parteien · ' + (ent.note || '') + '</dd>' +
          '</dl></div>' +
          '<div><dl>' +
            '<dt>Parlamentsgröße</dt><dd><strong>' + parl.size_pred +
              '</strong> Sitze (Wahr ' + parl.size_truth +
              ', Δ' + (parl.size_err > 0 ? '+' : '') + parl.size_err + ')</dd>' +
            '<dt>Sitze exakt</dt><dd><strong>' + sh.exact + '/' + sh.nParties +
              '</strong> Parteien · MAE ' + fmtNum(parl.seat_mae, 1) + '</dd>' +
            '<dt>Überhang (gesamt)</dt><dd>Nowcast ' + parl.total_oh_pred +
              ' · Wahr ' + parl.total_oh_truth + '</dd>' +
          '</dl></div>' +
        '</div>';
    }

    el.innerHTML =
      '<div class="wb-eval-grid">' +
        '<div><dl>' +
          '<dt>5-%-Hürde</dt><dd><strong>' + hh.n + '/' + hh.total + '</strong> richtig' +
            ' <span class="wb-art">naiv ' + hurdleHits(lv).n + '/' + hurdleHits(lv).total + '</span></dd>' +
          '<dt>Szenarien</dt><dd><strong>' +
            (scenProbs ? (scenProbs.n_ok + '/' + scenProbs.n_total) : '—') +
            '</strong> Richtung richtig' +
            '<div class="wb-art">P\u00a0≥\u00a050\u00a0%\u00a0=\u00a0eher ein vs. Wahrheit</div></dd>' +
        '</dl></div>' +
        '<div><dl>' +
          '<dt>Direktmandate</dt><dd><strong>' +
            (dir ? (dir.n_hit + '/' + dir.n_total) : '—') +
            '</strong> richtig' +
            ' <span class="wb-art">Erststimmen-Nowcast</span></dd>' +
          (hasBezirkslisten()
            ? ('<dt>Bezirkslisten (' + BEZIRKSLISTE_LABEL + ')</dt><dd>mittlerer Fehler <strong>' +
              (bzMae != null ? fmtNum(bzMae, 2) + '\u00a0PP' : '—') + '</strong>' +
              ' <span class="wb-art">naiv ' +
              (bzMaeN != null ? fmtNum(bzMaeN, 2) + '\u00a0PP' : '—') +
              '</span><div class="wb-art">Nur Parteien mit Bezirkslisten; ' +
              'Grüne/AfD/FDP: Landesliste</div></dd>')
            : '') +
        '</dl></div>' +
      '</div>' +
      instBlock +
      '<table class="wb-cov-table" style="margin-top:0.65rem;"><thead><tr>' +
        '<th>Partei</th><th>NC-Hürde</th><th>Wahr</th><th>Hürde</th>' +
        '<th>Dir NC</th><th>Dir Wahr</th><th>Einzug</th>' +
        '<th>Sitze NC</th><th>Sitze Wahr</th><th>Sitze</th></tr></thead><tbody>' +
        hurdleRows + '</tbody></table>' +
      '<p class="wb-meta" style="margin:0.5rem 0 0;">' + (ev.note || '') +
      (state.scenario === 'random'
        ? ' Bei diesem Meldefluss kann Naiv nah am Nowcast liegen — erwartbar, weil kaum Selektionsbias bleibt.'
        : '') +
      '</p>' +
      unitNote;
  }

  function statusPill(nRep, nTot, scopeLabel) {
    if (!nTot) return '<span class="wb-pill wb-pill-none">—</span>';
    if (nRep <= 0) return '<span class="wb-pill wb-pill-none">offen</span>';
    if (nRep >= nTot) {
      var done = scopeLabel ? (scopeLabel + ' ausgezählt') : 'ausgezählt';
      return '<span class="wb-pill wb-pill-done">' + done + '</span>';
    }
    return '<span class="wb-pill wb-pill-part">teilweise</span>';
  }

  function progressBar(nRep, nTot) {
    var pct = nTot ? Math.round(100 * nRep / nTot) : 0;
    return '<span class="wb-bar" title="' + pct + '%"><i style="width:' + pct + '%"></i></span>';
  }

  function reportedSet(s) {
    var set = {};
    if (isLivePage()) {
      var by = (s && s.by_wkr) || {};
      Object.keys(by).forEach(function (wid) {
        var r = by[wid] || {};
        if ((r.frac_reported || 0) > 0 || (r.n_reported || 0) > 0) set[wid] = true;
      });
      ((state.data && state.data.precincts) || []).forEach(function (p) {
        if ((p.gueltig || 0) > 0 || (p.gueltig_erst || 0) > 0) set[p.id] = true;
      });
      return set;
    }
    var b = scenarioBundle();
    var order = (b && b.reporting_order) || (state.data && state.data.reporting_order) || [];
    var n = s.n_reported || 0;
    for (var i = 0; i < n && i < order.length; i++) set[order[i]] = true;
    return set;
  }

  function isAggregatePrecinct(p) {
    return !p || p.art === 'S' || (p.wkr != null && String(p.id) === String(p.wkr));
  }

  function realPrecincts(list) {
    var raw = list || [];
    var real = raw.filter(function (p) { return !isAggregatePrecinct(p); });
    return real.length ? real : [];
  }

  function wkrWbCounts(wid) {
    var st = steps();
    var s = st.length ? st[Math.min(state.step, st.length - 1)] : null;
    var r = ((s && s.by_wkr) || {})[wid] || {};
    return {
      n: Number(r.n_total) || 0,
      rep: Number(r.n_reported) || 0
    };
  }

  function precinctArtLabel(p) {
    if (!p) return '';
    if (p.art === 'B') return 'Brief';
    if (isAggregatePrecinct(p)) return 'WK-Summe';
    return 'Urne';
  }

  function precinctsFiltered() {
    var list = (state.data && state.data.precincts) || [];
    if (state.scope === 'bezirk') {
      return list.filter(function (p) { return p.bezirk === state.unit; });
    }
    if (state.scope === 'wkr') {
      return list.filter(function (p) { return p.wkr === state.unit; });
    }
    return list;
  }

  function groupTree(list) {
    var byBez = {};
    list.forEach(function (p) {
      if (!byBez[p.bezirk]) byBez[p.bezirk] = { wkr: {} };
      if (!byBez[p.bezirk].wkr[p.wkr]) byBez[p.bezirk].wkr[p.wkr] = [];
      byBez[p.bezirk].wkr[p.wkr].push(p);
    });
    return byBez;
  }

  function countReported(plist, reported) {
    var n = 0;
    for (var i = 0; i < plist.length; i++) if (reported[plist[i].id]) n++;
    return n;
  }

  function precinctMap() {
    if (!state._precinctMap) {
      state._precinctMap = {};
      (state.data && state.data.precincts || []).forEach(function (p) {
        state._precinctMap[p.id] = p;
      });
    }
    return state._precinctMap;
  }

  function hasPrecinctCounts() {
    var list = (state.data && state.data.precincts) || [];
    return list.length > 0 && list[0].counts != null;
  }

  /** ballot: 'zweit' | 'erst' — sums only reported precincts in plist. */
  function aggregateActual(plist, reported, ballot) {
    ballot = ballot || 'zweit';
    var counts = {};
    PARTIES_ORDER.forEach(function (p) { counts[p] = 0; });
    var gueltig = 0;
    var gueltigTotal = 0;
    var waehler = 0;
    var wber = 0;
    plist.forEach(function (meta) {
      var p = precinctMap()[meta.id] || meta;
      var gTot = ballot === 'erst' && p.gueltig_erst != null ? p.gueltig_erst : (p.gueltig || 0);
      gueltigTotal += gTot;
      wber += p.wber || 0;
      if (!reported[meta.id]) return;
      waehler += p.waehler || 0;
      gueltig += gTot;
      var csrc = ballot === 'erst' && p.counts_erst ? p.counts_erst : (p.counts || {});
      PARTIES_ORDER.forEach(function (party) {
        counts[party] += csrc[party] || 0;
      });
    });
    return {
      gueltig: gueltig,
      gueltig_total: gueltigTotal,
      waehler: waehler,
      wber: wber,
      turnout: wber > 0 ? (100 * waehler / wber) : null,
      counts: counts,
      n_reported: countReported(plist, reported),
      n_total: plist.length
    };
  }

  function leaderFromCounts(counts, gueltig) {
    var best = null;
    var bestV = -1;
    PARTIES_ORDER.filter(function (p) { return p !== 'others'; }).forEach(function (p) {
      var v = counts[p] || 0;
      if (v > bestV) { bestV = v; best = p; }
    });
    if (best == null || bestV <= 0) return null;
    var pct = gueltig > 0 ? (100 * bestV / gueltig) : null;
    return { party: best, votes: bestV, pct: pct };
  }

  function actualSummaryCards(act, label) {
    var unit = isLivePage() ? 'WK' : 'WB';
    var wbTxt = act.n_reported + '/' + act.n_total + ' ' + unit;
    var gueltigTxt = fmtInt(act.gueltig);
    if (act.gueltig_total > act.gueltig) {
      gueltigTxt += ' <span class="wb-art">von ' + fmtInt(act.gueltig_total) + '</span>';
    }
    return '<div class="wb-hits" style="margin:0.5rem 0 0.75rem;">' +
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">' + escapeHtml(label) + ' · WB</span>' +
        '<div class="wb-hit-v">' + wbTxt + '</div>' +
        '<div class="wb-hit-s">gemeldet</div>' +
      '</div>' +
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">Gültige Stimmen</span>' +
        '<div class="wb-hit-v">' + gueltigTxt + '</div>' +
        '<div class="wb-hit-s">nur gemeldete Bezirke</div>' +
      '</div>' +
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">Wählerinnen/Wähler</span>' +
        '<div class="wb-hit-v">' + fmtInt(act.waehler) + '</div>' +
        '<div class="wb-hit-s">von ' + fmtInt(act.wber) + ' Wahlberechtigten</div>' +
      '</div>' +
      '<div class="wb-hit-card">' +
        '<span class="wb-hit-k">Wahlbeteiligung</span>' +
        '<div class="wb-hit-v">' +
          (act.turnout != null ? fmtNum(act.turnout, 1) + '\u00a0%' : '—') +
        '</div>' +
        '<div class="wb-hit-s">gemeldete WB / alle WB im Gebiet</div>' +
      '</div>' +
    '</div>';
  }

  function actualPartyTable(act, ballotLabel) {
    if (!act.gueltig) {
      return '<p class="wb-meta">Noch keine Stimmen gemeldet.</p>';
    }
    var parties = PARTIES_ORDER.filter(function (p) { return p !== 'others'; })
      .map(function (p) {
        return { p: p, v: act.counts[p] || 0 };
      })
      .filter(function (x) { return x.v > 0; })
      .sort(function (a, b) { return b.v - a.v; });
    if (!parties.length) return '<p class="wb-meta">Keine Parteistimmen.</p>';
    var rows = parties.map(function (x) {
      var pct = act.gueltig > 0 ? (100 * x.v / act.gueltig) : 0;
      return '<tr><td>' + partyShort(x.p) + '</td>' +
        '<td style="text-align:right;">' + fmtInt(x.v) + '</td>' +
        '<td style="text-align:right;">' + fmtNum(pct, 1) + '\u00a0%</td></tr>';
    }).join('');
    return '<p class="wb-chart-label" style="margin-top:0.75rem;">' +
      escapeHtml(ballotLabel) + ' — absolute Stimmen (gemeldet)</p>' +
      '<div style="overflow-x:auto;"><table class="wb-cov-table">' +
      '<thead><tr><th>Partei</th><th style="text-align:right;">Stimmen</th>' +
      '<th style="text-align:right;">Anteil</th></tr></thead><tbody>' +
      rows + '</tbody></table></div>';
  }

  function renderActual() {
    var el = $('wb-actual');
    if (!el || !state.data) return;
    var st = steps();
    if (!st.length) { el.innerHTML = ''; return; }
    var s = st[Math.min(state.step, st.length - 1)];
    var reported = reportedSet(s);
    if (!hasPrecinctCounts()) {
      el.innerHTML = isLivePage()
        ? '<p class="wb-meta">Noch keine Wahlkreis-Rohstimmen in dieser Datei. ' +
          'Sobald StaLA Wahlkreise zählt, erscheinen hier die absoluten Stimmen — ohne Nowcast.</p>'
        : ('<p class="wb-meta">Absolute Stimmen fehlen im JSON — Replay neu generieren ' +
          '(<code>python3 code/wahlabend_nowcast.py</code> bzw. LTW-Skript).</p>');
      return;
    }
    var meta = $('wb-actual-meta');
    if (meta && isLivePage()) {
      var liveNote = ((state.data && state.data.live) || {}).wb_level_note;
      if (liveNote) {
        meta.textContent = 'Absolute Stimmen nur aus gemeldeten Wahlkreisen — ohne Nowcast. ' + liveNote;
      } else if (state.land === 'mv') {
        meta.textContent =
          'Absolute Stimmen und Wahlbeteiligung nur aus bereits gemeldeten Wahlbezirken — ohne Nowcast.';
      } else {
        meta.textContent =
          'Absolute Stimmen und Wahlbeteiligung nur aus bereits gemeldeten Wahlkreisen — ohne Nowcast. Keine Wahlbezirk-CSV bisher.';
      }
    }

    var all = state.data.precincts || [];
    var landAct = aggregateActual(all, reported, 'zweit');
    var html = actualSummaryCards(landAct, 'Land');

    if (state.scope === 'wkr' && state.unit) {
      var wkrList = all.filter(function (p) { return String(p.wkr) === String(state.unit); });
      var ballot = state.land === 'be' ? 'erst' : 'zweit';
      var wkrAct = aggregateActual(wkrList, reported, ballot);
      var wkrLabel = unitLabel('wkr', state.unit);
      html += actualSummaryCards(wkrAct, wkrLabel);
      html += actualPartyTable(
        wkrAct,
        state.land === 'be' ? 'Erststimmen' : 'Zweitstimmen (WK-Proxy)'
      );
    } else if (state.scope === 'bezirk' && state.unit) {
      var bezList = all.filter(function (p) { return p.bezirk === state.unit; });
      var bezAct = aggregateActual(bezList, reported, 'zweit');
      html += actualSummaryCards(bezAct, unitLabel('bezirk', state.unit));
      html += actualPartyTable(bezAct, 'Zweitstimmen');
    } else {
      html += actualPartyTable(landAct, 'Zweitstimmen (Land)');
    }

    var units = ((state.data.geo_units || {}).wkr) || [];
    if (units.length) {
      var ballotWk = state.land === 'be' ? 'erst' : 'zweit';
      var wkrRows = units.map(function (u) {
        var pl = all.filter(function (p) { return String(p.wkr) === String(u.id); });
        var act = aggregateActual(pl, reported, ballotWk);
        var lead = leaderFromCounts(act.counts, act.gueltig);
        var leadTxt = lead
          ? (partyShort(lead.party) + ' ' + fmtInt(lead.votes) +
            (lead.pct != null ? ' (' + fmtNum(lead.pct, 1) + '\u00a0%)' : ''))
          : '—';
        var active = state.unit && String(state.unit) === String(u.id)
          ? ' class="wb-row-active"' : '';
        var nm = shortWkrLabel(u.label, u.id);
        var wkCell = escapeHtml(nm.num) +
          (nm.rest ? ' ' + escapeHtml(nm.rest) : '');
        return '<tr' + active + ' data-wkr-link="' + u.id + '" style="cursor:pointer;">' +
          '<td>' + wkCell + '</td>' +
          '<td>' + act.n_reported + '/' + act.n_total + '</td>' +
          '<td style="text-align:right;">' + fmtInt(act.gueltig) + '</td>' +
          '<td style="text-align:right;">' +
            (act.turnout != null ? fmtNum(act.turnout, 1) + '\u00a0%' : '—') + '</td>' +
          '<td>' + leadTxt + '</td></tr>';
      }).join('');
      html +=
        '<p class="wb-chart-label" style="margin-top:1rem;">Wahlkreise — Rohstand</p>' +
        '<div style="overflow-x:auto;"><table class="wb-cov-table" id="wb-actual-wkr-table">' +
        '<thead><tr><th>WK</th><th>WB</th><th style="text-align:right;">Gültige Stimmen</th>' +
        '<th style="text-align:right;">Wahlbeteiligung</th><th>Führend (gemeldet)</th>' +
        '</tr></thead><tbody>' + wkrRows + '</tbody></table></div>' +
        '<p class="wb-meta" style="margin:0.35rem 0 0;">Zeile antippen öffnet den Wahlkreis.</p>';
    }

    el.innerHTML = html;
    bindWkrLinks(el);
  }

  function renderCoverage() {
    var body = $('wb-coverage-body');
    var meta = $('wb-coverage-meta');
    if (!body || !state.data) return;
    var st = steps();
    if (!st.length) return;
    var s = st[Math.min(state.step, st.length - 1)];
    var reported = reportedSet(s);
    var list = precinctsFiltered();
    var tree = groupTree(list);
    var nWkr = (state.data && state.data.n_wkr) || 0;
    var landWb = (s.n_total && nWkr && s.n_total > nWkr)
      ? (s.n_reported + '/' + s.n_total + ' Wahlbezirke')
      : (s.n_reported + '/' + s.n_total);
    var realList = realPrecincts(list);
    var usingWkStubs = isLivePage() && realList.length === 0 && nWkr > 0;
    var noWbNote = ((state.data && state.data.live) || {}).wb_level_note;
    meta.textContent = usingWkStubs
      ? (noWbNote
        ? (noWbNote + ' Auszählungsstand (Land): ' + landWb + '.')
        : ('Noch keine einzelnen Wahlbezirke gemeldet (Land: ' + landWb +
          '). AfS/LAIV liefern erst WK-Summen; Urne/Brief kommen mit der Wahlbezirk-Datei.'))
      : (countReported(realList, reported) + ' von ' + realList.length +
        ' Wahlbezirken im gewählten Gebiet gemeldet (Land: ' + landWb + '). ' +
        (isLivePage()
          ? 'Karten-Einheiten = Wahlkreise; Zähler = Wahlbezirke.'
          : 'Urne = W, Brief = B. Wahlkreise und Wahlbezirke erst nach Aufklappen.'));

    if (!list.length) {
      body.innerHTML = '<p class="wb-meta">Keine Wahlbezirksdaten geladen.</p>';
      return;
    }

    if (state.scope === 'wkr') {
      body.innerHTML = precinctTable(realPrecincts(list), reported, state.unit);
      return;
    }

    var bezirkIds = Object.keys(tree).sort();
    var html = '<div class="wb-cov-list">';
    bezirkIds.forEach(function (bid) {
      var wkrs = tree[bid].wkr;
      var open = state.openBezirk[bid] ? ' open' : '';
      var wkrIds = Object.keys(wkrs).sort(function (a, b) {
        return Number(a) - Number(b);
      });
      var bezRep = 0, bezTot = 0;
      wkrIds.forEach(function (wid) {
        var wb = wkrWbCounts(wid);
        var pl = realPrecincts(wkrs[wid]);
        if (wb.n) {
          bezRep += wb.rep;
          bezTot += wb.n;
        } else {
          bezRep += countReported(pl, reported);
          bezTot += pl.length || wkrs[wid].length;
        }
      });
      html +=
        '<details class="wb-cov-nest" data-bez="' + bid + '"' + open + '>' +
        '<summary><strong>' + escapeHtml(unitLabel('bezirk', bid)) + '</strong> ' +
        statusPill(bezRep, bezTot, 'Bezirk') + ' ' + progressBar(bezRep, bezTot) +
        ' <span class="wb-art">' + bezRep + '/' + bezTot + '</span></summary>' +
        '<div class="wb-cov-wkr" data-bez-body="' + bid + '">';
      wkrIds.forEach(function (wid) {
        var pl = realPrecincts(wkrs[wid]);
        var wb = wkrWbCounts(wid);
        var wTot = wb.n || pl.length;
        var wr = wb.n ? wb.rep : countReported(pl, reported);
        var wopen = state.openWkr[wid] ? ' open' : '';
        var call = wkrCalls()[wid] || {};
        var doneHint = '';
        if (wTot && wr >= wTot && completeWhen(call)) {
          doneHint = ' <span class="wb-art">seit ' + completeWhen(call) + '</span>';
        }
        html +=
          '<details class="wb-cov-nest" data-wkr="' + wid + '" data-bez-parent="' + bid + '"' +
          wopen + '>' +
          '<summary>' + escapeHtml(unitLabel('wkr', wid)) + ' ' +
          statusPill(wr, wTot, 'WK') + ' ' + progressBar(wr, wTot) +
          ' <span class="wb-art">' + wr + '/' + wTot + '</span>' + doneHint +
          '</summary>' +
          '<div class="wb-cov-wb" data-wkr-body="' + wid + '"></div>' +
          '</details>';
      });
      html += '</div></details>';
    });
    html += '</div>';
    body.innerHTML = html;

    // Restore previously open WK precinct tables lazily
    body.querySelectorAll('details[data-wkr]').forEach(function (el) {
      if (el.open) fillWkrPrecincts(el, reported, tree);
      el.addEventListener('toggle', function () {
        var wid = el.getAttribute('data-wkr');
        state.openWkr[wid] = el.open;
        if (el.open) fillWkrPrecincts(el, reported, tree);
      });
    });
    body.querySelectorAll('details[data-bez]').forEach(function (el) {
      el.addEventListener('toggle', function () {
        state.openBezirk[el.getAttribute('data-bez')] = el.open;
      });
    });
  }

  function fillWkrPrecincts(el, reported, tree) {
    var wid = el.getAttribute('data-wkr');
    var bid = el.getAttribute('data-bez-parent');
    var slot = el.querySelector('[data-wkr-body="' + wid + '"]');
    if (!slot || slot.getAttribute('data-filled') === '1') return;
    var pl = (((tree[bid] || {}).wkr) || {})[wid] || [];
    if (!pl.length) {
      pl = ((state.data && state.data.precincts) || []).filter(function (p) {
        return p.wkr === wid && (!bid || p.bezirk === bid);
      });
    }
    slot.innerHTML = precinctTable(realPrecincts(pl), reported, wid);
    slot.setAttribute('data-filled', '1');
  }

  function precinctTable(plist, reported, wid) {
    var real = realPrecincts(plist || []);
    if (!real.length) {
      var wb = wkrWbCounts(wid);
      var soll = wb.n ? String(wb.n) : '—';
      return '<p class="wb-meta">Noch keine einzelnen Wahlbezirke (Urne/Brief) in diesem Kreis. ' +
        'Bisher nur die Wahlkreis-Summe. Vorgesehen: <strong>' + soll +
        '</strong> Wahlbezirke.</p>';
    }
    var rows = real.slice().sort(function (a, b) {
      if (a.art !== b.art) return a.art < b.art ? 1 : -1;
      return a.id < b.id ? -1 : 1;
    }).map(function (p) {
      var done = !!reported[p.id];
      return '<tr>' +
        '<td>' + escapeHtml(p.id) +
        ' <span class="wb-art">' + precinctArtLabel(p) + '</span></td>' +
        '<td>' + statusPill(done ? 1 : 0, 1) + '</td></tr>';
    }).join('');
    return '<table class="wb-cov-table"><thead><tr>' +
      '<th>Wahlbezirk</th><th>Status</th></tr></thead><tbody>' +
      rows + '</tbody></table>';
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderStep() {
    var st = steps();
    if (!st.length) return;
    var i = Math.min(state.step, st.length - 1);
    var s = st[i];
    var v = viewForStep(s);
    if (!v) return;

    syncScopePanels();
    renderScopeButtons();
    renderSubnav();

    var note = $('wb-scenario-note');
    if (note) {
      var office = ({ be: 'AfS', st: 'StaLA', mv: 'LAIV' }[state.land] || 'Amt');
      if (isLivePage() || /2026/.test(String((state.data && state.data.election) || ''))) {
        var liveMeta = (state.data && state.data.live) || {};
        var kindBit = liveMeta.result_kind_label
          ? (office + ': ' + liveMeta.result_kind_label)
          : ('Meldefluss: ' + office + ' Live-CSV');
        if (liveMeta.wb_level_note) {
          kindBit += ' · keine einzelnen Wahlbezirke';
        }
        note.textContent = kindBit;
      } else if (state.land === 'be') {
        note.textContent = 'Meldefluss: AfS-Zeiten';
      } else if (state.land === 'st') {
        note.textContent = 'Meldefluss: simuliert (StaLA Live-CSV ab Wahlabend 2026)';
      } else {
        note.textContent = 'Meldefluss: simuliert (LAIV Live-CSV ab ~19 Uhr 2026)';
      }
    }

    var landLabel = (state.data && state.data.state_label)
      || ({ be: 'Berlin', st: 'Sachsen-Anhalt', mv: 'Mecklenburg-Vorpommern' }[state.land] || state.land);
    var scopeTxt;
    if (state.scope === 'zweit') {
      scopeTxt = landLabel + ' · Zweitstimme';
    } else if (state.scope === 'lage') {
      scopeTxt = 'Szenarien & Parlamentsgröße';
    } else if (state.scope === 'land') {
      scopeTxt = 'Listen — wer kommt rein?';
    } else if (state.scope === 'wkr' && !state.unit) {
      scopeTxt = 'Wahlkreise — Übersicht';
    } else if (state.scope === 'wkr' && ['be', 'mv', 'st', 'BE', 'MV', 'ST'].indexOf(String(state.unit)) >= 0) {
      // Länder-"Einheit" im Wahlkreise-Modus: den Zusatz weglassen, da das durch die Buttons
      // (Sachsen-Anhalt / Berlin / Mecklenburg-Vorpommern) bereits klar ist.
      scopeTxt = 'Wahlkreise';
    } else {
      scopeTxt = unitLabel(state.scope, state.unit);
    }
    if ((state.scope === 'zweit' || state.scope === 'land') && state.partyFocus) {
      scopeTxt += ' · ' + partyShort(state.partyFocus);
    }
    $('wb-scope-label').textContent = scopeTxt;
    if (state.scope === 'wkr' && !state.unit) {
      $('wb-frac-label').textContent =
        stepWhen(s) + ' · ' + s.n_reported + '/' + s.n_total + ' WB (Land)';
    } else {
      $('wb-frac-label').textContent =
        stepWhen(s) +
        (state.scope === 'wkr'
          ? ' · Gebiet ' + Math.round(v.frac_reported * 100) + '\u00a0% · ' +
            v.n_reported + '/' + v.n_total + ' WB'
          : ' · ' + v.n_reported + '/' + v.n_total + ' WB');
    }

    if (state.scope === 'wkr') {
      if (!state.unit) {
        $('wb-stat').innerHTML =
          '<div>Wahlkreis oben antippen.</div>';
      } else {
        var lead = null;
        var stCur = steps()[Math.min(state.step, steps().length - 1)];
        var reg = stCur && stCur.by_wkr && stCur.by_wkr[state.unit];
        if (reg) lead = reg.direct_pred || reg.leader_pred;
        var uLead = (lead && v.uncertainty) ? v.uncertainty[lead] : null;
        $('wb-stat').innerHTML =
          (v.mae_nowcast != null
            ? '<div>Anteilsfehler in diesem WK: <strong>' + fmtNum(v.mae_nowcast, 2) + '\u00a0PP</strong>' +
              ' <span class="wb-art">naiv ' + fmtNum(v.mae_naive, 2) + '\u00a0PP</span></div>'
            : '') +
          (lead
            ? '<div>Führung <strong>' + partyShort(lead) + '</strong> (Erst): ' +
              fmtPct((reg && reg.erst ? reg.erst[lead] : null) != null
                ? (reg.erst[lead])
                : v.nowcast[lead]) +
              (uLead != null ? ' ±\u00a0' + fmtNum(uLead, 1) + '\u00a0PP' : '') +
              (reg && reg.margin != null
                ? ' · Marge ' + fmtNum(reg.margin, 1) +
                  (marginUnc(reg) != null ? ' ±\u00a0' + fmtNum(marginUnc(reg), 1) : '') +
                  '\u00a0PP'
                : '') +
              '</div>'
            : '');
      }
    } else if (state.scope === 'land') {
      $('wb-stat').innerHTML =
        '<div>Fokus: <strong>Listenplätze</strong> — ' + listenModeLabel() + '</div>' +
        (hasBezirkslisten()
          ? ('<div>Entweder/oder: CDU/SPD/Linke = Bezirkslisten; ' +
            'Grüne/AfD/FDP/BSW = Landesliste.</div>')
          : '<div>Nur Landeslisten (keine Bezirkslisten wie in Berlin).</div>');
    } else if (state.scope === 'lage') {
      var size = s.entry_mc && s.entry_mc.size;
      var to = s.turnout || {};
      var landDone = isLandComplete(s);
      var lastEl = lastElectionRef();
      var lastToTxt = (lastEl && lastEl.turnout != null)
        ? ' <span class="wb-art">· ' + lastElectionShort(lastEl) + ': ' +
          fmtNum(lastEl.turnout, 1) + '\u00a0%</span>'
        : '';
      var lastSizeTxt = (lastEl && lastEl.parliament_size != null)
        ? ' <span class="wb-art">· ' + lastElectionShort(lastEl) + ': ' +
          lastEl.parliament_size + '</span>'
        : '';
      $('wb-stat').innerHTML =
        '<div>Wahlbeteiligung, Szenarien und <strong>Parlamentsgröße</strong></div>' +
        (to.nowcast != null
          ? '<div>Wahlbeteiligung: <strong>' + fmtNum(to.nowcast, 1) + '\u00a0%</strong>' +
            (to.uncertainty != null && to.uncertainty > 0
              ? ' ±\u00a0' + fmtNum(to.uncertainty, 1) + '\u00a0PP'
              : '') +
            (landDone && to.truth != null
              ? ' <span class="wb-art">· Endstand ' + fmtNum(to.truth, 1) + '\u00a0%</span>'
              : '') +
            lastToTxt +
            '</div>'
          : (lastToTxt
            ? '<div>Wahlbeteiligung letzte Wahl (' + lastElectionShort(lastEl) +
              '): <strong>' + fmtNum(lastEl.turnout, 1) + '\u00a0%</strong></div>'
            : '')) +
        (size
          ? '<div>Größe jetzt: <strong>' + size[1] + '</strong> Sitze ' +
            '<span class="wb-art">(p10 ' + size[0] + ' – p90 ' + size[2] +
            (s.entry_mc && s.entry_mc.p_size_gt_base != null && s.entry_mc.p_size_gt_base > 0.005
              ? ' · Vergrößerung: ' + Math.round(s.entry_mc.p_size_gt_base * 100) + '\u00a0%' +
                (s.entry_mc.size_p95 != null ? ', p95 ' + s.entry_mc.size_p95 : '')
              : '') +
            ')</span>' +
            lastSizeTxt + '</div>'
          : (lastEl && lastEl.parliament_size != null
            ? '<div>Parlamentsgröße letzte Wahl (' + lastElectionShort(lastEl) +
              '): <strong>' + lastEl.parliament_size + '</strong> Sitze</div>'
            : ''));
    } else {
      var top = PARTIES_ORDER.filter(function (p) { return p !== 'others'; })
        .slice()
        .sort(function (a, b) {
          return (v.nowcast[b] || 0) - (v.nowcast[a] || 0);
        })
        .map(function (p) {
          var u = (v.uncertainty || {})[p];
          return partyShort(p) + '\u00a0' + fmtNum(v.nowcast[p], 1) +
            (u != null ? '±' + fmtNum(u, 1) : '');
        })
        .join(' · ');
      var mixLive = s.mix_live != null ? s.mix_live : s.learn_weight;
      var mixPrior = s.mix_prior != null ? s.mix_prior : (mixLive != null ? 1 - mixLive : null);
      $('wb-stat').innerHTML =
        '<div><strong>Zweitstimme-Nowcast</strong> ' + top + '</div>' +
        '<div>' +
          (mixLive != null
            ? 'Mischung <strong>' + Math.round(mixLive * 100) + '\u00a0%</strong> Live-Auszählung · ' +
              '<strong>' + Math.round((mixPrior != null ? mixPrior : 0) * 100) +
              '\u00a0%</strong> zweitstimme.org-Prognose'
            : 'Lerngewicht <strong>' +
              (s.learn_weight != null ? fmtNum(s.learn_weight, 2) : '—') +
              '</strong>') +
          (s.representativeness != null
            ? ' · Repräsentativität <strong>' + fmtNum(s.representativeness, 2) + '</strong>'
            : '') +
          (isLivePage()
            ? ''
            : ' <span class="wb-art">· MAE/Treffer unter Eval</span>') +
          '</div>';
    }

    var labels = state.data.party_labels || {};
    var unc = v.uncertainty || {};
    var mainTable = $('wb-table');
    var mainHead = mainTable && mainTable.querySelector('thead');
    var mainBody = mainTable && mainTable.querySelector('tbody');
    if (mainHead && mainBody) {
      mainHead.innerHTML = '<tr><th></th>' + PARTIES_ORDER.map(function (p) {
        var col = PARTY_COLORS[p] || '#888';
        return '<th style="border-top:3px solid ' + col + ';">' +
          escapeHtml(labels[p] || p) + '</th>';
      }).join('') + '</tr>';
      var ncCells = PARTIES_ORDER.map(function (p) {
        var nc = v.nowcast[p];
        var u = unc[p];
        var range = (u != null && isFinite(u) && nc != null)
          ? ('<span class="wb-h-band">[' + fmtNum(nc - u, 1) + '–' +
            fmtNum(nc + u, 1) + ']</span>')
          : '';
        return '<td class="wb-h-nc">' + fmtPct(nc) + range + '</td>';
      }).join('');
      var pmCells = PARTIES_ORDER.map(function (p) {
        var u = unc[p];
        var band = (u != null && isFinite(u)) ? ('±\u00a0' + fmtNum(u, 1)) : '—';
        return '<td class="wb-h-pm">' + band + '</td>';
      }).join('');
      mainBody.innerHTML =
        '<tr><td>Nowcast</td>' + ncCells + '</tr>' +
        '<tr><td>±</td>' + pmCells + '</tr>';
    }

    var landUncTxt = uncLandNote(s);
    var shareNote = $('wb-share-note');
    if (shareNote) {
      shareNote.textContent = isLivePage()
        ? ('Links von 0\u00a0%: Forecast, ARD/ZDF-Exit, Hochrechnung (±)' +
          (state.scope === 'wkr' ? ', auf diesen WK übertragen' : '') +
          '. Ab 0\u00a0%: Nowcast. ' +
          (state.scope === 'wkr' ? uncWkrNote(((steps()[Math.min(state.step, steps().length - 1)] || {}).by_wkr || {})[state.unit] || {}) : landUncTxt))
        : ('Linie = Nowcast. ' + landUncTxt);
    }
    var uncNote = $('wb-unc-note');
    if (uncNote) {
      uncNote.textContent = landUncTxt;
    }

    $('wb-foot').textContent =
      ((state.data.model && state.data.model.description) || '') +
      ' Ebene: ' + (SCOPE_LABELS[state.scope] || state.scope) + '.' +
      ' Generiert: ' + formatBerlin(state.data.generated_at) + '.';

    renderHitsStrip();
    renderScenarioProbs();
    renderHitsTimeline();
    renderCallBanner();
    renderWkrRace();
    renderWkrWhy();
    renderEntry();
    renderCoverage();
    renderActual();
    renderEval();
    renderMap();
    drawShareChart();
    drawCompareChart();
    if (state.scope === 'wkr') drawWkrRaceCharts();
    if (state.scope === 'zweit') drawChart();
    if (state.scope === 'lage') {
      drawTurnoutChart();
      drawSizeChart();
    }
    // Re-draw once after layout so canvas width is correct (bands included)
    requestAnimationFrame(function () {
      drawShareChart();
      drawCompareChart();
      if (state.scope === 'wkr') drawWkrRaceCharts();
      if (state.scope === 'zweit') drawChart();
      if (state.scope === 'lage') {
      drawTurnoutChart();
      drawSizeChart();
    }
    });
  }

  function bind() {
    var tabs = $('wb-scope-tabs');
    if (tabs) {
      tabs.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-scope]');
        if (!btn || !tabs.contains(btn)) return;
        setScope(btn.getAttribute('data-scope'));
      });
    }
    var sub = $('wb-subnav');
    if (sub) {
      sub.addEventListener('input', function (e) {
        if (e.target.id === 'wb-wkr-search') {
          state.wkrSearch = e.target.value;
          applyWkrSearchFilter();
        }
      });
      sub.addEventListener('keydown', function (e) {
        if (e.target.id !== 'wb-wkr-search' || e.key !== 'Enter') return;
        e.preventDefault();
        var first = sub.querySelector('.wb-wkr-tile:not([hidden])');
        if (first) openWkr(first.getAttribute('data-wkr-link'));
      });
      sub.addEventListener('click', function (e) {
        var partyBtn = e.target.closest('[data-party]');
        if (partyBtn && sub.contains(partyBtn)) {
          var p = partyBtn.getAttribute('data-party') || '';
          state.partyFocus = p || null;
          renderStep();
          return;
        }
        var unitBtn = e.target.closest('[data-unit]');
        if (unitBtn && sub.contains(unitBtn)) {
          state.unit = unitBtn.getAttribute('data-unit') || '';
          renderStep();
        }
      });
    }
    var slider = $('wb-slider');
    if (slider) {
      slider.addEventListener('input', function (e) {
        if (isLivePage()) return; // live: always the latest poll
        state.step = Number(e.target.value);
        renderStep();
      });
    }
    window.addEventListener('resize', function () {
      drawShareChart();
      drawCompareChart();
      if (state.scope === 'wkr') drawWkrRaceCharts();
      if (state.scope === 'zweit') drawChart();
      if (state.scope === 'lage') {
      drawTurnoutChart();
      drawSizeChart();
    }
    });
    window.addEventListener('zweitstimme-logo-ready', function () {
      drawShareChart();
      drawCompareChart();
      if (state.scope === 'wkr') drawWkrRaceCharts();
      if (state.scope === 'zweit') drawChart();
      if (state.scope === 'lage') {
        drawTurnoutChart();
        drawSizeChart();
      }
    });
    var evalRoot = $('wb-eval-root');
    if (evalRoot) {
      evalRoot.addEventListener('toggle', function () {
        if (!evalRoot.open || state.scope !== 'zweit') return;
        requestAnimationFrame(function () {
          drawChart();
          renderDirektMilestones();
        });
      });
    }
  }

  function renderLiveStatus() {
    var el = $('wb-live-status');
    if (!el) return;
    var live = (state.data && state.data.live) || null;
    var root = $('wahlabend-root');
    var n = steps().length;
    if (root) {
      if (isLivePage() && n <= 1) root.setAttribute('data-wb-single-step', '1');
      else root.removeAttribute('data-wb-single-step');
    }
    if (!live && !isLivePage()) {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    if (!live) {
      el.textContent = 'Live-Datei noch nicht veröffentlicht — zeige Replay, bis StaLA liefert.';
      return;
    }
    var nWkr = Number((state.data && state.data.n_wkr) || live.soll_wkr || 0);
    var nPrecincts = Number((state.data && state.data.n_precincts) || 0);
    var ist = live.ist_wb;
    var soll = live.soll_wb;
    if (nPrecincts > nWkr && (soll == null || Number(soll) <= nWkr)) {
      soll = nPrecincts;
    }
    var wbLine;
    if (ist != null && soll != null && Number(soll) > 0) {
      wbLine = '<strong>' + ist + '</strong> von <strong>' + soll +
        '</strong> Wahlbezirken ausgezählt';
    } else if (ist != null) {
      wbLine = '<strong>' + ist + '</strong> Wahlbezirke ausgezählt' +
        (Number(soll) === 0 ? ' <span class="wb-art">(Soll noch nicht gemeldet)</span>' : '');
    } else {
      wbLine = 'Wahlbezirke: —';
    }
    var istWkr = live.ist_wkr;
    var sollWkr = live.soll_wkr != null ? live.soll_wkr : (nWkr || null);
    if (sollWkr && Number(soll) !== Number(sollWkr)) {
      wbLine += ' <span class="wb-art">· ' +
        (istWkr != null ? istWkr : '0') + ' von ' + sollWkr +
        ' Wahlkreisen mit Meldung</span>';
    }
    var mixLive = live.mix_live;
    if (mixLive == null) {
      var stNow = steps();
      var last = stNow.length ? stNow[Math.min(state.step, stNow.length - 1)] : null;
      mixLive = last && last.mix_live != null ? last.mix_live : (last && last.learn_weight);
    }
    var mixPrior = live.mix_prior;
    if (mixPrior == null && mixLive != null) mixPrior = 1 - mixLive;
    var mixLine = (mixLive != null)
      ? ('<strong>' + Math.round(mixLive * 100) + '\u00a0%</strong> Live-Auszählung · ' +
        '<strong>' + Math.round((mixPrior || 0) * 100) +
        '\u00a0%</strong> zweitstimme.org-Prognose')
      : '';
    var gen = (state.data && state.data.generated_at) || null;
    var stamp = gen ? formatBerlin(gen) : '';
    var runBit = live.run_url
      ? (' · <a href="' + live.run_url + '" rel="noopener noreferrer">GitHub Action</a>')
      : (live.run_id ? ' · GitHub Action' : '');
    var kind = live.result_kind_label || live.result_kind || '';
    var bits = [];
    bits.push('<div class="wb-live-count">' + wbLine + '</div>');
    if (stamp) {
      bits.push('<div>Stand dieser Version: <strong>' + stamp + '</strong>' + runBit + '</div>');
    }
    if (mixLine) bits.push('<div>Mischung: ' + mixLine + '</div>');
    if (kind) bits.push('<div class="wb-art">' + kind + '</div>');
    var src = live.prediction_source_label || live.prediction_source;
    if (src) bits.push('<div>Quelle der Vorhersage: <strong>' + src + '</strong></div>');
    var beNoWb = state.land === 'be' && live.wb_level !== 'wahlbezirke' &&
      !(Number(live.n_wb_reported) > 0);
    var wbNote = live.wb_level_note || (beNoWb
      ? 'AfS liefert nachts keine Stimmen je Wahlbezirk (_W_ bleibt 404). Die Präsentation zeigt aber die Ankunftstafel — welche Wahlbezirke gerade eingegangen sind — plus Ist/Soll je Gebiet.'
      : '');
    var arrivals = live.ankunft_latest || [];
    if (arrivals.length) {
      bits.push(
        '<div class="wb-ankunft">Zuletzt eingegangen: ' +
        arrivals.slice(0, 8).map(function (a) {
          var label = (a.id || '') + (a.name ? ' ' + a.name : '');
          return '<span>' + escapeHtml(label) +
            (a.time ? ' <span class="wb-art">' + escapeHtml(a.time) + '</span>' : '') +
            '</span>';
        }).join(' · ') +
        (live.ankunft_source
          ? ' <a href="' + live.ankunft_source + '" rel="noopener noreferrer">Ankunftstafel</a>'
          : '') +
        (Number(live.n_ankunft) > arrivals.length
          ? ' <span class="wb-art">· ' + live.n_ankunft + ' seit Beginn der Aufzeichnung</span>'
          : '') +
        '</div>'
      );
    }
    if (wbNote) {
      bits.push(
        '<div class="wb-live-disclaimer">' + escapeHtml(wbNote) +
        (state.land === 'be'
          ? ' <a href="https://www.berlin.de/wahlen/pressemitteilungen/2026/pressemitteilung.1713317.php" rel="noopener noreferrer">AfS-Hinweis</a>.'
          : '') +
        '</div>'
      );
    }
    el.innerHTML = bits.join('');
  }

  function applyPayload(data, keepView) {
    state.data = data;
    state._precinctMap = null;
    ingestScenarioPStart(data, false);
    if (!keepView || !forecastPStartOfficial) loadForecastScenarioBaseline();
    applyPartyOrderFromData(data);
    var ids = Object.keys(data.scenarios || {});
    if (ids.indexOf('live') >= 0) state.scenario = 'live';
    else if (ids.indexOf('actual_times') >= 0) state.scenario = 'actual_times';
    else if (ids.indexOf('random') >= 0) state.scenario = 'random';
    else state.scenario = ids[0] || 'random';
    if (!keepView) {
      state.scope = 'zweit';
      state.unit = (data.geo_units && data.geo_units.land && data.geo_units.land[0])
        ? data.geo_units.land[0].id
        : (state.land === 'be' ? 'BE' : state.land.toUpperCase());
      state.partyFocus = null;
    }
    var n = steps().length;
    var slider = $('wb-slider');
    var liveish = isLivePage() || /2026/.test(String(data.election || ''));
    if (slider) {
      slider.max = String(Math.max(0, n - 1));
      if (liveish) {
        slider.value = String(Math.max(0, n - 1));
      } else if (!keepView) {
        slider.value = String(Math.min(10, Math.max(0, n - 1)));
      } else {
        slider.value = String(Math.min(Number(slider.value) || 0, Math.max(0, n - 1)));
      }
      state.step = Number(slider.value);
    }
    renderLiveStatus();
    if (!state._bound) {
      bind();
      state._bound = true;
    }
    renderStep();
  }

  function fetchNowcast(name) {
    var url = dataUrl(name);
    if (isLivePage()) url += (url.indexOf('?') >= 0 ? '&' : '?') + 't=' + Date.now();
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function fetchExternal() {
    return fetch(dataUrl('wahlabend_external.json'), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function init() {
    if (!$('wahlabend-root')) return;
    state.land = landFromQuery();
    $('wb-stat').innerHTML = '<span class="wb-loading">Lade Auswertung …</span>';
    document.querySelectorAll('[data-wb-land]').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute('data-wb-land') === state.land);
      btn.addEventListener('click', function () {
        var next = btn.getAttribute('data-wb-land');
        if (!next || next === state.land) return;
        var url = new URL(window.location.href);
        url.searchParams.set('state', next);
        window.location.href = url.toString();
      });
    });
    var primary = replayFileForLand(state.land);
    Promise.all([
      fetchNowcast(primary)
        .then(function (data) { return { data: data, fallback: false }; })
        .catch(function (err) {
          var fb = fallbackFileForLand(state.land);
          if (!isLivePage() || primary === fb) throw err;
          return fetchNowcast(fb).then(function (data) {
            return { data: data, fallback: true };
          });
        }),
      fetchExternal()
    ])
      .then(function (pair) {
        var pack = pair[0];
        if (pair[1]) state.external = pair[1];
        applyPayload(pack.data, false);
        if (pack.fallback) {
          var slider = $('wb-slider');
          if (slider) {
            slider.value = '0';
            state.step = 0;
            renderStep();
          }
          var el = $('wb-live-status');
          if (el) {
            el.hidden = false;
            el.textContent = 'Live-Nowcast-Datei noch nicht auf dem Preview — zeige Replay als Platzhalter.';
          }
        }
        if (isLivePage()) {
          window.setInterval(function () {
            Promise.all([
              fetchNowcast(replayFileForLand(state.land)),
              fetchExternal()
            ]).then(function (pair) {
              if (pair[1]) state.external = pair[1];
              applyPayload(pair[0], true);
            }).catch(function () { /* keep last good snapshot */ });
          }, 90000);
        }
      })
      .catch(function (err) {
        var stat = $('wb-stat');
        if (stat) {
          stat.innerHTML =
            '<span class="wb-err">Auswertung konnte nicht geladen werden: ' +
            String(err.message || err) + '</span>';
        }
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
