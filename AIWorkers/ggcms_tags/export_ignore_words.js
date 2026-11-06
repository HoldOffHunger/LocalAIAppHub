// Writes ListKeywords' own ignore list (its "Ignore common words" box) to ignore_words.json, so the worker skips exactly what the page skips.
// Run again whenever list-find-keywords.js changes: node export_ignore_words.js
const fs = require("fs");
const path = require("path");
const source = path.resolve(__dirname, "../../GGCMS/var/www/html/javascript/list-find-keywords.js");
const fallback = "E:/GGCMS/var/www/html/javascript/list-find-keywords.js";
let code = fs.readFileSync(fs.existsSync(source) ? source : fallback, "utf8");
// The functions live inside $(document).ready(...): hand the list out just before that closure ends
const end = code.lastIndexOf("});");
code = code.slice(0, end) + "globalThis.__ignore = getIgnoreKeywords();\n" + code.slice(end);
const quiet = () => ({ ready: (f) => f(), keyup() {}, click() {}, change() {}, text() {}, val: () => "", is: () => true, html: () => quiet() });
global.$ = Object.assign(quiet, { trim: (s) => String(s).trim(), each: (o, f) => Object.entries(o).forEach(([k, v]) => f(k, v)) });
global.document = {};
new Function(code)();
const words = [...new Set(globalThis.__ignore)].sort();
fs.writeFileSync(path.join(__dirname, "ignore_words.json"), JSON.stringify(words, null, 0));
console.log(`${words.length} ignore words written`);
