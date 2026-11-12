(function () {
  "use strict";

  var mermaidReady = false;
  var mermaidCounter = 0;

  function palette() {
    var css = getComputedStyle(document.documentElement);
    function v(name, fallback) {
      var value = (css.getPropertyValue(name) || "").trim();
      return value || fallback;
    }
    return {
      surface: v("--surface", "#1a1521"),
      card: v("--card", "#221b2b"),
      cardAlt: v("--card-alt", "#2c2336"),
      text: v("--text", "#f4eaf1"),
      muted: v("--muted", "#a893a7"),
      border: v("--border", "#3a2e44"),
      accent: v("--accent", "#e08bb5"),
      accentStrong: v("--accent-strong", "#f2a7cc"),
      accentDim: v("--accent-dim", "#7c4a63"),
      codeBg: v("--code-bg", "#100d15")
    };
  }

  function initMermaid() {
    if (mermaidReady) return true;
    if (typeof mermaid === "undefined") return false;
    var p = palette();
    try {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "base",
        fontFamily: '"Segoe UI", system-ui, sans-serif',
        themeVariables: {
          darkMode: document.body.dataset.theme !== "light",
          background: p.surface,
          primaryColor: p.cardAlt,
          primaryTextColor: p.text,
          primaryBorderColor: p.accentDim,
          secondaryColor: p.card,
          secondaryTextColor: p.text,
          secondaryBorderColor: p.border,
          tertiaryColor: p.surface,
          tertiaryTextColor: p.muted,
          tertiaryBorderColor: p.border,
          mainBkg: p.cardAlt,
          nodeBorder: p.accentDim,
          nodeTextColor: p.text,
          lineColor: p.accent,
          textColor: p.text,
          titleColor: p.accentStrong,
          edgeLabelBackground: p.codeBg,
          clusterBkg: p.card,
          clusterBorder: p.border,
          actorBkg: p.cardAlt,
          actorBorder: p.accentDim,
          actorTextColor: p.text,
          signalColor: p.muted,
          signalTextColor: p.text
        }
      });
      mermaidReady = true;
    } catch (err) {
      return false;
    }
    return true;
  }

  function typesetMath() {
    if (typeof katex === "undefined") return;
    document.querySelectorAll(".math:not([data-typeset])").forEach(function (el) {
      el.setAttribute("data-typeset", "1");
      try {
        katex.render(el.textContent || "", el, {
          displayMode: el.getAttribute("data-display") === "1",
          throwOnError: false,
          strict: "ignore"
        });
      } catch (err) {
        el.classList.add("math-error");
      }
    });
  }

  function typesetMermaid() {
    if (!initMermaid()) return;
    document.querySelectorAll("pre.mermaid:not([data-drawn])").forEach(function (el) {
      el.setAttribute("data-drawn", "1");
      var code = el.textContent || "";
      var id = "himari-mermaid-" + (++mermaidCounter);
      mermaid.render(id, code).then(function (out) {
        el.innerHTML = out.svg || "";
        el.classList.add("mermaid-done");
        if (typeof out.bindFunctions === "function") out.bindFunctions(el);
      }).catch(function () {
        el.classList.remove("mermaid-done");
        el.classList.add("mermaid-error");
        el.textContent = code;
      });
    });
  }

  function nearBottom() {
    return window.innerHeight + window.scrollY >=
      document.documentElement.scrollHeight - 90;
  }

  window.himari = {
    setContent: function (payload) {
      var root = document.getElementById("transcript");
      if (!root) return;
      var stick = nearBottom();
      root.innerHTML = (payload && payload.html) || "";
      typesetMath();
      if (payload && !payload.streaming) typesetMermaid();
      if ((payload && (payload.forceScroll || payload.streaming)) || stick) {
        window.scrollTo(0, document.documentElement.scrollHeight);
      }
    },
    selection: function () {
      return window.getSelection ? String(window.getSelection()) : "";
    },
    scrollToBottom: function () {
      window.scrollTo(0, document.documentElement.scrollHeight);
    }
  };
})();
