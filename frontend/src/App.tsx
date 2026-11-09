import { useEffect } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import AdminPage from "./pages/AdminPage";
import CustomPage from "./pages/CustomPage";
import Home from "./pages/Home";
import MePage from "./pages/MePage";
import PhotoPage from "./pages/PhotoPage";
import ReturnPage from "./pages/ReturnPage";
import SpecPage from "./pages/SpecPage";
import { FaqPage, NotFound, PrivacyPage, TermsPage } from "./pages/TextPages";

export default function App() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className="shell">
      <a className="skip" href="#main">跳到正文</a>
      <header className="topbar">
        <Link to="/" className="brand" aria-label="一次过 首页">
          <svg width="22" height="26" viewBox="0 0 22 26" aria-hidden="true">
            <rect x="0.5" y="0.5" width="21" height="25" rx="1.5" fill="#438EDB" />
            <circle cx="11" cy="10" r="4.4" fill="#fff" />
            <path d="M2.5 25.5c.8-5.2 4.2-7.8 8.5-7.8s7.7 2.6 8.5 7.8z" fill="#fff" />
          </svg>
          <span>一次过</span>
        </Link>
        <nav className="nav">
          <NavLink to="/custom">自定义</NavLink>
          <NavLink to="/faq">常见问题</NavLink>
          <NavLink to="/me">我的照片</NavLink>
        </nav>
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/spec/:key" element={<SpecPage />} />
          <Route path="/photo/:id" element={<PhotoPage />} />
          <Route path="/r/:req" element={<ReturnPage />} />
          <Route path="/me" element={<MePage />} />
          <Route path="/custom" element={<CustomPage />} />
          <Route path="/faq" element={<FaqPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="/terms" element={<TermsPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="footer">
        <p>规格来源于公开资料，最终以报名系统为准。照片只在本站服务器处理，24 小时自动删除。</p>
        <p>
          <Link to="/privacy">人脸信息处理规则</Link>
          <Link to="/terms">用户协议</Link>
          <Link to="/faq">常见问题</Link>
        </p>
      </footer>
    </div>
  );
}
