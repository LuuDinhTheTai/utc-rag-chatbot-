import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title: 'UTC · Trợ lý tuyển sinh', description: 'Tra cứu tuyển sinh Trường Đại học Giao thông Vận tải có nguồn tham khảo.'};
export default function Layout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="vi"><body>{children}</body></html>;
}
