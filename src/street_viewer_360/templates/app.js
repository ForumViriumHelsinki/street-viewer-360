// Street Viewer 360 - generated frontend.
(function () {
  "use strict";

  var FIT_MAX_ZOOM = 19;
  var MARKER_COLOR = "#2563eb";
  var MARKER_COLOR_ACTIVE = "#dc2626";
  var MARKER_RADIUS = 6;
  var PATH_COLOR = "#2563eb";

  var statusEl = document.getElementById("status");
  var mainEl = document.querySelector(".app-main");
  var mapEl = document.getElementById("map");
  var viewerEl = document.getElementById("viewer");
  var viewerInfoEl = document.getElementById("viewer-info");
  var panoramaEl = document.getElementById("panorama");
  var closeBtn = document.getElementById("viewer-close");
  var prevBtn = document.getElementById("viewer-prev");
  var nextBtn = document.getElementById("viewer-next");

  var currentPannellum = null;
  var leafletMap = null;
  var orderedPanoramas = [];
  var markersById = {};
  var currentIndex = -1;

  function setStatus(text) {
    statusEl.textContent = text || "";
  }

  function setActiveMarker(panoId) {
    Object.keys(markersById).forEach(function (id) {
      var m = markersById[id];
      if (!m) return;
      var isActive = id === panoId;
      m.setStyle({
        color: isActive ? MARKER_COLOR_ACTIVE : MARKER_COLOR,
        fillColor: isActive ? MARKER_COLOR_ACTIVE : MARKER_COLOR
      });
      if (isActive && m.bringToFront) m.bringToFront();
    });
  }

  function openViewer(panorama) {
    var idx = orderedPanoramas.findIndex(function (p) {
      return p.id === panorama.id;
    });
    if (idx < 0) return;
    currentIndex = idx;

    if (currentPannellum && typeof currentPannellum.destroy === "function") {
      currentPannellum.destroy();
      currentPannellum = null;
    }
    panoramaEl.innerHTML = "";

    var wasHidden = viewerEl.classList.contains("hidden");
    viewerEl.classList.remove("hidden");
    if (wasHidden) {
      mainEl.classList.add("split");
      if (leafletMap) {
        setTimeout(function () { leafletMap.invalidateSize(); }, 0);
      }
    }

    var infoParts = [panorama.source_filename];
    if (panorama.captured_at) infoParts.push(panorama.captured_at);
    if (panorama.camera && panorama.camera.model) infoParts.push(panorama.camera.model);
    viewerInfoEl.textContent = infoParts.join(" · ");

    var config = {
      type: "equirectangular",
      panorama: panorama.image_path,
      autoLoad: true,
      showZoomCtrl: true,
      showFullscreenCtrl: true,
      hfov: 100
    };
    if (typeof panorama.heading === "number") {
      config.yaw = panorama.heading;
    }
    currentPannellum = window.pannellum.viewer(panoramaEl, config);

    setActiveMarker(panorama.id);
    if (leafletMap && typeof panorama.lat === "number" && typeof panorama.lon === "number") {
      leafletMap.panTo([panorama.lat, panorama.lon]);
    }
  }

  function closeViewer() {
    viewerEl.classList.add("hidden");
    mainEl.classList.remove("split");
    if (currentPannellum && typeof currentPannellum.destroy === "function") {
      currentPannellum.destroy();
      currentPannellum = null;
    }
    panoramaEl.innerHTML = "";
    currentIndex = -1;
    setActiveMarker(null);
    if (leafletMap) {
      setTimeout(function () { leafletMap.invalidateSize(); }, 0);
    }
  }

  function navigate(delta) {
    if (!orderedPanoramas.length || currentIndex < 0) return;
    var n = orderedPanoramas.length;
    var next = (currentIndex + delta + n) % n;
    openViewer(orderedPanoramas[next]);
  }

  closeBtn.addEventListener("click", closeViewer);
  if (prevBtn) prevBtn.addEventListener("click", function () { navigate(-1); });
  if (nextBtn) nextBtn.addEventListener("click", function () { navigate(1); });

  document.addEventListener("keydown", function (e) {
    if (viewerEl.classList.contains("hidden")) return;
    if (e.key === "Escape") {
      closeViewer();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      navigate(-1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      navigate(1);
    }
  });

  function sortByCaptureOrder(panoramas) {
    // Stable sort: timestamped panoramas first (by ISO timestamp ascending),
    // then untimestamped panoramas in their original metadata order.
    var withTs = [];
    var withoutTs = [];
    panoramas.forEach(function (p, i) {
      if (p.captured_at) {
        withTs.push({ p: p, i: i });
      } else {
        withoutTs.push({ p: p, i: i });
      }
    });
    withTs.sort(function (a, b) {
      if (a.p.captured_at < b.p.captured_at) return -1;
      if (a.p.captured_at > b.p.captured_at) return 1;
      return a.i - b.i;
    });
    return withTs.concat(withoutTs).map(function (x) { return x.p; });
  }

  function buildMap(metadata) {
    var defaultZoom = metadata.default_zoom || 13;
    var layers = metadata.map_layers && metadata.map_layers.length
      ? metadata.map_layers
      : [{ name: "OSM", url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", attribution: "(c) OpenStreetMap contributors", default: true }];

    var map = L.map(mapEl, { zoomControl: true });
    leafletMap = map;

    var baseLayers = {};
    var defaultLayer = null;
    layers.forEach(function (layer) {
      var tile = L.tileLayer(layer.url, { attribution: layer.attribution || "", maxZoom: FIT_MAX_ZOOM });
      baseLayers[layer.name] = tile;
      if (layer.default && !defaultLayer) defaultLayer = tile;
    });
    if (!defaultLayer) {
      var firstName = Object.keys(baseLayers)[0];
      defaultLayer = baseLayers[firstName];
    }
    defaultLayer.addTo(map);
    if (Object.keys(baseLayers).length > 1) {
      L.control.layers(baseLayers, {}, { position: "topright" }).addTo(map);
    }

    var withCoords = (metadata.panoramas || []).filter(function (p) {
      return typeof p.lat === "number" && typeof p.lon === "number";
    });

    if (!withCoords.length) {
      setStatus("No geotagged panoramas in this package.");
      map.setView([0, 0], 2);
      return;
    }

    orderedPanoramas = sortByCaptureOrder(withCoords);

    var pathPoints = orderedPanoramas
      .filter(function (p) { return !!p.captured_at; })
      .map(function (p) { return [p.lat, p.lon]; });
    if (pathPoints.length >= 2) {
      L.polyline(pathPoints, { color: PATH_COLOR, weight: 2, opacity: 0.7 }).addTo(map);
    }

    var markerGroup = L.featureGroup();
    orderedPanoramas.forEach(function (p) {
      var marker = L.circleMarker([p.lat, p.lon], {
        radius: MARKER_RADIUS,
        color: MARKER_COLOR,
        fillColor: MARKER_COLOR,
        fillOpacity: 0.9,
        weight: 2
      });
      var tooltipText = p.captured_at || p.source_filename;
      marker.bindTooltip(tooltipText, { direction: "top", offset: [0, -4] });
      marker.on("click", function () { openViewer(p); });
      markersById[p.id] = marker;
      marker.addTo(markerGroup);
    });
    markerGroup.addTo(map);
    map.fitBounds(markerGroup.getBounds().pad(0.2), { maxZoom: FIT_MAX_ZOOM });

    setStatus(orderedPanoramas.length + " panorama(s) on map");
  }

  fetch("metadata.json", { cache: "no-cache" })
    .then(function (r) {
      if (!r.ok) throw new Error("metadata.json HTTP " + r.status);
      return r.json();
    })
    .then(buildMap)
    .catch(function (err) {
      setStatus("Failed to load metadata.json: " + err.message);
      console.error(err);
    });
})();
