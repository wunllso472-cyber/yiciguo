// 规格标注图：像制图一样给照片框标上宽高、头部比例、文件大小和底色。
// 首页用剪影 + 描线动画；规格页用剪影；结果页框住真实预览图。
import { useId } from "react";

interface Props {
  width: number;
  height: number;
  mm?: number[] | null;
  kbText?: string;
  dpi?: number;
  bg: string; // hex
  bgLabel?: string;
  image?: string;
  headRatio?: number; // 头部（头顶到下巴）占高度
  topMargin?: number;
  animate?: boolean;
  frameHeight?: number;
  minMode?: boolean;
}

export default function SpecDrawing({
  width,
  height,
  mm,
  kbText,
  dpi,
  bg,
  bgLabel,
  image,
  headRatio = 0.58,
  topMargin = 0.08,
  animate = false,
  frameHeight = 220,
  minMode = false,
}: Props) {
  const clip = useId().replace(/:/g, "");
  const aspect = width / height;
  const FH = aspect > 1.05 ? frameHeight * 0.82 : frameHeight;
  const FW = FH * aspect;
  const L = 40; // 左侧尺寸线区
  const T = 34; // 顶部尺寸线区
  const R = 108; // 右侧标注区
  const B = 28;
  const VW = L + FW + R;
  const VH = T + FH + B;
  const x0 = L;
  const y0 = T;

  // 剪影位置：头顶 → 下巴
  const crownY = y0 + FH * topMargin;
  const chinY = crownY + FH * headRatio;
  const headH = chinY - crownY;
  const cx = x0 + FW / 2;
  const headW = headH * 0.74;
  const dark = isDark(bg);
  const ink = dark ? "rgba(255,255,255,.88)" : "rgba(27,35,51,.82)";

  const wLabel = `${minMode ? "≥" : ""}${width} px`;
  const hLabel = `${minMode ? "≥" : ""}${height} px`;
  const notes = [kbText && kbText !== "不限" ? kbText : "KB 不限", "JPG", dpi ? `${dpi} dpi` : null, bgLabel ?? null].filter(
    Boolean,
  ) as string[];

  return (
    <svg
      className={`drawing ${animate ? "drawing-animate" : ""}`}
      viewBox={`0 0 ${VW} ${VH}`}
      role="img"
      aria-label={`照片规格：宽 ${width} 像素，高 ${height} 像素${mm ? `，${mm[0]}×${mm[1]} 毫米` : ""}，${notes.join("，")}`}
    >
      <defs>
        <clipPath id={clip}>
          <rect x={x0} y={y0} width={FW} height={FH} />
        </clipPath>
        <marker id={`${clip}a`} viewBox="0 0 8 8" refX="4" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L8 4 L0 8 z" fill="currentColor" />
        </marker>
      </defs>

      {/* 照片 */}
      <rect x={x0} y={y0} width={FW} height={FH} fill={bg} />
      {image ? (
        <image href={image} x={x0} y={y0} width={FW} height={FH} preserveAspectRatio="xMidYMid slice" clipPath={`url(#${clip})`} />
      ) : (
        <g clipPath={`url(#${clip})`} fill={ink} opacity={0.9}>
          <ellipse cx={cx} cy={crownY + headH * 0.5} rx={headW / 2} ry={headH / 2} />
          <path
            d={`M ${cx - FW * 0.62} ${y0 + FH + 2}
                C ${cx - FW * 0.55} ${chinY + headH * 0.18}, ${cx - headW * 0.75} ${chinY + headH * 0.06}, ${cx - headW * 0.28} ${chinY - headH * 0.04}
                L ${cx + headW * 0.28} ${chinY - headH * 0.04}
                C ${cx + headW * 0.75} ${chinY + headH * 0.06}, ${cx + FW * 0.55} ${chinY + headH * 0.18}, ${cx + FW * 0.62} ${y0 + FH + 2} Z`}
          />
        </g>
      )}
      <rect x={x0} y={y0} width={FW} height={FH} fill="none" className="drawing-frame" />

      {/* 宽度尺寸线 */}
      <g className="dim">
        <line x1={x0} y1={y0 - 4} x2={x0} y2={T - 26} className="dim-ext" />
        <line x1={x0 + FW} y1={y0 - 4} x2={x0 + FW} y2={T - 26} className="dim-ext" />
        <line x1={x0 + 2} y1={T - 16} x2={x0 + FW - 2} y2={T - 16} className="dim-line draw"
          markerStart={`url(#${clip}a)`} markerEnd={`url(#${clip}a)`} />
        <text x={x0 + FW / 2} y={T - 21} textAnchor="middle" className="dim-text label-in">{wLabel}</text>
      </g>

      {/* 高度尺寸线 */}
      <g className="dim">
        <line x1={x0 - 4} y1={y0} x2={L - 30} y2={y0} className="dim-ext" />
        <line x1={x0 - 4} y1={y0 + FH} x2={L - 30} y2={y0 + FH} className="dim-ext" />
        <line x1={L - 22} y1={y0 + 2} x2={L - 22} y2={y0 + FH - 2} className="dim-line draw"
          markerStart={`url(#${clip}a)`} markerEnd={`url(#${clip}a)`} />
        <text x={L - 27} y={y0 + FH / 2} textAnchor="middle" className="dim-text label-in"
          transform={`rotate(-90 ${L - 27} ${y0 + FH / 2})`}>{hLabel}</text>
      </g>

      {/* 头部比例 */}
      <g className="dim">
        <line x1={x0 + FW * 0.18} y1={crownY} x2={x0 + FW + 14} y2={crownY} className="guide draw" />
        <line x1={x0 + FW * 0.18} y1={chinY} x2={x0 + FW + 14} y2={chinY} className="guide draw" />
        <line x1={x0 + FW + 10} y1={crownY + 2} x2={x0 + FW + 10} y2={chinY - 2} className="dim-line draw"
          markerStart={`url(#${clip}a)`} markerEnd={`url(#${clip}a)`} />
        <text x={x0 + FW + 18} y={(crownY + chinY) / 2 - 4} className="note-text label-in">头部</text>
        <text x={x0 + FW + 18} y={(crownY + chinY) / 2 + 13} className="dim-text label-in">{Math.round(headRatio * 100)}%</text>
      </g>

      {/* 标注：KB、格式、分辨率、底色 */}
      <g className="label-in">
        {notes.map((n, i) => (
          <text key={n} x={x0 + FW + 18} y={chinY + 30 + i * 17} className="note-text">{n}</text>
        ))}
      </g>
      {mm && (
        <text x={x0 + FW / 2} y={y0 + FH + 19} textAnchor="middle" className="note-text label-in">
          {mm[0]} × {mm[1]} mm
        </text>
      )}
    </svg>
  );
}

function isDark(hex: string): boolean {
  const h = hex.replace("#", "");
  if (h.length !== 6) return false;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.299 * r + 0.587 * g + 0.114 * b < 150;
}
