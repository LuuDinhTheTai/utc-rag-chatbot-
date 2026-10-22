import type { Metadata } from 'next';
import './globals.css';
import './utc-theme.css';
import Sidebar from '../components/Sidebar';
import AuthProvider from '../components/AuthProvider';
import PlannerProvider from '../components/PlannerProvider';
export const metadata: Metadata = {icons: {icon: '/utc-logo.png', apple: '/utc-logo.png'}, title: 'UTC · Trợ lý tuyển sinh', description: 'Tra cứu tuyển sinh Trường Đại học Giao thông Vận tải có nguồn tham khảo.'};
export default function Layout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="vi"><body><AuthProvider><PlannerProvider><div className="app-shell"><Sidebar/><div className="app-content">{children}</div></div></PlannerProvider></AuthProvider></body></html>;
}
