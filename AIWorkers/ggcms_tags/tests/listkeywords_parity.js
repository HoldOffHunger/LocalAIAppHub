// Runs the page's own findKeywords() on stdin's text and prints its output, for test_tags.py to compare the Python port against
const fs = require("fs");
let code = fs.readFileSync("E:/GGCMS/var/www/html/javascript/list-find-keywords.js", "utf8");
const end = code.lastIndexOf("});");
code = code.slice(0, end) + "globalThis.__find = findKeywords;\n" + code.slice(end);
const input = fs.readFileSync(0, "utf8");
let output = "";
const node = (selector) => ({
  ready: (f) => f(), keyup() {}, click() {}, change() {}, text() {},
  is: () => selector !== "#show-counts" && selector !== ".strip-html",  // the text arrives plain; counts not shown
  val: (value) => { if (value !== undefined) { output = value; return; } return selector === "#sort-order" ? "most-common-to-least-common" : input; },
});
global.$ = Object.assign(node, { trim: (s) => String(s).trim(), each: (o, f) => Object.entries(o).forEach(([k, v]) => f(k, v)) });
global.document = {};
new Function(code)();
globalThis.__find();
process.stdout.write(output);
