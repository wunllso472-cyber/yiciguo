// 运行环境判断：决定支付时跳转支付宝、展示二维码，还是提示“在浏览器打开”。
const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";

export const isWeChat = /MicroMessenger/i.test(ua);
export const isAlipay = /AlipayClient/i.test(ua);
export const isMobile = /Android|iPhone|iPad|iPod|HarmonyOS|Mobile/i.test(ua);

export type PayEntry = "redirect" | "qr" | "wechat";

export function payEntry(): PayEntry {
  if (isWeChat) return "wechat"; // 微信内置浏览器会拦截 alipays:// 协议
  if (isMobile || isAlipay) return "redirect";
  return "qr";
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** 手机端上传前压缩到最长边 2400，减少流量；浏览器解不了的格式（如部分 HEIC）原样上传由服务端处理。 */
export async function shrinkImage(file: File, maxSide = 2400): Promise<Blob> {
  if (!/^image\/(jpeg|png|webp)$/i.test(file.type) || typeof createImageBitmap === "undefined") return file;
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" } as ImageBitmapOptions);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size < 4 * 1024 * 1024) {
      bitmap.close();
      return file;
    }
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.93));
    return blob ?? file;
  } catch {
    return file;
  }
}
