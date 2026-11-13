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

  // ---- Code blocks and copying -------------------------------------------

  var HIGHLIGHT_LIMIT = 20000;
  var copyBridge = false;

  var LANG_ALIASES = {
    py: "python",
    python: "python",
    js: "javascript",
    jsx: "javascript",
    mjs: "javascript",
    cjs: "javascript",
    javascript: "javascript",
    ts: "typescript",
    tsx: "typescript",
    typescript: "typescript",
    json: "json",
    jsonc: "json",
    sh: "bash",
    shell: "bash",
    zsh: "bash",
    bash: "bash",
    pwsh: "powershell",
    ps1: "powershell",
    powershell: "powershell",
    sql: "sql",
    c: "c",
    h: "c",
    cpp: "cpp",
    "c++": "cpp",
    hpp: "cpp",
    java: "java",
    css: "css"
  };

  var KEYWORDS = {
    python: (
      "False None True and as assert async await break class continue def del " +
      "elif else except finally for from global if import in is lambda " +
      "nonlocal not or pass raise return try while with yield"
    ).split(" "),
    javascript: (
      "async await break case catch class const continue debugger default " +
      "delete do else export extends false finally for from function if import " +
      "in instanceof let new null of return static super switch this throw " +
      "true try typeof undefined var void while yield"
    ).split(" "),
    typescript: (
      "async await break case catch class const continue default delete do " +
      "else enum export extends false finally for from function if implements " +
      "import in instanceof interface keyof let namespace new null of private " +
      "protected public readonly return static super switch this throw true " +
      "try type typeof undefined var void while yield"
    ).split(" "),
    bash: (
      "case do done elif else esac fi for function if in local return then " +
      "until while export echo"
    ).split(" "),
    powershell: (
      "begin break catch class continue do else elseif end exit filter " +
      "finally for foreach function if in param process return switch throw " +
      "trap try until while"
    ).split(" "),
    sql: (
      "ADD ALL ALTER AND AS ASC BETWEEN BY CASE CHECK COLUMN CREATE DELETE " +
      "DESC DISTINCT DROP ELSE END EXISTS FOREIGN FROM GROUP HAVING IN INDEX " +
      "INNER INSERT INTO IS JOIN KEY LEFT LIKE LIMIT NOT NULL ON OR ORDER " +
      "OUTER PRIMARY REFERENCES RIGHT SELECT SET TABLE THEN UNION UNIQUE " +
      "UPDATE VALUES VIEW WHERE"
    ).split(" "),
    c: (
      "break case char const continue default do else enum extern float for " +
      "goto if int long register return short signed sizeof static struct " +
      "switch typedef union unsigned void volatile while"
    ).split(" "),
    cpp: (
      "auto bool break case catch char class const constexpr continue " +
      "default delete do double else enum explicit false float for friend " +
      "if inline int long namespace new nullptr operator private protected " +
      "public return short signed sizeof static struct switch template this " +
      "throw true try typedef typename union unsigned using virtual void " +
      "volatile while"
    ).split(" "),
    java: (
      "abstract boolean break byte case catch char class continue default do " +
      "double else enum extends false final finally float for if implements " +
      "import instanceof int interface long new null package private " +
      "protected public return short static super switch this throw throws " +
      "true try void volatile while"
    ).split(" ")
  };

  var lexerCache = {};

  function buildLexer(lang) {
    var parts = [];
    var classes = [];
    function add(cls, source) {
      parts.push(source);
      classes.push(cls);
    }

    if (lang === "python") {
      add("tok-com", '"""[\\s\\S]*?(?:"""|$)');
      add("tok-com", "'''[\\s\\S]*?(?:'''|$)");
      add("tok-com", "#[^\\n]*");
      add("tok-str", '"(?:\\\\.|[^"\\\\\\n])*"');
      add("tok-str", "'(?:\\\\.|[^'\\\\\\n])*'");
    } else if (lang === "bash" || lang === "powershell") {
      add("tok-com", "#[^\\n]*");
      add("tok-str", '"(?:\\\\.|[^"\\\\\\n])*"');
      add("tok-str", "'[^'\\n]*'");
      add("tok-var", "\\$\\{?[A-Za-z_][A-Za-z0-9_]*\\}?");
    } else if (lang === "css") {
      add("tok-com", "\\/\\*[\\s\\S]*?\\*\\/");
      add("tok-str", '"(?:\\\\.|[^"\\\\\\n])*"');
      add("tok-str", "'(?:\\\\.|[^'\\\\\\n])*'");
      add("tok-num", "#[0-9a-fA-F]{3,8}\\b");
      add("tok-kw", "@[A-Za-z-]+");
      add(
        "tok-num",
        "\\b\\d+(?:\\.\\d+)?(?:px|rem|em|%|vh|vw|s|ms|fr|deg|ch|ex)?\\b"
      );
    } else if (lang === "json") {
      add("tok-str", '"(?:\\\\.|[^"\\\\\\n])*"');
      add("tok-kw", "\\b(?:true|false|null)\\b");
      add("tok-num", "-?\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b");
    } else {
      add("tok-com", "\\/\\*[\\s\\S]*?\\*\\/");
      add("tok-com", lang === "sql" ? "--[^\\n]*" : "\\/\\/[^\\n]*");
      add("tok-str", '"(?:\\\\.|[^"\\\\\\n])*"');
      add("tok-str", "'(?:\\\\.|[^'\\\\\\n])*'");
      if (lang === "javascript" || lang === "typescript") {
        add("tok-str", "`(?:\\\\.|[^`\\\\])*`");
      }
    }

    var words = KEYWORDS[lang];
    if (words && words.length) {
      add("tok-kw", "\\b(?:" + words.join("|") + ")\\b");
    }
    if (lang !== "json" && lang !== "css") {
      add("tok-fn", "\\b[A-Za-z_][A-Za-z0-9_]*(?=\\s*\\()");
    }
    if (lang !== "css") {
      add("tok-num", "\\b\\d+(?:\\.\\d+)?\\b");
    }
    return {
      re: new RegExp(
        parts
          .map(function (source) {
            return "(" + source + ")";
          })
          .join("|"),
        lang === "sql" ? "gi" : "g"
      ),
      classes: classes
    };
  }

  function lexerFor(lang) {
    if (!lexerCache[lang]) lexerCache[lang] = buildLexer(lang);
    return lexerCache[lang];
  }

  function tokenSpan(cls, text) {
    var node = document.createElement("span");
    node.className = cls;
    node.textContent = text;
    return node;
  }

  function highlightCode(code) {
    if (!code || code.getAttribute("data-highlighted")) return;
    var found = /(?:^|\s)language-([\w+#.-]+)/i.exec(code.className || "");
    var lang = found ? LANG_ALIASES[found[1].toLowerCase()] : "";
    if (!lang) return;
    var text = code.textContent || "";
    if (!text || text.length > HIGHLIGHT_LIMIT) return;

    var lexer = lexerFor(lang);
    var re = new RegExp(lexer.re.source, lexer.re.flags);
    var fragment = document.createDocumentFragment();
    var last = 0;
    var match;
    while ((match = re.exec(text)) !== null) {
      if (!match[0]) {
        re.lastIndex += 1;
        continue;
      }
      if (match.index > last) {
        fragment.appendChild(
          document.createTextNode(text.slice(last, match.index))
        );
      }
      var cls = "";
      for (var i = 1; i < match.length; i += 1) {
        if (match[i] !== undefined) {
          cls = lexer.classes[i - 1];
          break;
        }
      }
      fragment.appendChild(tokenSpan(cls, match[0]));
      last = re.lastIndex;
    }
    if (last < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(last)));
    }
    code.textContent = "";
    code.appendChild(fragment);
    code.setAttribute("data-highlighted", "1");
  }

  function codeLanguage(code) {
    var found = /(?:^|\s)language-([\w+#.-]+)/i.exec(
      (code && code.className) || ""
    );
    return found ? found[1] : "";
  }

  function addCodeToolbar(pre) {
    if (pre.closest(".code-block")) return;
    var wrap = document.createElement("div");
    wrap.className = "code-block";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);

    var bar = document.createElement("div");
    bar.className = "code-bar";
    var label = document.createElement("span");
    label.className = "code-lang";
    label.textContent = codeLanguage(pre.querySelector("code")) || "code";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "copy-code";
    button.textContent = "Copy";
    bar.appendChild(label);
    bar.appendChild(button);
    wrap.insertBefore(bar, pre);
  }

  function enhance(root, withHighlighting) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll(".bubble pre").forEach(function (pre) {
      if (pre.classList.contains("mermaid") || pre.closest(".code-block")) {
        return;
      }
      addCodeToolbar(pre);
      if (withHighlighting) highlightCode(pre.querySelector("code"));
    });
  }

  function flash(button, ok) {
    if (!button.getAttribute("data-label")) {
      button.setAttribute("data-label", button.textContent || "Copy");
    }
    button.textContent = ok ? "Copied" : "Copy failed";
    button.classList.toggle("copy-failed", !ok);
    window.setTimeout(function () {
      button.textContent = button.getAttribute("data-label") || "Copy";
      button.classList.remove("copy-failed");
    }, 1200);
  }

  function legacyCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(area);
    return ok;
  }

  function copyText(text, button) {
    if (copyBridge) {
      var result = null;
      try {
        result = window.prompt("himari-copy", text);
      } catch (err) {
        result = null;
      }
      if (result !== null) {
        flash(button, true);
        return;
      }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () {
          flash(button, true);
        },
        function () {
          flash(button, legacyCopy(text));
        }
      );
      return;
    }
    flash(button, legacyCopy(text));
  }

  function onCopyClick(event) {
    var button =
      event.target && event.target.closest
        ? event.target.closest("button.copy-code, button.copy-msg")
        : null;
    if (!button) return;
    event.preventDefault();
    var text = "";
    if (button.classList.contains("copy-code")) {
      var wrap = button.closest(".code-block");
      var code = wrap ? wrap.querySelector("pre code") : null;
      text = code ? code.textContent || "" : "";
    } else {
      var article = button.closest("article.msg");
      text = article ? article.getAttribute("data-copy") || "" : "";
    }
    if (text) copyText(text, button);
  }

  function markEntrance(root, previousCount) {
    var nodes = Array.prototype.slice.call(root.children);
    nodes.forEach(function (node, index) {
      if (index < previousCount) {
        node.classList.add("no-enter");
        return;
      }
      node.classList.remove("no-enter");
      node.classList.add("enter");
      node.style.animationDelay =
        Math.min(index - previousCount, 4) * 45 + "ms";
    });
  }

  function scrollBottom(smooth) {
    var top = document.documentElement.scrollHeight;
    if (smooth) {
      try {
        window.scrollTo({ top: top, behavior: "smooth" });
        return;
      } catch (err) {
        /* fall through to the instant scroll */
      }
    }
    window.scrollTo(0, top);
  }

  function onWelcomeClick(event) {
    var button =
      event.target && event.target.closest
        ? event.target.closest(".welcome-chips button")
        : null;
    if (!button) return;
    event.preventDefault();
    var text = button.getAttribute("data-prompt") || button.textContent || "";
    try {
      window.prompt("himari-fill", text);
    } catch (err) {
      /* the desktop bridge is optional */
    }
  }

  document.addEventListener("click", onCopyClick);
  document.addEventListener("click", onWelcomeClick);

  window.himari = {
    setContent: function (payload) {
      var root = document.getElementById("transcript");
      if (!root) return;
      var stick = nearBottom();
      var live = !!(payload && payload.streaming);
      var target = root;
      if (payload && typeof payload.last === "string" && root.lastElementChild) {
        root.lastElementChild.outerHTML = payload.last;
        target = root.lastElementChild;
      } else {
        var previous = root.firstElementChild;
        var previousCount =
          previous && previous.classList.contains("welcome")
            ? 0
            : root.children.length;
        root.innerHTML = (payload && payload.html) || "";
        markEntrance(root, previousCount);
      }
      enhance(target, !live);
      typesetMath();
      if (!live) typesetMermaid();
      if (live) {
        scrollBottom(false);
      } else if ((payload && payload.forceScroll) || stick) {
        scrollBottom(true);
      }
    },
    selection: function () {
      return window.getSelection ? String(window.getSelection()) : "";
    },
    enableBridge: function () {
      copyBridge = true;
    },
    scrollToBottom: function (smooth) {
      scrollBottom(smooth !== false);
    }
  };
})();
