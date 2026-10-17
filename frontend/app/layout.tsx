import type { Metadata } from 'next';
import './globals.css';
import Sidebar from '../components/Sidebar';
export const metadata: Metadata = {title: 'UTC · Trợ lý tuyển sinh', description: 'Tra cứu tuyển sinh Trường Đại học Giao thông Vận tải có nguồn tham khảo.'};
export default function Layout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="vi"><body><div className="app-shell"><Sidebar/><div className="app-content">{children}</div></div></body></html>;
}
