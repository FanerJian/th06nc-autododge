// 提取并搜索 PE 文件中的 ASCII/UTF-16 字符串
// 用法: node strings.js <file> [minLen] [关键词正则...]
const fs = require('fs');
const file = process.argv[2];
const minLen = parseInt(process.argv[3] || '5', 10);
const pats = process.argv.slice(4).map((p) => new RegExp(p, 'i'));
const buf = fs.readFileSync(file);

function scan(encoding) {
  const out = [];
  if (encoding === 'ascii') {
    let cur = '';
    let start = 0;
    for (let i = 0; i <= buf.length; i++) {
      const c = i < buf.length ? buf[i] : 0;
      if (c >= 0x20 && c < 0x7f) {
        if (!cur) start = i;
        cur += String.fromCharCode(c);
      } else {
        if (cur.length >= minLen) out.push({ off: start, s: cur });
        cur = '';
      }
    }
  } else {
    // UTF-16LE
    let cur = '';
    let start = 0;
    for (let i = 0; i + 1 <= buf.length; i += 2) {
      const c = i + 1 < buf.length ? buf.readUInt16LE(i) : 0;
      if (c >= 0x20 && c < 0x7f) {
        if (!cur) start = i;
        cur += String.fromCharCode(c);
      } else {
        if (cur.length >= minLen) out.push({ off: start, s: cur });
        cur = '';
      }
    }
  }
  return out;
}

const all = [...scan('ascii'), ...scan('utf16')].sort((a, b) => a.off - b.off);
const hits = pats.length ? all.filter((x) => pats.some((p) => p.test(x.s))) : all;
console.log('总字符串数: ' + all.length + '  命中: ' + hits.length);
for (const h of hits) {
  console.log('0x' + h.off.toString(16).padStart(8, '0') + '  ' + h.s.slice(0, 300));
}
