// Original 16x16 pixel-art placeholders, the same designs as output/desk_tickets.html (Problem 6).
// Each letter is a palette colour; "." is transparent.
import { memo } from "react";
import type { CharacterId } from "../types";

interface SpriteDef {
  pal: Record<string, string>;
  rows: string[];
}

export const SPRITES: Record<CharacterId, SpriteDef> = {
  mario: {
    pal: { R: "#e8333f", r: "#9e1b26", W: "#ffffff", S: "#ffc79a", s: "#e59a6a", K: "#1a1014", H: "#6b3a1e", B: "#2f5fe0", Y: "#ffd23f" },
    rows: ["....RRRRRRRR....", "...RRRRWWRRRR...", "..RRRRWWWWRRRR..", "..rrrrrrrrrrrr..",
           "...HSSSSSSSSH...", "...SSKSSSSKSS...", "...SSKSSSSKSS...", "..sSSSSSSSSSSs..",
           "...SKKKKKKKKS...", "....SSSKKSSS....", "...RRRBBBBRRR...", "..RRRBYBBYBRRR..",
           "..SSBBBBBBBBSS..", "....BBBBBBBB....", "....BBB..BBB....", "...HHHH..HHHH..."],
  },
  crash: {
    pal: { O: "#ff8a1f", o: "#c25a0a", T: "#ffd9a0", K: "#1a1014", W: "#ffffff", G: "#3ddc84", B: "#2f5fe0", R: "#e8333f" },
    rows: ["......K.K.......", ".....OKOKO......", "....OOOOOOOO....", "...OOOOOOOOOO...",
           "..OOWWGOOWWGOO..", "..OOWWKOOWWKOO..", "..OOOOOKKOOOOO..", "...OTTTTTTTTO...",
           "...OTKWWWWKTO...", "....TTTTTTTT....", "...OOOOOOOOOO...", "..OOOOTTTTOOOO..",
           "..TT.BBBBBB.TT..", ".....BBBBBB.....", ".....BB..BB.....", "....RRR..RRR...."],
  },
  spyro: {
    pal: { P: "#9b5cff", p: "#5e2fb0", Y: "#ffcf3f", W: "#ffffff", K: "#1a1014" },
    rows: ["..Y........Y....", "..YY......YY....", "...PY....YP.....", "...PPPPPPPP.....",
           "..PPPPPPPPPP....", "..PWKPPPPWKP....", "..PPPPPPPPPPPP..", "..PPPPPPPYYPPPP.",
           "...PPPPPPPPPPP..", "YY..PPPPPPPP..YY", "YYY.PYYYYYYP.YYY", ".YYPPYYYYYYPPYY.",
           "...PPPPPPPPPP...", "...PP.PPPP.PP...", "..pp...pp...pp..", "................"],
  },
  ryu: {
    pal: { K: "#1a1014", R: "#e8333f", S: "#f2c08f", W: "#f4f4f4", w: "#c9c9d6", k: "#2a2a2a" },
    rows: ["....KKKKKKKK....", "...KKKKKKKKKK...", "...RRRRRRRRRRRR.", "...SSSSSSSSSS.RR",
           "...SKKSSSSKKS..R", "...SSSSSSSSSS...", "....SSSKKSSS....", ".....SSSSSS.....",
           "..WWWWSSSSWWWW..", ".WWWWWWSSWWWWWW.", ".SSWWWWWWWWWWSS.", ".SSwWWWWWWWWwSS.",
           "...kkkkkkkkkk...", "...WWWWWWWWWW...", "...WWWW..WWWW...", "...SSS....SSS..."],
  },
  sonic: {
    pal: { B: "#2f6bff", b: "#1b3d99", T: "#ffcf9a", W: "#ffffff", G: "#3ddc84", K: "#1a1014", R: "#e8333f" },
    rows: ["......BBB.......", "...BBBBBBBB.....", ".BBBBBBBBBBB....", "BBBBBBBBBBBBB...",
           "..BBBWWWWWWBB...", ".BBBWGKWWGKWB...", "BBBBWGKWWGKWB...", "..BBTTTTTTTTB...",
           "...BTTTKKTTT....", "....TTTTTTTT....", "...BBBTTTTBBB...", "..TBBBTTTTBBBT..",
           "....BBBBBBBB....", "....BB....BB....", "...RRRW..RRRW...", "..RRRRW..RRRRW.."],
  },
};

function runs(def: SpriteDef) {
  const out: { x: number; y: number; w: number; fill: string }[] = [];
  def.rows.forEach((row, y) => {
    let x = 0;
    while (x < 16) {
      const c = row[x] ?? ".";
      let w = 1;
      while (x + w < 16 && (row[x + w] ?? ".") === c) w++;
      if (c !== "." && def.pal[c]) out.push({ x, y, w, fill: def.pal[c] });
      x += w;
    }
  });
  return out;
}

const RUNS = Object.fromEntries(Object.entries(SPRITES).map(([k, v]) => [k, runs(v)])) as Record<
  CharacterId, ReturnType<typeof runs>>;

export const Sprite = memo(function Sprite({ id, size = 48, className }: { id: CharacterId; size?: number; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" width={size} height={size} shapeRendering="crispEdges" aria-hidden="true" focusable="false">
      {RUNS[id].map((r) => (
        <rect key={`${r.x}-${r.y}`} x={r.x} y={r.y} width={r.w} height={1} fill={r.fill} />
      ))}
    </svg>
  );
});

/** Small padlock used for human-approval gates. */
export function Lock({ size = 20 }: { size?: number }) {
  return (
    <svg viewBox="0 0 10 12" width={size} height={(size * 12) / 10} shapeRendering="crispEdges" aria-hidden="true" focusable="false">
      <rect x="2" y="0" width="6" height="2" fill="#ffd23f" />
      <rect x="1" y="1" width="2" height="4" fill="#ffd23f" />
      <rect x="7" y="1" width="2" height="4" fill="#ffd23f" />
      <rect x="0" y="5" width="10" height="7" fill="#ffd23f" />
      <rect x="4" y="7" width="2" height="3" fill="#6b4a00" />
    </svg>
  );
}

/** The locked arcade gate graphic from Problem 6. */
export function Gate({ size = 64 }: { size?: number }) {
  return (
    <svg viewBox="0 0 22 22" width={size} height={size} shapeRendering="crispEdges" aria-hidden="true" focusable="false">
      <rect x="1" y="1" width="20" height="2" fill="#ff2e97" />
      <rect x="1" y="19" width="20" height="2" fill="#ff2e97" />
      {[2, 7, 13, 18].map((x) => (
        <rect key={x} x={x} y="3" width="2" height="16" fill="#6b1342" />
      ))}
      <rect x="8" y="7" width="6" height="2" fill="#ffd23f" />
      <rect x="7" y="8" width="2" height="4" fill="#ffd23f" />
      <rect x="13" y="8" width="2" height="4" fill="#ffd23f" />
      <rect x="6" y="11" width="10" height="7" fill="#ffd23f" />
      <rect x="10" y="13" width="2" height="3" fill="#6b4a00" />
    </svg>
  );
}
