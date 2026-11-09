// 上传入口：首次使用先单独征得人脸信息处理同意，再拍照或从相册选择。
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, track } from "../api";
import { shrinkImage } from "../env";
import { useApp } from "../state";
import { Sheet, Spinner } from "./ui";

interface Props {
  specKey: string;
  bg?: string;
  redoOf?: string;
  compact?: boolean;
}

export default function Uploader({ specKey, bg = "", redoOf = "", compact = false }: Props) {
  const { me, setMe, toast } = useApp();
  const nav = useNavigate();
  const camera = useRef<HTMLInputElement>(null);
  const gallery = useRef<HTMLInputElement>(null);
  const [consentOpen, setConsentOpen] = useState(false);
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [consentReq, setConsentReq] = useState<Promise<unknown> | null>(null);

  const pick = (which: "camera" | "gallery") => {
    if (!me?.consent && !consentReq) {
      setConsentOpen(true);
      return;
    }
    track("pick_photo", { from: which });
    (which === "camera" ? camera : gallery).current?.click();
  };

  const acceptAndPick = (which: "camera" | "gallery") => {
    if (!agree || !me) return;
    // 必须在点击事件里同步打开文件选择（iOS 限制），同意请求并行发送
    const req = api.post("/api/me/consent", { version: me.consent_version }).then((m) => setMe(m as typeof me));
    setConsentReq(req);
    setConsentOpen(false);
    track("consent");
    (which === "camera" ? camera : gallery).current?.click();
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      if (consentReq) await consentReq;
      const blob = await shrinkImage(file);
      const form = new FormData();
      form.append("file", blob, file.name.replace(/\.(heic|heif|png|webp)$/i, ".jpg") || "photo.jpg");
      form.append("spec_key", specKey);
      form.append("bg", bg);
      if (redoOf) form.append("redo_of", redoOf);
      const res = await api.upload<{ id: string }>("/api/photos", form);
      nav(`/photo/${res.id}`);
    } catch (err) {
      toast((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={compact ? "uploader uploader-compact" : "uploader"}>
      <input ref={camera} type="file" accept="image/*" capture="user" hidden onChange={onFile} />
      <input ref={gallery} type="file" accept="image/*,.heic,.heif" hidden onChange={onFile} />
      {busy ? (
        <div className="uploading"><Spinner label="正在上传…" /></div>
      ) : (
        <div className="btn-pair">
          <button className="btn btn-primary" onClick={() => pick("camera")}>拍一张</button>
          <button className="btn btn-ghost" onClick={() => pick("gallery")}>从相册选</button>
        </div>
      )}
      {!compact && (
        <p className="fine">
          预审免费。照片只在本站服务器处理，{me?.ttl_hours ?? 24} 小时后自动删除，也可以随时手动删除。
        </p>
      )}

      <Sheet open={consentOpen} onClose={() => setConsentOpen(false)} title="使用照片前，请确认">
        <div className="consent">
          <p>为了生成报名照，我们需要处理你的<strong>人脸照片</strong>。人脸信息属于敏感个人信息，所以单独征求你的同意：</p>
          <ul className="consent-list">
            <li><b>用途</b>只用于检测照片是否合规、抠图换底、裁剪和压缩，生成你要的报名照。</li>
            <li><b>处理方式</b>全部在本站服务器上完成，不发给第三方，不用于训练任何模型。</li>
            <li><b>保存期限</b>{me?.ttl_hours ?? 24} 小时后自动删除照片文件；你也可以在“我的照片”里立即删除。</li>
            <li><b>不美颜</b>只做合规处理（换底、裁剪、压缩），不改变五官和肤色。</li>
          </ul>
          <label className="check">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>
              我已阅读并同意<Link to="/privacy" target="_blank">《人脸信息处理规则》</Link>和
              <Link to="/terms" target="_blank">《用户协议》</Link>
            </span>
          </label>
          <div className="btn-pair">
            <button className="btn btn-primary" disabled={!agree} onClick={() => acceptAndPick("camera")}>同意并拍照</button>
            <button className="btn btn-ghost" disabled={!agree} onClick={() => acceptAndPick("gallery")}>同意并从相册选</button>
          </div>
        </div>
      </Sheet>
    </div>
  );
}

export function ShootingTips() {
  return (
    <ul className="tips">
      <li>站在白墙或纯色墙前，脸正对窗户或灯光，避免一边亮一边暗。</li>
      <li>手机举到与眼睛平齐，离脸 50 厘米以上，露出头顶和双肩。</li>
      <li>平视镜头，嘴巴自然闭合；刘海撩开露出眉毛，需要露耳的把头发别到耳后。</li>
      <li>戴眼镜注意镜片反光；如果考试要求摘镜，请摘下再拍。</li>
    </ul>
  );
}
