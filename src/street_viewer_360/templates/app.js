// Street Viewer 360 - generated frontend.
(function () {
  "use strict";

  var statusEl = document.getElementById("status");
  var mapEl = document.getElementById("map");
  var viewerEl = document.getElementById("viewer");
  var viewerInfoEl = document.getElementById("viewer-info");
  var panoramaEl = document.getElementById("panorama");
  var closeBtn = document.getElementById("viewer-close");

  var currentPannellum = null;

  function setStatus(text) {
    statusEl.textContent = text || "";
  }

  function openViewer(panorama) {
    if (currentPannellum && typeof currentPannellum.destroy === "function") {
      currentPannellum.destroy();
      currentPannellum = null;
    }
    panoramaEl.innerHTML = "";
    viewerEl.classList.remove("hidden");

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
  }

  function closeViewer() {
    viewerEl.classList.add("hidden");
    if (currentPannellum && typeof currentPannellum.destroy === "function") {
      currentPannellum.destroy();
      currentPannellum = null;
    }
    panoramaEl.innerHTML = "";
  }

  closeBtn.addEventListener("click", closeViewer);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeViewer();
  });

  function buildMap(metadata) {
    var defaultZoom = metadata.default_zoom || 13;
    var layers = metadata.map_layers && metadata.map_layers.length
      ? metadata.map_layers
      : [{ name: "OSM", url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", attribution: "(c) OpenStreetMap contributors", default: true }];

    var map = L.map(mapEl, { zoomControl: true });

    var baseLayers = {};
    var defaultLayer = null;
    layers.forEach(function (layer) {
      var tile = L.tileLayer(layer.url, { attribution: layer.attribution || "" });
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

    var markerGroup = L.featureGroup();
    withCoords.forEach(function (p) {
      var marker = L.marker([p.lat, p.lon]);
      var popupHtml = '<strong>' + escapeHtml(p.source_filename) + '</strong>'
        + (p.captured_at ? '<br/>' + escapeHtml(p.captured_at) : '')
        + '<br/><a href="#" data-pano-id="' + escapeHtml(p.id) + '">Open panorama</a>';
      marker.bindPopup(popupHtml);
      marker.on("popupopen", function (e) {
        var link = e.popup.getElement().querySelector('a[data-pano-id]');
        if (link) {
          link.addEventListener("click", function (ev) {
            ev.preventDefault();
            openViewer(p);
          });
        }
      });
      marker.addTo(markerGroup);
    });
    markerGroup.addTo(map);
    map.fitBounds(markerGroup.getBounds().pad(0.2), { maxZoom: defaultZoom });

    setStatus(withCoords.length + " panorama(s) on map");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
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
