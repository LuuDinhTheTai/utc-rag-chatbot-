'use client';
import Link from 'next/link';
import UtcLogo from './UtcLogo';
import Icon from './Icon';
import {useAuth, roleNames} from './AuthProvider';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const {user,loading}=useAuth();
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

  const links = [
    {href: '/', label: 'Hỏi đáp tuyển sinh', icon: 'chat' as const},
    {href: '/majors', label: 'Ngành học & điểm chuẩn', icon: 'book' as const},
    {href: '/freshmen', label: 'Hồ sơ tân sinh viên', icon: 'file' as const},
  ];
  return <aside className="sidebar" aria-label="Thanh điều hướng">
    <Link href="/" className="brand"><UtcLogo/><span>ĐẠI HỌC<br/>GIAO THÔNG VẬN TẢI<small>UNIVERSITY OF TRANSPORT<br/>AND COMMUNICATIONS</small></span></Link>
    <div className="sidebar-divider"/>
    <button className="new-chat" aria-label="Cuộc trò chuyện mới" title="Cuộc trò chuyện mới" disabled={pathname === '/' && chatBusy} onClick={newChat}><Icon name="plus"/><span>Cuộc trò chuyện mới</span></button>
    <div className="sidebar-label">ĐỒNG HÀNH CÙNG BẠN</div>
    <nav className="sidebar-nav" aria-label="Điều hướng chính">
      {links.map(link => <Link aria-label={link.label} title={link.label} key={link.href} className={pathname === link.href ? 'nav-active' : 'nav-link'} aria-current={pathname === link.href ? 'page' : undefined} href={link.href}><Icon name={link.icon}/><span>{link.label}</span></Link>)}
      <a aria-label="Cổng tuyển sinh UTC" title="Cổng tuyển sinh UTC" className="nav-link official-link" href="https://tuyensinh.utc.edu.vn" target="_blank" rel="noreferrer"><Icon name="arrow"/><span>Cổng tuyển sinh UTC</span></a>
    </nav>
    <div className="sidebar-note"><Icon name="shield"/><span className="eyebrow">THÔNG TIN CÓ CĂN CỨ</span><p>Tra cứu cùng trợ lý UTC.<br/>Kiểm chứng từ nguồn tài liệu.</p></div>
    <Link aria-label={user?'Tài khoản của bạn':'Đăng nhập'} title={user?roleNames[user.role]:'Đăng nhập'} className="admin-link" href="/account"><Icon name="shield"/><span>{loading?'Đang tải…':user?`${roleNames[user.role]} · Tài khoản`:'Khách · Đăng nhập'}</span></Link>
    {user?.permissions.includes('content:read')&&<Link aria-label="Không gian quản trị" title="Không gian quản trị" className={pathname === '/admin' ? 'admin-link active' : 'admin-link'} aria-current={pathname === '/admin' ? 'page' : undefined} href="/admin"><Icon name="settings"/><span>Không gian quản trị</span></Link>}
  </aside>;
}
