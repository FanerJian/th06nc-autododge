// PE 解析：导入表 / 导出表 / 节表 / 字符串线索
// 用法: node pe_info.js "<游戏目录>\th06nc.exe"
const fs = require('fs');

const path = process.argv[2];
const buf = fs.readFileSync(path);

function u8(o) { return buf.readUInt8(o); }
function u16(o) { return buf.readUInt16LE(o); }
function u32(o) { return buf.readUInt32LE(o); }
function u64(o) { return Number(buf.readBigUInt64LE(o)); }

const peOff = u32(0x3c);
if (u32(peOff) !== 0x00004550) throw new Error('not PE');
const machine = u16(peOff + 4);
const nsec = u16(peOff + 6);
const optSize = u16(peOff + 20);
const optOff = peOff + 24;
const magic = u16(optOff);
const is64 = magic === 0x20b;

// 数据目录
const ddOff = optOff + (is64 ? 112 : 96);
const dirs = [];
for (let i = 0; i < 16; i++) {
  dirs.push({ rva: u32(ddOff + i * 8), size: u32(ddOff + i * 8 + 4) });
}

// 节表
const secOff = optOff + optSize;
const secs = [];
for (let i = 0; i < nsec; i++) {
  const o = secOff + i * 40;
  secs.push({
    name: buf.toString('ascii', o, o + 8).replace(/\0+$/, ''),
    vaddr: u32(o + 12),
    vsize: u32(o + 8),
    rawptr: u32(o + 20),
    rawsize: u32(o + 16),
    chars: u32(o + 36),
  });
}
function rva2off(rva) {
  for (const s of secs) {
    if (rva >= s.vaddr && rva < s.vaddr + Math.max(s.vsize, s.rawsize)) {
      return s.rawptr + (rva - s.vaddr);
    }
  }
  return -1;
}
function cstr(off) {
  if (off < 0) return '';
  let end = off;
  while (end < buf.length && buf[end] !== 0) end++;
  return buf.toString('ascii', off, end);
}

console.log('=== 基本信息 ===');
console.log('Machine:', machine.toString(16), is64 ? 'PE32+ (x64)' : 'PE32 (x86)');
console.log('Sections:', nsec, '| ImageBase: 0x' + (is64 ? u64(optOff + 24).toString(16) : u32(optOff + 28).toString(16)));
console.log('EntryPoint RVA: 0x' + u32(optOff + 16).toString(16));
console.log('Subsystem:', u16(optOff + (is64 ? 68 : 68)));
const ts = u32(peOff + 8);
console.log('TimeDateStamp:', ts, '(' + new Date(ts * 1000).toISOString() + ')');

// 导入表
console.log('\n=== 导入 DLL / 函数 ===');
const impRva = dirs[1].rva;
if (impRva) {
  let o = rva2off(impRva);
  for (let i = 0; ; i++) {
    const desc = o + i * 20;
    const oft = u32(desc);
    const nameRva = u32(desc + 12);
    const iat = u32(desc + 16);
    if (!oft && !nameRva && !iat) break;
    const dllName = cstr(rva2off(nameRva));
    console.log('\n--- ' + dllName + ' ---');
    let thunk = oft || iat;
    let to = rva2off(thunk);
    const fns = [];
    for (let j = 0; ; j++) {
      const v = u64(to + j * 8);
      if (v === 0) break;
      if (v & 0x8000000000000000) {
        fns.push('Ordinal#' + (v & 0xffff));
      } else {
        fns.push(cstr(rva2off(v) + 2));
      }
      if (j > 4000) break;
    }
    console.log('  ' + fns.join('\n  '));
  }
}

// 延迟导入
if (dirs[13].rva) {
  console.log('\n=== 延迟导入 ===');
  let o = rva2off(dirs[13].rva);
  for (let i = 0; ; i++) {
    const d = o + i * 32;
    const nameRva = u32(d + 4);
    if (!nameRva) break;
    console.log('  ' + cstr(rva2off(nameRva)));
  }
}

// 字符串线索
console.log('\n=== 关键字符串线索 ===');
const pats = [
  /d3d1[012]/i, /dxgi/i, /Direct3D/i, /SDL/i, /OpenGL/i, /vulkan/i, /glfw/i,
  /XInput|dinput|RawInput/i, /\.lua|Lua/i, /script/i, /\.cpp|\.c$|\.h$/i,
  /assert|Assertion/i, /th06|TH06/i, /replay/i, /\.dat/i, /opus|ogg|vorbis/i,
  /vsnprintf|CRT/i, /Unity|Unreal|Godot/i,
];
const text = buf.toString('latin1');
const found = new Map();
for (const p of pats) {
  const re = new RegExp(p.source, 'gi');
  let m;
  let n = 0;
  while ((m = re.exec(text)) !== null && n < 12) {
    const s = m[0];
    if (!found.has(p.source)) found.set(p.source, new Set());
    found.get(p.source).add(s);
    n++;
  }
}
for (const [k, v] of found) console.log(' ', k, '=>', [...v].join(', '));

// 导出表
if (dirs[0].rva) {
  console.log('\n=== 导出表 ===');
  const eo = rva2off(dirs[0].rva);
  const nNames = u32(eo + 24);
  const namesRva = u32(eo + 32);
  for (let i = 0; i < Math.min(nNames, 50); i++) {
    console.log('  ' + cstr(rva2off(u32(rva2off(namesRva) + i * 4))));
  }
}
