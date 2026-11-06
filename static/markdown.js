// Small, dependency-free Markdown renderer. Escapes all HTML first, so model output can never inject markup.
(function () {
  function escapeHtml(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function renderInline(text) {
    var codeSpans = [];
    text = text.replace(/`([^`]+)`/g, function (_, code) { codeSpans.push(code); return "\u0000" + (codeSpans.length - 1) + "\u0000"; });
    text = text.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
               .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
               .replace(/__(.+?)__/g, "<strong>$1</strong>")
               .replace(/(^|[^*\w])\*(?!\s)(.+?)\*(?!\w)/g, "$1<em>$2</em>")
               .replace(/(^|[^_\w])_(?!\s)(.+?)_(?!\w)/g, "$1<em>$2</em>")
               .replace(/~~(.+?)~~/g, "<del>$1</del>");
    return text.replace(/\u0000(\d+)\u0000/g, function (_, index) { return "<code>" + codeSpans[index] + "</code>"; });
  }

  function renderList(lines, ordered) {
    var tag = ordered ? "ol" : "ul";
    var items = lines.map(function (line) { return "<li>" + renderInline(line.replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "")) + "</li>"; });
    return "<" + tag + ">" + items.join("") + "</" + tag + ">";
  }

  function takeWhile(lines, start, test) {
    var end = start;
    while (end < lines.length && test(lines[end])) end++;
    return end;
  }

  function renderBlock(lines, index, output) {
    var line = lines[index];
    var heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) { output.push("<h" + heading[1].length + ">" + renderInline(heading[2]) + "</h" + heading[1].length + ">"); return index + 1; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { output.push("<hr>"); return index + 1; }
    if (/^&gt;\s?/.test(line)) {
      var quoteEnd = takeWhile(lines, index, function (l) { return /^&gt;\s?/.test(l); });
      var quoted = lines.slice(index, quoteEnd).map(function (l) { return l.replace(/^&gt;\s?/, ""); });
      output.push("<blockquote>" + renderLines(quoted) + "</blockquote>");
      return quoteEnd;
    }
    var listMatch = /^\s*(?:([-*+])|(\d+[.)]))\s+/.exec(line);
    if (listMatch) {
      var listEnd = takeWhile(lines, index, function (l) { return /^\s*(?:[-*+]|\d+[.)])\s+/.test(l); });
      output.push(renderList(lines.slice(index, listEnd), !!listMatch[2]));
      return listEnd;
    }
    var paragraphEnd = takeWhile(lines, index, function (l) { return l.trim() !== "" && !/^(#{1,6}\s|&gt;|\s*(?:[-*+]|\d+[.)])\s+)/.test(l); });
    paragraphEnd = Math.max(paragraphEnd, index + 1);
    output.push("<p>" + lines.slice(index, paragraphEnd).map(renderInline).join("<br>") + "</p>");
    return paragraphEnd;
  }

  function renderLines(lines) {
    var output = [];
    var index = 0;
    while (index < lines.length) {
      if (lines[index].trim() === "") { index++; continue; }
      index = renderBlock(lines, index, output);
    }
    return output.join("\n");
  }

  function renderMarkdown(source) {
    var parts = escapeHtml(source || "").split(/^```.*$/m);
    var html = "";
    for (var i = 0; i < parts.length; i++) {
      if (i % 2 === 1) html += "<pre><code>" + parts[i].replace(/^\n/, "") + "</code></pre>";
      else html += renderLines(parts[i].split("\n"));
    }
    return html;
  }

  window.renderMarkdown = renderMarkdown;
  window.escapeHtml = escapeHtml;
})();
