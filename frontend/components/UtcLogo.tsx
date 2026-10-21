import Image from 'next/image';

export default function UtcLogo({welcome = false}: {welcome?: boolean}) {
  return <Image src="/utc-logo.png" alt="Logo Trường Đại học Giao thông Vận tải"
    width={welcome ? 72 : 56} height={welcome ? 72 : 56}
    sizes={welcome ? '72px' : '56px'} priority className={welcome ? 'welcome-logo' : 'logo'}/>;
}
