'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [chatBusy, setChatBusy] = useState(false);
  useEffect(() => {
    const update = (event: Event) => setChatBusy(Boolean((event as CustomEvent<boolean>).detail));
    window.addEventListener('utc:chat-busy', update);
    return () => window.removeEventListener('utc:chat-busy', update);
  }, []);

  function newChat() {
    const event = new Event('utc:new-chat', {cancelable: true});
    window.dispatchEvent(event);
    if (event.defaultPrevented) return;
    localStorage.removeItem('utc-session');
    if (pathname !== '/') router.push('/');
  }

  return <aside className="sidebar" aria-label="Thanh điều hướng">
    <Link href="/" className="brand"><span className="logo">UTC</span><span>Trợ lý tuyển sinh<small>GIAO THÔNG VẬN TẢI</small></span></Link>
    <button className="new-chat" disabled={pathname === '/' && chatBusy} onClick={newChat}>＋ Cuộc trò chuyện mới</button>
    <div className="sidebar-label">KHÔNG GIAN TRA CỨU</div>
    <nav className="sidebar-nav" aria-label="Điều hướng chính">
      <Link className={pathname === '/freshmen' ? 'nav-active' : 'nav-link'} aria-current={pathname === '/freshmen' ? 'page' : undefined} href="/freshmen">▦ &nbsp; Hồ sơ tân sinh viên</Link>
      <Link className={pathname === '/majors' ? 'nav-active' : 'nav-link'} aria-current={pathname === '/majors' ? 'page' : undefined} href="/majors">▦ &nbsp; Tra cứu ngành học</Link>
      <Link className={pathname === '/' ? 'nav-active' : 'nav-link'} aria-current={pathname === '/' ? 'page' : undefined} href="/">◈ &nbsp; Hỏi đáp tuyển sinh</Link>
      <a className="nav-link" href="https://tuyensinh.utc.edu.vn" target="_blank" rel="noreferrer">↗ &nbsp; Cổng tuyển sinh UTC</a>
    </nav>
    <div className="sidebar-note"><span className="eyebrow">CÓ NGUỒN, CÓ CĂN CỨ</span><p>Mỗi câu trả lời được đối chiếu với tài liệu trong kho tri thức tuyển sinh.</p></div>
    <Link className={pathname === '/admin' ? 'admin-link active' : 'admin-link'} aria-current={pathname === '/admin' ? 'page' : undefined} href="/admin">⚙ &nbsp; Quản trị tài liệu</Link>
  </aside>;
}